# Reverie Insight - AI 문지기 (Gemini Vision)
# Version: 1.1.0

"""
AI 문지기 - Gemini Vision 기반 콘텐츠 필터링

Level 1: REAL vs FACELESS 분류
Level 2: 스타일 분류 (silhouette, slideshow 등)
Level 3: 제작 가능성 필터 (RTX 4060 Ti 8GB 기준)
"""

import os
import json
import logging
import base64
import re
import requests
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


def _redact_gemini_key(text: str) -> str:
    return re.sub(r"([?&]key=)[^&\s]+", r"\1<redacted>", str(text or ""))


# ============================================================
# 분류 기준 (Reverie Filtering Protocol v1.1)
# ============================================================

class ContentType(Enum):
    """Level 1: 콘텐츠 유형"""
    REAL = "REAL"           # 실제 인물 출연 (연예인, 유튜버 등)
    FACELESS = "FACELESS"   # 얼굴 없는 콘텐츠
    UNKNOWN = "UNKNOWN"


class StyleType(Enum):
    """Level 2: Faceless 스타일 유형"""
    # PASS - 제작 가능
    SILHOUETTE = "silhouette"           # 실루엣/그림자
    SLIDESHOW = "slideshow"             # 이미지 슬라이드쇼
    ILLUSTRATION_2D = "2d_illustration" # 2D 일러스트
    PIXEL_ART = "pixel_art"             # 픽셀 아트
    AI_GENERATED = "ai_generated"       # AI 생성 이미지
    LOFI_ANIMATION = "lofi_animation"   # 간단한 애니메이션
    SCREEN_CAPTURE = "screen_capture"   # 화면 캡처/튜토리얼
    TEXT_BASED = "text_based"           # 텍스트 기반
    STOCK_FOOTAGE = "stock_footage"     # 스톡 영상/이미지

    # DROP - 제작 불가
    HIGH_POLY_3D = "3d_high_poly"           # 고퀄리티 3D
    COMPLEX_MOTION = "complex_motion"        # 복잡한 모션그래픽
    HAND_DRAWING = "hand_drawing_timelapse"  # 손그림 타임랩스
    STOP_MOTION = "stop_motion"              # 스톱모션
    HIGH_FRAME_ANIM = "high_frame_animation" # 고프레임 애니메이션

    UNKNOWN = "unknown"


# 제작 가능한 스타일 (PASS)
PASS_STYLES = {
    StyleType.SILHOUETTE,
    StyleType.SLIDESHOW,
    StyleType.ILLUSTRATION_2D,
    StyleType.PIXEL_ART,
    StyleType.AI_GENERATED,
    StyleType.LOFI_ANIMATION,
    StyleType.SCREEN_CAPTURE,
    StyleType.TEXT_BASED,
    StyleType.STOCK_FOOTAGE,
}

# 제작 불가능한 스타일 (DROP)
DROP_STYLES = {
    StyleType.HIGH_POLY_3D,
    StyleType.COMPLEX_MOTION,
    StyleType.HAND_DRAWING,
    StyleType.STOP_MOTION,
    StyleType.HIGH_FRAME_ANIM,
}


# ============================================================
# 분석 결과 데이터 클래스
# ============================================================

@dataclass
class AnalysisResult:
    """영상 분석 결과"""
    video_id: str

    # Level 1
    content_type: str  # REAL / FACELESS / UNKNOWN
    content_confidence: float  # 0.0 ~ 1.0

    # Level 2
    style_type: str  # silhouette, slideshow, etc.
    style_confidence: float

    # Level 3
    feasibility_score: int  # 0 ~ 100
    can_replicate: bool
    clone_difficulty: str  # EASY / MEDIUM / HARD / IMPOSSIBLE

    # 추가 정보
    drop_reason: Optional[str] = None  # DROP인 경우 이유
    replication_tips: Optional[str] = None  # 복제 팁
    raw_response: Optional[str] = None  # Gemini 원본 응답


# ============================================================
# AI 문지기 클래스
# ============================================================

class AIGatekeeper:
    """Gemini Vision 기반 AI 문지기"""

    # Gemini API 엔드포인트
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    def __init__(self, api_key: str = None):
        """
        Args:
            api_key: Gemini API 키 (없으면 환경변수/설정파일에서 로드)
        """
        self.api_key = api_key or self._load_api_key()
        if not self.api_key:
            raise ValueError("Gemini API 키가 필요합니다")

        logger.info("AIGatekeeper 초기화 완료")

    def _load_api_key(self) -> Optional[str]:
        """API 키 로드"""
        # 환경변수
        key = os.environ.get('GEMINI_API_KEY')
        if key:
            return key

        # api_settings.json
        try:
            from config.settings import config as app_config

            settings_path = Path(app_config.DATA_DIR) / "api_settings.json"
        except Exception:
            base_dir = Path(__file__).parent.parent.parent
            settings_path = base_dir / "data" / "api_settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    return settings.get('gemini_api_key')
            except (json.JSONDecodeError, OSError):
                pass

        return None

    def analyze_video(
        self,
        video_id: str,
        title: str,
        description: str,
        thumbnail_url: str,
        channel_title: str = "",
        category_name: str = "",
        tags: List[str] = None
    ) -> AnalysisResult:
        """
        단일 영상 분석

        Args:
            video_id: YouTube 영상 ID
            title: 영상 제목
            description: 영상 설명
            thumbnail_url: 썸네일 URL
            channel_title: 채널명
            category_name: 카테고리명
            tags: 태그 목록

        Returns:
            AnalysisResult: 분석 결과
        """
        tags = tags or []

        # 프롬프트 구성
        prompt = self._build_analysis_prompt(
            title=title,
            description=description,
            channel_title=channel_title,
            category_name=category_name,
            tags=tags
        )

        # Gemini API 호출 (텍스트 + 이미지)
        try:
            response = self._call_gemini_with_image(prompt, thumbnail_url)
            result = self._parse_response(video_id, response)
            return result
        except Exception as e:
            safe_error = _redact_gemini_key(str(e))
            logger.error(f"분석 실패 (video_id={video_id}): {safe_error}")
            return self._create_error_result(video_id, safe_error)

    def analyze_batch(
        self,
        videos: List[Dict[str, Any]],
        progress_callback: callable = None
    ) -> List[AnalysisResult]:
        """
        여러 영상 일괄 분석

        Args:
            videos: VideoMetadata 딕셔너리 목록
            progress_callback: 진행 콜백 (current, total, video_title)

        Returns:
            List[AnalysisResult]: 분석 결과 목록
        """
        results = []
        total = len(videos)

        for i, video in enumerate(videos):
            if progress_callback:
                progress_callback(i + 1, total, video.get('title', ''))

            result = self.analyze_video(
                video_id=video.get('video_id', ''),
                title=video.get('title', ''),
                description=video.get('description', ''),
                thumbnail_url=video.get('thumbnail_high_url') or video.get('thumbnail_url', ''),
                channel_title=video.get('channel_title', ''),
                category_name=video.get('category_name', ''),
                tags=video.get('tags', [])
            )
            results.append(result)

        return results

    def _build_analysis_prompt(
        self,
        title: str,
        description: str,
        channel_title: str,
        category_name: str,
        tags: List[str]
    ) -> str:
        """분석 프롬프트 구성"""

        tags_str = ", ".join(tags[:10]) if tags else "없음"

        prompt = f"""당신은 YouTube 콘텐츠 분석 전문가입니다. 아래 영상 정보와 썸네일을 분석하여 JSON 형식으로 응답해주세요.

## 영상 정보
- 제목: {title}
- 채널: {channel_title}
- 카테고리: {category_name}
- 태그: {tags_str}
- 설명: {description[:300]}...

## 분석 기준
목표: "RTX 4060 Ti 로컬 PC에서, 하루 10개 이상 찍어낼 수 있는가?"

### Level 1: 콘텐츠 유형
- REAL: 실제 인물이 출연하는 콘텐츠 (연예인, 유튜버, 인터뷰, 브이로그 등)
- FACELESS: 얼굴이 나오지 않는 콘텐츠 (나레이션, 텍스트, 일러스트, 화면녹화 등)

### Level 2: 스타일 유형 (FACELESS인 경우만)
- silhouette: 실루엣/그림자 스타일
- slideshow: 이미지 슬라이드쇼
- 2d_illustration: 2D 일러스트/만화
- pixel_art: 픽셀 아트
- ai_generated: AI 생성 이미지/영상
- lofi_animation: 간단한 애니메이션
- screen_capture: 화면 캡처/튜토리얼
- text_based: 텍스트 기반
- stock_footage: 스톡 영상/이미지
- 3d_high_poly: 고퀄리티 3D 모델링
- complex_motion: 복잡한 모션그래픽
- hand_drawing_timelapse: 손그림 타임랩스
- stop_motion: 스톱모션
- high_frame_animation: 고프레임 애니메이션

### Level 3: 제작 가능성 점수표 (RTX 4060 Ti 8GB 기준)

**0점 (절대 불가 / 폐기)**
- 유명 연예인 얼굴 노출 (저작권 Risk)
- 실제 방송국 영상 클립 (저작권 Risk)
- 복잡한 3D 애니메이션 (블렌더/마야급)
- 실사 촬영 필수 (먹방, 브이로그, 제품 리뷰)

**50점 (가능은 한데... 보류)**
- 화려한 모션 그래픽 (애프터이펙트 떡칠)
- 고난도 편집 템포 (1초에 컷 3번 바뀜)
- 특정 인물의 리액션이 영상의 핵심일 때

**80점 (꿀통)**
- 정보 전달형: 관련 자료화면(Stock)만 계속 깔아두면 되는 영상
- 단순 썰/낭독: 텍스트가 메인이고 화면은 거들 뿐인 영상
- 랭킹/순위: 1위~10위 이미지 슬라이드쇼

**100점 (Reverie 최적화)**
- 정적인 이미지 + 내레이션: 움직임 거의 없음
- 실루엣/일러스트 스타일: SD로 생성하기 가장 쉬움
- 뉴스/기사 요약: 캡처 화면 + 하이라이트 박스

## 응답 형식 (JSON)
```json
{{
  "content_type": "REAL 또는 FACELESS",
  "content_confidence": 0.0~1.0,
  "style_type": "스타일 유형 (FACELESS인 경우)",
  "style_confidence": 0.0~1.0,
  "feasibility_score": 0~100,
  "can_replicate": true/false,
  "clone_difficulty": "EASY/MEDIUM/HARD/IMPOSSIBLE",
  "drop_reason": "DROP인 경우 이유 (없으면 null)",
  "replication_tips": "복제 팁 (가능한 경우, 구체적으로)"
}}
```

can_replicate 기준:
- true: feasibility_score >= 70
- false: feasibility_score < 70

clone_difficulty 기준:
- EASY: 90-100점 (즉시 복제 가능)
- MEDIUM: 70-89점 (약간의 수정 필요)
- HARD: 50-69점 (상당한 노력 필요)
- IMPOSSIBLE: 0-49점 (복제 불가)

JSON만 응답해주세요. 다른 설명은 필요 없습니다."""

        return prompt

    def _call_gemini_with_image(self, prompt: str, image_url: str) -> str:
        """Gemini API 호출 (이미지 포함)"""

        # 이미지 다운로드 및 base64 인코딩
        image_data = None
        try:
            img_response = requests.get(image_url, timeout=10)
            if img_response.status_code == 200:
                image_data = base64.b64encode(img_response.content).decode('utf-8')
        except Exception as e:
            logger.warning(f"썸네일 다운로드 실패: {e}")

        # API 요청 구성
        url = f"{self.GEMINI_API_URL}?key={self.api_key}"

        parts = [{"text": prompt}]

        if image_data:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_data
                }
            })

        payload = {
            "contents": [{
                "parts": parts
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024
            }
        }

        response = requests.post(url, json=payload, timeout=30)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(_redact_gemini_key(str(exc))) from None

        data = response.json()

        # 응답 텍스트 추출
        try:
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text
        except (KeyError, IndexError) as e:
            raise ValueError(f"Gemini 응답 파싱 실패: {data}")

    def _parse_response(self, video_id: str, response: str) -> AnalysisResult:
        """Gemini 응답 파싱"""

        # JSON 추출
        try:
            # ```json ... ``` 형식 처리
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}\n응답: {response}")
            return self._create_error_result(video_id, f"JSON 파싱 실패: {e}")

        # 결과 생성
        content_type = data.get('content_type', 'UNKNOWN')
        style_type = data.get('style_type', 'unknown')
        feasibility_score = data.get('feasibility_score', 0)
        can_replicate = data.get('can_replicate', False)

        return AnalysisResult(
            video_id=video_id,
            content_type=content_type,
            content_confidence=data.get('content_confidence', 0.0),
            style_type=style_type if content_type == 'FACELESS' else 'N/A',
            style_confidence=data.get('style_confidence', 0.0),
            feasibility_score=feasibility_score,
            can_replicate=can_replicate,
            clone_difficulty=data.get('clone_difficulty', 'UNKNOWN'),
            drop_reason=data.get('drop_reason'),
            replication_tips=data.get('replication_tips'),
            raw_response=response
        )

    def _create_error_result(self, video_id: str, error_msg: str) -> AnalysisResult:
        """에러 결과 생성"""
        return AnalysisResult(
            video_id=video_id,
            content_type="UNKNOWN",
            content_confidence=0.0,
            style_type="unknown",
            style_confidence=0.0,
            feasibility_score=0,
            can_replicate=False,
            clone_difficulty="UNKNOWN",
            drop_reason=f"분석 오류: {error_msg}",
            replication_tips=None,
            raw_response=None
        )

    def get_summary_stats(self, results: List[AnalysisResult]) -> Dict[str, Any]:
        """분석 결과 요약 통계"""
        total = len(results)
        if total == 0:
            return {"total": 0}

        real_count = sum(1 for r in results if r.content_type == "REAL")
        faceless_count = sum(1 for r in results if r.content_type == "FACELESS")
        replicable_count = sum(1 for r in results if r.can_replicate)

        # 스타일별 카운트
        style_counts = {}
        for r in results:
            if r.content_type == "FACELESS":
                style = r.style_type
                style_counts[style] = style_counts.get(style, 0) + 1

        # 난이도별 카운트
        difficulty_counts = {}
        for r in results:
            diff = r.clone_difficulty
            difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1

        # 평균 feasibility score (FACELESS만)
        faceless_scores = [r.feasibility_score for r in results if r.content_type == "FACELESS"]
        avg_score = sum(faceless_scores) / len(faceless_scores) if faceless_scores else 0

        # v60.1.0: 빈 결과 방어 (ZeroDivisionError)
        if total == 0:
            return {
                "total": 0, "real_count": 0, "faceless_count": 0,
                "replicable_count": 0, "drop_count": 0,
                "real_percent": 0, "faceless_percent": 0, "replicable_percent": 0,
                "avg_feasibility_score": 0, "style_distribution": {}, "difficulty_distribution": {}
            }

        return {
            "total": total,
            "real_count": real_count,
            "faceless_count": faceless_count,
            "replicable_count": replicable_count,
            "drop_count": total - replicable_count,
            "real_percent": round(real_count / total * 100, 1),
            "faceless_percent": round(faceless_count / total * 100, 1),
            "replicable_percent": round(replicable_count / total * 100, 1),
            "avg_feasibility_score": round(avg_score, 1),
            "style_distribution": style_counts,
            "difficulty_distribution": difficulty_counts
        }


# ============================================================
# CLI 테스트
# ============================================================

def main():
    """CLI 테스트"""
    import sys

    # 테스트 데이터
    test_video = {
        "video_id": "test123",
        "title": "1월 26일부터, 보조배터리는 애물단지 됩니다!",
        "description": "공항 보조배터리 규정 변경 안내",
        "thumbnail_url": "https://i.ytimg.com/vi/test123/hqdefault.jpg",
        "channel_title": "테스트채널",
        "category_name": "Education",
        "tags": ["보조배터리", "공항", "여행"]
    }

    try:
        gatekeeper = AIGatekeeper()
        print("AIGatekeeper 초기화 성공")

        print(f"\n테스트 영상: {test_video['title']}")
        result = gatekeeper.analyze_video(**test_video)

        print(f"\n=== 분석 결과 ===")
        print(f"Content Type: {result.content_type} ({result.content_confidence:.0%})")
        print(f"Style Type: {result.style_type} ({result.style_confidence:.0%})")
        print(f"Feasibility: {result.feasibility_score}/100")
        print(f"Can Replicate: {result.can_replicate}")
        print(f"Difficulty: {result.clone_difficulty}")
        if result.drop_reason:
            print(f"Drop Reason: {result.drop_reason}")
        if result.replication_tips:
            print(f"Tips: {result.replication_tips}")

    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
