"""
NSFW 이미지 자동 검수 시스템 (2단계 검수)

1단계: 빠른 스크리닝 (색상 기반) - 명백한 위반만 탐지
2단계: Gemini Vision 심층 검수 - YouTube 정책 기준 맞춤 판단

사용:
    from utils.nsfw_detector import content_reviewer
    passed, reason = content_reviewer.review_image("image.png")
"""

import os
import logging
import time
from typing import Tuple, Optional, Callable
from PIL import Image
import numpy as np

from utils.gemini_compat import configure_gemini, generate_vision_content, get_gemini_model
from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


class QuickScreener:
    """
    1단계: 빠른 색상 기반 스크리닝
    - 명백한 위반 (과도한 피부색, 유혈)만 빠르게 걸러냄
    - Gemini API 호출 비용 절감용
    """

    # 피부색 범위 (HSV)
    SKIN_LOWER_1 = np.array([0, 20, 70])
    SKIN_UPPER_1 = np.array([20, 255, 255])
    SKIN_LOWER_2 = np.array([170, 20, 70])
    SKIN_UPPER_2 = np.array([180, 255, 255])

    # 붉은색 범위 (유혈/폭력)
    RED_LOWER_1 = np.array([0, 100, 100])
    RED_UPPER_1 = np.array([10, 255, 255])
    RED_LOWER_2 = np.array([160, 100, 100])
    RED_UPPER_2 = np.array([180, 255, 255])

    # 임계값 (1차 스크리닝용 - 느슨하게)
    SKIN_THRESHOLD = 0.35  # 35% 이상 피부색 = 명백한 위반
    RED_THRESHOLD = 0.20   # 20% 이상 붉은색 = 명백한 위반

    # v56.1.1: 채널별 임계값 (공포 채널은 어둡고 붉은 톤이 많음)
    # v56.1.2: 붉은색 임계값 하향 (45%→30%) - LM 협의: 고어 이미지 차단 강화
    CHANNEL_THRESHOLDS = {
        "daily_life_toon": {
            "red_threshold": 0.20,
            "min_brightness": 0.05,
        },
        "mystery_toon": {
            "red_threshold": 0.24,
            "min_brightness": 0.03,
        },
        "horror": {
            "red_threshold": 0.30,    # 붉은색 30%까지 허용 (붉은 조명 OK, 고어 차단)
            "min_brightness": 0.01,   # 1% 밝기까지 허용 (매우 어두운 배경)
        },
        "senior_makjang": {
            "red_threshold": 0.25,    # 드라마틱한 붉은 텍스트/배경 허용
            "min_brightness": 0.03,
        },
        # 기본값은 클래스 상수(RED_THRESHOLD=0.20) 사용
    }

    def screen(self, image_path: str, channel_type: str = None) -> Tuple[bool, str]:
        """
        빠른 1차 스크리닝

        Args:
            image_path: 이미지 파일 경로
            channel_type: 채널 타입 (horror, senior_touching 등) - v56.1.1 추가

        Returns:
            (의심 여부, 사유)
            - True = 의심됨, Gemini 검수 필요
            - False = 명백히 안전, Gemini 스킵 가능
        """
        if not os.path.exists(image_path):
            return True, "파일 없음"

        # v56.1.1: 채널별 임계값 적용
        # v56.1.2: senior_makjang 등 전체 키 먼저 시도, 없으면 첫 부분만 시도
        channel_key = channel_type.split("_")[0] if channel_type else None  # "horror_xxx" → "horror"
        thresholds = self.CHANNEL_THRESHOLDS.get(channel_type, self.CHANNEL_THRESHOLDS.get(channel_key, {}))
        red_threshold = thresholds.get("red_threshold", self.RED_THRESHOLD)
        min_brightness = thresholds.get("min_brightness", 0.05)

        try:
            img = Image.open(image_path).convert("RGB")
            img_array = np.array(img)

            # 피부색 비율
            skin_ratio = self._detect_skin_ratio(img_array)
            if skin_ratio > self.SKIN_THRESHOLD:
                return True, f"피부색 과다 ({skin_ratio:.1%})"

            # 붉은색 비율 (채널별 임계값 적용)
            red_ratio = self._detect_red_ratio(img_array)
            if red_ratio > red_threshold:
                return True, f"붉은색 과다 ({red_ratio:.1%})"

            # 기본 품질 체크 (채널별 밝기 임계값 적용)
            brightness = self._get_brightness(img_array)
            if brightness < min_brightness or brightness > 0.95:
                return True, f"밝기 이상 ({brightness:.1%})"

            return False, "1차 스크리닝 통과"

        except Exception as e:
            logger.warning(f"[1차 스크리닝] 분석 실패: {e}")
            return True, f"분석 오류"  # 오류 시 Gemini로 넘김

    def _detect_skin_ratio(self, img_array: np.ndarray) -> float:
        try:
            img_pil = Image.fromarray(img_array)
            img_hsv = img_pil.convert("HSV")
            hsv_array = np.array(img_hsv)

            mask1 = self._in_range(hsv_array, self.SKIN_LOWER_1, self.SKIN_UPPER_1)
            mask2 = self._in_range(hsv_array, self.SKIN_LOWER_2, self.SKIN_UPPER_2)
            skin_mask = mask1 | mask2

            return np.sum(skin_mask) / (img_array.shape[0] * img_array.shape[1])
        except Exception:
            return 0.0

    def _detect_red_ratio(self, img_array: np.ndarray) -> float:
        try:
            img_pil = Image.fromarray(img_array)
            img_hsv = img_pil.convert("HSV")
            hsv_array = np.array(img_hsv)

            mask1 = self._in_range(hsv_array, self.RED_LOWER_1, self.RED_UPPER_1)
            mask2 = self._in_range(hsv_array, self.RED_LOWER_2, self.RED_UPPER_2)
            red_mask = mask1 | mask2

            saturation = hsv_array[:, :, 1]
            high_sat_mask = saturation > 150

            return np.sum(red_mask & high_sat_mask) / (img_array.shape[0] * img_array.shape[1])
        except Exception:
            return 0.0

    def _get_brightness(self, img_array: np.ndarray) -> float:
        try:
            gray = np.mean(img_array, axis=2)
            return np.mean(gray) / 255.0
        except Exception:
            return 0.5

    def _in_range(self, hsv_array: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
        return (
            (hsv_array[:, :, 0] >= lower[0]) & (hsv_array[:, :, 0] <= upper[0]) &
            (hsv_array[:, :, 1] >= lower[1]) & (hsv_array[:, :, 1] <= upper[1]) &
            (hsv_array[:, :, 2] >= lower[2]) & (hsv_array[:, :, 2] <= upper[2])
        )


class GeminiContentReviewer:
    """
    2단계: Gemini Vision 기반 YouTube 정책 준수 검수관

    - YouTube 커뮤니티 가이드라인 기준 판단
    - 문맥 파악 가능 (수술실 vs 살인 장면 구분)
    - 채널 타입별 맞춤 기준 적용
    """

    # YouTube 검수 프롬프트
    REVIEW_PROMPT = """
너는 지금부터 '유튜브 콘텐츠 안전 관리자'야.
아래 이미지를 분석해서 [YouTube 커뮤니티 가이드라인]에 위배되는지 엄격하게 판단해.

특히 다음 요소들을 중점적으로 체크해:
1. 과도한 노출 또는 성적인 콘텐츠 (Sexually Explicit) - 나체, 속옷 노출, 성적 암시
2. 지나치게 잔인하거나 혐오스러운 묘사 (Violent or Repulsive) - 유혈, 내장, 절단
3. 아동에게 유해한 요소 (Harmful to Kids) - 약물, 위험한 행위
4. 혐오 표현 또는 차별적 상징 (Hate Speech/Symbols)

[추가 맥락]
이 이미지는 한국 YouTube 채널용 콘텐츠입니다.
주 시청층: {audience}
채널 장르: {genre}

[응답 형식]
이미지가 안전하다면 정확히 "SAFE"라고만 대답해.
위험하다면 "UNSAFE: [구체적 위반 사유]"라고 대답해.
애매하면 안전 쪽으로 판단하되, 경고만 해줘: "WARN: [주의 사항]"
"""

    # v50: 프롬프트 수정 제안 프롬프트 (자가 치유용)
    FIX_PROMPT_PROMPT = """
너는 'Stable Diffusion 프롬프트 수정 전문가'야.

방금 생성된 이미지가 YouTube 정책 위반으로 판정되었어.
위반 사유: {violation_reason}

원래 프롬프트: {original_prompt}

[너의 임무]
1. 위반 요소를 제거하면서도 원래 의도(분위기/장르)를 유지하는 새 프롬프트를 만들어줘.
2. 예를 들어:
   - "피가 너무 많음" → 피 대신 "어두운 그림자, 붉은 조명"으로 대체
   - "노출 과다" → 인물을 제거하고 "빈 방, 버려진 옷가지"로 대체
   - "폭력적" → "긴장감 있는 분위기, 깨진 물건, 어두운 조명"으로 순화

[규칙]
- 절대 사람/인물/신체 부위 언급 금지
- "blood", "gore", "nude", "body" 등 금지어 사용 금지
- 분위기와 오브젝트로만 표현
- 영어로 작성

[응답 형식]
수정된 프롬프트만 출력해. 설명 없이 프롬프트만.
"""

    # 채널별 맥락 정보
    CHANNEL_CONTEXT = {
        "horror": {
            "audience": "성인 (20-50대)",
            "genre": "공포/미스터리 (어두운 분위기, 긴장감 있는 이미지는 허용)"
        },
        "senior_touching": {
            "audience": "중장년층 (40-70대)",
            "genre": "감동/힐링 (따뜻하고 정서적인 이미지)"
        },
        "senior_makjang": {
            "audience": "중장년층 (40-70대)",
            "genre": "막장 드라마 (갈등/긴장감 있지만 선정적이지 않은 이미지)"
        },
    }

    def __init__(self):
        self.model = None
        self.quick_screener = QuickScreener()
        self._init_model()

    def _init_model(self):
        """Gemini 모델 초기화"""
        try:
            from config.settings import config

            if not configure_gemini(config.GEMINI_API_KEY):
                raise RuntimeError("Gemini API 초기화 실패")
            self.model = get_gemini_model("gemini-3-flash-preview")
            if self.model is None:
                raise RuntimeError("Gemini 모델 로드 실패")
            logger.info("[검수관] Gemini 3.0 Flash 모델 초기화 완료")

        except Exception as e:
            logger.warning(f"[검수관] Gemini 초기화 실패: {redact_sensitive_text(e)}")
            self.model = None

    def review_image(
        self,
        image_path: str,
        channel_type: str = "daily_life_toon",
        skip_quick_screen: bool = False
    ) -> Tuple[str, str]:
        """
        이미지 검수 (2단계)

        Args:
            image_path: 이미지 파일 경로
            channel_type: 채널 타입 (horror, senior_touching, senior_makjang)
            skip_quick_screen: True면 1차 스크리닝 스킵하고 바로 Gemini 검수

        Returns:
            (결과, 상세 사유)
            - "SAFE": 안전
            - "UNSAFE": 위반
            - "WARN": 경고 (통과하지만 주의)
            - "ERROR": 검수 실패
        """
        if not os.path.exists(image_path):
            return "ERROR", "파일 없음"

        # 1단계: 빠른 스크리닝 (v56.1.1: 채널별 임계값 적용)
        if not skip_quick_screen:
            suspicious, reason = self.quick_screener.screen(image_path, channel_type)
            if not suspicious:
                # 명백히 안전 → Gemini 호출 스킵 (비용 절감)
                logger.debug(f"[검수관] 1차 스크리닝 통과 (Gemini 스킵): {image_path}")
                return "SAFE", "1차 스크리닝 통과"

            logger.info(f"[검수관] 1차 스크리닝 의심: {reason} → Gemini 검수 진행")

        # 2단계: Gemini Vision 검수
        if not self.model:
            logger.warning("[검수관] Gemini 모델 없음 - 1차 스크리닝 결과만 사용")
            return "WARN", "Gemini 검수 불가 (API 미설정)"

        return self._gemini_review(image_path, channel_type)

    def _gemini_review(self, image_path: str, channel_type: str) -> Tuple[str, str]:
        """Gemini API를 통한 이미지 검수"""
        try:
            # 채널별 맥락 정보
            context = self.CHANNEL_CONTEXT.get(channel_type, self.CHANNEL_CONTEXT["horror"])

            # 프롬프트 생성
            prompt = self.REVIEW_PROMPT.format(
                audience=context["audience"],
                genre=context["genre"]
            )

            # Gemini API 호출
            response = generate_vision_content(self.model, prompt, [image_path])
            if response is None:
                return "ERROR", "Vision 응답 없음"
            result_text = response.text.strip().upper()

            # 결과 파싱
            if result_text.startswith("SAFE"):
                return "SAFE", "Gemini 검수 통과"
            elif result_text.startswith("UNSAFE"):
                reason = result_text.replace("UNSAFE:", "").strip()
                return "UNSAFE", reason or "정책 위반"
            elif result_text.startswith("WARN"):
                reason = result_text.replace("WARN:", "").strip()
                return "WARN", reason or "주의 필요"
            else:
                # 파싱 실패 - 보수적으로 경고 처리
                logger.warning(f"[검수관] Gemini 응답 파싱 실패: {result_text[:100]}")
                return "WARN", f"응답 형식 오류: {result_text[:50]}"

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[검수관] Gemini API 오류: {safe_error}")
            return "ERROR", f"API 오류: {safe_error}"

    def suggest_fixed_prompt(self, original_prompt: str, violation_reason: str) -> Optional[str]:
        """
        v50: 자가 치유 - 위반된 프롬프트를 수정한 새 프롬프트 제안

        Args:
            original_prompt: 원래 SD 프롬프트
            violation_reason: 위반 사유

        Returns:
            수정된 프롬프트 또는 None
        """
        if not self.model:
            logger.warning("[검수관] Gemini 모델 없음 - 프롬프트 수정 불가")
            return None

        try:
            prompt = self.FIX_PROMPT_PROMPT.format(
                violation_reason=violation_reason,
                original_prompt=original_prompt
            )

            response = self.model.generate_content(prompt)
            fixed_prompt = response.text.strip()

            # 기본 검증: 금지어 포함 여부
            banned_words = ["blood", "gore", "nude", "naked", "body", "person", "human", "face"]
            fixed_lower = fixed_prompt.lower()
            for banned in banned_words:
                if banned in fixed_lower:
                    logger.warning(f"[검수관] 수정 프롬프트에 금지어 포함: {banned}")
                    return None

            logger.info(f"[검수관] 프롬프트 수정 제안: {fixed_prompt[:100]}...")
            return fixed_prompt

        except Exception as e:
            logger.error(f"[검수관] 프롬프트 수정 실패: {redact_sensitive_text(e)}")
            return None

    def review_and_regenerate(
        self,
        image_path: str,
        regenerate_callback: Callable[[str], None],
        channel_type: str = "daily_life_toon",
        max_retries: int = 3
    ) -> Tuple[bool, str]:
        """
        이미지 검수 후 위반 시 재생성

        Args:
            image_path: 검수할 이미지 경로
            regenerate_callback: 재생성 함수 (경로를 받아 새 이미지 생성)
            channel_type: 채널 타입
            max_retries: 최대 재시도 횟수

        Returns:
            (성공 여부, 최종 이미지 경로 또는 에러 메시지)
        """
        for attempt in range(max_retries + 1):
            result, reason = self.review_image(image_path, channel_type)

            if result == "SAFE" or result == "WARN":
                if attempt > 0:
                    logger.info(f"[검수관] {attempt}회 재생성 후 통과: {image_path}")
                return True, image_path

            if result == "UNSAFE":
                if attempt < max_retries:
                    logger.warning(f"[검수관] 위반 ({reason}), 재생성 {attempt + 1}/{max_retries}")
                    try:
                        if os.path.exists(image_path):
                            os.remove(image_path)
                        regenerate_callback(image_path)
                        time.sleep(0.5)  # API 쿨다운
                    except Exception as e:
                        logger.error(f"[검수관] 재생성 실패: {e}")
                        return False, f"재생성 실패: {e}"
                else:
                    logger.error(f"[검수관] {max_retries}회 재생성 후에도 위반: {reason}")
                    return False, f"검수 실패: {reason}"

            elif result == "ERROR":
                logger.warning(f"[검수관] 검수 오류 ({reason}), 일단 통과 처리")
                return True, image_path

        return False, "알 수 없는 오류"

    def batch_review(
        self,
        image_paths: list,
        channel_type: str = "daily_life_toon",
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> dict:
        """
        여러 이미지 일괄 검수

        Returns:
            {
                "safe": [통과 경로들],
                "unsafe": [(경로, 사유), ...],
                "warn": [(경로, 사유), ...],
                "error": [(경로, 사유), ...]
            }
        """
        result = {"safe": [], "unsafe": [], "warn": [], "error": []}
        total = len(image_paths)

        for i, path in enumerate(image_paths):
            status, reason = self.review_image(path, channel_type)

            if status == "SAFE":
                result["safe"].append(path)
            elif status == "UNSAFE":
                result["unsafe"].append((path, reason))
            elif status == "WARN":
                result["warn"].append((path, reason))
            else:
                result["error"].append((path, reason))

            if progress_callback:
                progress_callback(i + 1, total)

        logger.info(f"[검수관] 일괄 검수 완료: "
                    f"SAFE={len(result['safe'])}, "
                    f"UNSAFE={len(result['unsafe'])}, "
                    f"WARN={len(result['warn'])}, "
                    f"ERROR={len(result['error'])}")

        return result


# 싱글톤 인스턴스
content_reviewer = GeminiContentReviewer()


# 편의 함수
def review_image(image_path: str, channel_type: str = "daily_life_toon") -> Tuple[str, str]:
    """이미지 검수 (간편 호출)"""
    return content_reviewer.review_image(image_path, channel_type)


def review_and_regenerate(
    image_path: str,
    regenerate_callback: Callable,
    channel_type: str = "daily_life_toon",
    max_retries: int = 3
) -> Tuple[bool, str]:
    """검수 후 재생성 (간편 호출)"""
    return content_reviewer.review_and_regenerate(
        image_path, regenerate_callback, channel_type, max_retries
    )
