# Reverie Factory - 채널 클론 팩 생성기
# Version: 1.2.0

"""
채널 분석 데이터를 기반으로 완전한 레베리팩 생성

입력: 채널 분석 결과 (ChannelAnalysis)
출력: .revpack (실제 영상 생산 가능한 완전한 팩)

생성 콘텐츠:
├── prompts/
│   ├── pd_system.txt      ← 시나리오 생성 프롬프트 (그 채널 스타일)
│   ├── writer_system.txt  ← 대사 스타일 가이드
│   └── sd_prompts.json    ← 이미지 스타일 (비주얼 복제)
├── topics.json            ← 토픽 30개 + 각 토픽의 줄거리 요약
├── emotions.json          ← 필요한 감정 목록 + 샘플 대사
├── style_guide.json       ← SD 모델, 색감, 구도
├── channel_config.json    ← 영상 길이, 구조, 업로드 시간
└── TTS_GUIDE.md           ← 목소리 학습 가이드
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path

from utils.gemini_compat import GEMINI_AVAILABLE, configure_gemini, get_gemini_model
from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


@dataclass
class TopicWithOutline:
    """토픽 + 줄거리"""
    topic: str                    # 토픽 제목
    title_template: str           # 제목 템플릿 ("절대 ~하지 마세요" 스타일)
    outline: str                  # 줄거리 요약 (3-5문장)
    keywords: List[str]           # 관련 키워드
    estimated_duration: int       # 예상 영상 길이 (초)
    mood: str                     # 분위기 (tense, scary, mysterious 등)


@dataclass
class ClonePackContent:
    """클론 팩 콘텐츠"""
    # 메타
    pack_id: str
    source_channel: str
    source_channel_id: str
    created_at: str

    # 프롬프트
    pd_system_prompt: str         # 시나리오 생성 프롬프트
    writer_system_prompt: str     # 대사 스타일 프롬프트

    # 토픽
    topics: List[TopicWithOutline]

    # 비주얼
    sd_prompts: Dict[str, Any]    # positive, negative, style
    style_guide: Dict[str, Any]   # 색감, 구도, 모델

    # 오디오
    emotions: Dict[str, Any]      # 필요 감정 + 샘플 대사
    tts_guide: str                # TTS 가이드 마크다운

    # 채널 설정
    channel_config: Dict[str, Any]  # 영상 길이, 구조, 업로드 시간


class ClonePackGenerator:
    """채널 클론 팩 생성기"""

    VERSION = "1.2.0"

    def __init__(self, gemini_api_key: str = None):
        """
        Args:
            gemini_api_key: Gemini API 키
        """
        self.gemini_api_key = gemini_api_key or os.environ.get('GEMINI_API_KEY')
        self.gemini = None

        if GEMINI_AVAILABLE and self.gemini_api_key:
            try:
                if configure_gemini(self.gemini_api_key):
                    self.gemini = get_gemini_model("gemini-3-flash-preview")
                logger.info(f"[ClonePackGenerator] v{self.VERSION} Gemini 3.0 Flash 초기화 완료")
            except Exception as e:
                logger.warning(f"Gemini 초기화 실패: {redact_sensitive_text(e)}")

    # ============================================================
    # 메인 생성 함수
    # ============================================================

    def generate_clone_pack(
        self,
        channel_analysis: Dict[str, Any],
        num_topics: int = 30,
        progress_callback=None
    ) -> ClonePackContent:
        """
        채널 분석 데이터를 기반으로 클론 팩 생성

        Args:
            channel_analysis: 채널 분석 결과 (to_clone_recipe_data 형태)
            num_topics: 생성할 토픽 수
            progress_callback: 진행 콜백 (current, total, stage)

        Returns:
            ClonePackContent
        """
        channel_title = channel_analysis.get("channel_title", "Unknown")
        channel_id = channel_analysis.get("channel_id", "")
        channel_type = channel_analysis.get("channel_type", "general")

        # 콘텐츠 공식 추출
        formula = channel_analysis.get("content_formula", {})
        title_keywords = formula.get("title_keywords", [])
        title_patterns = formula.get("title_patterns", [])
        best_day = formula.get("best_upload_day", "")
        best_hour = formula.get("best_upload_hour", 20)

        # 메타데이터
        metadata = channel_analysis.get("metadata", {})
        avg_views = metadata.get("avg_views", 0)
        upload_freq = metadata.get("upload_frequency", 3)

        # TOP 영상 정보
        top_videos = channel_analysis.get("top_videos", [])
        ai_strategy = channel_analysis.get("ai_strategy", "")

        logger.info(f"[ClonePackGenerator] 클론 팩 생성 시작: {channel_title}")

        # 1. PD 시스템 프롬프트 생성
        if progress_callback:
            progress_callback(0, 100, "시나리오 프롬프트 생성")

        pd_system = self._generate_pd_system_prompt(
            channel_title, channel_type, title_keywords, title_patterns,
            top_videos, ai_strategy
        )

        # 2. 작가 시스템 프롬프트 생성
        if progress_callback:
            progress_callback(15, 100, "대사 스타일 프롬프트 생성")

        writer_system = self._generate_writer_system_prompt(
            channel_type, ai_strategy
        )

        # 3. 토픽 + 줄거리 생성
        if progress_callback:
            progress_callback(30, 100, f"토픽 {num_topics}개 생성")

        topics = self._generate_topics_with_outlines(
            channel_type, title_keywords, title_patterns,
            top_videos, num_topics
        )

        # 4. SD 프롬프트 생성
        if progress_callback:
            progress_callback(60, 100, "비주얼 스타일 생성")

        sd_prompts = self._generate_sd_prompts(channel_type)

        # 5. 스타일 가이드 생성
        style_guide = self._generate_style_guide(channel_type, channel_analysis)

        # 6. 감정 + TTS 가이드 생성
        if progress_callback:
            progress_callback(75, 100, "음성 가이드 생성")

        emotions = self._generate_emotions(channel_type)
        tts_guide = self._generate_tts_guide(channel_type, channel_title)

        # 7. 채널 설정 생성
        if progress_callback:
            progress_callback(90, 100, "채널 설정 생성")

        channel_config = self._generate_channel_config(
            channel_type, best_day, best_hour, upload_freq, channel_analysis
        )

        if progress_callback:
            progress_callback(100, 100, "완료")

        # 결과 조립
        pack = ClonePackContent(
            pack_id=f"clone_{channel_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            source_channel=channel_title,
            source_channel_id=channel_id,
            created_at=datetime.now().isoformat(),
            pd_system_prompt=pd_system,
            writer_system_prompt=writer_system,
            topics=topics,
            sd_prompts=sd_prompts,
            style_guide=style_guide,
            emotions=emotions,
            tts_guide=tts_guide,
            channel_config=channel_config
        )

        logger.info(f"[ClonePackGenerator] 클론 팩 생성 완료: {pack.pack_id}")
        return pack

    # ============================================================
    # PD 시스템 프롬프트 생성
    # ============================================================

    def _generate_pd_system_prompt(
        self,
        channel_title: str,
        channel_type: str,
        title_keywords: List[str],
        title_patterns: List[str],
        top_videos: List[Dict],
        ai_strategy: str
    ) -> str:
        """시나리오 생성용 PD 시스템 프롬프트 생성"""

        # 성공 영상 제목 예시
        top_titles = "\n".join([f"- {v.get('title', '')}" for v in top_videos[:5]])

        # 키워드/패턴 문자열
        keywords_str = ", ".join(title_keywords[:10]) if title_keywords else "없음"
        patterns_str = "\n".join([f"- {p}" for p in title_patterns[:5]]) if title_patterns else "- 없음"

        if self.gemini:
            prompt = f"""당신은 YouTube 채널 "{channel_title}"의 시나리오를 작성하는 PD입니다.

## 채널 분석 결과
- 장르: {channel_type}
- 자주 쓰는 키워드: {keywords_str}
- 제목 패턴:
{patterns_str}

## 성공한 영상 제목 예시
{top_titles}

## AI 전략 리포트 요약
{ai_strategy[:1000] if ai_strategy else "없음"}

---

위 분석을 바탕으로, 이 채널 스타일에 맞는 시나리오를 생성하기 위한 **시스템 프롬프트**를 작성해주세요.

시스템 프롬프트에 포함할 내용:
1. 이 채널의 콘텐츠 특성 (톤, 분위기, 구조)
2. 시나리오 작성 시 지켜야 할 규칙
3. 제목 작성 공식
4. 도입부/본문/마무리 구조 가이드
5. 피해야 할 것들

프롬프트는 한국어로, Gemini에게 지시하는 형태로 작성하세요.
"당신은 ~입니다" 형식으로 시작하세요."""

            try:
                response = self.gemini.generate_content(prompt)
                return response.text
            except Exception as e:
                logger.warning(f"PD 프롬프트 AI 생성 실패: {redact_sensitive_text(e)}")

        # 폴백: 템플릿 기반 생성
        return self._generate_pd_prompt_template(channel_type, keywords_str, patterns_str, top_titles)

    def _generate_pd_prompt_template(
        self,
        channel_type: str,
        keywords: str,
        patterns: str,
        top_titles: str
    ) -> str:
        """템플릿 기반 PD 프롬프트"""

        templates = {
            "horror": f"""당신은 공포/괴담 전문 유튜브 채널의 시나리오 작가입니다.

## 채널 특성
- 장르: 공포, 괴담, 미스터리
- 분위기: 어둡고 긴장감 있는, 몰입감 있는 스토리텔링
- 시청자: 공포 콘텐츠를 즐기는 20-40대

## 자주 사용하는 키워드
{keywords}

## 제목 공식
{patterns}

## 성공 영상 예시
{top_titles}

## 시나리오 작성 규칙
1. **도입 (30초-1분)**: 호기심을 자극하는 훅으로 시작. "그날 밤...", "이 이야기는 실화입니다"
2. **전개 (본문 70%)**: 긴장감을 점진적으로 높이며 스토리 전개
3. **클라이맥스**: 가장 무서운/충격적인 장면
4. **마무리**: 여운을 남기는 결말, 때로는 열린 결말

## 제목 작성법
- 호기심 유발: "절대 ~하지 마세요", "이것을 보면 ~"
- 키워드 포함: {keywords}
- 20-40자 내외

## 피해야 할 것
- 실제 범죄 미화
- 과도한 잔인함
- 아동/청소년 대상 공포
- 자살/자해 묘사""",

            "emotional": f"""당신은 감동/힐링 전문 유튜브 채널의 시나리오 작가입니다.

## 채널 특성
- 장르: 감동 실화, 따뜻한 이야기, 힐링
- 분위기: 따뜻하고 감성적인, 눈물샘 자극
- 시청자: 감성적인 콘텐츠를 좋아하는 전 연령층

## 자주 사용하는 키워드
{keywords}

## 제목 공식
{patterns}

## 성공 영상 예시
{top_titles}

## 시나리오 작성 규칙
1. **도입**: 평범한 일상에서 시작, 주인공 소개
2. **전개**: 갈등/어려움 제시, 감정선 형성
3. **전환점**: 희망적인 변화의 순간
4. **마무리**: 감동적인 결말, 교훈/메시지

## 제목 작성법
- 감정 자극: "눈물이 멈추지 않는", "가슴이 뭉클해지는"
- 키워드 포함: {keywords}

## 피해야 할 것
- 과도한 비극적 결말
- 슬픔 강요
- 허위/과장된 이야기""",
        }

        return templates.get(channel_type, templates.get("horror"))

    # ============================================================
    # 작가 시스템 프롬프트 생성
    # ============================================================

    def _generate_writer_system_prompt(
        self,
        channel_type: str,
        ai_strategy: str
    ) -> str:
        """대사 스타일 프롬프트 생성"""

        if self.gemini:
            prompt = f"""장르가 "{channel_type}"인 YouTube 채널의 나레이션/대사 스타일 가이드를 작성해주세요.

채널 전략 요약:
{ai_strategy[:500] if ai_strategy else "없음"}

다음 내용을 포함하세요:
1. 나레이션 톤 (속삭임, 담담함, 긴장감 등)
2. 문장 스타일 (짧은 문장 vs 긴 문장)
3. 자주 사용하는 표현/어투
4. 감정 표현 방법
5. 피해야 할 표현

한국어로 작성하세요."""

            try:
                response = self.gemini.generate_content(prompt)
                return response.text
            except Exception as e:
                logger.warning(f"Writer 프롬프트 AI 생성 실패: {redact_sensitive_text(e)}")

        # 폴백
        return self._get_writer_template(channel_type)

    def _get_writer_template(self, channel_type: str) -> str:
        """템플릿 기반 작가 프롬프트"""
        templates = {
            "horror": """## 나레이션 스타일 가이드

### 톤
- 기본: 낮고 차분한 목소리, 담담하게 이야기하듯
- 긴장 고조: 점점 빠르고 떨리는 목소리
- 클라이맥스: 속삭임 또는 급격히 높아지는 톤

### 문장 스타일
- 짧은 문장 위주 (긴장감)
- "..." 사용으로 여백 표현
- 의문문으로 호기심 유발

### 자주 쓰는 표현
- "그때였습니다"
- "갑자기..."
- "그 순간"
- "믿기 어렵겠지만"
- "이 이야기는 실화입니다"

### 피해야 할 것
- 너무 설명적인 문장
- "무섭다"를 직접 말하기 (보여주기)
- 과도한 형용사""",

            "emotional": """## 나레이션 스타일 가이드

### 톤
- 기본: 따뜻하고 부드러운 목소리
- 슬픈 장면: 감정을 담아 천천히
- 희망적 장면: 밝고 부드럽게

### 문장 스타일
- 서정적인 표현
- 감정을 담은 긴 문장
- 여운을 남기는 마무리

### 자주 쓰는 표현
- "그렇게..."
- "마침내"
- "눈물이 흘렀습니다"
- "작은 기적이었습니다"

### 피해야 할 것
- 과장된 감정 표현
- "감동적이다"를 직접 말하기
- 교훈 강요""",
        }

        return templates.get(channel_type, templates.get("horror"))

    # ============================================================
    # 토픽 + 줄거리 생성
    # ============================================================

    def _generate_topics_with_outlines(
        self,
        channel_type: str,
        title_keywords: List[str],
        title_patterns: List[str],
        top_videos: List[Dict],
        num_topics: int
    ) -> List[TopicWithOutline]:
        """토픽과 줄거리 함께 생성"""

        # 성공 영상 제목 예시
        top_titles = [v.get('title', '') for v in top_videos[:5]]

        if self.gemini:
            prompt = f"""장르: {channel_type}
키워드: {', '.join(title_keywords[:10])}
제목 패턴: {', '.join(title_patterns[:3]) if title_patterns else '없음'}
성공 영상 예시: {', '.join(top_titles)}

위 채널 스타일에 맞는 영상 토픽 {num_topics}개를 생성해주세요.

각 토픽마다 다음을 포함하세요:
1. topic: 토픽 주제 (짧게)
2. title_template: 이 채널 스타일의 제목 (20-40자)
3. outline: 줄거리 요약 (3-5문장, 도입-전개-결말)
4. keywords: 관련 키워드 3개
5. estimated_duration: 예상 영상 길이 (초, 300-600)
6. mood: 분위기 (scary, tense, mysterious, sad, warm 등)

JSON 배열로 응답하세요:
[
  {{
    "topic": "...",
    "title_template": "...",
    "outline": "...",
    "keywords": ["...", "...", "..."],
    "estimated_duration": 480,
    "mood": "..."
  }},
  ...
]"""

            try:
                response = self.gemini.generate_content(prompt)
                text = response.text

                # JSON 추출
                import re
                json_match = re.search(r'\[[\s\S]*\]', text)
                if json_match:
                    data = json.loads(json_match.group())

                    topics = []
                    for item in data[:num_topics]:
                        topics.append(TopicWithOutline(
                            topic=item.get("topic", ""),
                            title_template=item.get("title_template", ""),
                            outline=item.get("outline", ""),
                            keywords=item.get("keywords", []),
                            estimated_duration=item.get("estimated_duration", 480),
                            mood=item.get("mood", "neutral")
                        ))
                    return topics

            except Exception as e:
                logger.warning(f"토픽 AI 생성 실패: {redact_sensitive_text(e)}")

        # 폴백: 기본 토픽
        return self._get_fallback_topics(channel_type, num_topics)

    def _get_fallback_topics(self, channel_type: str, num: int) -> List[TopicWithOutline]:
        """폴백 토픽"""
        fallback = {
            "horror": [
                TopicWithOutline("폐병원", "절대 폐병원에 들어가지 마세요", "오래된 폐병원을 탐험한 남자. 3층에서 이상한 소리를 듣고 도망친다. 집에 돌아온 후에도 그 소리가 들린다.", ["폐병원", "귀신", "탐험"], 480, "scary"),
                TopicWithOutline("엘리베이터", "엘리베이터에서 만난 이상한 여자", "늦은 밤 아파트 엘리베이터에서 이상한 여자를 만난다. 그녀는 모든 층에서 내리지 않고 함께 탄다.", ["엘리베이터", "아파트", "공포"], 420, "tense"),
                TopicWithOutline("빈집", "이사 간 집에서 발견한 것", "새로 이사한 집 벽장에서 이상한 일기장을 발견한다. 읽을수록 소름끼치는 내용이 적혀있다.", ["빈집", "일기장", "미스터리"], 540, "mysterious"),
            ],
            "emotional": [
                TopicWithOutline("재회", "20년 만에 다시 만난 엄마", "어린 시절 헤어진 엄마를 20년 만에 찾는다. 그동안 엄마는 병원에서 아들을 기다리고 있었다.", ["재회", "가족", "감동"], 480, "warm"),
                TopicWithOutline("기적", "포기하지 않은 기적", "사고로 걷지 못하게 된 청년이 재활 끝에 다시 걷는다. 그의 곁에는 항상 누나가 있었다.", ["기적", "재활", "희망"], 540, "hopeful"),
            ],
        }

        base_topics = fallback.get(channel_type, fallback["horror"])

        # 부족하면 복제
        while len(base_topics) < num:
            base_topics = base_topics + base_topics

        return base_topics[:num]

    # ============================================================
    # SD 프롬프트 생성
    # ============================================================

    def _generate_sd_prompts(self, channel_type: str) -> Dict[str, Any]:
        """SD 이미지 프롬프트 생성"""

        prompts = {
            "horror": {
                "positive_base": "dark atmospheric scene, cinematic lighting, dramatic shadows, horror mood, silhouette art style, masterpiece, best quality, highly detailed",
                "negative_base": "bright, cheerful, colorful, daylight, happy, cartoon, low quality, blurry, deformed, nsfw",
                "scene_templates": {
                    "indoor": "dark room, dim lighting, shadows, horror atmosphere, {scene_description}",
                    "outdoor": "dark night, moonlight, eerie fog, abandoned place, {scene_description}",
                    "character": "dark silhouette, mysterious figure, backlit, dramatic pose, {scene_description}",
                },
                "style_keywords": ["dark", "gloomy", "mysterious", "ominous", "eerie", "shadowy"],
                "quality_keywords": ["masterpiece", "best quality", "highly detailed", "8k", "cinematic"],
            },
            "emotional": {
                "positive_base": "soft lighting, warm colors, emotional scene, watercolor style, gentle atmosphere, masterpiece, beautiful",
                "negative_base": "harsh lighting, dark, horror, scary, low quality, blurry, deformed, nsfw",
                "scene_templates": {
                    "indoor": "warm interior, soft sunlight through window, cozy atmosphere, {scene_description}",
                    "outdoor": "golden hour, warm sunset, peaceful nature, {scene_description}",
                    "character": "gentle expression, soft lighting, emotional moment, {scene_description}",
                },
                "style_keywords": ["soft", "warm", "gentle", "nostalgic", "peaceful"],
                "quality_keywords": ["masterpiece", "beautiful", "detailed", "soft focus"],
            },
            "mystery": {
                "positive_base": "noir style, dramatic lighting, mysterious atmosphere, detective scene, high contrast, masterpiece",
                "negative_base": "bright, cheerful, simple, childish, low quality, blurry, deformed, nsfw",
                "scene_templates": {
                    "indoor": "dimly lit room, noir atmosphere, shadows, {scene_description}",
                    "outdoor": "foggy street, night scene, street lamp, mysterious, {scene_description}",
                    "character": "mysterious figure, dramatic lighting, contemplative pose, {scene_description}",
                },
                "style_keywords": ["noir", "mysterious", "atmospheric", "shadowy", "dramatic"],
                "quality_keywords": ["masterpiece", "best quality", "detailed", "cinematic"],
            },
        }

        return prompts.get(channel_type, prompts["horror"])

    # ============================================================
    # 스타일 가이드 생성
    # ============================================================

    def _generate_style_guide(
        self,
        channel_type: str,
        channel_analysis: Dict
    ) -> Dict[str, Any]:
        """스타일 가이드 생성"""

        style_guides = {
            "horror": {
                "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560", "#000000"],
                "primary_colors": "어두운 파랑, 검정, 핏빛 빨강",
                "mood": "어둡고 불안한, 긴장감",
                "composition": "낮은 앵글, 극적인 명암, 실루엣 활용",
                "recommended_models": [
                    {"name": "DarkSushi Mix", "civitai_id": "24779"},
                    {"name": "AbyssOrangeMix3", "civitai_id": "9942"},
                ],
                "aspect_ratio": "16:9",
                "resolution": "1280x720",
            },
            "emotional": {
                "color_palette": ["#ffeaa7", "#fdcb6e", "#fab1a0", "#ff7675", "#74b9ff"],
                "primary_colors": "따뜻한 노랑, 부드러운 주황, 파스텔",
                "mood": "따뜻하고 포근한, 감성적",
                "composition": "부드러운 조명, 따뜻한 색감, 인물 중심",
                "recommended_models": [
                    {"name": "Dreamshaper", "civitai_id": "4384"},
                    {"name": "ChilloutMix", "civitai_id": "6424"},
                ],
                "aspect_ratio": "16:9",
                "resolution": "1280x720",
            },
        }

        return style_guides.get(channel_type, style_guides["horror"])

    # ============================================================
    # 감정 + TTS 가이드 생성
    # ============================================================

    def _generate_emotions(self, channel_type: str) -> Dict[str, Any]:
        """필요 감정 목록 생성"""

        emotions = {
            "horror": {
                "required_emotions": ["calm", "fear", "whisper", "tense", "shocked"],
                "sample_scripts": {
                    "calm": "그날 밤, 모든 것이 시작되었습니다.",
                    "fear": "그 순간, 나는 무언가가 나를 지켜보고 있다는 것을 느꼈습니다.",
                    "whisper": "조용히... 들려오는 발자국 소리...",
                    "tense": "문 뒤에서 들려오는 소리는 점점 가까워지고 있었습니다.",
                    "shocked": "그것은... 사람이 아니었습니다!",
                },
                "emotion_weights": {
                    "calm": 0.4,
                    "fear": 0.2,
                    "whisper": 0.15,
                    "tense": 0.2,
                    "shocked": 0.05,
                },
            },
            "emotional": {
                "required_emotions": ["calm", "sad", "happy", "nostalgic", "hopeful"],
                "sample_scripts": {
                    "calm": "이것은 작은 마을에서 시작된 이야기입니다.",
                    "sad": "그녀는 마지막으로 그의 손을 잡았습니다.",
                    "happy": "그 순간, 모든 것이 의미 있게 느껴졌습니다.",
                    "nostalgic": "어린 시절의 그 여름이 떠오릅니다.",
                    "hopeful": "그렇게 새로운 시작이 열렸습니다.",
                },
                "emotion_weights": {
                    "calm": 0.3,
                    "sad": 0.25,
                    "happy": 0.15,
                    "nostalgic": 0.2,
                    "hopeful": 0.1,
                },
            },
        }

        return emotions.get(channel_type, emotions["horror"])

    def _generate_tts_guide(self, channel_type: str, channel_title: str) -> str:
        """TTS 가이드 마크다운 생성"""

        guides = {
            "horror": f"""# TTS 학습 가이드 - {channel_title} 스타일

## 목소리 특성
- **성별**: 남성 권장 (깊고 묵직한 목소리)
- **연령대**: 30-40대
- **톤**: 차분하면서도 긴장감 있는

## 필요한 감정 녹음
1. **calm** (기본): 담담하게 이야기하는 톤
2. **fear**: 두려움이 담긴 떨리는 목소리
3. **whisper**: 속삭이듯 낮은 목소리
4. **tense**: 긴장감 고조, 빠른 호흡
5. **shocked**: 놀람, 경악

## 녹음 팁
- 조용한 환경에서 녹음
- 감정별로 3-5초 x 3회 이상
- 속삭임은 마이크와 가깝게 (팝 필터 필수)
- 공포 감정은 약간 떨리는 목소리로

## 참조 스타일
- 한국 공포 라디오 DJ
- 괴담 유튜버 나레이션
- 미스터리 다큐 나레이터

## ElevenLabs 힌트
Deep, resonant voice with subtle tension. Korean horror radio announcer style.
Speaks slowly with occasional whispers and dramatic pauses.""",

            "emotional": f"""# TTS 학습 가이드 - {channel_title} 스타일

## 목소리 특성
- **성별**: 여성 또는 부드러운 남성
- **연령대**: 20-30대
- **톤**: 따뜻하고 감성적인

## 필요한 감정 녹음
1. **calm** (기본): 부드럽게 이야기하는 톤
2. **sad**: 슬픔이 담긴 목소리
3. **happy**: 밝고 따뜻한 목소리
4. **nostalgic**: 회상하는 듯한 감성적 톤
5. **hopeful**: 희망찬, 밝은 톤

## 녹음 팁
- 따뜻한 분위기에서 녹음
- 감정을 충분히 담아서
- 급하지 않게 천천히

## 참조 스타일
- 오디오북 나레이터
- 힐링 콘텐츠 유튜버
- 감성 에세이 낭독

## ElevenLabs 힌트
Warm, gentle voice with emotional depth. Audiobook narrator style.
Speaks with care and emotional nuance.""",
        }

        return guides.get(channel_type, guides["horror"])

    # ============================================================
    # 채널 설정 생성
    # ============================================================

    def _generate_channel_config(
        self,
        channel_type: str,
        best_day: str,
        best_hour: int,
        upload_freq: float,
        channel_analysis: Dict
    ) -> Dict[str, Any]:
        """채널 설정 생성"""

        # 메타데이터에서 평균 영상 길이 추정
        metadata = channel_analysis.get("metadata", {})

        configs = {
            "horror": {
                "video_duration": {
                    "target_seconds": 480,  # 8분
                    "min_seconds": 300,     # 5분
                    "max_seconds": 720,     # 12분
                },
                "structure": {
                    "intro_ratio": 0.1,      # 10% - 도입
                    "body_ratio": 0.75,      # 75% - 본문
                    "outro_ratio": 0.15,     # 15% - 마무리
                },
                "scenes_per_minute": 4,      # 분당 장면 수
                "upload_schedule": {
                    "best_day": best_day or "목",
                    "best_hour": best_hour or 20,
                    "frequency_per_week": round(upload_freq) or 3,
                },
                "seo": {
                    "title_length": {"min": 20, "max": 40},
                    "tags_count": 15,
                    "description_length": 500,
                },
            },
            "emotional": {
                "video_duration": {
                    "target_seconds": 420,  # 7분
                    "min_seconds": 240,
                    "max_seconds": 600,
                },
                "structure": {
                    "intro_ratio": 0.15,
                    "body_ratio": 0.70,
                    "outro_ratio": 0.15,
                },
                "scenes_per_minute": 3,
                "upload_schedule": {
                    "best_day": best_day or "일",
                    "best_hour": best_hour or 10,
                    "frequency_per_week": round(upload_freq) or 2,
                },
                "seo": {
                    "title_length": {"min": 15, "max": 35},
                    "tags_count": 12,
                    "description_length": 400,
                },
            },
        }

        return configs.get(channel_type, configs["horror"])

    # ============================================================
    # 내보내기
    # ============================================================

    def export_to_revpack_structure(
        self,
        pack: ClonePackContent,
        output_dir: str
    ) -> Dict[str, str]:
        """revpack 구조로 내보내기"""

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        files_created = {}

        # 1. prompts 폴더
        prompts_dir = output_path / "prompts"
        prompts_dir.mkdir(exist_ok=True)

        # pd_system.txt
        pd_path = prompts_dir / "pd_system.txt"
        pd_path.write_text(pack.pd_system_prompt, encoding='utf-8')
        files_created["pd_system"] = str(pd_path)

        # writer_system.txt
        writer_path = prompts_dir / "writer_system.txt"
        writer_path.write_text(pack.writer_system_prompt, encoding='utf-8')
        files_created["writer_system"] = str(writer_path)

        # sd_prompts.json
        sd_path = prompts_dir / "sd_prompts.json"
        sd_path.write_text(json.dumps(pack.sd_prompts, ensure_ascii=False, indent=2), encoding='utf-8')
        files_created["sd_prompts"] = str(sd_path)

        # 2. topics.json
        topics_data = [asdict(t) for t in pack.topics]
        topics_path = output_path / "topics.json"
        topics_path.write_text(json.dumps(topics_data, ensure_ascii=False, indent=2), encoding='utf-8')
        files_created["topics"] = str(topics_path)

        # 3. emotions.json
        emotions_path = output_path / "emotions.json"
        emotions_path.write_text(json.dumps(pack.emotions, ensure_ascii=False, indent=2), encoding='utf-8')
        files_created["emotions"] = str(emotions_path)

        # 4. style_guide.json
        style_path = output_path / "style_guide.json"
        style_path.write_text(json.dumps(pack.style_guide, ensure_ascii=False, indent=2), encoding='utf-8')
        files_created["style_guide"] = str(style_path)

        # 5. channel_config.json
        config_path = output_path / "channel_config.json"
        config_path.write_text(json.dumps(pack.channel_config, ensure_ascii=False, indent=2), encoding='utf-8')
        files_created["channel_config"] = str(config_path)

        # 6. TTS_GUIDE.md
        tts_path = output_path / "TTS_GUIDE.md"
        tts_path.write_text(pack.tts_guide, encoding='utf-8')
        files_created["tts_guide"] = str(tts_path)

        # 7. pack_info.json (메타)
        info = {
            "pack_id": pack.pack_id,
            "source_channel": pack.source_channel,
            "source_channel_id": pack.source_channel_id,
            "created_at": pack.created_at,
            "generator_version": self.VERSION,
        }
        info_path = output_path / "pack_info.json"
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        files_created["pack_info"] = str(info_path)

        logger.info(f"[ClonePackGenerator] 내보내기 완료: {output_path}")
        return files_created


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print(f"ClonePackGenerator v{ClonePackGenerator.VERSION}")
    print(f"Gemini: {'사용 가능' if GEMINI_AVAILABLE else '사용 불가'}")
