# src/config/pack_config.py
# ============================================================
# ReveriePack 활성 설정 관리
# v59.0.0: 비주얼 스토리텔링 - 캐릭터 라이브러리, 장면 분석, 스토리 연속성
# v58.0.0: 완전 팩화 - TTS/Visual/Hook/Scenario 등 모든 설정 팩에서 로드
# v57.7.1: 팩 기반 프롬프트 시스템 + 암호화 지원
# v62.42b: pack_models.py / pack_crypto.py로 분리 (하위호환 re-export 유지)
# ============================================================
"""
config.ACTIVE_PACK - 현재 활성화된 팩 설정

사용법:
    from config.pack_config import ACTIVE_PACK, load_pack, get_prompt

    # 팩 로드
    load_pack("path/to/pack.revpack")

    # 프롬프트 가져오기
    pd_prompt = get_prompt("pd_system")
    writer_prompt = get_prompt("writer_system")
    sd_positive = get_prompt("sd_positive")
"""

import os
import sys
import io
import json
import functools
import zipfile
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# pack_models.py에서 데이터 모델 import + re-export
# ============================================================
from config.pack_models import (
    # 헬퍼 함수
    _load_visual_storytelling_config,
    _normalize_pack_channel_toggle,
    _normalize_motiontoon_profile,
    _clone_motiontoon_config,
    # 데이터클래스
    PackPrompts,
    PackContent,
    PackAssets,
    PackTTS,
    PackVisual,
    PackHookStyle,
    PackSD,
    PackThumbnail,
    PackVideo,
    PackScenario,
    PackSFX,
    PackAtmosphere,
    PackEmergency,
    # v59 비주얼 스토리텔링
    ImageAction,
    SDModelConfig,
    CharacterDefinition,
    CharacterLibrary,
    CharacterLibraryConfig,
    SceneContext,
    SubtitleStyle,
    VisualEffect,
    TransitionStyle,
    ScriptQualityConfig,
    MotiontoonConfig,
    VisualStorytellingConfig,
)

# ============================================================
# pack_crypto.py에서 보안 기능 import + re-export
# ============================================================
from config.pack_crypto import (
    CRYPTO_AVAILABLE,
    _is_dev_pack_mode,
    _is_encrypted_pack_required,
    _allow_legacy_pack_key,
    configure_pack_crypto,
    _resolve_pack_crypto_params,
    _get_pack_sign_key,
    calc_pack_signature,
    _verify_pack_signature,
    _is_pack_strict_access,
    _check_pack_access,
    _server_pack_keys,
    fetch_pack_key_from_server,
    _decrypt_content_with_password,
    _get_decryption_key,
    _decrypt_content,
    # 하위호환: 내부 상수도 re-export (테스트에서 참조)
    _DEFAULT_PACK_ENCRYPTION_SALT,
    _LEGACY_PACK_ENCRYPTION_PASSWORD_ENV,
    _PACK_SIGN_SUFFIX,
)

# v59.1.0: 팩 검증기
try:
    from config.pack_validator import validate_pack, ValidationResult
    VALIDATOR_AVAILABLE = True
except ImportError:
    VALIDATOR_AVAILABLE = False
    logger.debug("[PackConfig] pack_validator 미설치, 검증 스킵")

# v61.1: 다른 모듈에서 `from config.pack_config import PACK_CONFIG_AVAILABLE` 할 때 사용
# scenario_planner, script_writers 등은 try/except로 자체 정의하지만,
# tts_manager, sfx_analyzer 등은 함수 내부에서 직접 import하므로 여기서 정의 필수
PACK_CONFIG_AVAILABLE = True


# ============================================================
# v59: 샘플 팩 설정 (야담 스타일)
# ============================================================

YADAM_VISUAL_STORYTELLING = VisualStorytellingConfig(
    enabled=True,
    sd_model=SDModelConfig(
        checkpoint="ghostmix_v20.safetensors",  # 예시
        sampler="DPM++ 2M Karras",
        steps=15,            # v59.5.17: 28→15 최적화 (DPM++ 2M Karras)
        cfg_scale=7.0,
        width=768,           # v59.5.14: 768x432 기본
        height=432,
    ),
    characters=[
        CharacterDefinition(
            id="narrator",
            name="이야기꾼",
            aliases=["나레이터", "화자"],
            base_prompt="korean elderly man, 60s, wise appearance, traditional hanbok",
        ),
        CharacterDefinition(
            id="protagonist",
            name="주인공",
            aliases=["주인공", "나", "청년"],
            base_prompt="korean young man, 20s, humble appearance",
            expressions={
                "neutral": "calm expression",
                "fear": "frightened, wide eyes, pale face",
                "surprise": "shocked expression, open mouth",
                "sad": "sorrowful, tears in eyes",
            },
            poses={
                "standing": "standing pose",
                "sitting": "sitting on floor, traditional style",
                "walking": "walking through path",
                "running": "running in fear",
            },
        ),
    ],
    subtitle_style=SubtitleStyle(
        font_family="Noto Serif KR",
        font_size=44,
        text_color="#F5E6C8",           # 골드/크림 색상
        stroke_color="#2C1810",         # 어두운 갈색
        stroke_width=4,
        background_enabled=True,
        background_color="rgba(20, 15, 10, 0.75)",
        background_padding=20,
        background_radius=4,
        position="bottom",
        margin_bottom=60,
    ),
    visual_effects=VisualEffect(
        vignette_enabled=True,
        vignette_intensity=0.4,
        color_filter_enabled=True,
        color_filter="sepia",
        color_filter_intensity=0.2,
        frame_enabled=True,
        frame_image="assets/frames/yadam_scroll_frame.png",
        particles_enabled=True,
        particles_type="dust",
        particles_density=0.3,
    ),
    transitions=TransitionStyle(
        default_transition="crossfade",
        transition_duration=0.6,
        scene_transitions={
            "flashback": "fade_white",
            "nightmare": "fade_black",
            "climax": "zoom_blur",
        },
    ),
    images_per_minute=4,
    min_scene_duration=4.0,
)


@dataclass
class ActivePack:
    """현재 활성화된 팩 설정"""
    # 기본 정보
    pack_id: str = ""
    pack_name: str = ""
    version: str = ""
    author: str = ""
    genre: str = ""
    channel_type: str = ""  # v59.1.6: genre의 별칭 (visual_director 등에서 참조)

    # 프롬프트
    prompts: PackPrompts = field(default_factory=PackPrompts)

    # 콘텐츠 설정
    content: PackContent = field(default_factory=PackContent)

    # 토픽 & 태그
    topic_templates: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    intro_scripts: List[str] = field(default_factory=list)  # v58: 인트로 멘트

    # 캐릭터 설정
    characters: Dict[str, Any] = field(default_factory=dict)
    character_config: Dict[str, str] = field(default_factory=dict)

    # v57.7.5: 감정 설정 (TTS 감정 연기용) - v58: PackTTS로 통합
    allowed_emotions: List[str] = field(default_factory=list)
    emotion_policy: Dict[str, int] = field(default_factory=dict)  # {"scared": 2, "calm": 5}
    emotion_correction_targets: Dict[str, int] = field(default_factory=dict)  # v62.21: _emotion_post_correct 장르별 타겟

    # 스타일 설정
    style: Dict[str, Any] = field(default_factory=dict)
    restrictions: Dict[str, Any] = field(default_factory=dict)

    # 에셋 경로
    assets: PackAssets = field(default_factory=PackAssets)

    # v58: 확장 설정
    tts: PackTTS = field(default_factory=PackTTS)
    visual: PackVisual = field(default_factory=PackVisual)
    hook_style: PackHookStyle = field(default_factory=PackHookStyle)
    sd: PackSD = field(default_factory=PackSD)
    thumbnail: PackThumbnail = field(default_factory=PackThumbnail)
    video: PackVideo = field(default_factory=PackVideo)
    scenario: PackScenario = field(default_factory=PackScenario)

    # v59: 비주얼 스토리텔링 설정
    visual_storytelling: VisualStorytellingConfig = field(default_factory=VisualStorytellingConfig)
    script_quality: ScriptQualityConfig = field(default_factory=ScriptQualityConfig)
    motiontoon: MotiontoonConfig = field(default_factory=MotiontoonConfig)

    # v59.1.0: 요구사항 (SD 모델 등)
    requirements: Dict[str, Any] = field(default_factory=dict)

    # v59.5.6: SceneAnalyzer 아트 스타일 (데이터 드리븐)
    scene_analyzer: Dict[str, Any] = field(default_factory=dict)
    background_library: Dict[str, Any] = field(default_factory=dict)

    # v60: 팩-클라이언트 아키텍처 확장
    sfx: PackSFX = field(default_factory=PackSFX)
    atmosphere: PackAtmosphere = field(default_factory=PackAtmosphere)
    emergency: PackEmergency = field(default_factory=PackEmergency)

    # 로드 상태
    is_loaded: bool = False
    source_path: str = ""

    def is_valid(self) -> bool:
        """팩이 유효한지 확인"""
        return self.is_loaded and bool(self.pack_id)


# ============================================================
# v63.0: 스레드 안전 래퍼
# ============================================================

class PackContext:
    """ACTIVE_PACK 스레드 안전 래퍼

    v63.0: 글로벌 ACTIVE_PACK의 스레드 안전 접근을 보장하고,
    향후 의존성 주입(DI) 패턴 전환의 브리지 역할.

    사용법:
        pack_ctx = PackContext.instance()
        pack = pack_ctx.current  # 현재 ActivePack 접근
        with pack_ctx.lock:     # 쓰기 시 락 사용
            pack_ctx.set(new_pack)
    """
    _instance = None
    _lock = threading.RLock()  # 재진입 가능 락

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pack = None
        return cls._instance

    @classmethod
    def instance(cls) -> 'PackContext':
        """싱글톤 인스턴스 반환"""
        return cls()

    @property
    def current(self) -> 'ActivePack':
        """현재 로드된 팩 반환 (읽기 — 락 불필요)"""
        return self._pack

    @property
    def lock(self) -> threading.RLock:
        """쓰기 작업 시 사용할 락"""
        return self._lock

    def set(self, pack: 'ActivePack') -> None:
        """팩 설정 (락 내에서 호출할 것)"""
        self._pack = pack

    @property
    def is_loaded(self) -> bool:
        """팩 로드 여부"""
        return self._pack is not None and self._pack.is_loaded

    def __getattr__(self, name):
        """ActivePack 주요 속성 위임 (하위호환)"""
        if name.startswith('_'):
            raise AttributeError(name)
        pack = self._pack
        if pack is not None:
            return getattr(pack, name)
        raise AttributeError(f"PackContext: 팩이 로드되지 않았습니다 (속성: {name})")


# ============================================================
# 전역 인스턴스
# ============================================================

ACTIVE_PACK = ActivePack()

# v63.0: PackContext 싱글톤에 ACTIVE_PACK 동기화
_pack_ctx = PackContext.instance()
_pack_ctx.set(ACTIVE_PACK)


def _with_pack_lock(func):
    """v63.0: ACTIVE_PACK 쓰기 함수에 RLock 자동 적용 데코레이터.
    RLock이므로 load_pack_by_id → load_pack 같은 재진입 호출도 안전."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _pack_ctx.lock:
            return func(*args, **kwargs)
    return wrapper


def _default_script_quality_config(category: str = "", mode: str = "") -> ScriptQualityConfig:
    category = (category or "").strip().lower()
    mode = (mode or "").strip().lower()

    if category == "horror":
        return ScriptQualityConfig(
            min_non_narrator_roles=2,
            max_narration_ratio=0.55,
        )
    if category == "senior" and mode == "makjang":
        return ScriptQualityConfig(
            min_non_narrator_roles=3,
            max_narration_ratio=0.35,
        )
    if category == "senior":
        return ScriptQualityConfig(
            min_non_narrator_roles=3,
            max_narration_ratio=0.5,
        )
    return ScriptQualityConfig()


def _load_script_quality_config(data: Dict[str, Any], category: str = "", mode: str = "") -> ScriptQualityConfig:
    defaults = _default_script_quality_config(category=category, mode=mode)
    quality_data = data.get("script_quality", {}) or {}
    if not isinstance(quality_data, dict):
        quality_data = {}

    return ScriptQualityConfig(
        min_non_narrator_roles=int(
            quality_data.get("min_non_narrator_roles", defaults.min_non_narrator_roles)
            or defaults.min_non_narrator_roles
        ),
        max_narration_ratio=float(
            quality_data.get("max_narration_ratio", defaults.max_narration_ratio)
            or defaults.max_narration_ratio
        ),
        min_turns_for_gate=int(
            quality_data.get("min_turns_for_gate", defaults.min_turns_for_gate)
            or defaults.min_turns_for_gate
        ),
        max_ellipsis_ratio=float(
            quality_data.get("max_ellipsis_ratio", defaults.max_ellipsis_ratio)
            or defaults.max_ellipsis_ratio
        ),
        warn_topic_overlap_ratio=float(
            quality_data.get("warn_topic_overlap_ratio", defaults.warn_topic_overlap_ratio)
            or defaults.warn_topic_overlap_ratio
        ),
    )


def _load_motiontoon_config(data: Dict[str, Any], fallback_enabled: bool = False) -> MotiontoonConfig:
    motion_data = data.get("motiontoon", {}) or {}
    prop_keywords = motion_data.get("prop_keywords", [])
    if isinstance(prop_keywords, dict):
        prop_keywords = list(prop_keywords.keys())
    if not isinstance(prop_keywords, list):
        prop_keywords = []

    scene_rules = motion_data.get("scene_motion_rules", {})
    if not isinstance(scene_rules, dict):
        scene_rules = {}
    cast_slots = motion_data.get("cast_slots", {})
    if not isinstance(cast_slots, dict):
        cast_slots = {}
    puppet_profiles = motion_data.get("puppet_profiles", {})
    if not isinstance(puppet_profiles, dict):
        puppet_profiles = {}

    enabled = motion_data.get("enabled", fallback_enabled)
    return MotiontoonConfig(
        enabled=enabled,
        mode=motion_data.get("mode", "screen_space"),
        profile=_normalize_motiontoon_profile(motion_data.get("profile", "basic"), enabled),
        character_layer_mode=str(motion_data.get("character_layer_mode", "") or ""),
        overlay_theme=str(motion_data.get("overlay_theme", "default") or "default"),
        default_scene_type=motion_data.get("default_scene_type", "dialogue"),
        blink_enabled=motion_data.get("blink_enabled", False),
        mouth_flap_enabled=motion_data.get("mouth_flap_enabled", False),
        layered_cutout_enabled=motion_data.get("layered_cutout_enabled", False),
        layered_cutout_strength=float(motion_data.get("layered_cutout_strength", 0.65) or 0.65),
        prop_overlay_enabled=motion_data.get("prop_overlay_enabled", True),
        dialogue_panel_enabled=motion_data.get("dialogue_panel_enabled", True),
        idle_drift_enabled=motion_data.get("idle_drift_enabled", True),
        impact_shake_enabled=motion_data.get("impact_shake_enabled", True),
        snap_zoom_enabled=motion_data.get("snap_zoom_enabled", True),
        subtitle_pulse_enabled=motion_data.get("subtitle_pulse_enabled", True),
        slow_push_enabled=motion_data.get("slow_push_enabled", True),
        shorts_vertical_ready=motion_data.get("shorts_vertical_ready", True),
        video_toon_local_enabled=motion_data.get("video_toon_local_enabled", False),
        video_toon_generation_backend=str(motion_data.get("video_toon_generation_backend", "comfyui") or "comfyui"),
        video_toon_layered_assets_required=motion_data.get("video_toon_layered_assets_required", False),
        video_toon_workflow_template=str(
            motion_data.get("video_toon_workflow_template", "sd15_ipadapter_openpose_v1")
            or "sd15_ipadapter_openpose_v1"
        ),
        prop_keywords=prop_keywords,
        scene_motion_rules=scene_rules,
        cast_slots=cast_slots,
        puppet_profiles=puppet_profiles,
    )


# ============================================================
# 기본 팩 (하드코딩 대체)
# ============================================================

DEFAULT_PACKS = {
    "horror": {
        "pack_id": "default_horror",
        "pack_name": "기본 공포팩",
        "version": "1.0.0",
        "author": "Reverie Studio",
        "genre": "horror",
        "prompts": {
            "pd_system": """당신은 공포 콘텐츠 전문 PD입니다. 114만 구독자 공포 유튜브 채널 수석 PD 경력 10년.
시청자가 밤에 혼자 이불 속에서 보다가 뒤를 돌아보게 만드는 스토리를 구성하세요.

■ 감정곡선 기반 구조 (5단계가 아닌 감정 흐름):
1. 실화풍 도입 (텐션 3/10) — "이건 2019년에 실제로..."  구체적 지명/날짜
2. 경고와 무시 (텐션 5/10) — 마을 사람의 경고, 주인공의 호기심
3. 점진적 공포 (텐션 7/10) — 감각 묘사, 카운트다운, 반복
4. 진실 접근 (텐션 9/10) — 단서 발견, 가해자 시점 반전
5. 소름 엔딩 (텐션 10/10) — 귀신의 일상어 대사, 열린 결말

핵심 원칙:
- 반전은 예측 불가능해야 한다. "알고 보니 귀신이었다"는 금지 (너무 뻔함)
- 가장 무서운 대사는 일상적인 말: "선생님, 이제 집에 가도 돼요?"
- 설명하지 말고 보여줘. 나레이션으로 "무서웠다" 쓰면 실패.
- 대사 7 : 나레이션 3 비율. 나레이션은 장면 전환에만.""",

            "writer_system": """공포 이야기 전문 작가입니다. 한국형 실화 공포의 대가.

■ 핵심 작법 (반드시 모두 사용):
1. 문장 길이 변화 = 템포 조절
   - 평온: 보통 문장 (15~30자)
   - 긴장: 짧은 문장 연속 (5~15자)
   - 임팩트: 한 단어만. "출석부." "피." "이빨."
2. 대사가 핵심이다
   - 설명 대사 금지. 사람은 상황을 친절히 설명하지 않는다.
   - 돌려 말하기, 회피, 침묵도 대사다.
   - ❌ "그 집은 흉가야" → ✅ "그 집 얘기는 꺼내지 마."
3. 공포 기법
   - 카운트다운 (시간/숫자 반복)
   - 반복 후 변형 ("아무도 없었다" → "아무도 없었다" → "한 명 있었다")
   - 일상어 귀신 (비명/저주 금지, 평범한 말이 가장 무섭다)
   - 감각 묘사 (시각 외: 냄새, 온도, 촉감 필수)
4. 감정 전달
   - "무서웠다" 쓰지 말고, 무서운 상황을 보여줘
   - 캐릭터가 떨리는 것, 말을 더듬는 것, 도망가려는 행동으로

캐릭터 말투:
- 할머니/할아버지: 사투리, 짧고 의미심장한 말
- 나레이터: 담담하지만 불길한 톤. 절대 감정 과잉 금지.
- 젊은 캐릭터: 현대적 말투, 당황하면 존댓말 무너짐""",

            "sd_positive": "masterpiece, best quality, dark atmosphere, horror, silhouette, dramatic lighting, eerie, mysterious, (dark background:1.2), cinematic",
            "sd_negative": "(worst quality:1.4), (low quality:1.4), bright colors, happy, cheerful, nsfw, text, watermark",
        },
        "content": {
            "duration_minutes": 5,
            "min_turns": 45,
            "max_turns": 70,
            "image_style": "silhouette horror",
        },
        "topic_templates": [
            "폐가에서 발견된 일기장의 비밀",
            "매일 밤 3시에 울리는 초인종",
            "거울 속에서 나를 바라보는 또 다른 나",
            "할머니가 절대 열지 말라던 다락방",
            "엘리베이터에서 함께 탄 그 사람",
        ],
        "tags": ["공포", "괴담", "무서운이야기", "호러", "귀신"],
        "character_config": {
            "narrator": "man",
            "grandma": "grandma",
            "grandpa": "grandpa",
            "protagonist": "woman",
            "나레이션": "narrator",
            "내레이션": "narrator",
            "주인공": "woman",
            "할머니": "grandma",
            "할아버지": "grandpa",
        },
        "assets": {
            "use_channel_bgm": "horror",
            "use_channel_sfx": "horror",
            "use_channel_tts": "horror",
            "narrator": "narrator_male",
        },
        "allowed_emotions": ["scared", "angry", "sad", "happy", "calm", "whisper", "worried", "desperate"],
        "emotion_policy": {"scared": 3, "angry": 1, "sad": 1, "calm": 5, "worried": 2, "desperate": 1},
        "sfx": {
            "category_guide": "This is a HORROR video. Available SFX: tension, heartbeat, suspense, jumpscare, whisper, footsteps, door, thunder, wind, night, rain.",
            "keyword_map": {
                "긴장": "tension", "두려": "tension", "심장": "heartbeat",
                "갑자기": "jumpscare", "속삭": "whisper", "발자국": "footsteps",
                "문이": "door", "천둥": "thunder", "바람": "wind", "밤": "night",
                "소름": "tension", "귀신": "suspense",
            },
        },
        "atmosphere": {
            "mood_map": {
                "horror": "ominous shadows, eerie fog",
                "tense": "harsh lighting, long shadows",
                "mysterious": "dim mysterious light, obscured details",
            },
            "keywords": {
                "horror": ["무섭", "소름", "공포", "귀신", "유령"],
                "tense": ["긴장", "위험", "급박"],
                "mysterious": ["이상", "수상", "의문"],
            },
        },
        "emergency": {
            "template_sequence": [
                ["나레이션", "narrator", "이 이야기는 실제 사례에서 모티프를 얻은 창작 재구성입니다.", "calm"],
                ["나레이션", "narrator", "어느 마을에서 일어난 일입니다.", "calm"],
                ["남자", "man", "여기가 그 집이야?", "calm"],
                ["여자", "woman", "오빠, 나 좀 무서운데.", "scared"],
            ],
        },
    },

    "senior": {
        "pack_id": "default_senior",
        "pack_name": "기본 시니어팩",
        "version": "1.0.0",
        "author": "Reverie Studio",
        "genre": "senior",
        "prompts": {
            "pd_system": """당신은 시니어 감성 콘텐츠 전문 PD입니다.
중장년층이 공감할 수 있는 따뜻하고 감동적인 스토리를 구성하세요.

스토리 구조:
1. 일상의 시작 - 평범한 하루
2. 추억 회상 - 과거의 따뜻한 기억
3. 갈등/고민 - 현재의 어려움
4. 깨달음 - 삶의 지혜
5. 감동적 마무리 - 따뜻한 여운

핵심 포인트:
- 세대 간 소통과 이해
- 삶의 지혜와 경험
- 가족의 소중함
- 잔잔한 감동""",

            "writer_system": """시니어 감성 콘텐츠 작가입니다.

문장 스타일:
- 따뜻하고 정감 있는 문체
- 적절한 비유와 속담 활용
- 회상 장면은 부드럽게
- 대화는 자연스럽게

캐릭터 말투:
- 할머니: 따뜻한 사투리, 정감 있는 말투
- 할아버지: 과묵하지만 깊은 말
- 손주: 존댓말, 공손한 태도

감정 태그 사용:
[calm] 차분한 서술
[sad] 슬픔, 그리움
[happy] 행복, 따뜻함
[warm] 훈훈한 감정""",

            "sd_positive": "masterpiece, best quality, warm atmosphere, emotional, family, illustration style, soft lighting, nostalgic, heartwarming",
            "sd_negative": "(worst quality:1.4), (low quality:1.4), horror, scary, dark, nsfw, text, watermark",
        },
        "content": {
            "duration_minutes": 5,
            "min_turns": 45,
            "max_turns": 70,
            "image_style": "warm illustration",
        },
        "topic_templates": [
            "할머니의 비밀 레시피",
            "40년 만에 다시 만난 첫사랑",
            "손주에게 전하는 인생 조언",
            "고향 마을의 추억",
            "아버지의 낡은 시계",
        ],
        "tags": ["감동", "시니어", "가족", "따뜻한이야기", "인생"],
        "character_config": {
            "narrator": "man",
            "grandma": "grandma",
            "grandpa": "grandpa",
            "grandchild": "woman",
            "나레이션": "narrator",
            "내레이션": "narrator",
            "할머니": "grandma",
            "할아버지": "grandpa",
            "손주": "woman",
            "손녀": "young_woman",
            "손자": "young_man",
        },
        "assets": {
            "use_channel_bgm": "senior",
            "use_channel_sfx": "senior",
            "use_channel_tts": "senior",
            "narrator": "narrator_female",
        },
        "allowed_emotions": ["sad", "happy", "calm", "excited", "whisper"],
        "emotion_policy": {"sad": 4, "happy": 3, "calm": 5},
        "sfx": {
            "category_guide": "This is an EMOTIONAL video. Available SFX: sad, crying, happy, whoosh.",
            "keyword_map": {
                "눈물": "crying", "울": "crying", "슬프": "sad",
                "행복": "happy", "기쁨": "happy", "감동": "sad",
            },
        },
        "atmosphere": {
            "mood_map": {
                "peaceful": "soft warm light, gentle atmosphere",
                "sad": "muted tones, soft shadows, melancholic light",
                "happy": "bright warm lighting, golden hour glow",
            },
            "keywords": {
                "peaceful": ["평화", "고요", "따뜻"],
                "sad": ["슬프", "애잔", "그리움", "눈물"],
                "happy": ["행복", "기쁨", "웃음"],
            },
        },
        "emergency": {
            "template_sequence": [
                ["나레이션", "narrator", "오래된 골목길, 작은 이발소가 하나 있었습니다.", "calm"],
                ["나레이션", "narrator", "주인 할아버지는 50년째 그 자리를 지키고 있었습니다.", "calm"],
                ["할아버지", "grandpa", "어서 오세요.", "calm"],
                ["남자", "man", "할아버지, 잘 지내셨어요?", "happy"],
            ],
        },
    },
}


# ============================================================
# 팩 로드 함수
# ============================================================

def _read_pack_file(zf: zipfile.ZipFile, file_list: List[str], file_name: str, is_encrypted: bool) -> Optional[bytes]:
    """
    팩 내부 파일 읽기 (암호화 자동 처리)

    Args:
        zf: ZipFile 객체
        file_list: 파일 목록
        file_name: 읽을 파일명
        is_encrypted: 암호화 여부

    Returns:
        복호화된 바이트 데이터
    """
    # v57.7.1: 암호화된 파일은 .enc 확장자
    enc_file_name = file_name + ".enc"

    if is_encrypted and enc_file_name in file_list:
        # 암호화된 파일 로드
        encrypted_data = zf.read(enc_file_name)
        decrypted = _decrypt_content(encrypted_data)
        if decrypted:
            return decrypted
        else:
            logger.error(f"[PackConfig] 복호화 실패: {enc_file_name}")
            return None
    elif file_name in file_list:
        # 일반 파일 로드
        return zf.read(file_name)
    else:
        return None


@_with_pack_lock
def _load_pack_from_json(pack_path: Path) -> bool:
    """
    v59.1.5: JSON 파일에서 팩 로드 (개발/테스트용)

    .revpack 대신 .json 파일 직접 로드 지원
    """
    global ACTIVE_PACK

    try:
        with open(pack_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        pack_dir = pack_path.parent
        is_loose_pack_manifest = pack_path.name.lower() == "manifest.json"
        if is_loose_pack_manifest:
            settings_path = pack_dir / "settings.json"
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as sf:
                    settings_data = json.load(sf)
                merged_data = dict(data)
                merged_data.update(settings_data)
                data = merged_data

            topics_path = pack_dir / "topics.json"
            if topics_path.exists():
                with open(topics_path, 'r', encoding='utf-8') as tf:
                    topics_data = json.load(tf)
                if "templates" in topics_data:
                    data["topic_templates"] = topics_data.get("templates", data.get("topic_templates", []))
                if "tags" in topics_data:
                    data["tags"] = topics_data.get("tags", data.get("tags", []))
                if "intro_scripts" in topics_data:
                    data["intro_scripts"] = topics_data.get("intro_scripts", data.get("intro_scripts", []))
                if "scenario" in topics_data:
                    merged_scenario = dict(data.get("scenario", {}) or {})
                    merged_scenario.update(topics_data.get("scenario", {}) or {})
                    data["scenario"] = merged_scenario

        # v59.1.6: 신형(pack_id/pack_name/genre) + 구형(package_id/package_name/channel_type) 양쪽 호환

        # 기본 정보
        ACTIVE_PACK.pack_id = data.get("pack_id", data.get("package_id", ""))
        ACTIVE_PACK.pack_name = data.get("pack_name", data.get("package_name", ""))
        ACTIVE_PACK.version = data.get("version", "1.0.0")
        ACTIVE_PACK.author = data.get("author", "")
        ACTIVE_PACK.genre = data.get("genre", data.get("channel_type", "horror"))
        ACTIVE_PACK.channel_type = data.get("channel_type", data.get("genre", "horror"))

        # prompts
        prompts_data = data.get("prompts", {})
        ACTIVE_PACK.prompts = PackPrompts(
            pd_system=prompts_data.get("pd_system_prompt", prompts_data.get("pd_system", "")),
            writer_system=prompts_data.get("writer_system_prompt", prompts_data.get("writer_system", "")),
            sd_positive=prompts_data.get("sd_positive", ""),
            sd_negative=prompts_data.get("sd_negative", ""),
            topic_generation=prompts_data.get("topic_generation", ""),
            topic_enhanced=prompts_data.get("topic_enhanced", ""),
            hook_generation=prompts_data.get("hook_generation", ""),
            hook_enhanced=prompts_data.get("hook_enhanced", ""),
            metadata_generation=prompts_data.get("metadata_generation", ""),
            thumbnail_style_guide=prompts_data.get("thumbnail_style_guide", ""),
            story_bible=prompts_data.get("story_bible", ""),
            story_bible_improve=prompts_data.get("story_bible_improve", ""),
            story_summarize=prompts_data.get("story_summarize", ""),
            structural_outline=prompts_data.get("structural_outline", ""),
            craft_rules=prompts_data.get("craft_rules", ""),
            pacing_part1=prompts_data.get("pacing_part1", ""),
            pacing_part2=prompts_data.get("pacing_part2", ""),
            pacing_part3=prompts_data.get("pacing_part3", ""),
            image_style=prompts_data.get("image_style", ""),
            image_llm_prompt=prompts_data.get("image_llm_prompt", ""),
        )

        # v60: 디렉토리 팩인 경우 prompts/ 폴더에서 .txt 파일 로딩
        pack_dir = pack_path.parent
        prompts_dir = pack_dir / "prompts"
        if prompts_dir.exists():
            _V60_PROMPT_FILES = {
                "pd_system": "pd_system.txt",
                "writer_system": "writer_system.txt",
                "topic_generation": "topic_generation.txt",
                "topic_enhanced": "topic_enhanced.txt",
                "hook_generation": "hook_generation.txt",
                "hook_enhanced": "hook_enhanced.txt",
                "metadata_generation": "metadata_generation.txt",
                "thumbnail_style_guide": "thumbnail_style.txt",
                "story_bible": "story_bible.txt",
                "story_bible_improve": "story_bible_improve.txt",
                "story_summarize": "story_summarize.txt",
                "structural_outline": "structural_outline.txt",
                "craft_rules": "craft_rules.txt",
                "pacing_part1": "pacing_part1.txt",
                "pacing_part2": "pacing_part2.txt",
                "pacing_part3": "pacing_part3.txt",
                "image_style": "image_style.txt",
                "image_llm_prompt": "image_llm_prompt.txt",
                "cold_open_bridge": "cold_open_bridge.txt",  # v61.1
                "story_blueprint": "story_blueprint.txt",  # v62
            }
            for field_name, file_name in _V60_PROMPT_FILES.items():
                txt_path = prompts_dir / file_name
                if txt_path.exists():
                    txt_content = txt_path.read_text(encoding='utf-8').strip()
                    if txt_content:
                        setattr(ACTIVE_PACK.prompts, field_name, txt_content)
            sd_prompts_path = prompts_dir / "sd_prompts.json"
            if sd_prompts_path.exists():
                try:
                    sd_prompts_data = json.loads(sd_prompts_path.read_text(encoding='utf-8'))
                    base_prompts = sd_prompts_data.get("base", {}) if isinstance(sd_prompts_data, dict) else {}
                    if not ACTIVE_PACK.prompts.sd_positive:
                        ACTIVE_PACK.prompts.sd_positive = base_prompts.get("positive", "")
                    if not ACTIVE_PACK.prompts.sd_negative:
                        ACTIVE_PACK.prompts.sd_negative = base_prompts.get("negative", "")
                except Exception as e:
                    logger.warning(f"[PackConfig] sd_prompts.json 로드 실패 (무시): {e}")

        # sd
        sd_data = data.get("sd", {})
        ACTIVE_PACK.sd = PackSD(
            positive=sd_data.get("positive", ""),
            negative=sd_data.get("negative", ""),
            cfg_scale=sd_data.get("cfg_scale", 6.5),
            steps=sd_data.get("steps", 15),  # v59.5.17: 28→15
            model=sd_data.get("checkpoint", ""),
        )

        # v59.1.6: SD 프롬프트 교차 연결
        if not ACTIVE_PACK.prompts.sd_positive and ACTIVE_PACK.sd.positive:
            ACTIVE_PACK.prompts.sd_positive = ACTIVE_PACK.sd.positive
        if not ACTIVE_PACK.prompts.sd_negative and ACTIVE_PACK.sd.negative:
            ACTIVE_PACK.prompts.sd_negative = ACTIVE_PACK.sd.negative

        # visual (v59.1.5 핵심!)
        visual_data = data.get("visual", {})
        ACTIVE_PACK.visual = PackVisual(
            character_system_enabled=visual_data.get("character_system_enabled", False),
            forced_style=visual_data.get("forced_style", {}),
            thumbnail_backgrounds=visual_data.get("thumbnail_backgrounds", []),
            safe_fallbacks=visual_data.get("safe_fallbacks", []),
            safe_fallback_prompt=visual_data.get("safe_fallback_prompt", ""),
        )

        # v59.1.6: visual.characters → ACTIVE_PACK.characters 로드
        ACTIVE_PACK.characters = visual_data.get("characters", {})

        # tts
        tts_data = data.get("tts", {})
        ACTIVE_PACK.tts = PackTTS(
            narrator=tts_data.get("default_voice", tts_data.get("narrator", "narrator_male")),
            default_emotion=tts_data.get("default_emotion", "calm"),
            character_mapping=tts_data.get("character_mapping", {}),
            allowed_emotions=tts_data.get("allowed_emotions", []),
            emotion_weights=tts_data.get("emotion_weights", {}),
        )
        # v61.1 (#85): character_config → tts.character_mapping 단일 소스
        ACTIVE_PACK.character_config = ACTIVE_PACK.tts.character_mapping

        # hook_style
        hook_data = data.get("hook_style", {})
        ACTIVE_PACK.hook_style = PackHookStyle(
            top_label=hook_data.get("top_label", "【 이야기 】"),
            top_color=hook_data.get("top_color", "#FFFFFF"),
            main_color=hook_data.get("main_color", "#FFFFFF"),
            bg_color=hook_data.get("bg_color", [0, 0, 0]),
            duration=hook_data.get("duration", 4.0),
        )

        # assets (v59.1.6: bgm/sfx 최상위 키 + assets 키 양쪽 호환)
        assets_data = data.get("assets", {})
        bgm_data = data.get("bgm", {})
        sfx_assets_data = data.get("sfx", {})
        ACTIVE_PACK.assets = PackAssets(
            bgm_folder=bgm_data.get("folder", assets_data.get("bgm_folder", "")),
            sfx_folder=sfx_assets_data.get("folder", assets_data.get("sfx_folder", "")),
            sfx_enabled=sfx_assets_data.get("enabled", assets_data.get("sfx_enabled", False)),
            sfx_category=sfx_assets_data.get("category", assets_data.get("sfx_category", "")),
            sfx_intensity=sfx_assets_data.get("intensity", assets_data.get("sfx_intensity", "low")),
            bgm_path=assets_data.get("bgm_path", ""),
            sfx_path=assets_data.get("sfx_path", ""),
            use_channel_bgm=_normalize_pack_channel_toggle(assets_data.get("use_channel_bgm", True)),
            use_channel_sfx=_normalize_pack_channel_toggle(assets_data.get("use_channel_sfx", True)),
            use_channel_tts=_normalize_pack_channel_toggle(assets_data.get("use_channel_tts", True)),
        )

        # content (v59.1.6: image_style 추가)
        content_data = data.get("content", {})
        ACTIVE_PACK.content = PackContent(
            duration_minutes=content_data.get("duration_minutes", 7),
            min_turns=content_data.get("min_turns", 45),
            max_turns=content_data.get("max_turns", 70),
            image_style=content_data.get("image_style", ""),
        )

        # visual_storytelling (v59)
        vs_data = data.get("visual_storytelling", {})
        if vs_data.get("enabled", False):
            try:
                ACTIVE_PACK.visual_storytelling = _load_visual_storytelling_config({"visual_storytelling": vs_data})
            except Exception as e:
                logger.warning(f"[PackConfig] visual_storytelling 파싱 실패, fallback 파싱: {e}")
                vs_config = VisualStorytellingConfig()
                vs_config.enabled = True
                vs_config.characters = vs_data.get("characters", {})

                sd_model_data = vs_data.get("sd_model", {})
                if sd_model_data:
                    vs_config.sd_model = SDModelConfig(
                        checkpoint=sd_model_data.get("checkpoint", ""),
                        vae=sd_model_data.get("vae", ""),
                        sampler=sd_model_data.get("sampler", "DPM++ 2M Karras"),
                        scheduler=sd_model_data.get("scheduler", "Karras"),
                        steps=sd_model_data.get("steps", 15),
                        cfg_scale=sd_model_data.get("cfg_scale", 7.0),
                        width=sd_model_data.get("width", 768),
                        height=sd_model_data.get("height", 432),
                        clip_skip=sd_model_data.get("clip_skip", 2),
                        positive_base=sd_model_data.get("positive_base", ""),
                        negative_base=sd_model_data.get("negative_base", ""),
                        lora_models=sd_model_data.get("lora_models", []),
                    )
                    logger.info(f"[PackConfig] fallback sd_model: ckpt={sd_model_data.get('checkpoint')}, vae={sd_model_data.get('vae')}")

                sub_data = vs_data.get("subtitle_style", {})
                if sub_data:
                    vs_config.subtitle_style = SubtitleStyle(
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
                        speaker_colors=sub_data.get("speaker_colors", {}),
                    )

                ve_data = vs_data.get("visual_effects", {})
                if ve_data:
                    vig = ve_data.get("vignette", {})
                    if isinstance(vig, dict) and vig:
                        v_en, v_int, v_col = vig.get("enabled", True), vig.get("intensity", 0.3), vig.get("color", "#000000")
                    else:
                        v_en, v_int, v_col = ve_data.get("vignette_enabled", True), ve_data.get("vignette_intensity", 0.3), ve_data.get("vignette_color", "#000000")

                    cf = ve_data.get("color_filter", {})
                    if isinstance(cf, dict) and cf:
                        cf_en, cf_type, cf_int = ("type" in cf), cf.get("type", ""), cf.get("saturation", cf.get("intensity", 0.5))
                    else:
                        cf_en, cf_type, cf_int = ve_data.get("color_filter_enabled", False), ve_data.get("color_filter", ""), ve_data.get("color_filter_intensity", 0.5)

                    vs_config.visual_effects = VisualEffect(
                        vignette_enabled=v_en, vignette_intensity=v_int, vignette_color=v_col,
                        color_filter_enabled=cf_en, color_filter=cf_type, color_filter_intensity=cf_int,
                        ken_burns_enabled=ve_data.get("ken_burns_enabled", True),
                        ken_burns_zoom_range=ve_data.get("ken_burns_zoom_range", [1.0, 1.15]),
                        ken_burns_pan_enabled=ve_data.get("ken_burns_pan_enabled", True),
                    )

                trans_data = ve_data.get("transitions", {}) if ve_data else {}
                if not trans_data:
                    trans_data = vs_data.get("transitions", {})
                if trans_data:
                    vs_config.transitions = TransitionStyle(
                        default_transition=trans_data.get("default_transition", trans_data.get("default", "crossfade")),
                        transition_duration=trans_data.get("transition_duration", trans_data.get("duration", 0.5)),
                        scene_transitions=trans_data.get("scene_transitions", {}),
                    )

                ig_data = vs_data.get("image_generation", {})
                if ig_data:
                    vs_config.images_per_minute = ig_data.get("target_images", 120) / 7
                    vs_config.max_consecutive_reuse = ig_data.get("max_consecutive_reuse", 2)

                vs_config.prompt_strategy = vs_data.get("prompt_strategy", "panel_card")
                vs_config.llm_hint_tag_limit = vs_data.get("llm_hint_tag_limit", 4)

                ACTIVE_PACK.visual_storytelling = vs_config
        else:
            ACTIVE_PACK.visual_storytelling = VisualStorytellingConfig()
        ACTIVE_PACK.script_quality = _load_script_quality_config(
            data,
            category=ACTIVE_PACK.genre,
            mode=ACTIVE_PACK.channel_type,
        )
        ACTIVE_PACK.motiontoon = _load_motiontoon_config(
            data,
            fallback_enabled=bool(getattr(ACTIVE_PACK.visual_storytelling, "enabled", False)),
        )

        # v59.1.6: video/thumbnail/scenario/topic_templates/tags/intro_scripts 로드
        video_data = data.get("video", {})
        ACTIVE_PACK.video = PackVideo(
            pause_duration=video_data.get("pause_duration", 0.4),
            zoom_speed=video_data.get("zoom_speed", 1.0),
        )

        scenario_data = data.get("scenario", {})
        ACTIVE_PACK.scenario = PackScenario(
            safe_templates=scenario_data.get("safe_templates", []),
            tone_pool=scenario_data.get("tone_pool", []),
            relationship_pool=scenario_data.get("relationship_pool", []),
            place_pool=scenario_data.get("place_pool", []),
            arc_pool=scenario_data.get("arc_pool", []),
            trigger_pool=scenario_data.get("trigger_pool", []),
            twist_pool=scenario_data.get("twist_pool", []),
            conflict_pool=scenario_data.get("conflict_pool", []),
            mystery_types=scenario_data.get("mystery_types", []),
            evidence_pool=scenario_data.get("evidence_pool", []),
        )

        thumb_data = data.get("thumbnail", {})
        ACTIVE_PACK.thumbnail = PackThumbnail(
            text_default=thumb_data.get("text_default", ""),
            style_guide=thumb_data.get("style_guide", ""),
            title_hooks=thumb_data.get("title_hooks", []),
        )

        ACTIVE_PACK.topic_templates = data.get("topic_templates", [])
        ACTIVE_PACK.tags = data.get("tags", [])
        ACTIVE_PACK.intro_scripts = data.get("intro_scripts", [])
        ACTIVE_PACK.requirements = data.get("requirements", {})

        ACTIVE_PACK.scene_analyzer = data.get("scene_analyzer", {})
        ACTIVE_PACK.background_library = data.get("background_library", {})

        # v60: 팩-클라이언트 아키텍처 확장 (JSON/디렉토리 팩)
        sfx_data = data.get("sfx", {})
        ACTIVE_PACK.sfx = PackSFX(
            category_guide=sfx_data.get("category_guide", ""),
            keyword_map=sfx_data.get("keyword_map", {}),
        )
        atmos_data = data.get("atmosphere", {})
        ACTIVE_PACK.atmosphere = PackAtmosphere(
            mood_map=atmos_data.get("mood_map", {}),
            keywords=atmos_data.get("keywords", {}),
        )
        emergency_data = data.get("emergency", {})
        ACTIVE_PACK.emergency = PackEmergency(
            template_sequence=emergency_data.get("template_sequence", []),
        )
        # v60: settings.json에서도 sfx/atmosphere/emergency 로드 (디렉토리 팩)
        settings_path = pack_path.parent / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as sf:
                    settings_data = json.load(sf)
                if "sfx" in settings_data:
                    s_sfx = settings_data["sfx"]
                    ACTIVE_PACK.sfx = PackSFX(
                        category_guide=s_sfx.get("category_guide", ACTIVE_PACK.sfx.category_guide),
                        keyword_map=s_sfx.get("keyword_map", ACTIVE_PACK.sfx.keyword_map),
                    )
                if "atmosphere" in settings_data:
                    s_atm = settings_data["atmosphere"]
                    ACTIVE_PACK.atmosphere = PackAtmosphere(
                        mood_map=s_atm.get("mood_map", ACTIVE_PACK.atmosphere.mood_map),
                        keywords=s_atm.get("keywords", ACTIVE_PACK.atmosphere.keywords),
                    )
                if "emergency" in settings_data:
                    s_emer = settings_data["emergency"]
                    ACTIVE_PACK.emergency = PackEmergency(
                        template_sequence=s_emer.get("template_sequence", ACTIVE_PACK.emergency.template_sequence),
                    )
            except Exception as e:
                logger.warning(f"[PackConfig] settings.json v60 로드 실패 (무시): {e}")

        ACTIVE_PACK.is_loaded = True
        ACTIVE_PACK.source_path = str(pack_path)

        logger.info(f"[PackConfig] JSON 팩 로드 완료: {ACTIVE_PACK.pack_name} from {Path(pack_path).name}")
        logger.info(f"[PackConfig] forced_style: {ACTIVE_PACK.visual.forced_style}")
        return True

    except Exception as e:
        logger.error(f"[PackConfig] JSON 팩 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


@_with_pack_lock
def load_pack(pack_path: str) -> bool:
    """
    .revpack 파일 로드 (암호화 자동 감지)

    Args:
        pack_path: .revpack 파일 경로

    Returns:
        성공 여부
    """
    global ACTIVE_PACK

    pack_path = Path(pack_path)

    if not pack_path.exists():
        logger.error(f"[PackConfig] 팩 파일 없음: {pack_path}")
        return False

    # v59.1.5: .json 파일 지원 (개발용/테스트용)
    if pack_path.suffix.lower() == ".json":
        return _load_pack_from_json(pack_path)

    if pack_path.suffix.lower() != ".revpack":
        logger.error(f"[PackConfig] 잘못된 파일 형식: {pack_path.suffix}")
        return False

    try:
        # v62: Fernet wrapper 감지 — 전체 ZIP을 Fernet으로 감싼 경우
        zip_source = None
        with open(pack_path, 'rb') as f:
            header = f.read(6)
        wrapper_encrypted = False
        if header == b'gAAAAA' and CRYPTO_AVAILABLE:
            wrapper_encrypted = True
            logger.info(f"[PackConfig] Fernet wrapper 감지: {pack_path.name}")
            with open(pack_path, 'rb') as f:
                encrypted_data = f.read()

            # v62.27: Phase B — 서버 키 우선 시도 (실패 시 Phase A 폴백)
            pack_stem = pack_path.stem  # e.g., "horror_v59"
            server_key = fetch_pack_key_from_server(pack_stem)
            decrypted_zip = None
            if server_key:
                decrypted_zip = _decrypt_content_with_password(
                    encrypted_data, server_key.encode("utf-8")
                )
                if decrypted_zip:
                    logger.info(f"[PackConfig] Phase B 서버 키 복호화 성공: {pack_path.name}")
                else:
                    logger.warning(f"[PackConfig] Phase B 서버 키 복호화 실패 — Phase A 폴백")

            if not decrypted_zip:
                decrypted_zip = _decrypt_content(encrypted_data)

            if decrypted_zip:
                zip_source = io.BytesIO(decrypted_zip)
                logger.info(f"[PackConfig] Fernet 복호화 성공 ({len(decrypted_zip):,} bytes)")
            else:
                logger.error(f"[PackConfig] Fernet 복호화 실패: {pack_path.name}")
                return False

        with zipfile.ZipFile(zip_source or pack_path, 'r') as zf:
            file_list = zf.namelist()

            # v57.7.1: 암호화 여부 확인 (manifest.json.enc 존재 여부)
            is_encrypted = "manifest.json.enc" in file_list
            encrypted_pack = wrapper_encrypted or is_encrypted

            # 운영 보안 모드: 평문 ZIP .revpack 거부
            if _is_encrypted_pack_required() and not encrypted_pack:
                logger.error(
                    f"[PackConfig] 암호화되지 않은 팩 거부: {pack_path.name} "
                    "(REVERIE_PACK_REQUIRE_ENCRYPTED=1)"
                )
                return False

            if is_encrypted:
                logger.info(f"[PackConfig] 암호화된 팩 감지: {pack_path.name}")
                if not CRYPTO_AVAILABLE:
                    logger.error("[PackConfig] 암호화된 팩이지만 cryptography 미설치")
                    return False

            # manifest.json 로드
            manifest = {}
            manifest_data = _read_pack_file(zf, file_list, "manifest.json", is_encrypted)
            if manifest_data:
                manifest = json.loads(manifest_data.decode('utf-8', errors='replace'))
            elif is_encrypted:
                logger.error(f"[PackConfig] ❌ 팩 로드 실패: manifest.json 복호화 불가 - 암호화 키 불일치")
                return False

            # settings.json 로드
            settings = {}
            settings_data = _read_pack_file(zf, file_list, "settings.json", is_encrypted)
            if settings_data:
                settings = json.loads(settings_data.decode('utf-8', errors='replace'))
            elif is_encrypted:
                logger.warning(f"[PackConfig] ⚠️ settings.json 복호화 실패 - 기본값 사용")

            # v59.1.0: 팩 스키마 검증
            if VALIDATOR_AVAILABLE:
                pack_name = manifest.get("package_name", pack_path.stem)
                combined_data = {**manifest, **settings}
                is_valid, validation_result = validate_pack(combined_data, pack_name)

                if not is_valid:
                    logger.error(f"[PackConfig] 팩 검증 실패: {pack_name}")
                    for err in validation_result.errors:
                        logger.error(f"  - {err}")
                    return False

            # v62.25: 팩 무결성 서명 검증
            if not _verify_pack_signature(zf, manifest):
                return False

            # v62.26: 라이선스 접근 제어
            plan_required = manifest.get("plan_required")
            if plan_required and not _check_pack_access(plan_required):
                logger.error(
                    f"[PackConfig] ❌ 팩 접근 거부: {pack_path.name} "
                    f"(plan_required={plan_required!r})"
                )
                return False

            # topics.json 로드 (암호화 안 함)
            topics = {}
            if "topics.json" in file_list:
                topics = json.loads(zf.read("topics.json").decode('utf-8', errors='replace'))

            # prompts 로드
            prompts = PackPrompts()

            pd_data = _read_pack_file(zf, file_list, "prompts/pd_system.txt", is_encrypted)
            if pd_data:
                prompts.pd_system = pd_data.decode('utf-8', errors='replace')

            writer_data = _read_pack_file(zf, file_list, "prompts/writer_system.txt", is_encrypted)
            if writer_data:
                prompts.writer_system = writer_data.decode('utf-8', errors='replace')

            sd_data = _read_pack_file(zf, file_list, "prompts/sd_prompts.json", is_encrypted)
            if sd_data:
                sd_json = json.loads(sd_data.decode('utf-8', errors='replace'))
                prompts.sd_positive = sd_json.get("positive", "")
                prompts.sd_negative = sd_json.get("negative", "")

            # v60: 새 프롬프트 파일들 로딩 (팩-클라이언트 아키텍처)
            _V60_PROMPT_FILES = {
                "topic_generation": "prompts/topic_generation.txt",
                "topic_enhanced": "prompts/topic_enhanced.txt",
                "hook_generation": "prompts/hook_generation.txt",
                "hook_enhanced": "prompts/hook_enhanced.txt",
                "metadata_generation": "prompts/metadata_generation.txt",
                "thumbnail_style_guide": "prompts/thumbnail_style.txt",
                "story_bible": "prompts/story_bible.txt",
                "story_bible_improve": "prompts/story_bible_improve.txt",
                "story_summarize": "prompts/story_summarize.txt",
                "structural_outline": "prompts/structural_outline.txt",
                "craft_rules": "prompts/craft_rules.txt",
                "pacing_part1": "prompts/pacing_part1.txt",
                "pacing_part2": "prompts/pacing_part2.txt",
                "pacing_part3": "prompts/pacing_part3.txt",
                "image_style": "prompts/image_style.txt",
                "image_llm_prompt": "prompts/image_llm_prompt.txt",
                "cold_open_bridge": "prompts/cold_open_bridge.txt",
                "story_blueprint": "prompts/story_blueprint.txt",
            }
            for field_name, file_path_in_zip in _V60_PROMPT_FILES.items():
                data = _read_pack_file(zf, file_list, file_path_in_zip, is_encrypted)
                if data:
                    setattr(prompts, field_name, data.decode('utf-8', errors='replace'))

            # content 설정
            content_data = settings.get("content", {})
            content = PackContent(
                duration_minutes=content_data.get("duration_minutes", 5),
                min_turns=content_data.get("min_turns", 45),
                max_turns=content_data.get("max_turns", 70),
                image_style=settings.get("style", {}).get("image_style", ""),
            )

            # assets 설정 (v58 확장)
            assets_data = settings.get("assets", {})
            assets = PackAssets(
                bgm_path=assets_data.get("bgm_path", ""),
                sfx_path=assets_data.get("sfx_path", ""),
                bgm_folder=assets_data.get("bgm_folder", ""),
                sfx_folder=assets_data.get("sfx_folder", ""),
                sfx_enabled=assets_data.get("sfx_enabled", True),
                sfx_category=assets_data.get("sfx_category", ""),
                sfx_intensity=assets_data.get("sfx_intensity", "medium"),
                use_channel_bgm=_normalize_pack_channel_toggle(assets_data.get("use_channel_bgm", True)),
                use_channel_sfx=_normalize_pack_channel_toggle(assets_data.get("use_channel_sfx", True)),
                use_channel_tts=_normalize_pack_channel_toggle(assets_data.get("use_channel_tts", True)),
                narrator=assets_data.get("narrator", ""),
            )

            # v58: TTS 설정 로드
            tts_data = settings.get("tts", {})
            tts = PackTTS(
                narrator=tts_data.get("narrator", "narrator_male"),
                narrator_voice=tts_data.get("narrator_voice", ""),
                character_mapping=tts_data.get("character_mapping", {}),
                default_emotion=tts_data.get("default_emotion", "calm"),
                allowed_emotions=tts_data.get("allowed_emotions", []),
                emotion_weights=tts_data.get("emotion_weights", {}),
                narration_only=bool(tts_data.get("narration_only", False)),
            )

            # v58: Visual 설정 로드
            visual_data = settings.get("visual", {})
            visual = PackVisual(
                character_system_enabled=visual_data.get("character_system_enabled", False),
                forced_style=visual_data.get("forced_style", {}),
                thumbnail_backgrounds=visual_data.get("thumbnail_backgrounds", []),
                safe_fallbacks=visual_data.get("safe_fallbacks", []),
                safe_fallback_prompt=visual_data.get("safe_fallback_prompt", ""),
            )

            # v58: Hook 스타일 로드
            hook_data = settings.get("hook_style", {})
            hook_style = PackHookStyle(
                top_label=hook_data.get("top_label", "【 이야기 】"),
                top_color=hook_data.get("top_color", "#FFFFFF"),
                main_color=hook_data.get("main_color", "#FFFFFF"),
                bg_color=hook_data.get("bg_color", [0, 0, 0]),
                duration=hook_data.get("duration", 4.0),
            )

            # v58: SD 설정 로드
            sd_data = settings.get("sd", {})
            sd = PackSD(
                positive=sd_data.get("positive", prompts.sd_positive),
                negative=sd_data.get("negative", prompts.sd_negative),
                cfg_scale=sd_data.get("cfg_scale", 6.5),
                steps=sd_data.get("steps", 15),
                model=sd_data.get("model", ""),
            )

            # v58: 썸네일 설정 로드
            thumb_data = settings.get("thumbnail", {})
            thumbnail = PackThumbnail(
                text_default=thumb_data.get("text_default", ""),
                style_guide=thumb_data.get("style_guide", ""),
                title_hooks=thumb_data.get("title_hooks", []),
            )

            # v58: 비디오 설정 로드
            video_data = settings.get("video", {})
            video = PackVideo(
                pause_duration=video_data.get("pause_duration", 0.4),
                zoom_speed=video_data.get("zoom_speed", 1.0),
            )

            # v58: 시나리오 풀 로드 (topics.json에서)
            scenario_data = topics.get("scenario", {})
            scenario = PackScenario(
                safe_templates=scenario_data.get("safe_templates", []),
                tone_pool=scenario_data.get("tone_pool", []),
                relationship_pool=scenario_data.get("relationship_pool", []),
                place_pool=scenario_data.get("place_pool", []),
                arc_pool=scenario_data.get("arc_pool", []),
                trigger_pool=scenario_data.get("trigger_pool", []),
                twist_pool=scenario_data.get("twist_pool", []),
                conflict_pool=scenario_data.get("conflict_pool", []),
                mystery_types=scenario_data.get("mystery_types", []),
                evidence_pool=scenario_data.get("evidence_pool", []),
            )

            # v59: 비주얼 스토리텔링 설정 로드
            visual_storytelling = _load_visual_storytelling_config(settings)

            # v59.1.0: requirements 로드 (항상 초기화 후 설정)
            requirements = settings.get("requirements", {})

            # v60: SFX 설정 로드 (settings.json)
            sfx_data = settings.get("sfx", {})
            sfx = PackSFX(
                category_guide=sfx_data.get("category_guide", ""),
                keyword_map=sfx_data.get("keyword_map", {}),
            )

            # v60: 분위기 설정 로드 (settings.json)
            atmos_data = settings.get("atmosphere", {})
            atmosphere = PackAtmosphere(
                mood_map=atmos_data.get("mood_map", {}),
                keywords=atmos_data.get("keywords", {}),
            )

            # v60: 비상 시퀀스 로드 (settings.json)
            emergency_data = settings.get("emergency", {})
            emergency = PackEmergency(
                template_sequence=emergency_data.get("template_sequence", []),
            )

            # ACTIVE_PACK 업데이트
            ACTIVE_PACK.pack_id = manifest.get("pack_id", "")
            ACTIVE_PACK.pack_name = manifest.get("pack_name", "")
            ACTIVE_PACK.version = manifest.get("version", "")
            ACTIVE_PACK.author = manifest.get("author", "")
            ACTIVE_PACK.genre = manifest.get("genre", "")
            ACTIVE_PACK.channel_type = manifest.get("channel_type", manifest.get("genre", "horror"))
            ACTIVE_PACK.prompts = prompts
            ACTIVE_PACK.content = content
            ACTIVE_PACK.topic_templates = topics.get("templates", [])
            ACTIVE_PACK.tags = topics.get("tags", [])
            ACTIVE_PACK.intro_scripts = topics.get("intro_scripts", [])
            ACTIVE_PACK.characters = settings.get("characters", {})
            ACTIVE_PACK.character_config = tts.character_mapping
            ACTIVE_PACK.allowed_emotions = tts.allowed_emotions if tts.allowed_emotions else ["scared", "angry", "sad", "happy", "calm"]
            ACTIVE_PACK.emotion_policy = tts.emotion_weights if tts.emotion_weights else {"calm": 5}
            ACTIVE_PACK.emotion_correction_targets = tts_data.get("emotion_correction_targets", {})
            ACTIVE_PACK.style = settings.get("style", {})
            ACTIVE_PACK.restrictions = settings.get("restrictions", {})
            ACTIVE_PACK.assets = assets
            ACTIVE_PACK.tts = tts
            ACTIVE_PACK.visual = visual
            ACTIVE_PACK.hook_style = hook_style
            ACTIVE_PACK.sd = sd
            ACTIVE_PACK.thumbnail = thumbnail
            ACTIVE_PACK.video = video
            ACTIVE_PACK.scenario = scenario
            ACTIVE_PACK.visual_storytelling = visual_storytelling
            ACTIVE_PACK.script_quality = _load_script_quality_config(
                settings,
                category=ACTIVE_PACK.genre,
                mode=ACTIVE_PACK.channel_type,
            )
            ACTIVE_PACK.motiontoon = _load_motiontoon_config(
                settings,
                fallback_enabled=bool(getattr(visual_storytelling, "enabled", False)),
            )
            ACTIVE_PACK.requirements = requirements
            ACTIVE_PACK.scene_analyzer = settings.get("scene_analyzer", {})
            ACTIVE_PACK.background_library = settings.get("background_library", {})
            ACTIVE_PACK.sfx = sfx
            ACTIVE_PACK.atmosphere = atmosphere
            ACTIVE_PACK.emergency = emergency

            # v61.1 (#81): 핵심 프롬프트 빈값 체크
            _essential_prompts = ["pd_system", "writer_system"]
            _empty_count = sum(1 for p in _essential_prompts if not getattr(prompts, p, ""))
            if _empty_count == len(_essential_prompts):
                logger.warning(f"[PackConfig] !! 핵심 프롬프트 전부 비어있음 (pd_system, writer_system) — 암호화 키 불일치 또는 손상된 팩?")

            ACTIVE_PACK.is_loaded = True
            ACTIVE_PACK.source_path = str(pack_path)

            if requirements:
                sd_check_result = _check_sd_model_requirements(requirements)
                if sd_check_result.get("message"):
                    logger.info(f"[PackConfig] SD 모델 체크: {sd_check_result['message']}")

            logger.info(f"[PackConfig] 팩 로드 완료: {ACTIVE_PACK.pack_name} (v{ACTIVE_PACK.version})")
            return True

    except zipfile.BadZipFile:
        logger.error(f"[PackConfig] 손상된 팩 파일: {pack_path}")
        return False
    except Exception as e:
        logger.error(f"[PackConfig] 팩 로드 실패: {e}")
        return False


def _check_sd_model_requirements(requirements: Dict[str, Any]) -> Dict[str, Any]:
    """v59.1.0: SD 모델 요구사항 체크"""
    import requests

    result = {
        "model_installed": False,
        "model_name": "",
        "download_url": "",
        "alternative_available": False,
        "message": ""
    }

    sd_req = requirements.get("sd_model", {})
    if not sd_req:
        return result

    required_filename = sd_req.get("filename", "")
    model_name = sd_req.get("name", required_filename)
    download_url = sd_req.get("download_url", "")

    result["model_name"] = model_name
    result["download_url"] = download_url

    try:
        try:
            from config.settings import config
            sd_url = config.SD_URL
        except Exception:
            sd_url = "http://127.0.0.1:7860"

        res = requests.get(f"{sd_url}/sdapi/v1/sd-models", timeout=5)
        if res.status_code == 200:
            models = res.json()
            installed_names = [m.get("model_name", "").lower() for m in models]
            installed_titles = [m.get("title", "").lower() for m in models]

            required_base = required_filename.replace(".safetensors", "").lower()
            if any(required_base in name for name in installed_names + installed_titles):
                result["model_installed"] = True
                result["message"] = f"✅ 권장 모델 설치됨: {model_name}"
                logger.info(f"[PackConfig] SD 모델 확인: {model_name} 설치됨")
            else:
                alternatives = sd_req.get("alternatives", [])
                for alt in alternatives:
                    alt_filename = alt.get("filename", "").replace(".safetensors", "").lower()
                    if any(alt_filename in name for name in installed_names + installed_titles):
                        result["alternative_available"] = True
                        result["message"] = f"⚠️ 권장 모델 없음, 대체 모델 사용 가능: {alt.get('name', alt_filename)}"
                        logger.warning(f"[PackConfig] SD 권장 모델 없음, 대체 사용: {alt.get('name')}")
                        break

                if not result["alternative_available"]:
                    result["message"] = f"❌ 필수 SD 모델 없음: {model_name}\n다운로드: {download_url}"
                    logger.warning(f"[PackConfig] ⚠️ SD 모델 없음: {model_name}")
                    logger.warning(f"[PackConfig] 다운로드: {download_url}")

    except requests.exceptions.ConnectionError:
        result["message"] = "SD WebUI 미연결 - 모델 확인 불가"
        logger.warning("[PackConfig] SD WebUI 미연결, 모델 확인 스킵")
    except Exception as e:
        result["message"] = f"모델 확인 실패: {e}"
        logger.error(f"[PackConfig] SD 모델 확인 오류: {e}")

    return result


def get_pack_requirements() -> Dict[str, Any]:
    """v59.1.0: 현재 로드된 팩의 요구사항 반환"""
    global ACTIVE_PACK
    return getattr(ACTIVE_PACK, 'requirements', {})


def check_sd_model_status() -> Dict[str, Any]:
    """v59.1.0: 현재 팩의 SD 모델 상태 확인 (GUI에서 호출용)"""
    requirements = get_pack_requirements()
    if requirements:
        return _check_sd_model_requirements(requirements)
    return {"model_installed": True, "message": "팩에 SD 모델 요구사항 없음"}


def get_installed_sd_models() -> List[Dict[str, str]]:
    """v59.1.0: 설치된 SD 모델 목록 조회"""
    import requests

    try:
        from config.settings import config
        sd_url = config.SD_URL
    except Exception:
        sd_url = "http://127.0.0.1:7860"

    try:
        res = requests.get(f"{sd_url}/sdapi/v1/sd-models", timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logger.warning(f"[PackConfig] SD 모델 목록 조회 실패: {e}")

    return []


def get_current_sd_model() -> str:
    """v59.1.0: 현재 로드된 SD 모델 이름 조회"""
    import requests

    try:
        from config.settings import config
        sd_url = config.SD_URL
    except Exception:
        sd_url = "http://127.0.0.1:7860"

    try:
        res = requests.get(f"{sd_url}/sdapi/v1/options", timeout=5)
        if res.status_code == 200:
            return res.json().get("sd_model_checkpoint", "")
    except Exception as e:
        logger.debug(f"[PackConfig] 현재 SD 모델 조회 실패: {e}")

    return ""


def set_sd_model(model_title: str) -> bool:
    """v59.1.0: SD 모델 변경"""
    import requests

    try:
        from config.settings import config
        sd_url = config.SD_URL
    except Exception:
        sd_url = "http://127.0.0.1:7860"

    try:
        res = requests.post(
            f"{sd_url}/sdapi/v1/options",
            json={"sd_model_checkpoint": model_title},
            timeout=180
        )
        if res.status_code == 200:
            logger.info(f"[PackConfig] SD 모델 변경 완료: {model_title}")
            return True
    except Exception as e:
        logger.error(f"[PackConfig] SD 모델 변경 실패: {e}")

    return False


def get_required_sd_model_info() -> Dict[str, Any]:
    """v59.1.0: 현재 팩의 필수 SD 모델 정보 반환 (GUI 안내용)"""
    result = {
        "required": False,
        "model_name": "",
        "filename": "",
        "download_url": "",
        "why": "",
        "installed": False,
        "alternative_installed": False,
        "message": ""
    }

    requirements = get_pack_requirements()
    sd_req = requirements.get("sd_model", {})

    if not sd_req:
        if ACTIVE_PACK and ACTIVE_PACK.visual_storytelling:
            vs_sd = ACTIVE_PACK.visual_storytelling.sd_model
            if vs_sd and vs_sd.checkpoint:
                sd_req = {
                    "name": vs_sd.checkpoint.replace(".safetensors", "").replace("_", " ").title(),
                    "filename": vs_sd.checkpoint,
                }
        if not sd_req:
            return result

    result["required"] = True
    result["model_name"] = sd_req.get("name", "")
    result["filename"] = sd_req.get("filename", "")
    result["download_url"] = sd_req.get("download_url", "")
    result["why"] = sd_req.get("why", "")

    installed_models = get_installed_sd_models()
    installed_names = [m.get("title", "").lower() for m in installed_models]

    required_base = result["filename"].replace(".safetensors", "").lower()
    if any(required_base in name for name in installed_names):
        result["installed"] = True
        result["message"] = f"✅ 권장 모델 설치됨: {result['model_name']}"
    else:
        alternatives = sd_req.get("alternatives", [])
        for alt in alternatives:
            alt_base = alt.get("filename", "").replace(".safetensors", "").lower()
            if any(alt_base in name for name in installed_names):
                result["alternative_installed"] = True
                result["message"] = f"⚠️ 대체 모델 사용 가능: {alt.get('name', '')}"
                break

        if not result["alternative_installed"]:
            result["message"] = f"❌ 필수 모델 없음: {result['model_name']}"

    return result


@_with_pack_lock
def load_pack_by_id(pack_id: str) -> bool:
    """v58.3.1: pack_id로 팩 로드"""
    global ACTIVE_PACK

    def _load_imported_channel_pack(channel_id: str) -> bool:
        try:
            from utils.package_manager import get_package_manager

            pm = get_package_manager()
            package = pm.get_channel(channel_id)
            if not package:
                return False

            source_revpack = ""
            if isinstance(getattr(package, "extra_config", None), dict):
                source_revpack = package.extra_config.get("source_revpack", "")

            if source_revpack and Path(source_revpack).exists():
                logger.info(f"[PackConfig] imported channel '{channel_id}' → source_revpack")
                return load_pack(source_revpack)

            for alias in (package.package_id, package.channel_type):
                if alias and alias != channel_id:
                    logger.info(f"[PackConfig] imported channel '{channel_id}' → alias '{alias}'")
                    if load_pack_by_id(alias):
                        return True
        except Exception as exc:
            logger.warning(f"[PackConfig] imported channel pack lookup failed ({channel_id}): {exc}")

        return False

    try:
        import config.settings as settings
        project_root = Path(settings.PROJECT_ROOT)
    except Exception:
        project_root = Path(__file__).parent.parent.parent

    packs_dir = project_root / "assets" / "packs"
    legacy_aliases = {
        "horror": "mystery_toon",
        "horror_v59": "mystery_toon",
        "senior": "daily_life_toon",
        "senior_touching": "daily_life_toon",
        "senior_makjang": "daily_life_toon",
        "senior_scam_alert": "mystery_toon",
        "senior_life_saguk": "daily_life_toon",
    }
    requested_pack_id = pack_id
    pack_id = legacy_aliases.get(pack_id, pack_id)
    if pack_id != requested_pack_id:
        logger.warning(
            f"[PackConfig] legacy pack '{requested_pack_id}' is retired; "
            f"routing to VideoToon pack '{pack_id}'"
        )

    if _load_imported_channel_pack(pack_id):
        return True

    pack_file = f"{pack_id}.revpack"

    pack_path = packs_dir / pack_file
    dir_pack_path = packs_dir / pack_id / "manifest.json"
    _dev_mode = _is_dev_pack_mode()
    dir_pack_attempted = False

    if _dev_mode and dir_pack_path.exists():
        dir_pack_attempted = True
        logger.info(
            f"[PackConfig] pack_id '{pack_id}' -> {dir_pack_path.parent} "
            "(DEV_MODE loose pack preferred over .revpack)"
        )
        if _load_pack_from_json(dir_pack_path):
            return True
        logger.warning(
            f"[PackConfig] loose pack load failed for '{pack_id}', "
            f"falling back to {pack_path.name}"
        )

    if pack_path.exists():
        logger.info(f"[PackConfig] pack_id '{pack_id}' → {pack_path.name}")
        if load_pack(str(pack_path)):
            return True
        _dev_mode = _is_dev_pack_mode()
        if not _dev_mode:
            logger.error(
                f"[PackConfig] {pack_path.name} 로드 실패 → "
                "배포 환경에서 평문 디렉토리 팩 폴백 차단 (Phase B 보안)"
            )
            return False
        logger.warning(f"[PackConfig] {pack_path.name} 로드 실패 → 디렉토리 팩 폴백 시도 (DEV_MODE)")

    _dev_mode = _is_dev_pack_mode()
    dir_pack_path = packs_dir / pack_id / "manifest.json"
    if dir_pack_path.exists():
        if not _dev_mode:
            logger.error(
                f"[PackConfig] 평문 디렉토리 팩 차단: {dir_pack_path.parent} "
                "(배포 환경, REVERIE_DEV_MODE 필요)"
            )
            return False
        logger.info(f"[PackConfig] pack_id '{pack_id}' → 디렉토리 팩 {dir_pack_path.parent} (DEV_MODE)")
        return _load_pack_from_json(dir_pack_path)

    if pack_id in {"daily_life_toon", "mystery_toon"}:
        genre = pack_id
    else:
        genre = pack_id.split("_")[0] if "_" in pack_id else pack_id

    logger.warning(f"[PackConfig] '{pack_file}' 없음, load_default_pack({genre})로 폴백")
    return load_default_pack(genre)


@_with_pack_lock
def load_default_pack(genre: str) -> bool:
    """기본 팩 로드 (하드코딩 대체)"""
    global ACTIVE_PACK

    pack_mapping = {
        "daily": ["daily_life_toon.revpack"],
        "daily_life_toon": ["daily_life_toon.revpack"],
        "mystery": ["mystery_toon.revpack"],
        "mystery_toon": ["mystery_toon.revpack"],
        # Retired pack IDs are kept as compatibility routes only.
        "horror": ["mystery_toon.revpack"],
        "horror_v59": ["mystery_toon.revpack"],
        "senior": ["daily_life_toon.revpack"],
        "senior_touching": ["daily_life_toon.revpack"],
        "senior_makjang": ["daily_life_toon.revpack"],
        "senior_scam_alert": ["mystery_toon.revpack"],
        "senior_life_saguk": ["daily_life_toon.revpack"],
    }

    try:
        import config.settings as settings
        project_root = Path(settings.PROJECT_ROOT)
    except Exception:
        project_root = Path(__file__).parent.parent.parent

    packs_dir = project_root / "assets" / "packs"

    candidates = pack_mapping.get(genre, ["daily_life_toon.revpack"])
    for pack_file in candidates:
        pack_path = packs_dir / pack_file
        if pack_path.exists():
            try:
                if pack_file.endswith(".revpack"):
                    logger.info(f"[PackConfig] .revpack 파일 발견: {pack_path}")
                    result = load_pack(str(pack_path))
                    if result:
                        return True
                    logger.warning(f"[PackConfig] .revpack 로드 실패, 다음 후보 시도")
                elif pack_file.endswith(".json"):
                    _dev_mode = _is_dev_pack_mode()
                    if not _dev_mode:
                        logger.warning(f"[PackConfig] .json 팩 차단 (배포 환경): {pack_path.name}")
                        continue
                    logger.info(f"[PackConfig] .json 팩 파일 발견: {pack_path} (DEV_MODE)")
                    result = _load_pack_from_json(pack_path)
                    if result:
                        return True
                    logger.warning(f"[PackConfig] .json 로드 실패, 다음 후보 시도")
            except Exception as e:
                logger.warning(f"[PackConfig] {pack_file} 로드 중 오류: {e}, 다음 후보 시도")

    if genre not in DEFAULT_PACKS:
        logger.warning(f"[PackConfig] 알 수 없는 장르: {genre}, senior 내장 폴백 사용")
        genre = "senior"

    pack_data = DEFAULT_PACKS[genre]

    prompts_data = pack_data.get("prompts", {})
    prompts = PackPrompts(
        pd_system=prompts_data.get("pd_system", ""),
        writer_system=prompts_data.get("writer_system", ""),
        sd_positive=prompts_data.get("sd_positive", ""),
        sd_negative=prompts_data.get("sd_negative", ""),
    )
    _V60_DEFAULT_KEYS = [
        "topic_generation", "topic_enhanced", "hook_generation", "hook_enhanced",
        "metadata_generation", "thumbnail_style_guide", "story_bible",
        "story_bible_improve", "story_summarize", "structural_outline",
        "craft_rules", "pacing_part1", "pacing_part2", "pacing_part3",
        "image_style", "image_llm_prompt", "cold_open_bridge",
    ]
    for _key in _V60_DEFAULT_KEYS:
        _val = prompts_data.get(_key, "")
        if _val:
            setattr(prompts, _key, _val)

    content_data = pack_data.get("content", {})
    content = PackContent(
        duration_minutes=content_data.get("duration_minutes", 5),
        min_turns=content_data.get("min_turns", 45),
        max_turns=content_data.get("max_turns", 70),
        image_style=content_data.get("image_style", ""),
    )

    ACTIVE_PACK.pack_id = pack_data.get("pack_id", "")
    ACTIVE_PACK.pack_name = pack_data.get("pack_name", "")
    ACTIVE_PACK.version = pack_data.get("version", "")
    ACTIVE_PACK.author = pack_data.get("author", "")
    ACTIVE_PACK.genre = genre
    ACTIVE_PACK.channel_type = genre
    ACTIVE_PACK.prompts = prompts
    ACTIVE_PACK.content = content
    ACTIVE_PACK.motiontoon = MotiontoonConfig(enabled=True, mode="screen_space", shorts_vertical_ready=True)
    ACTIVE_PACK.topic_templates = pack_data.get("topic_templates", [])
    ACTIVE_PACK.tags = pack_data.get("tags", [])

    ACTIVE_PACK.allowed_emotions = pack_data.get("allowed_emotions", ["scared", "angry", "sad", "happy", "calm"])
    ACTIVE_PACK.emotion_policy = pack_data.get("emotion_policy", {"calm": 5})
    _tts_section = pack_data.get("tts", {})
    ACTIVE_PACK.emotion_correction_targets = (
        _tts_section.get("emotion_correction_targets", {})
        or pack_data.get("emotion_correction_targets", {})
    )

    assets_data = pack_data.get("assets", {})
    ACTIVE_PACK.assets = PackAssets(
        bgm_path=assets_data.get("bgm_path", ""),
        sfx_path=assets_data.get("sfx_path", ""),
        bgm_folder=genre,
        sfx_folder=genre,
        sfx_enabled=True,
        sfx_category=genre,
        sfx_intensity="medium",
        use_channel_bgm=True,
        use_channel_sfx=True,
        use_channel_tts=True,
        narrator=assets_data.get("narrator", "narrator_male"),
    )

    ACTIVE_PACK.tts = PackTTS(
        narrator=assets_data.get("narrator", "narrator_male"),
        character_mapping=pack_data.get("character_config", {}),
        default_emotion="calm",
        allowed_emotions=pack_data.get("allowed_emotions", []),
        emotion_weights=pack_data.get("emotion_policy", {}),
    )
    ACTIVE_PACK.character_config = ACTIVE_PACK.tts.character_mapping

    ACTIVE_PACK.visual = PackVisual()
    ACTIVE_PACK.hook_style = PackHookStyle()
    ACTIVE_PACK.sd = PackSD(
        positive=prompts.sd_positive,
        negative=prompts.sd_negative,
    )
    ACTIVE_PACK.thumbnail = PackThumbnail()
    ACTIVE_PACK.video = PackVideo()
    ACTIVE_PACK.scenario = PackScenario()
    ACTIVE_PACK.visual_storytelling = VisualStorytellingConfig()
    ACTIVE_PACK.script_quality = _default_script_quality_config(
        category=ACTIVE_PACK.genre,
        mode=ACTIVE_PACK.channel_type,
    )
    ACTIVE_PACK.requirements = {}
    ACTIVE_PACK.background_library = {}

    sfx_data = pack_data.get("sfx", {})
    ACTIVE_PACK.sfx = PackSFX(
        category_guide=sfx_data.get("category_guide", ""),
        keyword_map=sfx_data.get("keyword_map", {}),
    )

    atmos_data = pack_data.get("atmosphere", {})
    ACTIVE_PACK.atmosphere = PackAtmosphere(
        mood_map=atmos_data.get("mood_map", {}),
        keywords=atmos_data.get("keywords", {}),
    )

    emergency_data = pack_data.get("emergency", {})
    ACTIVE_PACK.emergency = PackEmergency(
        template_sequence=emergency_data.get("template_sequence", []),
    )

    ACTIVE_PACK.is_loaded = True
    ACTIVE_PACK.source_path = f"default:{genre}"

    logger.info(f"[PackConfig] 기본 팩 로드 (하드코딩): {ACTIVE_PACK.pack_name}")
    return True


@_with_pack_lock
def clear_pack():
    """활성 팩 초기화"""
    ACTIVE_PACK.pack_id = ""
    ACTIVE_PACK.pack_name = ""
    ACTIVE_PACK.version = ""
    ACTIVE_PACK.author = ""
    ACTIVE_PACK.genre = ""
    ACTIVE_PACK.channel_type = ""
    ACTIVE_PACK.prompts = PackPrompts()
    ACTIVE_PACK.content = PackContent()
    ACTIVE_PACK.topic_templates = []
    ACTIVE_PACK.tags = []
    ACTIVE_PACK.intro_scripts = []
    ACTIVE_PACK.characters = {}
    ACTIVE_PACK.character_config = {}
    ACTIVE_PACK.allowed_emotions = []
    ACTIVE_PACK.emotion_policy = {}
    ACTIVE_PACK.style = {}
    ACTIVE_PACK.restrictions = {}
    ACTIVE_PACK.assets = PackAssets()
    ACTIVE_PACK.tts = PackTTS()
    ACTIVE_PACK.visual = PackVisual()
    ACTIVE_PACK.hook_style = PackHookStyle()
    ACTIVE_PACK.sd = PackSD()
    ACTIVE_PACK.thumbnail = PackThumbnail()
    ACTIVE_PACK.video = PackVideo()
    ACTIVE_PACK.scenario = PackScenario()
    ACTIVE_PACK.visual_storytelling = VisualStorytellingConfig()
    ACTIVE_PACK.script_quality = _default_script_quality_config(
        category=ACTIVE_PACK.genre,
        mode=ACTIVE_PACK.channel_type,
    )
    ACTIVE_PACK.requirements = {}
    ACTIVE_PACK.background_library = {}
    ACTIVE_PACK.sfx = PackSFX()
    ACTIVE_PACK.atmosphere = PackAtmosphere()
    ACTIVE_PACK.emergency = PackEmergency()
    ACTIVE_PACK.is_loaded = False
    ACTIVE_PACK.source_path = ""
    logger.info("[PackConfig] 팩 초기화됨")


# ============================================================
# 프롬프트 접근 함수
# ============================================================

def get_prompt(prompt_type: str, fallback_genre: str = "daily_life_toon") -> str:
    """프롬프트 가져오기 — v60: 팩-클라이언트 아키텍처, 21개 프롬프트 키 지원"""
    SD_QUALITY_POSITIVE = "masterpiece, best quality, "
    SD_QUALITY_NEGATIVE = "(worst quality:1.4), (low quality:1.4), nsfw, text, watermark"

    V60_PROMPT_FIELDS = {
        "topic_generation", "topic_enhanced",
        "hook_generation", "hook_enhanced",
        "metadata_generation", "thumbnail_style_guide",
        "story_bible", "story_bible_improve", "story_summarize",
        "structural_outline",
        "craft_rules", "pacing_part1", "pacing_part2", "pacing_part3",
        "image_style", "image_llm_prompt",
        "cold_open_bridge",
        "story_blueprint",
    }

    if not ACTIVE_PACK.is_loaded:
        load_default_pack(fallback_genre)

    if prompt_type in V60_PROMPT_FIELDS:
        result = getattr(ACTIVE_PACK.prompts, prompt_type, "")
        if not result and prompt_type in {"writer_system", "story_bible", "craft_rules", "image_llm_prompt"}:
            logger.warning(f"[PackConfig] ⚠️ 필수 프롬프트 '{prompt_type}' 비어있음 — 팩 prompts/ 확인 필요")
        return result

    if prompt_type == "pd_system":
        return ACTIVE_PACK.prompts.pd_system
    elif prompt_type == "writer_system":
        return ACTIVE_PACK.prompts.writer_system
    elif prompt_type == "sd_positive":
        prompt = ACTIVE_PACK.prompts.sd_positive
        if not prompt:
            logger.warning("[PackConfig] ⚠️ SD positive 프롬프트 없음 → 기본 품질 태그 사용")
            return SD_QUALITY_POSITIVE.rstrip(", ")
        if "masterpiece" not in prompt.lower() and "best quality" not in prompt.lower():
            logger.info("[PackConfig] SD positive에 품질 태그 추가")
            return SD_QUALITY_POSITIVE + prompt
        return prompt
    elif prompt_type == "sd_negative":
        prompt = ACTIVE_PACK.prompts.sd_negative
        if not prompt:
            logger.warning("[PackConfig] ⚠️ SD negative 프롬프트 없음 → 기본 부정 태그 사용")
            return SD_QUALITY_NEGATIVE
        if "worst quality" not in prompt.lower() and "low quality" not in prompt.lower():
            logger.info("[PackConfig] SD negative에 품질 태그 추가")
            return prompt + ", " + SD_QUALITY_NEGATIVE
        return prompt
    elif prompt_type == "safe_fallback":
        prompt = ACTIVE_PACK.visual.safe_fallback_prompt
        if not prompt:
            logger.warning("[PackConfig] safe_fallback_prompt 없음 - 빈 문자열 반환")
        return prompt
    else:
        logger.warning(f"[PackConfig] 알 수 없는 프롬프트 타입: {prompt_type}")
        return ""


def get_sfx_config() -> PackSFX:
    """v60: SFX 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.sfx


def get_atmosphere_config() -> PackAtmosphere:
    """v60: 분위기 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.atmosphere


def get_emergency_sequence() -> List[List[str]]:
    """v60: 비상 템플릿 시퀀스 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    seq = ACTIVE_PACK.emergency.template_sequence
    if not seq:
        logger.warning("[PackConfig] emergency_sequence 비어있음 — script_writers 자체 폴백 사용")
    return seq


def get_content_settings() -> PackContent:
    """콘텐츠 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.content


def get_topic_templates() -> List[str]:
    """토픽 템플릿 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.topic_templates


def get_tags() -> List[str]:
    """태그 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.tags


def get_character_config() -> Dict[str, str]:
    """캐릭터 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.character_config


def get_allowed_emotions() -> List[str]:
    """v57.7.5: 허용된 감정 목록 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.allowed_emotions if ACTIVE_PACK.allowed_emotions else ["scared", "angry", "sad", "happy", "calm"]


def get_emotion_policy() -> Dict[str, int]:
    """v57.7.5: 감정 정책 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.emotion_policy if ACTIVE_PACK.emotion_policy else {"calm": 5}


def get_emotion_correction_targets(category: str = "", mode: str = "") -> Dict[str, int]:
    """감정 후처리 보정 타깃을 팩 우선으로 반환한다."""
    if ACTIVE_PACK.is_loaded and ACTIVE_PACK.emotion_correction_targets:
        return dict(ACTIVE_PACK.emotion_correction_targets)

    category = (category or getattr(ACTIVE_PACK, "genre", "")).strip().lower()
    mode = (mode or getattr(ACTIVE_PACK, "channel_type", "")).strip().lower()

    if category == "horror":
        return {"scared": 5, "worried": 5, "whisper": 4, "desperate": 3}
    if category == "senior" and mode == "makjang":
        return {"angry": 4, "worried": 4, "desperate": 3}
    if category == "senior":
        return {"sad": 4, "worried": 3, "happy": 2}
    return {"worried": 3, "sad": 2}


def get_script_quality_config(category: str = "", mode: str = "") -> ScriptQualityConfig:
    """대본 품질 게이트 임계값을 팩 우선으로 반환한다."""
    if ACTIVE_PACK.is_loaded:
        current = getattr(ACTIVE_PACK, "script_quality", None)
        if isinstance(current, ScriptQualityConfig):
            return current

    return _default_script_quality_config(category=category, mode=mode)


# ============================================================
# v58: 확장 필드 Getter 함수
# ============================================================

def get_tts_settings() -> PackTTS:
    """v58: TTS 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.tts


def get_visual_settings() -> PackVisual:
    """v58: Visual 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.visual


def get_hook_style() -> PackHookStyle:
    """v58: Hook 스타일 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.hook_style


def get_sd_settings() -> PackSD:
    """v58: SD 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.sd


def get_thumbnail_settings() -> PackThumbnail:
    """v58: 썸네일 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.thumbnail


def get_video_settings() -> PackVideo:
    """v58: 비디오 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.video


def get_scenario_pools() -> PackScenario:
    """v58: 시나리오 풀 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    scenario = ACTIVE_PACK.scenario
    if not scenario.tone_pool and not scenario.twist_pool:
        logger.warning("[PackConfig] scenario pools 비어있음 (tone_pool, twist_pool 없음) — 팩 topics.json 확인 필요")
    return scenario


def get_safe_templates() -> List[str]:
    """v58: 안전한 이미지 프롬프트 템플릿 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.scenario.safe_templates


def get_intro_scripts() -> List[str]:
    """v58: 인트로 멘트 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.intro_scripts


def get_narrator() -> str:
    """v58: 나레이터 타입 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    if ACTIVE_PACK.tts.narrator:
        return ACTIVE_PACK.tts.narrator
    return ACTIVE_PACK.assets.narrator or "narrator_male"


def get_forced_style() -> Dict[str, str]:
    """v58: 강제 스타일 프롬프트 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.visual.forced_style


def get_thumbnail_backgrounds() -> List[str]:
    """v58: 썸네일 배경 프롬프트 목록 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.visual.thumbnail_backgrounds


# ============================================================
# v59: 비주얼 스토리텔링 Getter 함수
# ============================================================

def get_visual_storytelling_config() -> VisualStorytellingConfig:
    """v59: 비주얼 스토리텔링 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    return ACTIVE_PACK.visual_storytelling


def is_visual_storytelling_enabled() -> bool:
    """v59: 비주얼 스토리텔링 활성화 여부"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    vs = ACTIVE_PACK.visual_storytelling
    if isinstance(vs, dict):
        return vs.get('enabled', False)
    return vs.enabled


def get_character_definitions() -> List[CharacterDefinition]:
    """v59: 캐릭터 정의 목록 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    vs = ACTIVE_PACK.visual_storytelling
    if isinstance(vs, dict):
        return vs.get('characters', [])
    return vs.characters


def get_character_by_id(character_id: str) -> Optional[CharacterDefinition]:
    """v59: ID로 캐릭터 정의 가져오기"""
    for char in get_character_definitions():
        if char.id == character_id:
            return char
    return None


def get_character_by_alias(alias: str) -> Optional[CharacterDefinition]:
    """v59: 별칭으로 캐릭터 정의 가져오기"""
    alias_lower = alias.lower()
    for char in get_character_definitions():
        if char.name.lower() == alias_lower:
            return char
        if alias_lower in [a.lower() for a in char.aliases]:
            return char
    return None


def get_sd_model_config() -> SDModelConfig:
    """v59: SD 모델 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    vs = ACTIVE_PACK.visual_storytelling
    if isinstance(vs, dict):
        return vs.get('sd_model', {})
    return vs.sd_model


def get_subtitle_style() -> SubtitleStyle:
    """v59: 자막 스타일 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    vs = ACTIVE_PACK.visual_storytelling
    if isinstance(vs, dict):
        return vs.get('subtitle_style', {})
    return vs.subtitle_style


def get_visual_effects() -> VisualEffect:
    """v59: 시각 효과 설정 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    vs = ACTIVE_PACK.visual_storytelling
    if isinstance(vs, dict):
        return vs.get('visual_effects', {})
    return vs.visual_effects


def get_transition_style() -> TransitionStyle:
    """v59: 씬 전환 스타일 가져오기"""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    vs = ACTIVE_PACK.visual_storytelling
    if isinstance(vs, dict):
        return vs.get('transitions', {})
    return vs.transitions


def get_motiontoon_config() -> MotiontoonConfig:
    """모션툰 설정을 가져온다."""
    if not ACTIVE_PACK.is_loaded:
        load_default_pack("horror")
    motiontoon = ACTIVE_PACK.motiontoon
    vs = ACTIVE_PACK.visual_storytelling
    vs_enabled = bool(getattr(vs, "enabled", False)) if not isinstance(vs, dict) else bool(vs.get("enabled", False))
    if not getattr(motiontoon, "enabled", False) and vs_enabled:
        return MotiontoonConfig(
            enabled=True,
            mode=getattr(motiontoon, "mode", "screen_space"),
            profile=_normalize_motiontoon_profile(
                getattr(motiontoon, "profile", "basic"),
                True,
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
            prop_keywords=getattr(motiontoon, "prop_keywords", []),
            scene_motion_rules=getattr(motiontoon, "scene_motion_rules", {}),
            cast_slots=getattr(motiontoon, "cast_slots", {}),
            puppet_profiles=getattr(motiontoon, "puppet_profiles", {}),
        )
    return _clone_motiontoon_config(motiontoon)


def get_motiontoon_support_info(
    requested_mode: Optional[str] = None,
    motiontoon: Optional[MotiontoonConfig] = None,
) -> Dict[str, Any]:
    """Return pack support and requested/effective runtime mode."""
    motiontoon = _clone_motiontoon_config(motiontoon or get_motiontoon_config())
    profile = _normalize_motiontoon_profile(motiontoon.profile, motiontoon.enabled)

    if getattr(motiontoon, "video_toon_local_enabled", False):
        support_level = "videotoon"
        label = "VideoToon Layered"
    elif not motiontoon.enabled or profile == "none":
        support_level = "disabled"
        label = "Disabled"
    elif profile == "gishini":
        support_level = "gishini"
        label = "Gishini Ready"
    else:
        support_level = "basic"
        label = "Basic Only"

    requested = (requested_mode or "").strip().lower()
    if requested not in {"classic_dynamic", "gishini_motiontoon", "videotoon_layered", "disabled"}:
        requested = "videotoon_layered" if support_level == "videotoon" else "disabled"

    effective = requested
    reason = ""
    if requested == "disabled":
        effective = "disabled"
    elif requested == "videotoon_layered":
        if support_level != "videotoon":
            effective = "disabled"
            reason = "pack_not_videotoon"
    elif requested == "gishini_motiontoon":
        if support_level == "disabled":
            effective = "disabled"
            reason = "pack_disabled"
        elif support_level != "gishini":
            effective = "disabled"
            reason = "pack_basic_only"

    return {
        "profile": profile,
        "support_level": support_level,
        "label": label,
        "requested_mode": requested,
        "effective_mode": effective,
        "reason": reason,
        "enabled": motiontoon.enabled,
    }


def resolve_motiontoon_runtime_config(
    render_mode_override: Optional[str] = None,
    motiontoon: Optional[MotiontoonConfig] = None,
) -> Tuple[MotiontoonConfig, Dict[str, Any]]:
    """Resolve the final runtime motiontoon config after GUI/pack compatibility checks."""
    resolved = _clone_motiontoon_config(motiontoon or get_motiontoon_config())
    support = get_motiontoon_support_info(
        requested_mode=render_mode_override,
        motiontoon=resolved,
    )

    effective_mode = support["effective_mode"]
    if effective_mode == "videotoon_layered" and getattr(resolved, "video_toon_local_enabled", False):
        # Keep only the VideoToon layer assembly controls. Old dynamic zoom/shake
        # effects stay off because they caused artificial overlay artifacts.
        resolved.enabled = True
        resolved.mode = "videotoon_layered"
        resolved.character_layer_mode = resolved.character_layer_mode or "foreground_cutout"
        resolved.layered_cutout_enabled = True
        resolved.blink_enabled = bool(getattr(resolved, "blink_enabled", True))
        resolved.mouth_flap_enabled = bool(getattr(resolved, "mouth_flap_enabled", True))
        resolved.prop_overlay_enabled = False
        resolved.dialogue_panel_enabled = True
        resolved.idle_drift_enabled = bool(getattr(resolved, "idle_drift_enabled", True))
        resolved.impact_shake_enabled = False
        resolved.snap_zoom_enabled = False
        resolved.subtitle_pulse_enabled = False
        resolved.slow_push_enabled = bool(getattr(resolved, "slow_push_enabled", True))
        logger.info("[VideoToon] layered assembly enabled; legacy dynamic motion disabled")
    else:
        resolved.enabled = False
        resolved.mode = "disabled"
        resolved.idle_drift_enabled = False
        resolved.impact_shake_enabled = False
        resolved.snap_zoom_enabled = False
        resolved.subtitle_pulse_enabled = False
        resolved.slow_push_enabled = False
        resolved.character_layer_mode = ""
        resolved.layered_cutout_enabled = False
        resolved.blink_enabled = False
        resolved.mouth_flap_enabled = False
        resolved.prop_overlay_enabled = False
        resolved.dialogue_panel_enabled = False
        logger.info(f"[Motiontoon] legacy dynamic motion disabled (requested={effective_mode})")

    return resolved, support


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== PackConfig 테스트 ===\n")

    print("1. 기본 horror 팩 로드:")
    load_default_pack("horror")
    print(f"   팩 이름: {ACTIVE_PACK.pack_name}")
    print(f"   장르: {ACTIVE_PACK.genre}")
    print(f"   PD 프롬프트 길이: {len(ACTIVE_PACK.prompts.pd_system)}자")
    print()

    print("2. get_prompt() 테스트:")
    pd = get_prompt("pd_system")
    print(f"   PD: {pd[:50]}...")
    print()

    print("3. 기본 senior 팩 로드:")
    load_default_pack("senior")
    print(f"   팩 이름: {ACTIVE_PACK.pack_name}")
    print(f"   토픽 예시: {ACTIVE_PACK.topic_templates[:2]}")
