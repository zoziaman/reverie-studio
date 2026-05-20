# src/core/evaluators.py
# ============================================================
# v56.8: PDCA Evaluator 모듈
# bkit 스타일 품질 검증 시스템
# - StoryCritic: Gemini 기반 대본/스토리바이블 품질 평가
# - VisualCritic: Gemini Vision 기반 이미지 일관성 검증
# ============================================================
import os
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum


# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("evaluators")
except ImportError:
    logger = logging.getLogger("evaluators")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)

from utils.gemini_compat import (
    GEMINI_AVAILABLE,
    configure_gemini,
    generate_vision_content,
    get_gemini_model,
)


# ============================================================
# 평가 결과 데이터 클래스
# ============================================================
@dataclass
class EvaluationResult:
    """
    평가 결과 데이터 클래스

    E-O 패턴에서 Evaluator가 반환하는 표준 형식
    """
    score: int = 0                      # 0-100 점수
    passed: bool = False                # 합격 여부 (threshold 기준)
    feedback: str = ""                  # 개선을 위한 피드백
    details: Dict[str, Any] = field(default_factory=dict)  # 상세 평가 항목
    improved_content: Optional[str] = None  # Optimizer가 제안한 개선 버전

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "score": self.score,
            "passed": self.passed,
            "feedback": self.feedback,
            "details": self.details,
            "improved_content": self.improved_content
        }


# ============================================================
# 채널별 평가 기준
# ============================================================
CHANNEL_CRITERIA = {
    "horror": {
        "tone": "공포, 긴장감, 미스터리",
        "elements": ["반전", "복선", "긴장 고조", "공포 분위기"],
        "avoid": ["과도한 폭력", "혐오 표현", "정치적 내용"],
        "visual_style": "어둡고 음침한 분위기, 그림자 활용, 차가운 색감"
    },
    "senior_touching": {
        "tone": "감동, 가족애, 따뜻함",
        "elements": ["가족 간의 사랑", "인생의 교훈", "세대 간 화해", "희망적 결말"],
        "avoid": ["자극적 내용", "부정적 결말", "폭력"],
        "visual_style": "따뜻한 색감, 부드러운 조명, 가정적 분위기"
    },
    "senior_makjang": {
        "tone": "드라마틱, 갈등, 반전",
        "elements": ["가족 갈등", "재산 분쟁", "숨겨진 비밀", "극적 반전"],
        "avoid": ["지나친 막장", "범죄 미화", "차별 표현"],
        "visual_style": "드라마틱 조명, 대비 강한 색감, 긴장감 있는 구도"
    }
}

# 기본 평가 기준 (채널 타입 없을 때)
DEFAULT_CRITERIA = {
    "tone": "자연스럽고 몰입감 있는",
    "elements": ["개연성", "캐릭터 일관성", "흥미로운 전개"],
    "avoid": ["비논리적 전개", "부적절한 내용"],
    "visual_style": "일관된 스타일, 고품질"
}


# ============================================================
# StoryCritic: 대본/스토리바이블 평가자
# ============================================================
# VideoToon packs are the production defaults after the 2026-05 pivot. Keep the
# legacy criteria above as aliases only; new runtime channels should evaluate
# against layered webtoon consistency and story specificity.
CHANNEL_CRITERIA.update({
    "daily_life_toon": {
        "tone": "natural Korean daily-life webtoon drama with specific, lived-in details",
        "elements": ["fresh everyday dilemma", "consistent recurring cast", "clear emotional choice", "scene-specific props"],
        "avoid": ["generic family melodrama", "AI-template repetition", "unmotivated twist", "flat narration"],
        "visual_style": "premium Korean webtoon video-toon, reusable background layer, character foreground, readable facial acting",
    },
    "mystery_toon": {
        "tone": "restrained Korean mystery webtoon with grounded clues and character suspicion",
        "elements": ["concrete clue object", "quiet escalation", "fair-play reveal", "consistent recurring cast"],
        "avoid": ["jump-scare horror", "gore", "random occult reveal", "exploitative shock"],
        "visual_style": "premium Korean mystery webtoon video-toon, layered background, character foreground, controlled shadows",
    },
})


class StoryCritic:
    """
    대본 및 스토리바이블 품질 평가자

    v56.8: Gemini를 이용한 텍스트 콘텐츠 품질 검증
    - E-O 패턴의 Evaluator 역할
    - 채널별 맞춤 평가 기준 적용
    """

    def __init__(self, api_key: Optional[str] = None, threshold: int = 80):
        """
        초기화

        Args:
            api_key: Gemini API 키 (없으면 config에서 로드)
            threshold: 합격 기준 점수 (기본 80)
        """
        self.threshold = threshold
        self._model = None

        # API 키 설정
        if api_key:
            self._api_key = api_key
        else:
            try:
                from config.settings import config
                self._api_key = config.GEMINI_API_KEY
            except ImportError:
                self._api_key = os.getenv("GEMINI_API_KEY", "")

        # 모델 초기화
        if GEMINI_AVAILABLE and self._api_key:
            try:
                if configure_gemini(self._api_key):
                    self._model = get_gemini_model("gemini-1.5-flash")
                logger.info("[StoryCritic] Gemini 모델 초기화 완료")
            except Exception as e:
                logger.error(f"[StoryCritic] 모델 초기화 실패: {e}")

    @property
    def is_available(self) -> bool:
        """사용 가능 여부"""
        return self._model is not None

    def evaluate_story_bible(
        self,
        bible: str,
        channel_type: str = "default"
    ) -> EvaluationResult:
        """
        스토리바이블 평가

        대본 작성 전 설계 문서(세계관, 캐릭터, 줄거리)를 평가

        Args:
            bible: 스토리바이블 텍스트 또는 JSON
            channel_type: 채널 타입 (horror, senior_touching 등)

        Returns:
            EvaluationResult: 평가 결과
        """
        if not self.is_available:
            logger.warning("[StoryCritic] 모델 미사용 가능, 기본 통과 처리")
            return EvaluationResult(score=70, passed=True, feedback="평가 스킵됨")

        criteria = CHANNEL_CRITERIA.get(channel_type, DEFAULT_CRITERIA)

        prompt = f"""당신은 YouTube 영상 대본의 품질을 평가하는 전문가입니다.

다음 스토리바이블(기획 문서)을 평가해주세요:

---
{bible}
---

평가 기준 ({channel_type} 채널):
- 톤앤매너: {criteria['tone']}
- 필수 요소: {', '.join(criteria['elements'])}
- 금지 요소: {', '.join(criteria['avoid'])}

다음 JSON 형식으로 응답해주세요:
{{
    "score": 0-100 사이 점수,
    "passed": true/false (80점 이상이면 true),
    "feedback": "개선이 필요한 부분 설명",
    "details": {{
        "coherence": 0-100,  // 개연성/논리성
        "originality": 0-100,  // 참신함
        "channel_fit": 0-100,  // 채널 정체성 부합
        "engagement": 0-100  // 몰입도/흥미
    }},
    "suggestions": ["개선 제안 1", "개선 제안 2"]
}}"""

        try:
            response = self._model.generate_content(prompt)
            result_text = response.text

            # JSON 파싱
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result_json = json.loads(result_text[json_start:json_end])

                return EvaluationResult(
                    score=result_json.get("score", 0),
                    passed=result_json.get("passed", False),
                    feedback=result_json.get("feedback", ""),
                    details={
                        "coherence": result_json.get("details", {}).get("coherence", 0),
                        "originality": result_json.get("details", {}).get("originality", 0),
                        "channel_fit": result_json.get("details", {}).get("channel_fit", 0),
                        "engagement": result_json.get("details", {}).get("engagement", 0),
                        "suggestions": result_json.get("suggestions", [])
                    }
                )
        except Exception as e:
            logger.error(f"[StoryCritic] 평가 실패: {e}")

        return EvaluationResult(score=0, passed=False, feedback=f"평가 오류: {e}")

    def evaluate_script(
        self,
        script: List[Dict[str, Any]],
        channel_type: str = "default"
    ) -> EvaluationResult:
        """
        완성된 대본 평가

        Args:
            script: 대본 리스트 [{"text": "...", "image_prompt": "..."}]
            channel_type: 채널 타입

        Returns:
            EvaluationResult: 평가 결과
        """
        if not self.is_available:
            return EvaluationResult(score=70, passed=True, feedback="평가 스킵됨")

        # 대본을 텍스트로 변환
        script_text = "\n".join([
            f"[장면 {i+1}] {item.get('text', '')}"
            for i, item in enumerate(script)
        ])

        criteria = CHANNEL_CRITERIA.get(channel_type, DEFAULT_CRITERIA)

        prompt = f"""당신은 YouTube 영상 대본의 품질을 평가하는 전문가입니다.

다음 대본을 평가해주세요:

---
{script_text[:5000]}  # 토큰 제한
---

평가 기준 ({channel_type} 채널):
- 톤앤매너: {criteria['tone']}
- 필수 요소: {', '.join(criteria['elements'])}

다음 JSON 형식으로 응답:
{{
    "score": 0-100,
    "passed": true/false,
    "feedback": "개선점",
    "details": {{
        "flow": 0-100,  // 흐름/전개
        "dialogue": 0-100,  // 대사 자연스러움
        "pacing": 0-100,  // 페이싱
        "ending": 0-100  // 결말 만족도
    }},
    "weak_scenes": [약한 장면 번호들]
}}"""

        try:
            response = self._model.generate_content(prompt)
            result_text = response.text

            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result_json = json.loads(result_text[json_start:json_end])

                return EvaluationResult(
                    score=result_json.get("score", 0),
                    passed=result_json.get("score", 0) >= self.threshold,
                    feedback=result_json.get("feedback", ""),
                    details=result_json.get("details", {})
                )
        except Exception as e:
            logger.error(f"[StoryCritic] 대본 평가 실패: {e}")

        return EvaluationResult(score=0, passed=False, feedback="평가 오류")

    def suggest_improvements(
        self,
        content: str,
        feedback: str,
        channel_type: str = "default"
    ) -> str:
        """
        개선된 버전 제안 (Optimizer 역할)

        Args:
            content: 원본 콘텐츠
            feedback: 평가 피드백
            channel_type: 채널 타입

        Returns:
            개선된 콘텐츠
        """
        if not self.is_available:
            return content

        criteria = CHANNEL_CRITERIA.get(channel_type, DEFAULT_CRITERIA)

        prompt = f"""다음 콘텐츠를 피드백에 따라 개선해주세요.

원본:
{content[:3000]}

피드백:
{feedback}

채널 스타일: {criteria['tone']}

개선된 버전만 출력해주세요 (설명 없이):"""

        try:
            response = self._model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"[StoryCritic] 개선 제안 실패: {e}")
            return content


# ============================================================
# VisualCritic: 이미지 스타일 일관성 검증자
# ============================================================
class VisualCritic:
    """
    이미지 스타일 일관성 검증자

    v56.8: Gemini Vision을 이용한 이미지 품질 검증
    - VisualBoard와의 스타일 일치도 검사
    - 캐릭터 외모 일관성 검증
    """

    def __init__(self, api_key: Optional[str] = None, threshold: int = 75):
        """
        초기화

        Args:
            api_key: Gemini API 키
            threshold: 합격 기준 점수
        """
        self.threshold = threshold
        self._model = None

        # API 키 설정
        if api_key:
            self._api_key = api_key
        else:
            try:
                from config.settings import config
                self._api_key = config.GEMINI_API_KEY
            except ImportError:
                self._api_key = os.getenv("GEMINI_API_KEY", "")

        # Vision 모델 초기화
        if GEMINI_AVAILABLE and self._api_key:
            try:
                if configure_gemini(self._api_key):
                    self._model = get_gemini_model("gemini-1.5-flash")
                logger.info("[VisualCritic] Gemini Vision 모델 초기화 완료")
            except Exception as e:
                logger.error(f"[VisualCritic] 모델 초기화 실패: {e}")

    @property
    def is_available(self) -> bool:
        """사용 가능 여부"""
        return self._model is not None

    def _load_image(self, image_path: str) -> Optional[str]:
        """이미지 경로 유효성 확인."""
        return image_path if os.path.exists(image_path) else None

    def evaluate_style_consistency(
        self,
        image_path: str,
        visual_board: Dict[str, Any],
        channel_type: str = "default"
    ) -> EvaluationResult:
        """
        스타일 일관성 평가

        VisualBoard에 정의된 스타일과 이미지가 일치하는지 검증

        Args:
            image_path: 평가할 이미지 경로
            visual_board: 비주얼 가이드 {"style": "...", "colors": [...], "mood": "..."}
            channel_type: 채널 타입

        Returns:
            EvaluationResult: 평가 결과
        """
        if not self.is_available:
            return EvaluationResult(score=70, passed=True, feedback="Vision 평가 스킵됨")

        image_data = self._load_image(image_path)
        if not image_data:
            return EvaluationResult(score=0, passed=False, feedback="이미지 로드 실패")

        criteria = CHANNEL_CRITERIA.get(channel_type, DEFAULT_CRITERIA)

        prompt = f"""이 이미지가 다음 비주얼 가이드와 일치하는지 평가해주세요.

비주얼 가이드:
- 스타일: {visual_board.get('style', criteria['visual_style'])}
- 분위기: {visual_board.get('mood', criteria['tone'])}
- 색감: {visual_board.get('colors', '지정 없음')}

JSON으로 응답:
{{
    "score": 0-100,
    "passed": true/false,
    "feedback": "불일치 부분 설명",
    "details": {{
        "style_match": 0-100,
        "mood_match": 0-100,
        "color_match": 0-100,
        "quality": 0-100
    }},
    "improved_prompt": "개선된 이미지 프롬프트 제안"
}}"""

        try:
            response = generate_vision_content(self._model, prompt, [image_data])
            if response is None:
                raise RuntimeError("Vision 응답 없음")
            result_text = response.text

            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result_json = json.loads(result_text[json_start:json_end])

                return EvaluationResult(
                    score=result_json.get("score", 0),
                    passed=result_json.get("score", 0) >= self.threshold,
                    feedback=result_json.get("feedback", ""),
                    details=result_json.get("details", {}),
                    improved_content=result_json.get("improved_prompt")
                )
        except Exception as e:
            logger.error(f"[VisualCritic] 스타일 평가 실패: {e}")

        return EvaluationResult(score=0, passed=False, feedback="평가 오류")

    def evaluate_character_consistency(
        self,
        current_image: str,
        reference_images: List[str],
        character_description: str = ""
    ) -> EvaluationResult:
        """
        캐릭터 일관성 평가

        이전 장면의 캐릭터와 현재 이미지의 캐릭터가 동일인인지 검증

        Args:
            current_image: 현재 이미지 경로
            reference_images: 참조 이미지 경로 리스트
            character_description: 캐릭터 설명

        Returns:
            EvaluationResult: 평가 결과
        """
        if not self.is_available:
            return EvaluationResult(score=70, passed=True, feedback="일관성 검사 스킵됨")

        current_data = self._load_image(current_image)
        if not current_data:
            return EvaluationResult(score=0, passed=False, feedback="현재 이미지 로드 실패")

        # 참조 이미지 로드 (최대 2개)
        ref_images = []
        for ref_path in reference_images[:2]:
            ref_data = self._load_image(ref_path)
            if ref_data:
                ref_images.append(ref_data)

        if not ref_images:
            return EvaluationResult(score=70, passed=True, feedback="참조 이미지 없음, 스킵")

        prompt = f"""이 이미지들에서 캐릭터의 일관성을 평가해주세요.

캐릭터 설명: {character_description or '지정 없음'}

첫 번째 이미지가 현재 장면, 나머지가 이전 장면입니다.
같은 캐릭터로 보이는지 확인해주세요.

JSON으로 응답:
{{
    "score": 0-100,
    "passed": true/false,
    "feedback": "불일치 부분",
    "details": {{
        "face_match": 0-100,
        "clothing_match": 0-100,
        "overall_consistency": 0-100
    }}
}}"""

        try:
            response = generate_vision_content(self._model, prompt, [current_data, *ref_images])
            if response is None:
                raise RuntimeError("Vision 응답 없음")
            result_text = response.text

            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result_json = json.loads(result_text[json_start:json_end])

                return EvaluationResult(
                    score=result_json.get("score", 0),
                    passed=result_json.get("score", 0) >= self.threshold,
                    feedback=result_json.get("feedback", ""),
                    details=result_json.get("details", {})
                )
        except Exception as e:
            logger.error(f"[VisualCritic] 캐릭터 일관성 평가 실패: {e}")

        return EvaluationResult(score=0, passed=False, feedback="평가 오류")


# ============================================================
# 편의 함수
# ============================================================
def get_story_critic(threshold: int = 80) -> StoryCritic:
    """StoryCritic 인스턴스 생성"""
    return StoryCritic(threshold=threshold)


def get_visual_critic(threshold: int = 75) -> VisualCritic:
    """VisualCritic 인스턴스 생성"""
    return VisualCritic(threshold=threshold)
