# Reverie Factory - 팩 설계 AI
# Version: 1.0.0

"""
팩 설계 AI

Insight 분석 결과를 기반으로 채널 팩 컨셉을 자동 설계합니다.
- Gemini를 활용한 채널 컨셉 자동 설계
- SD 모델/LoRA 추천 + Civitai 링크
- 목소리 가이드 자동 생성
- .revpack 연동
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path
from enum import Enum

from utils.gemini_compat import GEMINI_AVAILABLE, configure_gemini, get_gemini_model

logger = logging.getLogger(__name__)


# ============================================================
# 데이터 클래스
# ============================================================

class ChannelGenre(Enum):
    """채널 장르"""
    HORROR = "horror"
    MYSTERY = "mystery"
    EMOTIONAL = "emotional"
    COMEDY = "comedy"
    DOCUMENTARY = "documentary"
    NEWS = "news"
    EDUCATION = "education"
    ASMR = "asmr"
    ENTERTAINMENT = "entertainment"


@dataclass
class CharacterSpec:
    """캐릭터 스펙"""
    name: str
    role: str  # narrator, protagonist, antagonist, support
    description: str
    visual_style: str  # 시각적 특징 (실루엣, 애니메이션 등)
    voice_spec: Dict[str, str] = field(default_factory=dict)  # gender, age, tone


@dataclass
class VoiceGuideSpec:
    """목소리 가이드 스펙"""
    voice_gender: str  # male, female, neutral
    voice_age: str  # child, young, adult, elderly
    voice_tone: str  # calm, energetic, mysterious, warm
    reference_style: str  # 참조 스타일 ("한국 공포 라디오 DJ" 등)
    required_emotions: List[str] = field(default_factory=list)
    sample_scripts: Dict[str, str] = field(default_factory=dict)  # emotion -> sample script
    recording_tips: List[str] = field(default_factory=list)
    elevenlabs_hints: str = ""


@dataclass
class SDModelRecommendation:
    """SD 모델 추천"""
    model_name: str
    model_type: str  # checkpoint, lora, vae
    civitai_url: str
    civitai_id: str
    match_reason: str
    style_tags: List[str] = field(default_factory=list)
    recommended_settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptTemplate:
    """프롬프트 템플릿"""
    positive_base: str
    negative_base: str
    style_keywords: List[str] = field(default_factory=list)
    quality_keywords: List[str] = field(default_factory=list)
    mood_keywords: List[str] = field(default_factory=list)


@dataclass
class ChannelPackDesign:
    """채널 팩 설계"""
    # 필수 필드 (기본값 없음) - 먼저 선언
    design_id: str
    channel_name: str
    channel_name_kr: str
    genre: str
    theme: str
    visual_style: str  # 비주얼 스타일 (필수)

    # 선택적 필드 (기본값 있음)
    theme_kr: str = ""
    concept_summary: str = ""
    target_audience: str = ""
    unique_selling_point: str = ""

    # 캐릭터
    characters: List[CharacterSpec] = field(default_factory=list)

    # 비주얼
    color_palette: List[str] = field(default_factory=list)
    sd_models: List[SDModelRecommendation] = field(default_factory=list)
    prompt_template: Optional[PromptTemplate] = None

    # 음성
    voice_guide: Optional[VoiceGuideSpec] = None

    # 콘텐츠 가이드
    topic_categories: List[str] = field(default_factory=list)
    sample_topics: List[str] = field(default_factory=list)
    banned_keywords: List[str] = field(default_factory=list)

    # 메타데이터
    created_at: str = ""
    source_insight_id: str = ""  # Insight 분석 결과 ID


# ============================================================
# SD 모델 데이터베이스 (Civitai 기반)
# ============================================================

CIVITAI_MODEL_DATABASE = {
    # 호러/미스터리
    "horror": [
        {
            "model_name": "DarkSushi Mix",
            "civitai_id": "24779",
            "civitai_url": "https://civitai.com/models/24779",
            "style_tags": ["dark", "horror", "anime", "dramatic"],
            "match_genres": ["horror", "mystery", "supernatural"],
        },
        {
            "model_name": "AbyssOrangeMix3",
            "civitai_id": "9942",
            "civitai_url": "https://civitai.com/models/9942",
            "style_tags": ["anime", "dark", "detailed"],
            "match_genres": ["horror", "mystery"],
        },
        {
            "model_name": "Counterfeit-V3.0",
            "civitai_id": "4468",
            "civitai_url": "https://civitai.com/models/4468",
            "style_tags": ["anime", "high-quality", "versatile"],
            "match_genres": ["horror", "mystery", "emotional"],
        },
    ],

    # 감동/로맨스
    "emotional": [
        {
            "model_name": "Dreamshaper",
            "civitai_id": "4384",
            "civitai_url": "https://civitai.com/models/4384",
            "style_tags": ["dreamy", "soft", "emotional"],
            "match_genres": ["emotional", "romance", "drama"],
        },
        {
            "model_name": "ChilloutMix",
            "civitai_id": "6424",
            "civitai_url": "https://civitai.com/models/6424",
            "style_tags": ["realistic", "soft", "portrait"],
            "match_genres": ["emotional", "lifestyle"],
        },
    ],

    # 다큐/뉴스
    "documentary": [
        {
            "model_name": "Realistic Vision V5.1",
            "civitai_id": "4201",
            "civitai_url": "https://civitai.com/models/4201",
            "style_tags": ["realistic", "photographic", "detailed"],
            "match_genres": ["documentary", "news", "education"],
        },
        {
            "model_name": "epiCRealism",
            "civitai_id": "25694",
            "civitai_url": "https://civitai.com/models/25694",
            "style_tags": ["realistic", "cinematic", "dramatic"],
            "match_genres": ["documentary", "drama"],
        },
    ],

    # 엔터테인먼트/코미디
    "entertainment": [
        {
            "model_name": "AnythingV5",
            "civitai_id": "9409",
            "civitai_url": "https://civitai.com/models/9409",
            "style_tags": ["anime", "versatile", "colorful"],
            "match_genres": ["entertainment", "comedy", "kids"],
        },
        {
            "model_name": "MeinaMix",
            "civitai_id": "7240",
            "civitai_url": "https://civitai.com/models/7240",
            "style_tags": ["anime", "cute", "vibrant"],
            "match_genres": ["entertainment", "comedy"],
        },
    ],

    # ASMR/릴랙싱
    "asmr": [
        {
            "model_name": "Lofi V1",
            "civitai_id": "48139",
            "civitai_url": "https://civitai.com/models/48139",
            "style_tags": ["lofi", "soft", "aesthetic"],
            "match_genres": ["asmr", "relaxing", "study"],
        },
        {
            "model_name": "Pastel Mix",
            "civitai_id": "5414",
            "civitai_url": "https://civitai.com/models/5414",
            "style_tags": ["pastel", "soft", "anime"],
            "match_genres": ["asmr", "relaxing"],
        },
    ],

    # 교육
    "education": [
        {
            "model_name": "Realistic Vision V5.1",
            "civitai_id": "4201",
            "civitai_url": "https://civitai.com/models/4201",
            "style_tags": ["realistic", "clean", "professional"],
            "match_genres": ["education", "documentary"],
        },
        {
            "model_name": "SDXL Base",
            "civitai_id": "101055",
            "civitai_url": "https://civitai.com/models/101055",
            "style_tags": ["versatile", "high-quality", "detailed"],
            "match_genres": ["education", "general"],
        },
    ],
}

# 장르별 LoRA 추천
LORA_RECOMMENDATIONS = {
    "horror": [
        {"name": "Dark Fantasy LoRA", "civitai_id": "17094", "weight": 0.6},
        {"name": "Horror Lighting LoRA", "civitai_id": "23456", "weight": 0.5},
    ],
    "emotional": [
        {"name": "Soft Light LoRA", "civitai_id": "19327", "weight": 0.5},
        {"name": "Emotion Expression LoRA", "civitai_id": "21543", "weight": 0.4},
    ],
    "documentary": [
        {"name": "Cinematic LoRA", "civitai_id": "15678", "weight": 0.5},
        {"name": "Detail Enhancement LoRA", "civitai_id": "18234", "weight": 0.4},
    ],
}


# ============================================================
# 장르별 프롬프트 템플릿
# ============================================================

GENRE_PROMPT_TEMPLATES = {
    "horror": PromptTemplate(
        positive_base="dark atmospheric scene, cinematic lighting, dramatic shadows, horror mood",
        negative_base="bright, cheerful, colorful, daylight, happy, cartoon, low quality, blurry",
        style_keywords=["dark", "gloomy", "mysterious", "ominous", "eerie"],
        quality_keywords=["masterpiece", "best quality", "highly detailed", "8k"],
        mood_keywords=["fear", "tension", "suspense", "dread"],
    ),
    "mystery": PromptTemplate(
        positive_base="mysterious atmosphere, noir style, dramatic lighting, enigmatic",
        negative_base="bright, simple, childish, low quality, blurry",
        style_keywords=["noir", "mysterious", "atmospheric", "shadowy"],
        quality_keywords=["masterpiece", "best quality", "detailed"],
        mood_keywords=["intrigue", "suspense", "curiosity"],
    ),
    "emotional": PromptTemplate(
        positive_base="soft lighting, warm colors, emotional scene, cinematic",
        negative_base="harsh lighting, dark, horror, scary, low quality",
        style_keywords=["soft", "warm", "gentle", "nostalgic"],
        quality_keywords=["masterpiece", "beautiful", "detailed"],
        mood_keywords=["touching", "heartwarming", "melancholy"],
    ),
    "documentary": PromptTemplate(
        positive_base="realistic scene, documentary style, professional photography",
        negative_base="anime, cartoon, stylized, low quality, artistic",
        style_keywords=["realistic", "documentary", "photographic", "natural"],
        quality_keywords=["high resolution", "detailed", "professional"],
        mood_keywords=["informative", "neutral", "objective"],
    ),
    "entertainment": PromptTemplate(
        positive_base="vibrant colors, dynamic composition, energetic, anime style",
        negative_base="dull, boring, static, low quality, blurry",
        style_keywords=["colorful", "dynamic", "energetic", "fun"],
        quality_keywords=["masterpiece", "best quality", "vibrant"],
        mood_keywords=["exciting", "fun", "engaging"],
    ),
    "asmr": PromptTemplate(
        positive_base="soft aesthetic, lo-fi style, pastel colors, calm atmosphere",
        negative_base="harsh, loud, bright, chaotic, low quality",
        style_keywords=["lofi", "aesthetic", "soft", "pastel"],
        quality_keywords=["beautiful", "gentle", "soothing"],
        mood_keywords=["relaxing", "calm", "peaceful"],
    ),
}


# ============================================================
# 팩 설계 AI
# ============================================================

class PackDesigner:
    """팩 설계 AI"""

    def __init__(
        self,
        gemini_api_key: str = None,
        output_dir: str = None
    ):
        """
        Args:
            gemini_api_key: Gemini API 키 (없으면 환경변수에서)
            output_dir: 출력 디렉토리
        """
        self.gemini_api_key = gemini_api_key or os.environ.get('GEMINI_API_KEY')
        self.gemini_model = None

        if GEMINI_AVAILABLE and self.gemini_api_key:
            try:
                if configure_gemini(self.gemini_api_key):
                    self.gemini_model = get_gemini_model("gemini-1.5-flash")
                logger.info("PackDesigner: Gemini 모델 초기화 완료")
            except Exception as e:
                logger.warning(f"PackDesigner: Gemini 초기화 실패: {e}")

        # 출력 디렉토리
        if output_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            output_dir = base_dir / "data" / "factory"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # 메인 설계 함수
    # --------------------------------------------------------

    def design_channel_pack(
        self,
        insight_data: Dict[str, Any] = None,
        manual_config: Dict[str, Any] = None
    ) -> ChannelPackDesign:
        """
        채널 팩 컨셉 설계

        Args:
            insight_data: Insight 분석 결과 (CloneRecipe 형태)
            manual_config: 수동 설정 (장르, 테마 등)

        Returns:
            ChannelPackDesign
        """
        # 설정 병합
        config = manual_config or {}
        if insight_data:
            config = self._merge_insight_config(insight_data, config)

        # 필수 값 확인
        genre = config.get("genre", "horror")
        theme = config.get("theme", "")
        style_type = config.get("style_type", "silhouette")

        logger.info(f"팩 설계 시작: 장르={genre}, 테마={theme}, 스타일={style_type}")

        # 1. AI로 채널 컨셉 설계
        concept = self._generate_channel_concept(genre, theme, style_type, config)

        # 2. SD 모델 추천
        sd_models = self._recommend_sd_models(genre, style_type, config)

        # 3. 프롬프트 템플릿
        prompt_template = self._get_prompt_template(genre, style_type)

        # 4. 캐릭터 설계
        characters = self._design_characters(genre, concept)

        # 5. 목소리 가이드
        voice_guide = self._generate_voice_guide(genre, concept)

        # 6. 콘텐츠 가이드
        topics = self._generate_topic_suggestions(genre, theme)

        # 설계 결과 생성
        design = ChannelPackDesign(
            design_id=f"design_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            channel_name=concept.get("channel_name", f"{genre}_channel"),
            channel_name_kr=concept.get("channel_name_kr", f"{genre} 채널"),
            genre=genre,
            theme=theme,
            theme_kr=config.get("theme_kr", theme),
            concept_summary=concept.get("summary", ""),
            target_audience=concept.get("target_audience", ""),
            unique_selling_point=concept.get("usp", ""),
            characters=characters,
            visual_style=style_type,
            color_palette=config.get("color_palette", []),
            sd_models=sd_models,
            prompt_template=prompt_template,
            voice_guide=voice_guide,
            topic_categories=topics.get("categories", []),
            sample_topics=topics.get("samples", []),
            banned_keywords=topics.get("banned", []),
            created_at=datetime.now().isoformat(),
            source_insight_id=insight_data.get("video_id", "") if insight_data else "",
        )

        # 저장
        self._save_design(design)

        logger.info(f"팩 설계 완료: {design.design_id}")
        return design

    def _merge_insight_config(
        self,
        insight_data: Dict,
        manual_config: Dict
    ) -> Dict:
        """Insight 데이터와 수동 설정 병합"""
        merged = dict(manual_config)

        # Insight에서 추출
        if "style_type" in insight_data:
            merged.setdefault("style_type", insight_data["style_type"])

        if "color_palette" in insight_data:
            palette = insight_data["color_palette"]
            if isinstance(palette, dict):
                merged.setdefault("color_palette", palette.get("hex_colors", []))

        if "sd_models" in insight_data:
            merged.setdefault("recommended_models", insight_data["sd_models"])

        if "tts_guide" in insight_data:
            merged.setdefault("voice_reference", insight_data["tts_guide"])

        return merged

    # --------------------------------------------------------
    # AI 컨셉 생성
    # --------------------------------------------------------

    def _generate_channel_concept(
        self,
        genre: str,
        theme: str,
        style_type: str,
        config: Dict
    ) -> Dict:
        """AI로 채널 컨셉 생성"""
        if not self.gemini_model:
            return self._generate_fallback_concept(genre, theme, style_type)

        prompt = f"""당신은 유튜브 채널 기획 전문가입니다.
다음 조건에 맞는 유튜브 채널 컨셉을 설계해주세요.

## 조건
- 장르: {genre}
- 테마: {theme or "자유"}
- 비주얼 스타일: {style_type}
- 대상 하드웨어: RTX 4060 Ti 8GB (AI 이미지 생성)
- 컨텐츠 형식: 나레이션 + AI 생성 이미지 + TTS

## 요청사항
1. 채널 이름 (영문/한글)
2. 채널 컨셉 요약 (2-3문장)
3. 타겟 시청자
4. 차별화 포인트 (USP)
5. 추천 콘텐츠 테마 3개

JSON 형식으로 응답하세요:
{{
  "channel_name": "English Name",
  "channel_name_kr": "한글 이름",
  "summary": "채널 컨셉 요약",
  "target_audience": "타겟 시청자",
  "usp": "차별화 포인트",
  "content_themes": ["테마1", "테마2", "테마3"]
}}
"""

        try:
            response = self.gemini_model.generate_content(prompt)
            text = response.text

            # JSON 추출
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group())
            else:
                return self._generate_fallback_concept(genre, theme, style_type)

        except Exception as e:
            logger.warning(f"AI 컨셉 생성 실패: {e}")
            return self._generate_fallback_concept(genre, theme, style_type)

    def _generate_fallback_concept(
        self,
        genre: str,
        theme: str,
        style_type: str
    ) -> Dict:
        """폴백 컨셉"""
        concepts = {
            "horror": {
                "channel_name": "Midnight Whispers",
                "channel_name_kr": "자정의 속삭임",
                "summary": "어둠 속에서 들려오는 섬뜩한 이야기. 한국의 도시괴담과 실화 공포 이야기를 나레이션과 AI 이미지로 전달합니다.",
                "target_audience": "공포 콘텐츠를 즐기는 20-40대",
                "usp": "몰입감 있는 나레이션과 분위기 있는 AI 이미지",
            },
            "mystery": {
                "channel_name": "Unsolved Files",
                "channel_name_kr": "미제 사건 파일",
                "summary": "풀리지 않은 미스터리와 미제 사건들을 깊이 있게 파헤칩니다.",
                "target_audience": "미스터리와 범죄 다큐를 즐기는 시청자",
                "usp": "철저한 리서치와 몰입감 있는 스토리텔링",
            },
            "emotional": {
                "channel_name": "Heartfelt Stories",
                "channel_name_kr": "마음을 울리는 이야기",
                "summary": "감동적인 실화와 따뜻한 이야기를 전합니다.",
                "target_audience": "감성적인 콘텐츠를 좋아하는 전 연령층",
                "usp": "진정성 있는 스토리텔링",
            },
        }

        base = concepts.get(genre, {
            "channel_name": f"{genre.title()} Channel",
            "channel_name_kr": f"{genre} 채널",
            "summary": f"{genre} 장르의 콘텐츠를 제공합니다.",
            "target_audience": "해당 장르 팬",
            "usp": "고품질 AI 생성 콘텐츠",
        })

        if theme:
            base["summary"] = f"{theme}를 주제로 한 {base['summary']}"

        return base

    # --------------------------------------------------------
    # SD 모델 추천
    # --------------------------------------------------------

    def _recommend_sd_models(
        self,
        genre: str,
        style_type: str,
        config: Dict
    ) -> List[SDModelRecommendation]:
        """SD 모델 추천"""
        recommendations = []

        # 장르 기반 모델 조회
        genre_key = genre.lower()
        if genre_key in ["horror", "mystery", "supernatural"]:
            db_key = "horror"
        elif genre_key in ["emotional", "romance", "drama"]:
            db_key = "emotional"
        elif genre_key in ["documentary", "news"]:
            db_key = "documentary"
        elif genre_key in ["asmr", "relaxing"]:
            db_key = "asmr"
        elif genre_key in ["education"]:
            db_key = "education"
        else:
            db_key = "entertainment"

        models = CIVITAI_MODEL_DATABASE.get(db_key, [])

        for model_data in models[:3]:  # 최대 3개
            rec = SDModelRecommendation(
                model_name=model_data["model_name"],
                model_type="checkpoint",
                civitai_url=model_data["civitai_url"],
                civitai_id=model_data["civitai_id"],
                match_reason=f"{genre} 장르에 적합한 {', '.join(model_data['style_tags'][:2])} 스타일",
                style_tags=model_data["style_tags"],
                recommended_settings={
                    "steps": 15,
                    "cfg_scale": 7.0,
                    "sampler": "DPM++ 2M Karras",
                    "size": "768x512",
                }
            )
            recommendations.append(rec)

        # LoRA 추천
        loras = LORA_RECOMMENDATIONS.get(db_key, [])
        for lora_data in loras[:2]:
            rec = SDModelRecommendation(
                model_name=lora_data["name"],
                model_type="lora",
                civitai_url=f"https://civitai.com/models/{lora_data['civitai_id']}",
                civitai_id=lora_data["civitai_id"],
                match_reason=f"{genre} 장르 강화용 LoRA",
                style_tags=[],
                recommended_settings={"weight": lora_data["weight"]}
            )
            recommendations.append(rec)

        return recommendations

    # --------------------------------------------------------
    # 프롬프트 템플릿
    # --------------------------------------------------------

    def _get_prompt_template(
        self,
        genre: str,
        style_type: str
    ) -> PromptTemplate:
        """장르별 프롬프트 템플릿 반환"""
        genre_key = genre.lower()

        if genre_key in ["horror", "mystery", "supernatural"]:
            template_key = "horror"
        elif genre_key in ["emotional", "romance", "drama"]:
            template_key = "emotional"
        elif genre_key in ["documentary", "news"]:
            template_key = "documentary"
        elif genre_key in ["asmr", "relaxing"]:
            template_key = "asmr"
        else:
            template_key = "entertainment"

        return GENRE_PROMPT_TEMPLATES.get(template_key, GENRE_PROMPT_TEMPLATES["entertainment"])

    # --------------------------------------------------------
    # 캐릭터 설계
    # --------------------------------------------------------

    def _design_characters(
        self,
        genre: str,
        concept: Dict
    ) -> List[CharacterSpec]:
        """캐릭터 설계"""
        characters = []

        # 기본 나레이터
        narrator_voice = {
            "horror": {"gender": "male", "age": "adult", "tone": "mysterious"},
            "mystery": {"gender": "male", "age": "adult", "tone": "calm"},
            "emotional": {"gender": "female", "age": "young", "tone": "warm"},
            "documentary": {"gender": "male", "age": "adult", "tone": "professional"},
            "entertainment": {"gender": "female", "age": "young", "tone": "energetic"},
        }

        voice = narrator_voice.get(genre, {"gender": "neutral", "age": "adult", "tone": "calm"})

        narrator = CharacterSpec(
            name="Narrator",
            role="narrator",
            description="채널의 메인 나레이터. 모든 이야기를 전달합니다.",
            visual_style="off-screen",
            voice_spec=voice
        )
        characters.append(narrator)

        # 장르별 추가 캐릭터
        if genre in ["horror", "mystery"]:
            characters.append(CharacterSpec(
                name="Witness",
                role="support",
                description="이야기의 목격자 또는 증인",
                visual_style="silhouette",
                voice_spec={"gender": "varies", "age": "varies", "tone": "scared"}
            ))

        if genre == "emotional":
            characters.append(CharacterSpec(
                name="Protagonist",
                role="protagonist",
                description="이야기의 주인공",
                visual_style="soft_illustration",
                voice_spec={"gender": "varies", "age": "varies", "tone": "emotional"}
            ))

        return characters

    # --------------------------------------------------------
    # 목소리 가이드
    # --------------------------------------------------------

    def _generate_voice_guide(
        self,
        genre: str,
        concept: Dict
    ) -> VoiceGuideSpec:
        """목소리 가이드 생성"""
        # 장르별 기본 설정
        voice_configs = {
            "horror": {
                "gender": "male",
                "age": "adult",
                "tone": "mysterious",
                "reference": "한국 공포 라디오 DJ, 깊고 묵직한 목소리",
                "emotions": ["calm", "fear", "whisper", "tense"],
                "elevenlabs": "Deep, resonant voice with subtle tension. Korean horror radio announcer style.",
            },
            "mystery": {
                "gender": "male",
                "age": "adult",
                "tone": "calm",
                "reference": "다큐멘터리 나레이터, 신뢰감 있는 목소리",
                "emotions": ["calm", "curious", "serious", "suspenseful"],
                "elevenlabs": "Calm, authoritative voice. Documentary narrator style with occasional intensity.",
            },
            "emotional": {
                "gender": "female",
                "age": "young",
                "tone": "warm",
                "reference": "따뜻한 오디오북 나레이터",
                "emotions": ["calm", "sad", "happy", "nostalgic"],
                "elevenlabs": "Warm, gentle voice with emotional depth. Audiobook narrator style.",
            },
            "documentary": {
                "gender": "male",
                "age": "adult",
                "tone": "professional",
                "reference": "뉴스 앵커 또는 다큐 나레이터",
                "emotions": ["calm", "serious", "informative"],
                "elevenlabs": "Professional, clear voice. News anchor or documentary narrator style.",
            },
        }

        config = voice_configs.get(genre, {
            "gender": "neutral",
            "age": "adult",
            "tone": "calm",
            "reference": "일반 나레이터",
            "emotions": ["calm"],
            "elevenlabs": "Clear, neutral voice.",
        })

        # 샘플 스크립트
        sample_scripts = self._generate_sample_scripts(genre, config["emotions"])

        # 녹음 팁
        recording_tips = [
            "조용한 환경에서 녹음하세요",
            "마이크와 15-20cm 거리를 유지하세요",
            "감정별로 3-5초 분량을 3회 이상 녹음하세요",
            "자연스러운 호흡과 포즈를 유지하세요",
        ]

        if genre == "horror":
            recording_tips.append("속삭임(whisper) 녹음 시 마이크에 가깝게 하되 팝 필터 사용")
            recording_tips.append("공포 감정은 약간 떨리는 목소리로 표현")

        return VoiceGuideSpec(
            voice_gender=config["gender"],
            voice_age=config["age"],
            voice_tone=config["tone"],
            reference_style=config["reference"],
            required_emotions=config["emotions"],
            sample_scripts=sample_scripts,
            recording_tips=recording_tips,
            elevenlabs_hints=config["elevenlabs"],
        )

    def _generate_sample_scripts(
        self,
        genre: str,
        emotions: List[str]
    ) -> Dict[str, str]:
        """감정별 샘플 스크립트 생성"""
        scripts = {
            "horror": {
                "calm": "그날 밤, 모든 것이 시작되었습니다.",
                "fear": "그 순간, 나는 무언가가 나를 지켜보고 있다는 것을 느꼈습니다.",
                "whisper": "조용히... 들려오는 발자국 소리...",
                "tense": "문 뒤에서 들려오는 소리는 점점 가까워지고 있었습니다.",
            },
            "mystery": {
                "calm": "이 사건의 시작은 1995년으로 거슬러 올라갑니다.",
                "curious": "과연 그 문 뒤에는 무엇이 있었을까요?",
                "serious": "경찰은 마침내 충격적인 사실을 발견했습니다.",
                "suspenseful": "그러나 아무도 예상하지 못한 일이 벌어졌습니다.",
            },
            "emotional": {
                "calm": "이것은 작은 마을에서 시작된 이야기입니다.",
                "sad": "그녀는 마지막으로 그의 손을 잡았습니다.",
                "happy": "그 순간, 모든 것이 의미 있게 느껴졌습니다.",
                "nostalgic": "어린 시절의 그 여름이 떠오릅니다.",
            },
        }

        genre_scripts = scripts.get(genre, {})
        result = {}

        for emotion in emotions:
            if emotion in genre_scripts:
                result[emotion] = genre_scripts[emotion]
            else:
                result[emotion] = f"{emotion} 감정으로 말하는 샘플 대사입니다."

        return result

    # --------------------------------------------------------
    # 토픽 제안
    # --------------------------------------------------------

    def _generate_topic_suggestions(
        self,
        genre: str,
        theme: str
    ) -> Dict[str, List[str]]:
        """토픽 제안 생성"""
        topic_data = {
            "horror": {
                "categories": ["도시괴담", "실화 공포", "심령현상", "학교 괴담", "병원 괴담"],
                "samples": [
                    "밤에 울려 퍼지는 전화벨",
                    "엘리베이터에서 만난 이상한 승객",
                    "빈 교실에서 들려오는 목소리",
                    "이사 간 집에서 발견한 일기장",
                    "야간 경비원이 본 것들",
                ],
                "banned": ["실제 범죄 미화", "자살 묘사", "아동 학대"],
            },
            "mystery": {
                "categories": ["미제 사건", "역사 미스터리", "과학 미스터리", "실종 사건"],
                "samples": [
                    "50년간 풀리지 않은 암호",
                    "사라진 비행기의 비밀",
                    "설명할 수 없는 현상들",
                    "역사 속 미해결 사건",
                ],
                "banned": ["피해자 신원 공개", "범죄 방법 상세 설명"],
            },
            "emotional": {
                "categories": ["감동 실화", "가족 이야기", "극복 스토리", "사랑 이야기"],
                "samples": [
                    "20년 만에 다시 만난 가족",
                    "기적의 생존 이야기",
                    "평범한 영웅들의 이야기",
                    "마지막 편지",
                ],
                "banned": ["비극적 결말 강조"],
            },
        }

        return topic_data.get(genre, {
            "categories": [f"{genre} 카테고리"],
            "samples": [f"{genre} 샘플 토픽"],
            "banned": [],
        })

    # --------------------------------------------------------
    # 저장
    # --------------------------------------------------------

    def _save_design(self, design: ChannelPackDesign) -> Path:
        """설계 결과 저장"""
        filepath = self.output_dir / f"{design.design_id}.json"

        # dataclass를 dict로 변환
        data = {
            "design_id": design.design_id,
            "channel_name": design.channel_name,
            "channel_name_kr": design.channel_name_kr,
            "genre": design.genre,
            "theme": design.theme,
            "theme_kr": design.theme_kr,
            "concept_summary": design.concept_summary,
            "target_audience": design.target_audience,
            "unique_selling_point": design.unique_selling_point,
            "characters": [asdict(c) for c in design.characters],
            "visual_style": design.visual_style,
            "color_palette": design.color_palette,
            "sd_models": [asdict(m) for m in design.sd_models],
            "prompt_template": asdict(design.prompt_template) if design.prompt_template else None,
            "voice_guide": asdict(design.voice_guide) if design.voice_guide else None,
            "topic_categories": design.topic_categories,
            "sample_topics": design.sample_topics,
            "banned_keywords": design.banned_keywords,
            "created_at": design.created_at,
            "source_insight_id": design.source_insight_id,
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"팩 설계 저장: {filepath}")
        return filepath

    def load_design(self, design_id: str) -> Optional[ChannelPackDesign]:
        """설계 결과 로드"""
        filepath = self.output_dir / f"{design_id}.json"

        if not filepath.exists():
            return None

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return ChannelPackDesign(
            # 필수 필드
            design_id=data["design_id"],
            channel_name=data["channel_name"],
            channel_name_kr=data["channel_name_kr"],
            genre=data["genre"],
            theme=data["theme"],
            visual_style=data.get("visual_style", "silhouette"),
            # 선택적 필드
            theme_kr=data.get("theme_kr", ""),
            concept_summary=data.get("concept_summary", ""),
            target_audience=data.get("target_audience", ""),
            unique_selling_point=data.get("unique_selling_point", ""),
            characters=[CharacterSpec(**c) for c in data.get("characters", [])],
            color_palette=data.get("color_palette", []),
            sd_models=[SDModelRecommendation(**m) for m in data.get("sd_models", [])],
            prompt_template=PromptTemplate(**data["prompt_template"]) if data.get("prompt_template") else None,
            voice_guide=VoiceGuideSpec(**data["voice_guide"]) if data.get("voice_guide") else None,
            topic_categories=data.get("topic_categories", []),
            sample_topics=data.get("sample_topics", []),
            banned_keywords=data.get("banned_keywords", []),
            created_at=data.get("created_at", ""),
            source_insight_id=data.get("source_insight_id", ""),
        )

    def list_designs(self) -> List[Dict]:
        """저장된 설계 목록"""
        files = sorted(self.output_dir.glob("design_*.json"), reverse=True)

        designs = []
        for f in files[:20]:
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    designs.append({
                        "design_id": data.get("design_id"),
                        "channel_name": data.get("channel_name"),
                        "channel_name_kr": data.get("channel_name_kr"),
                        "genre": data.get("genre"),
                        "created_at": data.get("created_at"),
                        "filepath": str(f),
                    })
            except (json.JSONDecodeError, KeyError, OSError) as e:
                    logger.debug(f"팩 디자인 파일 읽기 건너뜀: {f.name}: {e}")

        return designs


# ============================================================
# 유틸리티 함수
# ============================================================

def format_design_summary(design: ChannelPackDesign) -> str:
    """설계 요약 문자열 생성"""
    lines = [
        "━" * 50,
        f"📦 채널 팩 설계: {design.channel_name_kr}",
        "━" * 50,
        f"",
        f"🎬 장르: {design.genre}",
        f"🎯 테마: {design.theme_kr or design.theme}",
        f"",
        f"📝 컨셉:",
        f"   {design.concept_summary}",
        f"",
        f"👥 타겟: {design.target_audience}",
        f"✨ 차별점: {design.unique_selling_point}",
        f"",
        f"🎨 비주얼 스타일: {design.visual_style}",
    ]

    if design.sd_models:
        lines.append(f"")
        lines.append(f"🤖 추천 SD 모델:")
        for m in design.sd_models[:3]:
            lines.append(f"   • {m.model_name} ({m.model_type})")
            lines.append(f"     {m.civitai_url}")

    if design.voice_guide:
        vg = design.voice_guide
        lines.append(f"")
        lines.append(f"🎙️ 목소리 가이드:")
        lines.append(f"   성별: {vg.voice_gender} / 연령: {vg.voice_age} / 톤: {vg.voice_tone}")
        lines.append(f"   참조: {vg.reference_style}")
        lines.append(f"   필요 감정: {', '.join(vg.required_emotions)}")

    if design.sample_topics:
        lines.append(f"")
        lines.append(f"💡 샘플 토픽:")
        for topic in design.sample_topics[:3]:
            lines.append(f"   • {topic}")

    lines.append("")
    lines.append("━" * 50)

    return "\n".join(lines)


# ============================================================
# CLI 테스트
# ============================================================

def main():
    """CLI 테스트"""
    print("\n=== Reverie Factory - 팩 설계 AI ===\n")

    designer = PackDesigner()

    # 테스트 설계
    design = designer.design_channel_pack(
        manual_config={
            "genre": "horror",
            "theme": "학교 괴담",
            "style_type": "silhouette",
        }
    )

    print(format_design_summary(design))


if __name__ == "__main__":
    main()
