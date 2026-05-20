# src/utils/thumbnail_reviewer.py
"""
v54.2: 썸네일 품질 검증 시스템 (Gemini Vision)

Gemini가 생성된 썸네일을 분석하고:
1. 품질 점수 매김
2. 문제점 지적
3. 개선 명령 생성
4. 자동 재생성 트리거

"AI가 AI를 검수한다"
"""
import os
import json
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from utils.gemini_compat import configure_gemini, generate_vision_content, get_gemini_model

logger = logging.getLogger(__name__)


class ThumbnailReviewer:
    """
    썸네일 품질 검증기

    Gemini Vision으로 썸네일을 분석하고 품질을 평가

    v54.7.2: Thread Safety 강화 (인스턴스 레벨 lock으로 병렬성 향상)
    """

    # 합격 기준 점수 (100점 만점)
    PASS_THRESHOLD = 70

    # 최대 재생성 시도 횟수
    MAX_RETRY = 3

    def __init__(self, api_key: str = None):
        """
        Args:
            api_key: Gemini API 키 (없으면 config에서 가져옴)
        """
        self.api_key = api_key

        # v54.7.2: 인스턴스 레벨 lock (다른 채널/프로젝트는 병렬 처리 가능)
        self._api_lock = threading.Lock()

        self._init_gemini()

    def _init_gemini(self):
        """Gemini 초기화"""
        try:
            if not self.api_key:
                from config.settings import config
                self.api_key = config.GEMINI_API_KEY

            if not configure_gemini(self.api_key):
                raise RuntimeError("Gemini API 초기화 실패")
            self.model = get_gemini_model("gemini-3-flash-preview")
            if self.model is None:
                raise RuntimeError("Gemini 모델 로드 실패")
            self.vision_available = True
            logger.info("Gemini 3.0 Flash Vision 초기화 완료")

        except Exception as e:
            logger.error(f"Gemini 초기화 실패: {e}")
            self.model = None
            self.vision_available = False

    def review_thumbnail(
        self,
        thumbnail_path: str,
        title: str,
        sub_title: str = "",
        category: str = "daily_life_toon",
        expected_emotion: str = None,
        story_summary: str = None,
        script_preview: str = None
    ) -> Dict[str, Any]:
        """
        썸네일 품질 검증 (v54.2: 대본 내용 기반 검증 추가)

        Args:
            thumbnail_path: 썸네일 이미지 경로
            title: 영상 제목 (썸네일에 들어간 텍스트)
            sub_title: 서브 텍스트
            category: 카테고리 (horror/touching/makjang)
            expected_emotion: 기대되는 감정
            story_summary: 스토리 요약 (1-2문장)
            script_preview: 대본 앞부분 (첫 500자 정도)

        Returns:
            {
                'passed': bool,           # 합격 여부
                'score': int,             # 총점 (100점 만점)
                'scores': {               # 세부 점수
                    'text_quality': int,      # 텍스트 가독성 (0-20)
                    'image_quality': int,     # 이미지 품질 (0-20)
                    'composition': int,       # 구도/배치 (0-20)
                    'click_appeal': int,      # 클릭 유도력 (0-20)
                    'content_match': int,     # 내용 일치도 (0-20) - v54.2 변경
                },
                'issues': [],             # 발견된 문제점
                'suggestions': [],        # 개선 제안
                'regenerate_prompt': str, # 재생성용 프롬프트 (불합격시)
                'review_text': str,       # 전체 리뷰 텍스트
                'content_mismatch': bool, # 내용 불일치 여부
            }
        """
        if not self.vision_available or not self.model:
            return self._fallback_review(thumbnail_path)

        if not os.path.exists(thumbnail_path):
            return {
                'passed': False,
                'score': 0,
                'issues': ['썸네일 파일이 존재하지 않습니다.'],
                'suggestions': [],
                'regenerate_prompt': None,
                'review_text': '파일 없음'
            }

        try:
            # 이미지 접근 가능 여부만 확인
            from PIL import Image
            Image.open(thumbnail_path)

            # 카테고리별 기대 요소
            category_expectations = {
                'horror': {
                    'mood': '공포, 긴장감, 어두운 분위기',
                    'colors': '어두운 톤, 빨간색 강조',
                    'elements': '불안한 표정, 어두운 배경, 긴장감 있는 구도'
                },
                'touching': {
                    'mood': '감동, 따뜻함, 희망',
                    'colors': '따뜻한 톤, 밝은 색상',
                    'elements': '미소, 가족, 자연, 희망적 이미지'
                },
                'makjang': {
                    'mood': '충격, 반전, 극적',
                    'colors': '강렬한 대비, 빨간색/노란색',
                    'elements': '놀란 표정, 충격적 상황, 극적 구도'
                }
            }

            expectations = category_expectations.get(category, category_expectations['horror'])

            # v54.2: 대본 내용이 있으면 포함
            story_context = ""
            if story_summary or script_preview:
                story_context = f"""
[영상 실제 내용] ⚠️ 중요: 썸네일이 이 내용과 맞는지 판단해주세요!
- 스토리 요약: {story_summary or '제공되지 않음'}
- 대본 미리보기: {(script_preview[:500] + '...') if script_preview and len(script_preview) > 500 else (script_preview or '제공되지 않음')}
"""

            # 프롬프트 구성
            prompt = f"""당신은 YouTube 썸네일 전문 검수관입니다.
아래 썸네일 이미지를 분석하고 품질을 평가해주세요.

[영상 정보]
- 메인 제목: {title}
- 서브 텍스트: {sub_title}
- 카테고리: {category}
- 기대 분위기: {expectations['mood']}
- 기대 색상: {expectations['colors']}
{story_context}

[평가 기준] (각 20점, 총 100점)
1. 텍스트 가독성 (text_quality)
   - 글자가 선명하게 보이는가?
   - 글자 깨짐이나 왜곡이 없는가?
   - 배경과 대비가 충분한가?

2. 이미지 품질 (image_quality)
   - AI 생성 티가 심하게 나는가?
   - 이상한 부분(손가락, 눈, 왜곡)이 있는가?
   - 해상도가 충분한가?

3. 구도/배치 (composition)
   - 텍스트와 이미지 배치가 적절한가?
   - 시선이 분산되지 않는가?
   - 핵심 요소가 잘 보이는가?

4. 클릭 유도력 (click_appeal)
   - 클릭하고 싶게 만드는가?
   - 궁금증을 유발하는가?
   - YouTube 추천 피드에서 눈에 띄겠는가?

5. 내용 일치도 (content_match) - ⚠️ 매우 중요!
   - 썸네일 이미지가 실제 영상 내용(스토리)과 맞는가?
   - 시청자가 썸네일을 보고 기대한 내용이 영상에 있겠는가?
   - 낚시 썸네일이 아닌가? (내용과 너무 다르면 감점)
   - 스토리의 핵심 요소가 썸네일에 반영되어 있는가?

[응답 형식 - 반드시 이 JSON 형식으로만 응답]
```json
{{
    "scores": {{
        "text_quality": 0,
        "image_quality": 0,
        "composition": 0,
        "click_appeal": 0,
        "content_match": 0
    }},
    "total_score": 0,
    "issues": ["발견된 문제점 1", "발견된 문제점 2"],
    "content_mismatch_reason": "내용 불일치 이유 (있을 경우)",
    "suggestions": ["개선 제안 1", "개선 제안 2"],
    "regenerate_needed": true/false,
    "regenerate_prompt": "재생성시 사용할 프롬프트 (영어로, SD용). 반드시 스토리 내용을 반영해서 작성!",
    "suggested_scene": "이 스토리에 맞는 썸네일 장면 제안 (한국어)",
    "summary": "한 줄 요약"
}}
```

이미지를 분석하고 위 JSON 형식으로만 응답해주세요.
특히 '내용 일치도'를 꼼꼼히 평가해주세요. 썸네일이 스토리 내용과 맞지 않으면 시청자가 이탈합니다!
"""

            # v54.7.1: Thread Safe API 호출 (rate limiting)
            with self._api_lock:
                response = generate_vision_content(self.model, prompt, [thumbnail_path])
                if response is None:
                    raise RuntimeError("Vision 응답 없음")
                response_text = response.text

            # JSON 파싱
            result = self._parse_review_response(response_text)
            result['review_text'] = response_text

            # 합격 여부 판단
            result['passed'] = result.get('score', 0) >= self.PASS_THRESHOLD

            logger.info(f"썸네일 검수 완료: {result.get('score', 0)}점 ({'합격' if result['passed'] else '불합격'})")

            return result

        except Exception as e:
            logger.error(f"썸네일 검수 실패: {e}")
            return self._fallback_review(thumbnail_path)

    def _parse_review_response(self, response_text: str) -> Dict[str, Any]:
        """Gemini 응답 파싱"""
        try:
            # JSON 블록 추출
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)

            if json_match:
                json_str = json_match.group(1)
            else:
                # JSON 블록이 없으면 전체를 파싱 시도
                json_str = response_text

            data = json.loads(json_str)

            # 결과 구성
            scores = data.get('scores', {})
            total = sum(scores.values())

            # v54.2: 내용 불일치 체크
            content_score = scores.get('content_match', 20)
            content_mismatch = content_score < 12  # 12점 미만이면 내용 불일치

            return {
                'passed': total >= self.PASS_THRESHOLD and not content_mismatch,
                'score': total,
                'scores': scores,
                'issues': data.get('issues', []),
                'suggestions': data.get('suggestions', []),
                'regenerate_prompt': data.get('regenerate_prompt', ''),
                'summary': data.get('summary', ''),
                'content_mismatch': content_mismatch,
                'content_mismatch_reason': data.get('content_mismatch_reason', ''),
                'suggested_scene': data.get('suggested_scene', '')
            }

        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패, 텍스트 분석 시도: {e}")
            # 텍스트에서 점수 추출 시도
            return self._extract_from_text(response_text)

    def _extract_from_text(self, text: str) -> Dict[str, Any]:
        """텍스트에서 정보 추출 (JSON 파싱 실패시)"""
        import re

        # 점수 패턴 찾기
        score_patterns = {
            'text_quality': r'text_quality["\s:]+(\d+)',
            'image_quality': r'image_quality["\s:]+(\d+)',
            'composition': r'composition["\s:]+(\d+)',
            'click_appeal': r'click_appeal["\s:]+(\d+)',
            'mood_match': r'mood_match["\s:]+(\d+)',
        }

        scores = {}
        for key, pattern in score_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                scores[key] = min(20, max(0, int(match.group(1))))
            else:
                scores[key] = 10  # 기본값

        total = sum(scores.values())

        return {
            'passed': total >= self.PASS_THRESHOLD,
            'score': total,
            'scores': scores,
            'issues': ['자동 파싱 실패 - 수동 확인 필요'],
            'suggestions': [],
            'regenerate_prompt': '',
            'summary': text[:200] if text else ''
        }

    def _fallback_review(self, thumbnail_path: str) -> Dict[str, Any]:
        """Gemini 사용 불가시 기본 검수"""
        # 기본 이미지 체크만 수행
        try:
            from PIL import Image
            img = Image.open(thumbnail_path)
            width, height = img.size

            issues = []
            score = 70  # 기본 점수

            # 해상도 체크
            if width < 1280 or height < 720:
                issues.append(f"해상도 부족: {width}x{height} (권장: 1280x720)")
                score -= 10

            # 비율 체크
            ratio = width / height
            if abs(ratio - 16/9) > 0.1:
                issues.append(f"비율 불일치: {ratio:.2f} (권장: 16:9)")
                score -= 5

            return {
                'passed': score >= self.PASS_THRESHOLD,
                'score': score,
                'scores': {
                    'text_quality': 14,
                    'image_quality': 14,
                    'composition': 14,
                    'click_appeal': 14,
                    'mood_match': 14,
                },
                'issues': issues if issues else ['Gemini Vision 미사용 - 기본 검수만 수행'],
                'suggestions': ['Gemini API 키를 설정하면 상세 검수가 가능합니다.'],
                'regenerate_prompt': '',
                'review_text': 'Fallback review (Gemini unavailable)'
            }

        except Exception as e:
            return {
                'passed': False,
                'score': 0,
                'issues': [f'이미지 로드 실패: {str(e)}'],
                'suggestions': [],
                'regenerate_prompt': '',
                'review_text': f'Error: {str(e)}'
            }

    def review_and_regenerate(
        self,
        thumbnail_path: str,
        title: str,
        sub_title: str,
        category: str,
        regenerate_callback,
        max_attempts: int = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        검수 + 자동 재생성 루프

        Args:
            thumbnail_path: 썸네일 경로
            title: 제목
            sub_title: 서브 텍스트
            category: 카테고리
            regenerate_callback: 재생성 함수 (prompt를 받아 새 경로 반환)
            max_attempts: 최대 시도 횟수

        Returns:
            (success, final_path, final_review)
        """
        if max_attempts is None:
            max_attempts = self.MAX_RETRY

        current_path = thumbnail_path
        all_reviews = []

        for attempt in range(max_attempts):
            logger.info(f"썸네일 검수 시도 {attempt + 1}/{max_attempts}")

            # 검수
            review = self.review_thumbnail(
                current_path,
                title,
                sub_title,
                category
            )
            all_reviews.append(review)

            # 합격
            if review['passed']:
                logger.info(f"썸네일 합격! 점수: {review['score']}")
                return True, current_path, review

            # 불합격 - 재생성
            logger.warning(f"썸네일 불합격 (점수: {review['score']}), 재생성 시도...")

            if not review.get('regenerate_prompt'):
                logger.warning("재생성 프롬프트 없음, 기본 프롬프트 사용")
                regen_prompt = f"{category} style, dramatic, high quality, youtube thumbnail"
            else:
                regen_prompt = review['regenerate_prompt']

            # 재생성 콜백 호출
            try:
                new_path = regenerate_callback(regen_prompt)
                if new_path and os.path.exists(new_path):
                    current_path = new_path
                else:
                    logger.error("재생성 실패 - 새 경로 없음")
                    break
            except Exception as e:
                logger.error(f"재생성 콜백 오류: {e}")
                break

        # 최대 시도 초과
        logger.warning(f"최대 시도 횟수 초과, 마지막 결과 반환")
        return False, current_path, all_reviews[-1] if all_reviews else {}

    def get_improvement_tips(self, category: str) -> List[str]:
        """카테고리별 썸네일 개선 팁"""
        tips = {
            'horror': [
                "어두운 배경에 빨간색 텍스트가 잘 보입니다",
                "얼굴에 그림자를 넣으면 공포감이 올라갑니다",
                "눈만 밝게 처리하면 섬뜩한 느낌을 줍니다",
                "질문형 제목('왜?', '누가?')이 클릭률을 높입니다",
            ],
            'touching': [
                "따뜻한 톤의 배경이 감동을 강조합니다",
                "눈물 또는 미소 표정이 효과적입니다",
                "가족/관계를 암시하는 요소를 넣으세요",
                "희망적인 빛 효과가 좋습니다",
            ],
            'makjang': [
                "강렬한 색상 대비가 시선을 끕니다",
                "놀란 표정이나 충격적 상황을 보여주세요",
                "'충격', '반전' 같은 키워드가 효과적입니다",
                "두 인물의 대립 구도가 잘 먹힙니다",
            ]
        }

        return tips.get(category, tips['horror'])

    def compare_thumbnails(
        self,
        path_a: str,
        path_b: str,
        title: str,
        category: str
    ) -> Dict[str, Any]:
        """
        두 썸네일 비교 (A/B 테스트용)

        Returns:
            {
                'winner': 'A' or 'B',
                'score_a': int,
                'score_b': int,
                'reason': str
            }
        """
        if not self.vision_available:
            return {'winner': 'A', 'score_a': 70, 'score_b': 70, 'reason': 'Gemini 미사용'}

        review_a = self.review_thumbnail(path_a, title, "", category)
        review_b = self.review_thumbnail(path_b, title, "", category)

        score_a = review_a.get('score', 0)
        score_b = review_b.get('score', 0)

        if score_a > score_b:
            winner = 'A'
            reason = f"A가 {score_a - score_b}점 더 높음"
        elif score_b > score_a:
            winner = 'B'
            reason = f"B가 {score_b - score_a}점 더 높음"
        else:
            winner = 'A'  # 동점시 A
            reason = "동점 (기존 유지)"

        return {
            'winner': winner,
            'score_a': score_a,
            'score_b': score_b,
            'reason': reason,
            'review_a': review_a,
            'review_b': review_b
        }


# 전역 인스턴스
_reviewer_instance: Optional[ThumbnailReviewer] = None


def get_thumbnail_reviewer(api_key: str = None) -> ThumbnailReviewer:
    """ThumbnailReviewer 인스턴스 가져오기"""
    global _reviewer_instance

    if _reviewer_instance is None:
        _reviewer_instance = ThumbnailReviewer(api_key)

    return _reviewer_instance
