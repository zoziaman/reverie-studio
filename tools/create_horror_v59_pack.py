# tools/create_horror_v59_pack.py
# ============================================================
# v59 Visual Storytelling 공포팩 생성 스크립트
# horror_default.revpack 기반 + v59 Visual Storytelling 활성화
# ============================================================
# 실행: python tools/create_horror_v59_pack.py
# 출력: assets/packs/horror_v59.revpack
# ============================================================

import sys
import json
import zipfile
import base64
from pathlib import Path
from datetime import datetime

# 암호화 라이브러리
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "packs"

# ============================================================
# 암호화 설정 (pack_creator_full.py와 동일)
# ============================================================

PACK_ENCRYPTION_SALT = b'ReveriePack2024Salt!'
PACK_ENCRYPTION_PASSWORD = b'ReverieStudio_PackEncryption_v57'

ENCRYPTED_FILES = [
    "manifest.json",
    "settings.json",
    "prompts/pd_system.txt",
    "prompts/writer_system.txt",
    "prompts/sd_prompts.json",
]


def get_encryption_key() -> bytes:
    """Fernet 암호화 키 생성 (PBKDF2 기반)"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=PACK_ENCRYPTION_SALT,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PACK_ENCRYPTION_PASSWORD))
    return key


def encrypt_content(content: bytes) -> bytes:
    """콘텐츠 암호화"""
    key = get_encryption_key()
    fernet = Fernet(key)
    return fernet.encrypt(content)


# ============================================================
# v59 공포팩 설정
# ============================================================

def create_manifest() -> dict:
    """manifest.json 생성"""
    return {
        "pack_id": "horror_v59",
        "pack_name": "v59 비주얼 공포팩",
        "version": "59.0.0",
        "author": "Reverie Studio",
        "genre": "horror",
        "description": "v59 Visual Storytelling이 활성화된 공포 콘텐츠 팩",
        "created_at": datetime.now().isoformat(),
        # 두 가지 키 모두 제공 (호환성)
        "min_reverie_version": "1",
        "reverie_version_min": "1",
        "features": ["visual_storytelling", "character_consistency", "scene_analysis"],
    }


def create_settings() -> dict:
    """settings.json 생성 - v59 Visual Storytelling 포함"""
    return {
        # v58 기존 설정들
        "content": {
            "duration_minutes": 5,
            "min_turns": 45,
            "max_turns": 70,
        },
        "style": {
            "image_style": "dark silhouette horror, atmospheric, cinematic",
            "setting": "한국, 현대 또는 과거, 폐가/산속/도시 어두운 곳",
            "mood": ["공포", "긴장감", "미스터리", "심리적 불안"],
            "intensity": 7,
        },
        "characters": {
            "types": ["주인공", "귀신/괴물", "조력자", "희생자"],
            "count": "2~4",
            "special": "귀신은 서서히 드러나야 함, 주인공은 평범한 사람",
        },
        "restrictions": {
            "forbidden": ["과도한 고어", "성인 콘텐츠", "노출"],
            "required": ["반전", "공포 클라이맥스", "긴장감 고조"],
        },

        # TTS 설정
        "tts": {
            "narrator": "narrator_male",
            "character_mapping": {
                "narrator": "man",
                "protagonist": "woman",
                "ghost": "woman",
                "grandma": "grandma",
                "grandpa": "grandpa",
                "나레이션": "narrator",
                "내레이션": "narrator",
                "주인공": "woman",
                "귀신": "woman",
                "할머니": "grandma",
                "할아버지": "grandpa",
            },
            "default_emotion": "calm",
            "allowed_emotions": ["scared", "angry", "sad", "calm", "whisper", "desperate"],
            "emotion_weights": {"scared": 4, "calm": 3, "whisper": 2},
        },

        # Visual 설정
        "visual": {
            "character_system_enabled": True,
            "forced_style": {
                "force_positive": "dark atmosphere, horror, silhouette, dramatic lighting",
                "force_negative": "bright colors, happy, cheerful, cute",
            },
            "thumbnail_backgrounds": [
                "dark forest at night",
                "abandoned house interior",
                "foggy graveyard",
                "dimly lit corridor",
            ],
            "safe_fallbacks": [
                "dark silhouette in fog",
                "eerie shadow on wall",
                "moonlit window with curtains",
            ],
            "safe_fallback_prompt": "dark silhouette, horror atmosphere, fog, dramatic lighting",
        },

        # Hook 스타일
        "hook_style": {
            "top_label": "【 괴담 】",
            "top_color": "#FF4444",
            "main_color": "#FFFFFF",
            "bg_color": [0, 0, 0],
            "duration": 4.0,
        },

        # SD 설정 (기본)
        "sd": {
            "positive": "masterpiece, best quality, dark atmosphere, horror, silhouette, dramatic lighting, eerie, mysterious, (dark background:1.2), cinematic, korean ghost story style",
            "negative": "(worst quality:1.4), (low quality:1.4), bright colors, happy, cheerful, nsfw, text, watermark, cute, colorful",
            "cfg_scale": 7.0,
            "steps": 28,
            "model": "",
        },

        # 썸네일
        "thumbnail": {
            "text_default": "소름 돋는 실화",
            "style_guide": "dark, horror, mysterious, red accent",
        },

        # 비디오
        "video": {
            "pause_duration": 0.5,
            "zoom_speed": 1.2,
        },

        # ======================================================
        # v59: Visual Storytelling 설정 (핵심!)
        # ======================================================
        "visual_storytelling": {
            "enabled": True,  # v59 활성화!
            "prompt_strategy": "panel_card",
            "llm_hint_tag_limit": 4,

            # SD 모델 설정
            "sd_model": {
                "checkpoint": "ghostmix_v20.safetensors",
                "vae": "vae-ft-mse-840000-ema-pruned.safetensors",
                "sampler": "DPM++ 2M Karras",
                "scheduler": "Karras",
                "steps": 28,
                "cfg_scale": 7.0,
                "width": 1024,
                "height": 576,
                "clip_skip": 2,
                "lora_models": [],
            },

            # 캐릭터 정의 (핵심!)
            "characters": [
                {
                    "id": "narrator",
                    "name": "이야기꾼",
                    "aliases": ["나레이터", "화자", "나레이션"],
                    "base_prompt": "mysterious storyteller, dark silhouette, traditional korean, wise elderly",
                    "style_suffix": "atmospheric, dramatic lighting",
                    "expressions": {
                        "neutral": "calm mysterious expression",
                        "ominous": "knowing mysterious smile",
                        "warning": "serious concerned expression",
                    },
                    "poses": {
                        "sitting": "sitting in traditional room, candlelight",
                        "standing": "standing in shadows",
                    },
                    "reference_images": [],
                    "lora": None,
                },
                {
                    "id": "protagonist",
                    "name": "주인공",
                    "aliases": ["주인공", "나", "청년", "여자", "남자"],
                    "base_prompt": "korean young adult, ordinary appearance, casual clothes",
                    "style_suffix": "realistic, natural lighting",
                    "expressions": {
                        "neutral": "calm normal expression",
                        "fear": "terrified, wide eyes, pale face, trembling",
                        "surprise": "shocked, gasping, open mouth",
                        "confusion": "puzzled, furrowed brows",
                        "dread": "horrified realization, cold sweat",
                    },
                    "poses": {
                        "standing": "standing alert",
                        "running": "running in fear, motion blur",
                        "hiding": "hiding behind furniture, peeking",
                        "frozen": "frozen in terror, unable to move",
                    },
                    "reference_images": [],
                    "lora": None,
                },
                {
                    "id": "ghost",
                    "name": "귀신",
                    "aliases": ["귀신", "유령", "혼령", "그것", "그녀"],
                    "base_prompt": "korean ghost, long black hair, white traditional dress, pale skin",
                    "style_suffix": "eerie, translucent, supernatural, horror",
                    "expressions": {
                        "neutral": "emotionless blank stare",
                        "malevolent": "twisted smile, dark eyes",
                        "sorrowful": "crying black tears, tragic",
                        "rage": "screaming, distorted features",
                    },
                    "poses": {
                        "floating": "floating in air, long hair flowing",
                        "standing": "standing unnaturally still",
                        "crawling": "crawling on ceiling, contorted",
                        "appearing": "emerging from shadows, partial visibility",
                    },
                    "reference_images": [],
                    "lora": None,
                },
                {
                    "id": "grandma",
                    "name": "할머니",
                    "aliases": ["할머니", "노인", "어르신"],
                    "base_prompt": "korean elderly woman, gray hair, wrinkled kind face, traditional hanbok",
                    "style_suffix": "warm but mysterious, knows secrets",
                    "expressions": {
                        "neutral": "serene elderly expression",
                        "worried": "concerned, knowing look",
                        "warning": "serious urgent expression",
                        "mysterious": "cryptic knowing smile",
                    },
                    "poses": {
                        "sitting": "sitting on floor, traditional style",
                        "praying": "praying hands, eyes closed",
                    },
                    "reference_images": [],
                    "lora": None,
                },
            ],

            # 자막 스타일 (가독성 최우선: 검정 박스 + 흰 글씨)
            # 귀신 대사는 SPEAKER_COLORS["ghost"]="#FF0000" 빨간색으로 자동 적용
            "subtitle_style": {
                "font_family": "Noto Sans KR",
                "font_size": 48,
                "font_weight": "bold",
                "text_color": "#FFFFFF",  # 흰색 (가독성)
                "stroke_color": "#000000",  # 검정 테두리
                "stroke_width": 3,
                "shadow_color": "rgba(0, 0, 0, 0.8)",  # 검정 그림자
                "shadow_blur": 8,
                "background_enabled": True,
                "background_color": "rgba(0, 0, 0, 0.85)",  # 불투명 검정 박스
                "background_padding": 16,
                "background_radius": 4,
                "position": "bottom",
                "margin_bottom": 80,
                "text_align": "center",
                "animation_in": "fadeIn",
                "animation_out": "fadeOut",
                "animation_duration": 0.3,
            },

            # 시각 효과 (공포 특화)
            "visual_effects": {
                "vignette_enabled": True,
                "vignette_intensity": 0.5,  # 강한 비네팅
                "vignette_color": "#000000",
                "color_filter_enabled": True,
                "color_filter": "horror",  # 공포 필터
                "color_filter_intensity": 0.3,
                "frame_enabled": False,
                "frame_image": "",
                "frame_opacity": 1.0,
                "particles_enabled": True,
                "particles_type": "dust",  # 먼지 파티클
                "particles_density": 0.4,
                "ken_burns_enabled": True,
                "ken_burns_zoom_range": [1.0, 1.2],  # 더 강한 줌
                "ken_burns_pan_enabled": True,
            },

            # 씬 전환
            "transitions": {
                "default_transition": "fade_black",  # 어둠으로 페이드
                "transition_duration": 0.6,
                "scene_transitions": {
                    "flashback": "fade_white",
                    "nightmare": "glitch",
                    "climax": "zoom_blur",
                    "ghost_appear": "fade_black",
                },
            },

            # 이미지 생성 설정
            "images_per_minute": 4,  # 분당 4장 (공포는 빠른 전개)
            "min_scene_duration": 3.0,
            "max_consecutive_reuse": 2,
            "face_detection_enabled": True,
            "nsfw_filter_enabled": True,
            "blur_check_enabled": True,
            "retry_on_failure": 3,
        },

        # 라이선스
        "license": {
            "type": "test",
            "key_required": False,
        },

        # 에셋
        "assets": {
            "bgm_path": "assets/bgm/horror/",
            "sfx_path": "assets/sfx/horror/",
            "use_channel_bgm": "horror",
            "use_channel_sfx": "horror",
            "use_channel_tts": "horror",
        },
    }


def create_topics() -> dict:
    """topics.json 생성"""
    return {
        "templates": [
            "폐가에서 발견된 일기장의 비밀",
            "매일 밤 3시에 울리는 초인종",
            "거울 속에서 나를 바라보는 또 다른 나",
            "할머니가 절대 열지 말라던 다락방",
            "엘리베이터에서 함께 탄 그 사람",
            "이사 온 집에서 들리는 발자국 소리",
            "고시원 옆방에서 들리는 기이한 소리",
            "산 속 폐교에서 보낸 하룻밤",
            "귀신 들린 휴대폰",
            "새벽 지하철 마지막 칸의 승객",
        ],
        "tags": [
            "공포", "괴담", "무서운이야기", "호러", "귀신",
            "심령", "실화괴담", "무서운실화", "공포썰", "오싹한이야기"
        ],
        "intro_scripts": [
            "오늘 들려드릴 이야기는... 저도 처음 들었을 때 소름이 돋았습니다.",
            "이 이야기는 실제로 있었던 일입니다. 믿거나 말거나...",
            "혹시... 지금 혼자 계신가요? 그럼 조심하세요.",
        ],
        "scenario": {
            "safe_templates": [
                "dark silhouette in foggy forest",
                "eerie shadow on cracked wall",
                "moonlight through old window",
                "empty dark corridor",
                "candle flickering in darkness",
            ],
            "place_pool": ["폐가", "산속 오두막", "고시원", "지하철", "학교"],
            "trigger_pool": ["이상한 소리", "문이 열림", "그림자", "전화"],
            "arc_pool": ["발견", "조사", "도망", "대면", "탈출"],
        },
    }


def create_pd_system() -> str:
    """PD 시스템 프롬프트"""
    return """당신은 공포 콘텐츠 전문 PD입니다.
시청자가 몰입할 수 있는 긴장감 있는 스토리를 구성하세요.

스토리 구조:
1. 평화로운 일상 - 주인공의 평범한 하루 (10%)
2. 이상한 징조 - 작은 불안 요소 등장 (15%)
3. 본격적인 공포 - 긴장감 고조, 귀신의 존재 암시 (30%)
4. 클라이맥스 - 공포의 정점, 귀신과의 대면 (30%)
5. 반전/여운 - 충격적인 결말 또는 열린 결말 (15%)

핵심 포인트:
- 서서히 고조되는 공포 분위기 (점프스케어 X, 분위기 공포 O)
- 예상치 못한 반전
- 감각적 묘사 (소리, 어둠, 냄새, 온도)
- 화자의 심리적 불안감 표현
- 한국적 공포 요소 (귀신, 무속, 전통)

v59 비주얼 가이드:
- 각 장면의 분위기와 등장인물을 명확히 서술
- 귀신 등장 시 점진적으로 묘사 (처음엔 그림자, 나중에 전신)
- 캐릭터 감정 변화를 구체적으로 표현
- 시각적 대비 활용 (어둠↔빛, 평화↔공포)"""


def create_writer_system() -> str:
    """작가 시스템 프롬프트"""
    return """공포 이야기 전문 작가입니다.

문장 스타일:
- 짧고 강렬한 문장으로 긴장감 유지
- "..." 사용하여 불안감 조성
- 감각적 묘사 중시 (싸늘한 손길, 축축한 공기, 썩은 냄새)
- 과거형 서술 기본, 긴장 고조 시 현재형
- 의성어/의태어 활용 (끼이익, 둥둥, 스르르)

캐릭터 말투:
- 나레이터: 차분하지만 긴장감 있는 톤, 가끔 속삭임
- 할머니/할아버지: 사투리, 느린 말투, 의미심장한 말
- 주인공: 존댓말, 당황하고 두려워하는 톤
- 귀신: 느리고 기이한 말투, 또는 침묵

감정 태그 사용:
[calm] 차분한 서술
[fear] 두려움, 떨리는 목소리
[whisper] 속삭임, 긴박한 상황
[shock] 충격, 놀람
[desperate] 절박함, 공포의 정점

v59 비주얼 힌트:
- 화자가 누구인지 명확히 (나레이션: ... / 주인공: ...)
- 중요 장면은 시각적 묘사 포함
- 귀신 등장 시 외형 묘사 (긴 머리, 흰 옷, 창백한 얼굴)"""


def create_sd_prompts() -> dict:
    """SD 프롬프트"""
    return {
        "positive": "masterpiece, best quality, dark atmosphere, horror, silhouette, dramatic lighting, eerie, mysterious, (dark background:1.2), cinematic, korean ghost story, traditional korean horror, atmospheric fog, moonlight, shadows",
        "negative": "(worst quality:1.4), (low quality:1.4), bright colors, happy, cheerful, nsfw, text, watermark, cute, colorful, cartoon, anime, 3d render, deformed, ugly, blurry",
    }


# ============================================================
# 팩 생성
# ============================================================

def create_pack():
    """horror_v59.revpack 생성"""
    print("=" * 60)
    print("v59 공포팩 생성 시작")
    print("=" * 60)

    # 출력 경로
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "horror_v59.revpack"

    # 데이터 생성
    manifest = create_manifest()
    settings = create_settings()
    topics = create_topics()
    pd_system = create_pd_system()
    writer_system = create_writer_system()
    sd_prompts = create_sd_prompts()

    # ZIP 파일 생성
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # manifest.json (암호화)
        print("[1/6] manifest.json 암호화 중...")
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8')
        encrypted_manifest = encrypt_content(manifest_bytes)
        zf.writestr("manifest.json.enc", encrypted_manifest)

        # settings.json (암호화)
        print("[2/6] settings.json 암호화 중...")
        settings_bytes = json.dumps(settings, indent=2, ensure_ascii=False).encode('utf-8')
        encrypted_settings = encrypt_content(settings_bytes)
        zf.writestr("settings.json.enc", encrypted_settings)

        # topics.json (비암호화)
        print("[3/6] topics.json 저장 중...")
        topics_bytes = json.dumps(topics, indent=2, ensure_ascii=False).encode('utf-8')
        zf.writestr("topics.json", topics_bytes)

        # prompts/pd_system.txt (암호화)
        print("[4/6] prompts/pd_system.txt 암호화 중...")
        pd_bytes = pd_system.encode('utf-8')
        encrypted_pd = encrypt_content(pd_bytes)
        zf.writestr("prompts/pd_system.txt.enc", encrypted_pd)

        # prompts/writer_system.txt (암호화)
        print("[5/6] prompts/writer_system.txt 암호화 중...")
        writer_bytes = writer_system.encode('utf-8')
        encrypted_writer = encrypt_content(writer_bytes)
        zf.writestr("prompts/writer_system.txt.enc", encrypted_writer)

        # prompts/sd_prompts.json (암호화)
        print("[6/6] prompts/sd_prompts.json 암호화 중...")
        sd_bytes = json.dumps(sd_prompts, indent=2, ensure_ascii=False).encode('utf-8')
        encrypted_sd = encrypt_content(sd_bytes)
        zf.writestr("prompts/sd_prompts.json.enc", encrypted_sd)

    print("=" * 60)
    print(f"✅ 생성 완료: {output_path}")
    print(f"   파일 크기: {output_path.stat().st_size / 1024:.1f} KB")
    print("=" * 60)

    # 검증
    print("\n검증 중...")
    with zipfile.ZipFile(output_path, 'r') as zf:
        files = zf.namelist()
        print(f"포함된 파일: {files}")

        # visual_storytelling 확인
        if "settings.json.enc" in files:
            from cryptography.fernet import Fernet
            key = get_encryption_key()
            fernet = Fernet(key)
            decrypted = fernet.decrypt(zf.read("settings.json.enc"))
            loaded_settings = json.loads(decrypted.decode('utf-8'))
            vs = loaded_settings.get("visual_storytelling", {})
            print(f"\nVisual Storytelling 설정:")
            print(f"  - enabled: {vs.get('enabled', False)}")
            print(f"  - characters 수: {len(vs.get('characters', []))}")
            print(f"  - images_per_minute: {vs.get('images_per_minute', 0)}")
            print(f"  - vignette_intensity: {vs.get('visual_effects', {}).get('vignette_intensity', 0)}")
            print(f"  - color_filter: {vs.get('visual_effects', {}).get('color_filter', 'none')}")

    print("\n✅ 검증 완료! horror_v59.revpack 사용 가능")
    return output_path


if __name__ == "__main__":
    create_pack()
