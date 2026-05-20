# src/config/pack_models.py
# ============================================================
# ReveriePack 데이터 모델 (DataClass / Enum / 헬퍼)
# v62.42b: pack_config.py에서 분리
# ============================================================
"""
팩 데이터 모델 정의 — 데이터클래스, Enum, 로딩 헬퍼 함수.

이 모듈은 순수 데이터 정의만 포함하며, 외부 의존성(cryptography, firebase 등)이 없다.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================
# 헬퍼 함수 (데이터 로딩)
# ============================================================

def _load_visual_storytelling_config(settings: Dict[str, Any]) -> 'VisualStorytellingConfig':
    """
    v59: 비주얼 스토리텔링 설정 로드 헬퍼

    Args:
        settings: settings.json에서 로드한 딕셔너리

    Returns:
        VisualStorytellingConfig 인스턴스
    """
    vs_data = settings.get("visual_storytelling", {})

    if not vs_data:
        return VisualStorytellingConfig()  # 기본값

    # SD 모델 설정
    sd_model_data = vs_data.get("sd_model", {})
    sd_model = SDModelConfig(
        checkpoint=sd_model_data.get("checkpoint", ""),
        vae=sd_model_data.get("vae", ""),
        sampler=sd_model_data.get("sampler", "DPM++ 2M Karras"),
        scheduler=sd_model_data.get("scheduler", "Karras"),
        steps=sd_model_data.get("steps", 15),  # v59.5.17: 28→15
        cfg_scale=sd_model_data.get("cfg_scale", 7.0),
        width=sd_model_data.get("width", 768),       # v59.5.14: 768x432 기본
        height=sd_model_data.get("height", 432),     # v59.5.14: SD 1.5 최적
        clip_skip=sd_model_data.get("clip_skip", 2),
        positive_base=sd_model_data.get("positive_base", ""),   # v59.3.0
        negative_base=sd_model_data.get("negative_base", ""),   # v59.3.0
        lora_models=sd_model_data.get("lora_models", []),
    )

    # v59.3.0: FIX-7 - 캐릭터 정의 (dict / list 둘 다 지원)
    characters = []
    chars_raw = vs_data.get("characters", [])
    if isinstance(chars_raw, dict):
        # JSON에서 characters가 dict인 경우 (horror_horror_v59.json 등)
        for char_id, char_data in chars_raw.items():
            if char_id.startswith('_'):
                continue
            if not isinstance(char_data, dict):
                continue
            char = CharacterDefinition(
                id=char_id,
                name=char_data.get("name", char_id),
                aliases=char_data.get("aliases", [char_id, char_data.get("name", "")]),
                base_prompt=char_data.get("base", char_data.get("base_prompt", "")),
                style_suffix=char_data.get("style", char_data.get("style_suffix", "")),
                expressions=char_data.get("expressions", {}),
                poses=char_data.get("poses", {}),
                reference_images=char_data.get("reference_images", []),
                lora=char_data.get("lora"),
                # v62.7: 성별/연령 교정 필드
                display_name=char_data.get("display_name", char_data.get("name", char_id)),
                gender_negative=char_data.get("gender_negative", ""),
                age_negative=char_data.get("age_negative", ""),
            )
            characters.append(char)
    else:
        # JSON에서 characters가 list인 경우 (기존 형식)
        for char_data in chars_raw:
            char = CharacterDefinition(
                id=char_data.get("id", ""),
                name=char_data.get("name", ""),
                aliases=char_data.get("aliases", []),
                base_prompt=char_data.get("base_prompt", char_data.get("base", "")),
                style_suffix=char_data.get("style_suffix", char_data.get("style", "")),
                expressions=char_data.get("expressions", {}),
                poses=char_data.get("poses", {}),
                reference_images=char_data.get("reference_images", []),
                lora=char_data.get("lora"),
                # v62.7: 성별/연령 교정 필드
                display_name=char_data.get("display_name", char_data.get("name", "")),
                gender_negative=char_data.get("gender_negative", ""),
                age_negative=char_data.get("age_negative", ""),
            )
            characters.append(char)

    cl_data = vs_data.get("character_library", {}) or {}
    if not isinstance(cl_data, dict):
        cl_data = {}
    character_library = CharacterLibraryConfig(
        enabled=cl_data.get("enabled", True),
        library_path=str(cl_data.get("library_path", "") or ""),
        auto_generate=cl_data.get("auto_generate", True),
        auto_generate_count=cl_data.get("auto_generate_count", 1),
        min_quality_score=cl_data.get("min_quality_score", 0.5),
        max_retries=cl_data.get("max_retries", 3),
        use_fixed_seed=cl_data.get("use_fixed_seed", True),
        face_detection_required=cl_data.get("face_detection_required", True),
        checkpoint_override=str(cl_data.get("checkpoint_override", "") or ""),
        preferred_slots=list(cl_data.get("preferred_slots", []) or []),
        preferred_expressions=list(cl_data.get("preferred_expressions", []) or []),
        preferred_poses=list(cl_data.get("preferred_poses", []) or []),
        required_variant_keys=list(cl_data.get("required_variant_keys", []) or []),
        required_variant_keys_by_slot=dict(cl_data.get("required_variant_keys_by_slot", {}) or {}),
        face_part_boxes_by_character=dict(cl_data.get("face_part_boxes_by_character", {}) or {}),
        sheet_style=str(cl_data.get("sheet_style", "cutout_sheet") or "cutout_sheet"),
        prioritize_sheet_generation=bool(cl_data.get("prioritize_sheet_generation", False)),
        max_face_count=int(cl_data.get("max_face_count", 1) or 1),
    )

    # 자막 스타일
    sub_data = vs_data.get("subtitle_style", {})
    subtitle_style = SubtitleStyle(
        font_family=sub_data.get("font_family", "Noto Sans KR"),
        font_size=sub_data.get("font_size", 48),
        font_weight=sub_data.get("font_weight", "bold"),
        text_color=sub_data.get("text_color", "#FFFFFF"),
        stroke_color=sub_data.get("stroke_color", "#000000"),
        stroke_width=sub_data.get("stroke_width", 3),
        shadow_color=sub_data.get("shadow_color", "rgba(0,0,0,0.8)"),
        shadow_blur=sub_data.get("shadow_blur", 8),
        background_enabled=sub_data.get("background_enabled", False),
        background_color=sub_data.get("background_color", "rgba(0,0,0,0.6)"),
        background_padding=sub_data.get("background_padding", 16),
        background_radius=sub_data.get("background_radius", 8),
        position=sub_data.get("position", "bottom"),
        margin_bottom=sub_data.get("margin_bottom", 80),
        text_align=sub_data.get("text_align", "center"),
        animation_in=sub_data.get("animation_in", "fadeIn"),
        animation_out=sub_data.get("animation_out", "fadeOut"),
        animation_duration=sub_data.get("animation_duration", 0.3),
        speaker_colors=sub_data.get("speaker_colors", {}),  # v59.5.14
    )

    # v59.5.14: 시각 효과 — nested 구조(horror_default.json)와 flat 구조 모두 지원
    ve_data = vs_data.get("visual_effects", {})

    # vignette: nested {"vignette": {"enabled": true, "intensity": 0.4}} 또는 flat {"vignette_enabled": true}
    vignette_data = ve_data.get("vignette", {})
    if isinstance(vignette_data, dict) and vignette_data:
        # nested 구조 (v59 JSON 팩: horror_default.json 등)
        ve_vignette_enabled = vignette_data.get("enabled", True)
        ve_vignette_intensity = vignette_data.get("intensity", 0.3)
        ve_vignette_color = vignette_data.get("color", "#000000")
    else:
        # flat 구조 (레거시 또는 create_horror_v59_pack.py 등)
        ve_vignette_enabled = ve_data.get("vignette_enabled", True)
        ve_vignette_intensity = ve_data.get("vignette_intensity", 0.3)
        ve_vignette_color = ve_data.get("vignette_color", "#000000")

    # color_filter: nested {"color_filter": {"type": "horror", ...}} 또는 flat {"color_filter_enabled": true}
    color_data = ve_data.get("color_filter", {})
    if isinstance(color_data, dict) and color_data:
        ve_color_enabled = "type" in color_data  # type 존재 = 활성화
        ve_color_filter = color_data.get("type", "")
        ve_color_intensity = color_data.get("saturation", color_data.get("intensity", 0.5))
    else:
        ve_color_enabled = ve_data.get("color_filter_enabled", False)
        ve_color_filter = ve_data.get("color_filter", "")
        ve_color_intensity = ve_data.get("color_filter_intensity", 0.5)

    # film_grain: nested {"film_grain": {"enabled": true, "intensity": 0.15}}
    film_data = ve_data.get("film_grain", {})
    # film_grain은 dataclass에 없으므로 로그만 남김 (미래 확장용)

    visual_effects = VisualEffect(
        vignette_enabled=ve_vignette_enabled,
        vignette_intensity=ve_vignette_intensity,
        vignette_color=ve_vignette_color,
        color_filter_enabled=ve_color_enabled,
        color_filter=ve_color_filter,
        color_filter_intensity=ve_color_intensity,
        frame_enabled=ve_data.get("frame_enabled", False),
        frame_image=ve_data.get("frame_image", ""),
        frame_opacity=ve_data.get("frame_opacity", 1.0),
        particles_enabled=ve_data.get("particles_enabled", False),
        particles_type=ve_data.get("particles_type", ""),
        particles_density=ve_data.get("particles_density", 0.5),
        ken_burns_enabled=ve_data.get("ken_burns_enabled", True),
        ken_burns_zoom_range=ve_data.get("ken_burns_zoom_range", [1.0, 1.15]),
        ken_burns_pan_enabled=ve_data.get("ken_burns_pan_enabled", True),
    )

    # v59.5.14: 씬 전환 — visual_effects.transitions 또는 visual_storytelling.transitions 둘 다 지원
    trans_data = ve_data.get("transitions", {})  # visual_effects 내부 (horror_default.json 구조)
    if not trans_data:
        trans_data = vs_data.get("transitions", {})  # visual_storytelling 직접 자식 (레거시)

    transitions = TransitionStyle(
        # "default" 또는 "default_transition" 둘 다 지원
        default_transition=trans_data.get("default_transition", trans_data.get("default", "crossfade")),
        transition_duration=trans_data.get("transition_duration", trans_data.get("duration", 0.5)),
        scene_transitions=trans_data.get("scene_transitions", {}),
    )

    return VisualStorytellingConfig(
        enabled=vs_data.get("enabled", False),
        sd_model=sd_model,
        characters=characters,
        character_library=character_library,
        subtitle_style=subtitle_style,
        visual_effects=visual_effects,
        transitions=transitions,
        images_per_minute=vs_data.get("images_per_minute", 3),
        min_scene_duration=vs_data.get("min_scene_duration", 3.0),
        max_consecutive_reuse=vs_data.get("max_consecutive_reuse", 2),
        prompt_strategy=vs_data.get("prompt_strategy", "panel_card"),
        llm_hint_tag_limit=vs_data.get("llm_hint_tag_limit", 4),
        face_detection_enabled=vs_data.get("face_detection_enabled", True),
        nsfw_filter_enabled=vs_data.get("nsfw_filter_enabled", True),
        blur_check_enabled=vs_data.get("blur_check_enabled", True),
        retry_on_failure=vs_data.get("retry_on_failure", 3),
    )


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class PackPrompts:
    """팩 프롬프트 설정 — v60: 모든 Gemini 프롬프트를 팩에서 로딩"""
    # === 기존 (유지) ===
    pd_system: str = ""
    writer_system: str = ""
    sd_positive: str = ""
    sd_negative: str = ""
    # === v60: 토픽 생성 ===
    topic_generation: str = ""       # prompts/topic_generation.txt
    topic_enhanced: str = ""         # prompts/topic_enhanced.txt
    # === v60: 훅 생성 ===
    hook_generation: str = ""        # prompts/hook_generation.txt
    hook_enhanced: str = ""          # prompts/hook_enhanced.txt
    # === v60: 메타데이터 ===
    metadata_generation: str = ""    # prompts/metadata_generation.txt
    thumbnail_style_guide: str = ""  # prompts/thumbnail_style.txt
    # === v60: 스토리 바이블 ===
    story_bible: str = ""            # prompts/story_bible.txt
    story_bible_improve: str = ""    # prompts/story_bible_improve.txt
    story_summarize: str = ""        # prompts/story_summarize.txt
    # === v60: 구조적 아웃라인 ===
    structural_outline: str = ""     # prompts/structural_outline.txt
    # === v60: 글쓰기 규칙 ===
    craft_rules: str = ""            # prompts/craft_rules.txt
    pacing_part1: str = ""           # prompts/pacing_part1.txt
    pacing_part2: str = ""           # prompts/pacing_part2.txt
    pacing_part3: str = ""           # prompts/pacing_part3.txt
    # === v60: 이미지 생성 ===
    image_style: str = ""            # prompts/image_style.txt
    image_llm_prompt: str = ""       # prompts/image_llm_prompt.txt
    # === v61.1: 콜드 오프닝 ===
    cold_open_bridge: str = ""       # prompts/cold_open_bridge.txt
    # === v62: 바이블+아웃라인 통합 ===
    story_blueprint: str = ""        # prompts/story_blueprint.txt


@dataclass
class PackContent:
    """팩 콘텐츠 설정"""
    duration_minutes: int = 5
    min_turns: int = 45  # 기본값: 45턴 × 3파트 = 135턴
    max_turns: int = 70  # 기본 상한: 45~70턴 범위로 여유 확보
    image_style: str = ""


@dataclass
class PackAssets:
    """팩 에셋 경로"""
    bgm_path: str = ""
    sfx_path: str = ""
    bgm_folder: str = ""  # v58: assets/bgm/{folder} 형태
    sfx_folder: str = ""  # v58: assets/sfx/{folder} 형태
    sfx_enabled: bool = True
    sfx_category: str = ""  # "horror", "emotional" 등
    sfx_intensity: str = "medium"  # "low", "medium", "high"
    # v57.7.3: 기존 채널 리소스 사용 설정
    use_channel_bgm: bool = True
    use_channel_sfx: bool = True
    use_channel_tts: bool = True
    # v57.8: 나레이터 타입 직접 지정
    narrator: str = ""  # "narrator_male", "narrator_female" - 사용할 나레이터 모델


def _normalize_pack_channel_toggle(value: Any) -> Any:
    """Allow legacy bool-like strings while preserving explicit channel ids."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        return value.strip()
    return value


# v58: TTS 설정
@dataclass
class PackTTS:
    """v58: TTS 설정"""
    narrator: str = "narrator_male"
    narrator_voice: str = ""  # v62.40: 채널별 나레이터 TTS 고정 (임의 voice_type 허용, 빈 값=기존 분기)
    character_mapping: Dict[str, str] = field(default_factory=dict)
    default_emotion: str = "calm"
    allowed_emotions: List[str] = field(default_factory=list)
    emotion_weights: Dict[str, int] = field(default_factory=dict)
    narration_only: bool = False  # v62.40: True이면 나레이션 전용 모드 (모든 대사를 narrator 단일 역할로)


# v58: Visual 설정
@dataclass
class PackVisual:
    """v58: Visual/이미지 생성 설정"""
    character_system_enabled: bool = False
    forced_style: Dict[str, str] = field(default_factory=dict)  # force_positive, force_negative
    thumbnail_backgrounds: List[str] = field(default_factory=list)
    safe_fallbacks: List[str] = field(default_factory=list)
    safe_fallback_prompt: str = ""


# v58: Hook 스타일 설정
@dataclass
class PackHookStyle:
    """v58: 훅 장면 스타일"""
    top_label: str = "【 이야기 】"
    top_color: str = "#FFFFFF"
    main_color: str = "#FFFFFF"
    bg_color: List[int] = field(default_factory=lambda: [0, 0, 0])
    duration: float = 4.0


# v58: SD 설정
@dataclass
class PackSD:
    """v58: Stable Diffusion 설정"""
    positive: str = ""
    negative: str = ""
    cfg_scale: float = 6.5
    steps: int = 15  # v59.5.17: 28→15
    model: str = ""  # 체크포인트 이름 (기존 환경 사용)


# v58: 썸네일 설정
@dataclass
class PackThumbnail:
    """v58: 썸네일 설정"""
    text_default: str = ""
    style_guide: str = ""
    title_hooks: List[str] = field(default_factory=list)  # v60.1.0: 썸네일 제목 후크


# v58: 비디오 설정
@dataclass
class PackVideo:
    """v58: 비디오 렌더링 설정"""
    pause_duration: float = 0.4
    zoom_speed: float = 1.0


# v58: 시나리오 풀
@dataclass
class PackScenario:
    """v58: 시나리오 생성용 풀"""
    safe_templates: List[str] = field(default_factory=list)  # 이미지 프롬프트 템플릿
    tone_pool: List[str] = field(default_factory=list)  # 감동 스토리 톤
    relationship_pool: List[str] = field(default_factory=list)
    place_pool: List[str] = field(default_factory=list)
    arc_pool: List[str] = field(default_factory=list)
    trigger_pool: List[str] = field(default_factory=list)
    twist_pool: List[str] = field(default_factory=list)  # 막장용
    conflict_pool: List[str] = field(default_factory=list)  # 막장용
    mystery_types: List[str] = field(default_factory=list)  # 미스터리용
    evidence_pool: List[str] = field(default_factory=list)  # 미스터리용


# v60: SFX 설정
@dataclass
class PackSFX:
    """v60: 팩별 SFX 설정 — settings.json의 sfx 섹션에서 로딩"""
    category_guide: str = ""  # AI 분석용 SFX 카테고리 가이드
    keyword_map: Dict[str, str] = field(default_factory=dict)  # 한국어 키워드 → SFX 태그


# v60: 분위기 설정
@dataclass
class PackAtmosphere:
    """v60: 팩별 분위기 설정 — settings.json의 atmosphere 섹션에서 로딩"""
    mood_map: Dict[str, str] = field(default_factory=dict)  # 분위기 → SD 라이팅 키워드
    keywords: Dict[str, List[str]] = field(default_factory=dict)  # 분위기 → 한국어 키워드


# v60: 비상 템플릿
@dataclass
class PackEmergency:
    """v60: 비상 템플릿 시퀀스 — settings.json의 emergency 섹션에서 로딩"""
    template_sequence: List[List[str]] = field(default_factory=list)  # [[role, char, text, emotion], ...]


# ============================================================
# v59: 비주얼 스토리텔링 DataClass (Visual Storytelling)
# ============================================================

class ImageAction(Enum):
    """v59: 이미지 액션 타입"""
    NEW = "new"                      # 새 이미지 생성
    EXPRESSION_SWAP = "expression"   # 표정만 변경 (같은 캐릭터)
    POSE_SWAP = "pose"               # 포즈 변경 (같은 캐릭터)
    REUSE = "reuse"                  # 이전 이미지 재사용


@dataclass
class SDModelConfig:
    """
    v59: SD 모델 설정
    팩별로 다른 체크포인트/VAE/샘플러 사용 가능
    """
    checkpoint: str = ""              # 체크포인트 파일명 (예: "ghostmix_v20.safetensors")
    vae: str = ""                     # VAE 파일명 (빈 문자열 = 기본 VAE)
    sampler: str = "DPM++ 2M Karras"  # 샘플러
    scheduler: str = "Karras"         # 스케줄러
    steps: int = 15                   # 샘플링 스텝 (v59.5.17: 28→15)
    cfg_scale: float = 7.0            # CFG 스케일
    width: int = 768                  # v59.5.5: 768x432 기본 (16:9)
    height: int = 432                 # v59.5.5: SD 1.5 최적 해상도
    clip_skip: int = 2                # CLIP Skip

    # v59.3.0: 기본 프롬프트 (모든 이미지에 공통 적용)
    positive_base: str = ""           # 기본 positive (예: "dark digital painting, horror concept art")
    negative_base: str = ""           # 기본 negative (예: "bright colors, anime, photorealistic")

    # LoRA 설정 (캐릭터/스타일)
    lora_models: List[Dict[str, Any]] = field(default_factory=list)
    # 예: [{"name": "yadam_style_v1", "weight": 0.7}]


@dataclass
class CharacterDefinition:
    """
    v59: 캐릭터 정의
    스토리 내 캐릭터의 외형/프롬프트 정의
    """
    id: str = ""                      # 고유 ID (예: "chulsoo", "younghee")
    name: str = ""                    # 표시 이름 (예: "철수", "영희")
    aliases: List[str] = field(default_factory=list)  # 별칭 (예: ["철수", "주인공", "남자"])

    # 외형 프롬프트
    base_prompt: str = ""             # 기본 외형 (예: "korean man, 30s, short black hair")
    style_suffix: str = ""            # 스타일 접미사 (예: "hanbok, traditional")

    # v62.7: 성별/연령 교정용 negative 프롬프트
    display_name: str = ""            # 자막 표시용 한국어 이름 (예: "할머니")
    gender_negative: str = ""         # 성별 교정 negative (예: "female, girl, woman, ...")
    age_negative: str = ""            # 연령 교정 negative (예: "young, teenager, ...")

    # 표정/포즈 프롬프트 매핑
    expressions: Dict[str, str] = field(default_factory=dict)
    # 예: {"happy": "smiling, bright eyes", "sad": "crying, tears"}

    poses: Dict[str, str] = field(default_factory=dict)
    # 예: {"standing": "standing pose", "sitting": "sitting on floor"}

    # 참조 이미지 경로 (LoRA 학습용 또는 IP-Adapter용)
    reference_images: List[str] = field(default_factory=list)

    # LoRA 모델 (캐릭터 전용)
    lora: Optional[Dict[str, Any]] = None
    # 예: {"name": "chulsoo_lora_v1", "weight": 0.8, "trigger": "chulsoo_character"}


@dataclass
class CharacterLibrary:
    """
    v59: 캐릭터 라이브러리
    사전 생성된 캐릭터 이미지 풀
    """
    character_id: str = ""

    # 사전 생성된 이미지 경로 (표정 × 포즈 조합)
    # 키: "{expression}_{pose}" (예: "happy_standing", "sad_sitting")
    images: Dict[str, str] = field(default_factory=dict)

    # 생성 상태
    is_generated: bool = False
    generation_timestamp: str = ""


@dataclass
class CharacterLibraryConfig:
    """v64: 고정 캐스트 시트/캐릭터 라이브러리 설정"""
    enabled: bool = True
    library_path: str = ""
    auto_generate: bool = True
    auto_generate_count: int = 1
    min_quality_score: float = 0.5
    max_retries: int = 3
    use_fixed_seed: bool = True
    face_detection_required: bool = True
    checkpoint_override: str = ""
    preferred_slots: List[str] = field(default_factory=list)
    preferred_expressions: List[str] = field(default_factory=list)
    preferred_poses: List[str] = field(default_factory=list)
    required_variant_keys: List[str] = field(default_factory=list)
    required_variant_keys_by_slot: Dict[str, List[str]] = field(default_factory=dict)
    face_part_boxes_by_character: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    sheet_style: str = "cutout_sheet"
    prioritize_sheet_generation: bool = False
    max_face_count: int = 1


@dataclass
class SceneContext:
    """
    v59: 장면 컨텍스트
    SceneAnalyzer가 대사를 분석해서 추출한 정보
    """
    # 등장 캐릭터
    characters: List[Dict[str, str]] = field(default_factory=list)
    # 예: [{"id": "chulsoo", "emotion": "happy", "action": "talking"}]

    # 장면 설정
    location: str = ""                # 장소 (예: "한옥 마루", "숲속 오두막")
    time_of_day: str = ""             # 시간대 (예: "night", "dawn", "afternoon")
    weather: str = ""                 # 날씨 (예: "rainy", "foggy", "clear")
    atmosphere: str = ""              # 분위기 (예: "tense", "peaceful", "mysterious")

    # 스토리 흐름
    story_beat: str = ""              # 스토리 비트 (예: "rising_action", "climax")
    previous_scene_id: Optional[str] = None  # 이전 장면 ID (연속성)

    # 이미지 액션 결정
    image_action: str = "new"         # "new", "expression", "pose", "reuse"
    reuse_image_path: Optional[str] = None  # reuse 시 참조할 이미지


@dataclass
class SubtitleStyle:
    """
    v59: 자막 스타일
    팩별 자막 디자인
    """
    font_family: str = "Noto Sans KR"
    font_size: int = 48
    font_weight: str = "bold"

    # 색상 (HEX)
    text_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 3
    shadow_color: str = "rgba(0,0,0,0.8)"
    shadow_blur: int = 8

    # 배경 (선택적)
    background_enabled: bool = False
    background_color: str = "rgba(0,0,0,0.6)"
    background_padding: int = 16
    background_radius: int = 8

    # 위치/정렬
    position: str = "bottom"          # "top", "center", "bottom"
    margin_bottom: int = 80
    text_align: str = "center"

    # 애니메이션
    animation_in: str = "fadeIn"      # "fadeIn", "slideUp", "typewriter"
    animation_out: str = "fadeOut"
    animation_duration: float = 0.3

    # v59.5.14: 화자별 자막 색상
    speaker_colors: Dict[str, str] = field(default_factory=dict)
    # 예: {"나레이션": "#CCCCCC", "주인공": "#FFFFFF", "귀신": "#FF4444"}


@dataclass
class VisualEffect:
    """
    v59: 시각 효과
    팩별 비주얼 효과
    """
    # 비네팅
    vignette_enabled: bool = True
    vignette_intensity: float = 0.3
    vignette_color: str = "#000000"

    # 컬러 필터
    color_filter_enabled: bool = False
    color_filter: str = ""            # "sepia", "cold", "warm", "horror"
    color_filter_intensity: float = 0.5

    # 프레임/오버레이
    frame_enabled: bool = False
    frame_image: str = ""             # 프레임 이미지 경로
    frame_opacity: float = 1.0

    # 파티클 효과
    particles_enabled: bool = False
    particles_type: str = ""          # "dust", "rain", "snow", "fireflies"
    particles_density: float = 0.5

    # Ken Burns (이미 v58에서 구현됨, 설정 확장)
    ken_burns_enabled: bool = True
    ken_burns_zoom_range: List[float] = field(default_factory=lambda: [1.0, 1.15])
    ken_burns_pan_enabled: bool = True


@dataclass
class TransitionStyle:
    """
    v59: 씬 전환 스타일
    """
    default_transition: str = "crossfade"  # "crossfade", "fade_black", "slide", "zoom"
    transition_duration: float = 0.5

    # 장면 유형별 전환
    scene_transitions: Dict[str, str] = field(default_factory=dict)
    # 예: {"flashback": "fade_white", "nightmare": "glitch", "climax": "zoom_blur"}


@dataclass
class ScriptQualityConfig:
    """팩이 제어하는 대본 품질 게이트 임계값."""

    min_non_narrator_roles: int = 3
    max_narration_ratio: float = 0.5
    min_turns_for_gate: int = 20
    max_ellipsis_ratio: float = 0.12
    warn_topic_overlap_ratio: float = 0.25


@dataclass
class MotiontoonConfig:
    """팩이 제어하는 제한 애니메이션 설정."""

    enabled: bool = False
    mode: str = "screen_space"
    profile: str = "basic"
    character_layer_mode: str = ""
    overlay_theme: str = "default"
    default_scene_type: str = "dialogue"
    blink_enabled: bool = False
    mouth_flap_enabled: bool = False
    layered_cutout_enabled: bool = False
    layered_cutout_strength: float = 0.65
    prop_overlay_enabled: bool = True
    dialogue_panel_enabled: bool = True
    idle_drift_enabled: bool = True
    impact_shake_enabled: bool = True
    snap_zoom_enabled: bool = True
    subtitle_pulse_enabled: bool = True
    slow_push_enabled: bool = True
    shorts_vertical_ready: bool = True
    video_toon_local_enabled: bool = False
    video_toon_generation_backend: str = "comfyui"
    video_toon_layered_assets_required: bool = False
    video_toon_workflow_template: str = "sd15_ipadapter_openpose_v1"
    prop_keywords: List[str] = field(default_factory=list)
    scene_motion_rules: Dict[str, List[str]] = field(default_factory=dict)
    cast_slots: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    puppet_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _normalize_motiontoon_profile(profile: Any, enabled: bool) -> str:
    """Normalize pack-declared motiontoon support tiers."""
    if not enabled:
        return "none"

    normalized = str(profile or "").strip().lower().replace("-", "_")
    aliases = {
        "": "basic",
        "default": "basic",
        "screen_space": "basic",
        "basic_only": "basic",
        "classic": "basic",
        "none": "none",
        "disabled": "none",
        "off": "none",
        "gishini": "gishini",
        "gishini_motiontoon": "gishini",
        "advanced": "gishini",
        "cinematic": "gishini",
    }
    return aliases.get(normalized, "basic")


def _clone_motiontoon_config(motiontoon: "MotiontoonConfig") -> "MotiontoonConfig":
    return MotiontoonConfig(
        enabled=getattr(motiontoon, "enabled", False),
        mode=getattr(motiontoon, "mode", "screen_space"),
        profile=_normalize_motiontoon_profile(
            getattr(motiontoon, "profile", "basic"),
            getattr(motiontoon, "enabled", False),
        ),
        character_layer_mode=str(getattr(motiontoon, "character_layer_mode", "") or ""),
        overlay_theme=str(getattr(motiontoon, "overlay_theme", "default") or "default"),
        default_scene_type=getattr(motiontoon, "default_scene_type", "dialogue"),
        blink_enabled=getattr(motiontoon, "blink_enabled", False),
        mouth_flap_enabled=getattr(motiontoon, "mouth_flap_enabled", False),
        layered_cutout_enabled=getattr(motiontoon, "layered_cutout_enabled", False),
        layered_cutout_strength=float(getattr(motiontoon, "layered_cutout_strength", 0.65) or 0.65),
        prop_overlay_enabled=getattr(motiontoon, "prop_overlay_enabled", True),
        dialogue_panel_enabled=getattr(motiontoon, "dialogue_panel_enabled", True),
        idle_drift_enabled=getattr(motiontoon, "idle_drift_enabled", True),
        impact_shake_enabled=getattr(motiontoon, "impact_shake_enabled", True),
        snap_zoom_enabled=getattr(motiontoon, "snap_zoom_enabled", True),
        subtitle_pulse_enabled=getattr(motiontoon, "subtitle_pulse_enabled", True),
        slow_push_enabled=getattr(motiontoon, "slow_push_enabled", True),
        shorts_vertical_ready=getattr(motiontoon, "shorts_vertical_ready", True),
        video_toon_local_enabled=getattr(motiontoon, "video_toon_local_enabled", False),
        video_toon_generation_backend=str(getattr(motiontoon, "video_toon_generation_backend", "comfyui") or "comfyui"),
        video_toon_layered_assets_required=getattr(motiontoon, "video_toon_layered_assets_required", False),
        video_toon_workflow_template=str(
            getattr(motiontoon, "video_toon_workflow_template", "sd15_ipadapter_openpose_v1")
            or "sd15_ipadapter_openpose_v1"
        ),
        prop_keywords=list(getattr(motiontoon, "prop_keywords", []) or []),
        scene_motion_rules=dict(getattr(motiontoon, "scene_motion_rules", {}) or {}),
        cast_slots=dict(getattr(motiontoon, "cast_slots", {}) or {}),
        puppet_profiles=dict(getattr(motiontoon, "puppet_profiles", {}) or {}),
    )


@dataclass
class VisualStorytellingConfig:
    """
    v59: 비주얼 스토리텔링 통합 설정
    팩에 추가되는 최상위 설정
    """
    # 활성화 여부
    enabled: bool = False

    # SD 모델 설정
    sd_model: SDModelConfig = field(default_factory=SDModelConfig)

    # 캐릭터 정의
    characters: List[CharacterDefinition] = field(default_factory=list)
    character_library: CharacterLibraryConfig = field(default_factory=CharacterLibraryConfig)

    # 자막 스타일
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)

    # 시각 효과
    visual_effects: VisualEffect = field(default_factory=VisualEffect)

    # 씬 전환
    transitions: TransitionStyle = field(default_factory=TransitionStyle)

    # 이미지 생성 설정
    images_per_minute: int = 3        # 분당 이미지 수 (기본 3 → 45/15분)
    min_scene_duration: float = 3.0   # 최소 장면 유지 시간 (초)
    max_consecutive_reuse: int = 2    # 연속 재사용 최대 횟수
    prompt_strategy: str = "panel_card"
    llm_hint_tag_limit: int = 4

    # 품질 설정
    face_detection_enabled: bool = True   # 얼굴 검출 (품질 검증)
    nsfw_filter_enabled: bool = True      # NSFW 필터
    blur_check_enabled: bool = True       # 블러 체크
    retry_on_failure: int = 3             # 실패 시 재시도 횟수
