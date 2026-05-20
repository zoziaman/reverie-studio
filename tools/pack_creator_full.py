# tools/pack_creator_full.py
# ============================================================
# ReveriePack 완전 자동 생성 시스템
# 챗봇 대화 → 설정 수집 → 프롬프트 생성 → .revpack 출력
# ============================================================
# v57.7.1: 암호화 기능 추가 (Fernet)
# v58.0.0: 완전 팩화 - tts, visual, hook_style, sd, thumbnail, video, scenario 필드 추가
# v58.2: deprecated 경고 숨기기
# v59.0.0: Visual Storytelling 설정 추가 - sd_model, characters, subtitle_style, visual_effects, transitions
# 실행: python tools/pack_creator_full.py
# ============================================================

# v58.2: 경고 필터 먼저 적용 (google.generativeai deprecated)
import os
os.environ["PYTHONWARNINGS"] = "ignore::FutureWarning"

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*support.*google.generativeai.*")

import sys
import json
import zipfile
import hashlib
import base64
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict

# 암호화 라이브러리
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QMessageBox,
    QProgressBar, QFileDialog, QGroupBox, QSplitter, QTabWidget,
    QPlainTextEdit, QSpinBox, QComboBox, QFormLayout, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor

import google.generativeai as genai
from dotenv import load_dotenv

# .env 로드
load_dotenv(PROJECT_ROOT / ".env")


# ============================================================
# 암호화 설정
# ============================================================

# v57.7.1: Reverie Pack 암호화 키 (고정 솔트 + 패스워드)
# 주의: 실제 배포 시에는 환경변수나 별도 설정 파일로 관리
PACK_ENCRYPTION_SALT = b'ReveriePack2024Salt!'
PACK_ENCRYPTION_PASSWORD = b'ReverieStudio_PackEncryption_v57'

# 암호화 대상 파일 (핵심 파일만 암호화)
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


def decrypt_content(encrypted: bytes) -> bytes:
    """콘텐츠 복호화 (로딩 시 사용)"""
    key = get_encryption_key()
    fernet = Fernet(key)
    return fernet.decrypt(encrypted)


# ============================================================
# 데이터 모델
# ============================================================

@dataclass
class PackSettings:
    """챗봇에서 수집된 설정"""
    pack_name: str = ""
    pack_id: str = ""
    genre: str = ""
    style: Dict = field(default_factory=dict)
    characters: Dict = field(default_factory=dict)
    content: Dict = field(default_factory=dict)
    restrictions: Dict = field(default_factory=dict)


@dataclass
class GeneratedPrompts:
    """Gemini가 생성한 프롬프트"""
    pd_system: str = ""
    writer_system: str = ""
    sd_positive: str = ""
    sd_negative: str = ""
    topic_templates: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    character_config: Dict = field(default_factory=dict)
    # v57.7.5: 감정 설정
    allowed_emotions: List[str] = field(default_factory=list)
    emotion_policy: Dict[str, int] = field(default_factory=dict)

    # === v60: 팩-클라이언트 아키텍처 — 모든 프롬프트를 팩에서 로딩 ===
    # 토픽 생성
    topic_generation: str = ""
    topic_enhanced: str = ""
    # 훅 생성
    hook_generation: str = ""
    hook_enhanced: str = ""
    # 메타데이터
    metadata_generation: str = ""
    thumbnail_style_guide: str = ""
    # 스토리 바이블
    story_bible: str = ""
    story_bible_improve: str = ""
    story_summarize: str = ""
    # 구조적 아웃라인
    structural_outline: str = ""
    # 글쓰기 규칙
    craft_rules: str = ""
    pacing_part1: str = ""
    pacing_part2: str = ""
    pacing_part3: str = ""
    # 이미지 생성
    image_style: str = ""
    image_llm_prompt: str = ""
    # SFX/분위기/비상
    sfx_config: Dict = field(default_factory=dict)
    atmosphere_config: Dict = field(default_factory=dict)
    emergency_sequence: List[List[str]] = field(default_factory=list)


# ============================================================
# v59.5.14: 장르별 기본값 매핑
# ============================================================

GENRE_DEFAULTS = {
    "horror": {
        "checkpoint": "dreamshaper_8.safetensors",
        "bgm_folder": "horror",
        "sfx_folder": "horror",
        "sfx_category": "horror",
        "sfx_intensity": "high",
        "hook_top_label": "【 괴 담 】",
        "hook_top_color": "#8B0000",
        "hook_main_color": "#FFFFFF",
        "hook_bg_color": [0, 0, 0],
        "thumbnail_text": "실화",
        "thumbnail_style": "공포/미스터리 느낌의 강렬한 제목. 예시: \"그날 밤 본 것\", \"문 뒤에서 들린 소리\". 짧고 임팩트 있게 (2~4어절). 의문/공포심 유발.",
        "default_emotion": "calm",
        "pause_duration": 0.4,
        "cfg_scale": 7.0,          # v59.5.15
        "steps": 20,               # v59.5.15
        "color_filter_type": "horror",  # v59.5.15: visual_effects.color_filter.type
    },
    "senior": {
        "checkpoint": "revAnimated_v2Rebirth.safetensors",
        "bgm_folder": "touching",
        "sfx_folder": "touching",
        "sfx_category": "emotional",
        "sfx_intensity": "medium",
        "hook_top_label": "【 사 연 】",
        "hook_top_color": "#D4A574",
        "hook_main_color": "#FFFFFF",
        "hook_bg_color": [10, 5, 0],
        "thumbnail_text": "실화",
        "thumbnail_style": "감성/가족 드라마 제목. 예시: \"어머니의 편지\", \"40년 만의 재회\". 감동+궁금증 유발.",
        "default_emotion": "calm",
        "pause_duration": 0.5,
        "cfg_scale": 6.0,          # v59.5.15
        "steps": 28,               # v59.5.15
        "color_filter_type": "drama",   # v59.5.15: "senior" 아님! "drama"가 올바른 값
    },
}

# ============================================================
# 시스템 프롬프트
# ============================================================

# v59.5.14: v59 구조에 맞춘 CHATBOT_SYSTEM_PROMPT
CHATBOT_SYSTEM_PROMPT = """너는 "레베리 팩 생성 도우미"야.
사용자(개발자)가 고객 요청을 전달하면, 대화를 통해 ReveriePack v59 생성에 필요한 정보를 수집해.

## 수집해야 할 정보

### 1. 기본 정보
- 팩 이름 (예: "해외 슬래셔 공포팩", "시니어 감동 채널", "가족사 막장드라마 채널")
- 장르 키 (horror / senior 중 선택)
  - horror: 공포/미스터리/스릴러
  - senior: 감동/로맨스/가족/막장/세대갈등

### 2. 스타일 세부사항
- 배경 설정 (한국/해외, 현대/과거/미래, 도시/시골/학교/직장 등)
- 분위기 키워드 (고어, 잔잔한, 긴장감, 달달한, 애절한, 코믹한 등)
- 수위 (1~10, 장르에 따라 공포수위/로맨스수위/막장수위 등)

### 3. 캐릭터 구성 (v59: 9종 음성 체계)
사용할 캐릭터 유형을 아래 9종 voice_type 중에서 선택:
  1. narrator - 나레이터 (narrator_male 또는 narrator_female 선택 필수)
  2. man - 청년 남성 (20-30대)
  3. woman - 청년 여성 (20-30대)
  4. middle_man - 중년 남성 (40-50대)
  5. middle_woman - 중년 여성 (40-50대)
  6. grandpa - 할아버지 (70대+)
  7. grandma - 할머니 (70대+)
  (young_man = man의 별칭, young_woman = woman의 별칭)

- 나레이터 성별 선택: narrator_male (차분한 남성) / narrator_female (따뜻한 여성)
- 특별 캐릭터 (예: ghost, antagonist, protagonist 등)

### 4. 콘텐츠 설정
- 예상 영상 길이 (3분, 5분, 10분)
- 턴 수 범위 (50~80, 80~120 등)

### 5. 아트 스타일 & 비주얼 (v59 필수!)
- 이미지 화풍 (아래 예시 참고):
  - 흑백 만화 (monochrome manga) — 공포에 적합
  - 수채화 (watercolor illustration) — 감동에 적합
  - 웹툰 (webtoon illustration) — 막장에 적합
  - 유화 (oil painting illustration) — 가족사에 적합
  - 기타 (사용자 요청에 따라)
- SD checkpoint 모델 (모르면 장르 기본값 사용):
  - horror → dreamshaper_8.safetensors
  - senior → revAnimated_v2Rebirth.safetensors
- LoRA 모델 사용 여부 (있으면 이름, weight, trigger word)

### 6. 특별 요청
- 금지 요소 (욕설, 폭력 묘사, 성인 콘텐츠 등)
- 필수 포함 요소 (반전, 해피엔딩, 새드엔딩, 열린결말 등)

### 7. BGM/SFX 폴더 선택
- BGM 폴더: "horror" / "makjang" / "touching" 중 선택
- SFX 폴더: "horror" / "makjang" / "touching" 중 선택

## 대화 규칙

1. 한 번에 1~2개 질문만 해. 너무 많이 물어보면 피곤해.
2. 선택지를 줄 때는 번호로 쉽게 선택할 수 있게 해.
3. 사용자가 애매하게 답하면 구체적으로 다시 물어봐.
4. 충분한 정보가 모이면 설정을 요약해서 확인받아.
5. 확정되면 JSON 형식으로 최종 설정을 출력해.

## 출력 JSON 형식 (확정 시)

마지막에 반드시 아래 형식의 JSON을 ```json 코드블록으로 출력해:

```json
{
  "pack_name": "팩 이름",
  "genre": "horror 또는 senior",
  "style": {
    "setting": "배경 설명",
    "mood": ["분위기", "키워드", "목록"],
    "intensity": 7
  },
  "characters": {
    "types": ["사용할 voice_type 목록"],
    "count": "2~3",
    "special": "특별 요청사항",
    "narrator_gender": "narrator_male 또는 narrator_female"
  },
  "content": {
    "duration_minutes": 5,
    "min_turns": 80,
    "max_turns": 120,
    "image_style": "이미지 화풍 설명"
  },
  "restrictions": {
    "forbidden": ["금지 요소"],
    "required": ["필수 요소"]
  },
  "art_style": {
    "prefix": "아트 스타일 SD prefix (영어, 쉼표로 끝남)",
    "description": "아트 스타일 설명 (한국어)",
    "texture_keywords": "텍스처 키워드 (영어)",
    "forbidden_styles": "금지 스타일 (영어)"
  },
  "sd_model": {
    "checkpoint": "체크포인트 파일명",
    "lora_models": []
  },
  "bgm_folder": "horror/makjang/touching",
  "sfx_folder": "horror/makjang/touching"
}
```

## 시작

"안녕하세요! 레베리 팩 생성 도우미입니다 (v59). 어떤 콘텐츠 팩을 만들어 드릴까요?"
"""


# v59.5.14: 2단계 Gemini 호출 — 1단계: 코어 프롬프트 (항목 1~8)
PROMPT_GENERATOR_TEMPLATE = """당신은 YouTube {content_type} 콘텐츠 전문 프로듀서입니다.
아래 설정을 바탕으로 실제 영상 제작에 사용할 프롬프트들을 생성해주세요.

## 입력 설정

{settings_json}

## 생성해야 할 항목

### 1. PD 시스템 프롬프트 (pd_system)
- 영상 기획자 역할
- 이 장르/스타일에 맞는 스토리 구조 지시 (5막 구성)
- 분위기, 전개 방식, 반전 포인트 가이드
- 캐릭터 배치 전략 (3세대 가족물이면 세대별 역할)
- 금지사항 명시
- 500~800자

### 2. 작가 시스템 프롬프트 (writer_system)
- 대사 작성자 역할
- 문장 스타일, 말투, 감정 표현 방식
- 캐릭터별 말투 차이 (세대별 말투 필수):
  - grandma: 사투리, 한 맺힌 또는 따뜻한 말투
  - grandpa: 가부장적 또는 회고하는 말투
  - middle_man: 책임감, 갈등하는 말투
  - middle_woman: 현실적, 억울함 또는 강인한 말투
  - man/woman: 존댓말, 당황 또는 반항 말투
  - narrator: 차분하지만 긴장감/따뜻함 있는 톤
- SFX 태그 사용법: [SFX:door], [SFX:impact], [SFX:whoosh] 등
- 감정 태그: 반드시 아래 목록에서만 선택 (동의어 금지!):
  [calm], [scared], [angry], [sad], [happy], [whisper], [desperate], [worried], [excited]
  ★ [fear], [shock], [terrified] 등 동의어 절대 사용 금지! TTS 인식 불가
- 감정 분포 가이드 포함 (예: "[angry] 전체 대사의 30%, [sad] 30%, [calm] 20%")
- 500~800자

### 3. SD 긍정 프롬프트 (sd_positive)
- Stable Diffusion 이미지 생성용 기본 프롬프트
- 반드시 "masterpiece, best quality"로 시작
- 그 뒤에 장르/분위기/화풍 키워드 추가
- SD 가중치 문법 사용: (keyword:1.2) 형태로 핵심 분위기 강조
- 예시(공포): "masterpiece, best quality, dark atmosphere, horror, (dramatic lighting:1.2), eerie, cinematic"
- 예시(감동): "masterpiece, best quality, dramatic atmosphere, emotional, (oil painting style:1.2), warm lighting"
- 영어로 작성, 쉼표로 구분

### 4. SD 부정 프롬프트 (sd_negative)
- 반드시 포함: nsfw, nude, naked, revealing clothes
- 반드시 포함 (해부학 품질): deformed, bad anatomy, extra limbs, bad hands, mutation, extra fingers, poorly drawn hands
- 반드시 포함 (일반 품질): text, watermark, blurry, low quality, worst quality
- 장르에 따른 추가 부정 키워드 포함
- 영어로 작성

### 5. 토픽 템플릿 (topic_templates)
- 이 팩으로 만들 수 있는 예시 주제 5~10개
- 구체적이고 흥미로운 한국어 제목
- 클릭을 유도하는 스타일

### 6. 태그 (tags)
- YouTube 검색용 태그 5~10개
- 한국어로 작성

### 7. 캐릭터 설정 (character_config)
- 역할별 TTS 음성 타입 매핑 (한글 이름 + 영어 이름 모두 필수)
- v59 9종 voice_type: narrator, man, woman, middle_man, middle_woman, grandpa, grandma
  (young_man = man 별칭, young_woman = woman 별칭)
- narrator 값은 반드시 "narrator_male" 또는 "narrator_female" 사용
- 기본 한글 매핑 반드시 포함:
  "나레이션": "narrator_male/female", "할아버지": "grandpa", "할머니": "grandma",
  "아버지": "middle_man", "어머니": "middle_woman", "아빠": "middle_man", "엄마": "middle_woman",
  "남자": "man", "여자": "woman", "아들": "man", "딸": "woman",
  "아저씨": "middle_man", "아줌마": "middle_woman"
- 장르별 추가 매핑 (예: 가족물이면 "며느리": "middle_woman", "시어머니": "grandma" 등)

### 8. 감정 설정 (allowed_emotions, emotion_weights)
- TTS 감정 연기에 사용할 감정 목록
- 가능한 감정: scared, angry, sad, happy, calm, excited, whisper, worried, desperate
- 장르에 맞는 감정만 선택 (공포: scared 필수, 감동: sad/happy 필수, 막장: angry/desperate 필수)
- emotion_weights: 대본에서 감정의 상대적 빈도 가중치 (예: {{"scared": 3, "calm": 5}})

## 출력 형식

반드시 아래 JSON 형식으로만 출력하세요. 다른 텍스트 없이 JSON만!

```json
{{
  "pd_system": "PD 시스템 프롬프트 전문... (500~800자)",
  "writer_system": "작가 시스템 프롬프트 전문... (500~800자)",
  "sd_positive": "masterpiece, best quality, ...",
  "sd_negative": "(worst quality:1.4), ...",
  "topic_templates": ["주제1", "주제2", "...최소 5개"],
  "tags": ["태그1", "태그2", "...최소 5개"],
  "character_config": {{
    "narrator": "narrator_male",
    "나레이션": "narrator_male",
    "내레이션": "narrator_male",
    "할아버지": "grandpa",
    "할머니": "grandma",
    "아버지": "middle_man",
    "어머니": "middle_woman",
    "아빠": "middle_man",
    "엄마": "middle_woman",
    "남자": "man",
    "여자": "woman",
    "아들": "man",
    "딸": "woman",
    "아저씨": "middle_man",
    "아줌마": "middle_woman",
    "grandpa": "grandpa",
    "grandma": "grandma",
    "man": "man",
    "woman": "woman",
    "young_man": "man",
    "young_woman": "woman",
    "middle_man": "middle_man",
    "middle_woman": "middle_woman"
  }},
  "allowed_emotions": ["scared", "angry", "sad", "happy", "calm", "whisper"],
  "emotion_weights": {{"scared": 3, "calm": 5}}
}}
```
"""

# v59.5.14: 2단계 Gemini 호출 — 2단계: 비주얼/시나리오 (항목 9~15)
PROMPT_GENERATOR_TEMPLATE_PHASE2 = """당신은 YouTube 영상 비주얼 디렉터입니다.
1단계에서 생성된 코어 프롬프트를 기반으로 비주얼/시나리오 데이터를 생성하세요.

## 입력 설정

{settings_json}

## 1단계 결과 (참고용)

- SD 긍정 프롬프트: {sd_positive}
- 아트 스타일: {art_style_info}
- 캐릭터 구성: {character_types}
- 나레이터 성별: {narrator_gender}

## 생성해야 할 항목

### 9. 비주얼 캐릭터 정의 (visual_characters)
- 각 voice_type별로 Stable Diffusion 프롬프트 생성
- 반드시 포함할 voice_type: {required_voice_types}
- 각 캐릭터마다 2개 필드:
  - "base": 캐릭터 외형 설명 (영어, 아트 스타일 반영, "fully clothed" 필수 포함)
  - "style": 렌더링 스타일 (영어, 아트 스타일 일관성)
- "_default" 캐릭터도 반드시 포함 (매핑 안 되는 캐릭터용 폴백)
- 노인 캐릭터(grandpa/grandma)는 (elderly:1.4), (wrinkled face:1.3), (aged skin:1.2) 가중치 필수

### 10. 씬 분석기 설정 (scene_analyzer)
- art_style_prefix: 모든 이미지에 붙는 스타일 접두어 (영어, 쉼표로 끝남)
- art_style_description: 아트 스타일 설명 (한국어, "같은 만화가의 ~~" 형식)
- texture_keywords: 텍스처 키워드 (영어, 쉼표 구분)
- forbidden_styles: 반드시 포함: "photograph, 3d render, photorealistic" + 선택한 화풍과 충돌하는 스타일
  (흑백만화면: colorful, oil painting, watercolor 추가 / 유화면: manga, monochrome, anime 추가)
- good_examples: 4개 프롬프트 (영어):
  - 반드시 art_style_prefix로 시작
  - 구체적인 장면 묘사: 캐릭터, 장소, 분위기, 카메라앵글 포함
  - 카메라앵글 중 하나 필수: "close-up", "bust shot", "medium shot", "wide shot"

### 11. 시나리오 풀 (scenario_pools)
- tone_pool: 이야기 톤 5~7개 (한국어, "~~ 중심 (설명)" 형식)
  예시: "비밀 폭로 중심 (숨겨진 문서가 발견되며 모든 것이 뒤집히는 구조)"
  ★ 괄호 안에 서사 메커니즘 필수 설명!
- twist_pool: 반전 장치 5~7개 (한국어)
- relationship_pool: 캐릭터 관계 유형 5~7개 (한국어, "A-B" 형식)
- place_pool: 배경 장소 5~7개 (한국어)

### 12. 썸네일 배경 (thumbnail_backgrounds)
- 20~30개의 SD 프롬프트 (영어)
- 아트 스타일과 일관된 배경 이미지
- 모든 프롬프트에 "no people" 필수 포함
- 구성 비율: 환경/장소(60-70%), 클로즈업/소품(20-30%), 분위기/추상(10%)
  예시: "close-up: old key on dusty floor, long shadow, no people"
- 장르 분위기 반영 (공포: 어둡고 으스스, 감동: 따뜻하고 서정적)

### 13. 안전 폴백 (safe_fallbacks)
- 캐릭터가 잘 생성되지 않을 때 사용하는 안전한 배경 이미지 8개 (영어)
- 모든 프롬프트에 "no people" 필수 포함
- 아트 스타일 키워드를 각 프롬프트에 포함 (예: "manga style" 또는 "oil painting style")
- safe_fallback_prompt: 대표 폴백 프롬프트 1개 (영어)

### 14. 인트로 스크립트 (intro_scripts)
- 영상 시작 시 나레이터가 읽는 인트로 멘트 2~3개 (한국어)
- 장르 분위기에 맞는 도입부

### 15. 화자 색상 (speaker_colors)
- 자막에 표시될 화자별 색상 (hex 코드)
- narrator/나레이션: 회색 계열 (#CCCCCC)
- 의미적 색상 선택:
  - 노인 캐릭터: 따뜻한 흙 톤 (#D4A574, #8B7355)
  - 악역/귀신: 붉은 톤 (#FF4444, #CC3333)
  - 청년 캐릭터: 밝은 톤 (#FFFFFF, #88CCFF)
  - 중년 캐릭터: 차분한 톤 (#C8B099, #A0A0A0)
- 한글 이름과 영어 이름 모두 매핑

## 출력 형식

반드시 아래 JSON 형식으로만 출력하세요. 다른 텍스트 없이 JSON만!

```json
{{
  "visual_characters": {{
    "narrator": {{
      "base": "아트스타일 narrator 외형 설명..., fully clothed",
      "style": "렌더링 스타일..."
    }},
    "man": {{ "base": "..., fully clothed", "style": "..." }},
    "woman": {{ "base": "..., fully clothed", "style": "..." }},
    "middle_man": {{ "base": "..., fully clothed", "style": "..." }},
    "middle_woman": {{ "base": "..., fully clothed", "style": "..." }},
    "grandpa": {{ "base": "(elderly grandfather:1.4), ..., fully clothed", "style": "..." }},
    "grandma": {{ "base": "(elderly grandmother:1.4), ..., fully clothed", "style": "..." }},
    "_default": {{ "base": "..., fully clothed", "style": "..." }}
  }},
  "scene_analyzer": {{
    "art_style_prefix": "스타일 접두어, 쉼표로 끝남,",
    "art_style_description": "같은 만화가의 ~~",
    "texture_keywords": "keyword1, keyword2, ...",
    "forbidden_styles": "photograph, 3d render, photorealistic, ...",
    "good_examples": [
      "art_style_prefix + 예시1",
      "art_style_prefix + 예시2",
      "art_style_prefix + 예시3",
      "art_style_prefix + 예시4"
    ]
  }},
  "scenario_pools": {{
    "tone_pool": ["톤1", "톤2", "..."],
    "twist_pool": ["반전1", "반전2", "..."],
    "relationship_pool": ["A-B", "C-D", "..."],
    "place_pool": ["장소1", "장소2", "..."]
  }},
  "thumbnail_backgrounds": [
    "background prompt 1, no people",
    "background prompt 2, no people",
    "...20~30개"
  ],
  "safe_fallbacks": [
    "fallback prompt 1, no people",
    "...8개"
  ],
  "safe_fallback_prompt": "대표 폴백 프롬프트, no people",
  "intro_scripts": [
    "한국어 인트로 멘트 1",
    "한국어 인트로 멘트 2"
  ],
  "speaker_colors": {{
    "나레이션": "#CCCCCC",
    "narrator": "#CCCCCC",
    "주인공": "#FFFFFF",
    "...기타 캐릭터": "#색상코드"
  }}
}}
```
"""


# ============================================================
# Gemini 워커
# ============================================================

class GeminiWorker(QThread):
    """비동기 Gemini API 호출"""
    response_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, model, chat, message: str):
        super().__init__()
        self.model = model
        self.chat = chat
        self.message = message
        self.use_chat = chat is not None

    def run(self):
        try:
            if self.use_chat:
                response = self.chat.send_message(self.message)
            else:
                response = self.model.generate_content(self.message)
            self.response_ready.emit(response.text)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ============================================================
# 메인 윈도우
# ============================================================

class PackCreatorWindow(QMainWindow):
    """ReveriePack 완전 자동 생성 GUI"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ReveriePack Creator - 완전 자동 생성")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # API 설정
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            QMessageBox.critical(self, "오류", "GEMINI_API_KEY가 설정되지 않았습니다.")
            sys.exit(1)

        genai.configure(api_key=self.api_key)

        # 챗봇 모델 (대화용)
        self.chat_model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=CHATBOT_SYSTEM_PROMPT
        )
        self.chat = self.chat_model.start_chat(history=[])

        # 프롬프트 생성 모델 (단발성)
        self.prompt_model = genai.GenerativeModel(model_name="gemini-2.0-flash")

        # 상태
        self.collected_settings: Optional[Dict] = None
        self.generated_prompts: Optional[Dict] = None
        self.worker: Optional[GeminiWorker] = None

        self._setup_ui()
        self._start_conversation()

    def _setup_ui(self):
        """UI 구성"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 좌측: 챗봇
        left_panel = self._create_chat_panel()
        main_layout.addWidget(left_panel, stretch=1)

        # 우측: 결과 & 생성
        right_panel = self._create_result_panel()
        main_layout.addWidget(right_panel, stretch=1)

    def _create_chat_panel(self) -> QWidget:
        """챗봇 패널"""
        panel = QGroupBox("1단계: 설정 수집 (챗봇 대화)")
        layout = QVBoxLayout(panel)

        # 채팅 영역
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("맑은 고딕", 10))
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #333;
                border-radius: 5px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.chat_display, stretch=1)

        # 입력 영역
        input_layout = QHBoxLayout()

        self.input_field = QLineEdit()
        self.input_field.setFont(QFont("맑은 고딕", 11))
        self.input_field.setPlaceholderText("메시지를 입력하세요...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 2px solid #4CAF50;
                border-radius: 5px;
                padding: 8px;
                background-color: #2d2d2d;
                color: white;
            }
        """)
        self.input_field.returnPressed.connect(self._send_message)
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("전송")
        self.send_btn.setFont(QFont("맑은 고딕", 10, QFont.Bold))
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #666; }
        """)
        self.send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self.send_btn)

        layout.addLayout(input_layout)

        # 버튼
        btn_layout = QHBoxLayout()

        self.reset_btn = QPushButton("대화 초기화")
        self.reset_btn.clicked.connect(self._reset_conversation)
        btn_layout.addWidget(self.reset_btn)

        btn_layout.addStretch()

        layout.addLayout(btn_layout)

        return panel

    def _create_result_panel(self) -> QWidget:
        """결과 패널"""
        panel = QGroupBox("2단계: 프롬프트 생성 & 팩 출력")
        layout = QVBoxLayout(panel)

        # 탭 위젯
        tabs = QTabWidget()

        # 탭 1: 수집된 설정
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        self.settings_display = QPlainTextEdit()
        self.settings_display.setReadOnly(True)
        self.settings_display.setFont(QFont("Consolas", 9))
        self.settings_display.setStyleSheet("background-color: #1e1e1e; color: #9cdcfe;")
        settings_layout.addWidget(self.settings_display)
        tabs.addTab(settings_tab, "수집된 설정")

        # 탭 2: 생성된 프롬프트
        prompts_tab = QWidget()
        prompts_layout = QVBoxLayout(prompts_tab)
        self.prompts_display = QPlainTextEdit()
        self.prompts_display.setReadOnly(True)
        self.prompts_display.setFont(QFont("Consolas", 9))
        self.prompts_display.setStyleSheet("background-color: #1e1e1e; color: #ce9178;")
        prompts_layout.addWidget(self.prompts_display)
        tabs.addTab(prompts_tab, "생성된 프롬프트")

        # 탭 3: 추가 설정
        extra_tab = QWidget()
        extra_layout = QFormLayout(extra_tab)

        self.author_input = QLineEdit("Reverie Studio")
        extra_layout.addRow("제작자:", self.author_input)

        self.version_input = QLineEdit("1.0.0")
        extra_layout.addRow("버전:", self.version_input)

        self.encrypt_check = QCheckBox()
        self.encrypt_check.setChecked(True)
        extra_layout.addRow("암호화:", self.encrypt_check)

        # v59.5.14: studio_version은 JSON 팩에서 사용하지 않음 (레거시 .revpack용)
        self.studio_version = QLineEdit("1")
        extra_layout.addRow("Studio 버전:", self.studio_version)

        tabs.addTab(extra_tab, "추가 설정")

        layout.addWidget(tabs, stretch=1)

        # 진행 상태
        self.status_label = QLabel("대기 중...")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 생성 버튼
        btn_layout = QHBoxLayout()

        self.generate_prompts_btn = QPushButton("프롬프트 자동 생성")
        self.generate_prompts_btn.setEnabled(False)
        self.generate_prompts_btn.setFont(QFont("맑은 고딕", 11, QFont.Bold))
        self.generate_prompts_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 12px;
            }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #666; }
        """)
        self.generate_prompts_btn.clicked.connect(self._generate_prompts)
        btn_layout.addWidget(self.generate_prompts_btn)

        # v59.5.14: JSON 팩 생성 (기본)
        self.create_pack_btn = QPushButton("JSON 팩 생성")
        self.create_pack_btn.setEnabled(False)
        self.create_pack_btn.setFont(QFont("맑은 고딕", 11, QFont.Bold))
        self.create_pack_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 12px;
            }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:disabled { background-color: #666; }
        """)
        self.create_pack_btn.clicked.connect(self._create_json_pack)
        btn_layout.addWidget(self.create_pack_btn)

        # .revpack 생성 (레거시 호환)
        self.create_revpack_btn = QPushButton(".revpack")
        self.create_revpack_btn.setEnabled(False)
        self.create_revpack_btn.setFont(QFont("맑은 고딕", 9))
        self.create_revpack_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #F57C00; }
            QPushButton:disabled { background-color: #666; }
        """)
        self.create_revpack_btn.clicked.connect(self._create_revpack)
        btn_layout.addWidget(self.create_revpack_btn)

        layout.addLayout(btn_layout)

        return panel

    # ============================================================
    # 채팅 기능
    # ============================================================

    def _append_message(self, sender: str, message: str, is_bot: bool = False):
        """채팅 메시지 추가"""
        color = "#64b5f6" if is_bot else "#81c784"
        prefix = "🤖" if is_bot else "👤"

        html = f'<p style="color: {color}; margin: 5px 0;"><b>{prefix} {sender}:</b></p>'
        html += f'<p style="color: #e0e0e0; margin: 0 0 15px 20px; white-space: pre-wrap;">{message}</p>'

        self.chat_display.append(html)
        self.chat_display.moveCursor(QTextCursor.End)

    def _start_conversation(self):
        """대화 시작"""
        self._set_input_enabled(False)
        self.status_label.setText("챗봇 시작 중...")

        self.worker = GeminiWorker(self.chat_model, self.chat, "시작해줘")
        self.worker.response_ready.connect(self._on_chat_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _send_message(self):
        """메시지 전송"""
        message = self.input_field.text().strip()
        if not message:
            return

        self._append_message("나", message, is_bot=False)
        self.input_field.clear()
        self._set_input_enabled(False)
        self.status_label.setText("응답 대기 중...")

        self.worker = GeminiWorker(self.chat_model, self.chat, message)
        self.worker.response_ready.connect(self._on_chat_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_chat_response(self, response: str):
        """챗봇 응답 처리"""
        self._append_message("도우미", response, is_bot=True)
        self._set_input_enabled(True)
        self.input_field.setFocus()
        self.status_label.setText("대화 중...")

        # JSON 설정 추출
        if "```json" in response:
            self._extract_settings(response)

    def _on_error(self, error: str):
        """에러 처리"""
        self._append_message("시스템", f"오류: {error}", is_bot=True)
        self._set_input_enabled(True)
        self.status_label.setText(f"오류: {error}")

    def _set_input_enabled(self, enabled: bool):
        """입력 활성화/비활성화"""
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.send_btn.setText("전송" if enabled else "응답 중...")

    def _extract_settings(self, response: str):
        """응답에서 JSON 설정 추출"""
        try:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if start > 6 and end > start:
                json_str = response[start:end].strip()
                self.collected_settings = json.loads(json_str)

                # 팩 ID 생성
                self.collected_settings["pack_id"] = hashlib.md5(
                    self.collected_settings.get("pack_name", "pack").encode()
                ).hexdigest()[:8]

                # UI 업데이트
                self.settings_display.setPlainText(
                    json.dumps(self.collected_settings, indent=2, ensure_ascii=False)
                )
                self.generate_prompts_btn.setEnabled(True)
                self.progress_bar.setValue(33)
                self.status_label.setText("설정 수집 완료! '프롬프트 자동 생성' 버튼을 클릭하세요.")

                QMessageBox.information(self, "설정 수집 완료",
                    "팩 설정이 수집되었습니다!\n'프롬프트 자동 생성' 버튼을 클릭하세요.")

        except json.JSONDecodeError as e:
            print(f"JSON 파싱 실패: {e}")

    def _reset_conversation(self):
        """대화 초기화"""
        reply = QMessageBox.question(self, "대화 초기화",
            "대화를 초기화하시겠습니까?")

        if reply == QMessageBox.Yes:
            self.chat = self.chat_model.start_chat(history=[])
            self.collected_settings = None
            self.generated_prompts = None
            self.chat_display.clear()
            self.settings_display.clear()
            self.prompts_display.clear()
            self.generate_prompts_btn.setEnabled(False)
            self.create_pack_btn.setEnabled(False)
            self.create_revpack_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self._start_conversation()

    # ============================================================
    # 프롬프트 생성 (v59.5.14: 2단계 순차 호출)
    # ============================================================

    def _extract_json_from_response(self, response: str) -> Optional[dict]:
        """Gemini 응답에서 JSON 추출 (공통 유틸)"""
        try:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if start > 6 and end > start:
                json_str = response[start:end].strip()
                return json.loads(json_str)
            else:
                # 코드블록 없으면 전체가 JSON일 수도
                return json.loads(response)
        except json.JSONDecodeError:
            return None

    def _generate_prompts(self):
        """Gemini로 프롬프트 자동 생성 — 1단계: 코어 프롬프트"""
        if not self.collected_settings:
            QMessageBox.warning(self, "오류", "먼저 설정을 수집해주세요.")
            return

        self.generate_prompts_btn.setEnabled(False)
        self._phase1_prompts = None  # 1단계 결과 초기화
        self.status_label.setText("1단계: 코어 프롬프트 생성 중... (10~20초)")
        self.progress_bar.setValue(40)

        # 프롬프트 생성 요청
        settings_json = json.dumps(self.collected_settings, indent=2, ensure_ascii=False)

        # v57.7.5: duration_minutes에 따라 숏폼/롱폼 구분
        duration = self.collected_settings.get("content", {}).get("duration_minutes", 5)
        content_type = "숏폼" if duration <= 5 else "롱폼"

        prompt = PROMPT_GENERATOR_TEMPLATE.format(
            content_type=content_type,
            settings_json=settings_json
        )

        self.worker = GeminiWorker(self.prompt_model, None, prompt)
        self.worker.response_ready.connect(self._on_phase1_generated)
        self.worker.error_occurred.connect(self._on_prompt_error)
        self.worker.start()

    def _on_phase1_generated(self, response: str):
        """1단계 코어 프롬프트 생성 완료 → 2단계 자동 시작"""
        parsed = self._extract_json_from_response(response)
        if not parsed:
            self.status_label.setText("1단계 JSON 파싱 실패")
            self.prompts_display.setPlainText(response)
            self.generate_prompts_btn.setEnabled(True)
            QMessageBox.warning(self, "파싱 오류",
                "1단계 프롬프트 JSON 파싱 실패.\n원본 응답을 확인하고 다시 시도하세요.")
            return

        self._phase1_prompts = parsed

        # UI에 1단계 결과 표시
        self.prompts_display.setPlainText(
            "=== 1단계 (코어 프롬프트) 완료 ===\n\n" +
            json.dumps(parsed, indent=2, ensure_ascii=False)
        )
        self.progress_bar.setValue(55)
        self.status_label.setText("2단계: 비주얼/시나리오 생성 중... (10~20초)")

        # 2단계 호출 준비 — 1단계 결과를 컨텍스트로 전달
        settings_json = json.dumps(self.collected_settings, indent=2, ensure_ascii=False)

        # 1단계에서 추출한 컨텍스트
        sd_positive = parsed.get("sd_positive", "masterpiece, best quality")
        character_config = parsed.get("character_config", {})
        character_types = [k for k in character_config.values()
                          if k not in ("narrator_male", "narrator_female")]
        character_types = list(set(character_types))

        # 아트 스타일 정보 (chatbot에서 수집된 것)
        art_style = self.collected_settings.get("art_style", {})
        art_style_info = (
            f"prefix: {art_style.get('prefix', 'N/A')}, "
            f"description: {art_style.get('description', 'N/A')}"
        )

        narrator_gender = self.collected_settings.get("characters", {}).get(
            "narrator_gender", "narrator_male"
        )

        # 실제 사용될 voice_type 결정
        used_types = self.collected_settings.get("characters", {}).get("types", [])
        if not used_types:
            used_types = character_types if character_types else [
                "narrator", "man", "woman", "middle_man", "middle_woman",
                "grandpa", "grandma"
            ]
        required_voice_types = ", ".join(used_types)

        prompt_phase2 = PROMPT_GENERATOR_TEMPLATE_PHASE2.format(
            settings_json=settings_json,
            sd_positive=sd_positive,
            art_style_info=art_style_info,
            character_types=json.dumps(character_config, ensure_ascii=False),
            narrator_gender=narrator_gender,
            required_voice_types=required_voice_types,
        )

        self.worker = GeminiWorker(self.prompt_model, None, prompt_phase2)
        self.worker.response_ready.connect(self._on_phase2_generated)
        self.worker.error_occurred.connect(self._on_prompt_error)
        self.worker.start()

    def _on_phase2_generated(self, response: str):
        """2단계 비주얼/시나리오 생성 완료 → 최종 병합"""
        parsed = self._extract_json_from_response(response)
        if not parsed:
            self.status_label.setText("2단계 JSON 파싱 실패")
            self.prompts_display.appendPlainText(
                "\n\n=== 2단계 (비주얼/시나리오) 실패 ===\n\n" + response
            )
            self.generate_prompts_btn.setEnabled(True)
            QMessageBox.warning(self, "파싱 오류",
                "2단계 비주얼/시나리오 JSON 파싱 실패.\n1단계 결과는 유지됩니다.\n원본 응답을 확인하고 다시 시도하세요.")
            # 1단계만으로도 팩 생성 가능하게 (visual 없이)
            self.generated_prompts = self._phase1_prompts
            self.create_pack_btn.setEnabled(True)
            self.create_revpack_btn.setEnabled(True)
            return

        # 1단계 + 2단계 병합
        self.generated_prompts = {**self._phase1_prompts, **parsed}

        # UI 업데이트
        self.prompts_display.setPlainText(
            json.dumps(self.generated_prompts, indent=2, ensure_ascii=False)
        )
        self.create_pack_btn.setEnabled(True)
        self.create_revpack_btn.setEnabled(True)
        self.progress_bar.setValue(66)
        self.status_label.setText("프롬프트 생성 완료! (1단계+2단계 병합) 팩 생성 버튼을 클릭하세요.")

        QMessageBox.information(self, "프롬프트 생성 완료",
            f"프롬프트가 생성되었습니다! (총 {len(self.generated_prompts)}개 필드)\n"
            "내용을 확인하고 팩 생성 버튼을 클릭하세요.")

        self.generate_prompts_btn.setEnabled(True)

    def _on_prompt_error(self, error: str):
        """프롬프트 생성 오류"""
        self.status_label.setText(f"오류: {error}")
        self.generate_prompts_btn.setEnabled(True)
        QMessageBox.critical(self, "오류", f"프롬프트 생성 실패:\n{error}")

    # ============================================================
    # v59.5.14: JSON 팩 생성 (기본 출력 형식)
    # ============================================================

    def _create_json_pack(self):
        """v59.5.14: 단일 JSON 파일로 팩 저장 (assets/packs/ 기본 경로)"""
        if not self.collected_settings or not self.generated_prompts:
            QMessageBox.warning(self, "오류", "설정과 프롬프트가 모두 필요합니다.")
            return

        # 팩 ID로 파일명 생성
        pack_id = self.collected_settings.get("pack_id", "new_pack")
        pack_name = self.collected_settings.get("pack_name", "new_pack")
        default_name = pack_name.replace(" ", "_").lower()

        # 저장 경로 선택 (기본: assets/packs/)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "JSON 팩 저장",
            str(PROJECT_ROOT / "assets" / "packs" / f"{default_name}.json"),
            "JSON Pack (*.json)"
        )

        if not file_path:
            return

        self.status_label.setText("JSON 팩 생성 중...")
        self.progress_bar.setValue(80)

        try:
            # 패키지 데이터 조립
            pack_data = self._assemble_pack_data()

            # JSON 저장
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(pack_data, f, indent=2, ensure_ascii=False)

            self.progress_bar.setValue(100)
            self.status_label.setText(f"완료! {Path(file_path).name}")

            QMessageBox.information(self, "JSON 팩 생성 완료",
                f"JSON 팩이 생성되었습니다!\n\n{file_path}\n\n"
                f"이 파일을 assets/packs/에 넣으면 Studio에서 바로 사용 가능합니다.")

        except Exception as e:
            self.status_label.setText(f"오류: {e}")
            QMessageBox.critical(self, "오류", f"JSON 팩 생성 실패:\n{e}")

    # ============================================================
    # .revpack 생성 (레거시 호환)
    # ============================================================

    def _create_revpack(self):
        """최종 .revpack 파일 생성"""
        if not self.collected_settings or not self.generated_prompts:
            QMessageBox.warning(self, "오류", "설정과 프롬프트가 모두 필요합니다.")
            return

        # 저장 경로 선택
        default_name = self.collected_settings.get("pack_name", "new_pack").replace(" ", "_")
        file_path, _ = QFileDialog.getSaveFileName(
            self, ".revpack 저장",
            str(PROJECT_ROOT / "data" / "exports" / f"{default_name}.revpack"),
            "ReveriePack (*.revpack)"
        )

        if not file_path:
            return

        self.status_label.setText(".revpack 생성 중...")
        self.progress_bar.setValue(80)

        try:
            # 패키지 데이터 조립
            pack_data = self._assemble_pack_data()

            # 임시 폴더 생성
            temp_dir = Path(file_path).parent / f"_temp_{pack_data['pack_id']}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                # 파일들 저장
                self._write_pack_files(temp_dir, pack_data)

                # ZIP으로 압축
                with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for file_path_item in temp_dir.rglob('*'):
                        if file_path_item.is_file():
                            arcname = file_path_item.relative_to(temp_dir)
                            zf.write(file_path_item, arcname)

                self.progress_bar.setValue(100)
                self.status_label.setText(f"완료! {Path(file_path).name}")

                QMessageBox.information(self, "생성 완료",
                    f".revpack 파일이 생성되었습니다!\n\n{file_path}")

            finally:
                # 임시 폴더 삭제
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            self.status_label.setText(f"오류: {e}")
            QMessageBox.critical(self, "오류", f".revpack 생성 실패:\n{e}")

    def _build_character_mapping(self, character_config: Dict, narrator_gender: str) -> Dict:
        """v59.5.14: 기본 한국어-영어 alias 테이블 + Gemini 생성 매핑 병합"""
        # 기본 매핑 테이블 (모든 팩에 공통)
        base_mapping = {
            # 나레이터
            "narrator": narrator_gender,
            "나레이션": narrator_gender,
            "내레이션": narrator_gender,
            # 노인
            "할아버지": "grandpa",
            "할머니": "grandma",
            "할배": "grandpa",
            "할매": "grandma",
            # 청년
            "남자": "man",
            "여자": "woman",
            "청년": "man",
            "오빠": "man",
            "형": "man",
            "남동생": "man",
            "언니": "woman",
            "누나": "woman",
            "여동생": "woman",
            # 중년
            "아저씨": "middle_man",
            "아줌마": "middle_woman",
            "아버지": "middle_man",
            "어머니": "middle_woman",
            "아빠": "middle_man",
            "엄마": "middle_woman",
            "남편": "middle_man",
            "아내": "middle_woman",
            "중년남성": "middle_man",
            "중년여성": "middle_woman",
            "삼촌": "middle_man",
            "이모": "middle_woman",
            # 영어 self-mapping
            "grandpa": "grandpa",
            "grandma": "grandma",
            "man": "man",
            "woman": "woman",
            "young_man": "man",
            "young_woman": "woman",
            "middle_man": "middle_man",
            "middle_woman": "middle_woman",
        }

        # Gemini가 생성한 매핑으로 덮어쓰기 (장르별 특화 매핑 추가)
        if character_config:
            base_mapping.update(character_config)

        return base_mapping

    def _generate_hook_style(self, settings: Dict, genre_defaults: Dict) -> Dict:
        """v59.5.14: 장르에 따른 hook_style 자동 생성"""
        genre = settings.get("genre", "horror")
        pack_name = settings.get("pack_name", "이야기")

        # 팩 이름에서 hook label 추출 (2~3글자)
        hook_label = genre_defaults.get("hook_top_label", "【 이야기 】")

        # chatbot에서 bgm_folder가 makjang이면 막장 스타일
        bgm_folder = settings.get("bgm_folder", genre_defaults.get("bgm_folder", "horror"))
        if bgm_folder == "makjang":
            hook_label = "【 가 족 사 】"
            top_color = "#C0392B"
            bg_color = [15, 5, 5]
        elif genre == "horror":
            top_color = genre_defaults.get("hook_top_color", "#8B0000")
            bg_color = genre_defaults.get("hook_bg_color", [0, 0, 0])
        else:
            top_color = genre_defaults.get("hook_top_color", "#D4A574")
            bg_color = genre_defaults.get("hook_bg_color", [10, 5, 0])

        return {
            "top_label": hook_label,
            "top_color": top_color,
            "main_color": genre_defaults.get("hook_main_color", "#FFFFFF"),
            "bg_color": bg_color,
            "duration": 4.0,
        }

    def _assemble_pack_data(self) -> Dict:
        """v59.5.14: horror_default.json 구조에 맞춘 v59 팩 데이터 조립"""
        settings = self.collected_settings
        prompts = self.generated_prompts

        genre = settings.get("genre", "horror")
        genre_defaults = GENRE_DEFAULTS.get(genre, GENRE_DEFAULTS["horror"])

        # 나레이터 성별 결정
        narrator_gender = settings.get("characters", {}).get(
            "narrator_gender", "narrator_male"
        )

        # 캐릭터 매핑 구축
        character_mapping = self._build_character_mapping(
            prompts.get("character_config", {}),
            narrator_gender
        )

        # SD checkpoint 결정 (chatbot에서 수집 > 장르 기본값)
        sd_checkpoint = (
            settings.get("sd_model", {}).get("checkpoint") or
            genre_defaults["checkpoint"]
        )

        # BGM/SFX 폴더 결정 (chatbot에서 수집 > 장르 기본값)
        bgm_folder = settings.get("bgm_folder", genre_defaults["bgm_folder"])
        sfx_folder = settings.get("sfx_folder", genre_defaults["sfx_folder"])

        # LoRA 모델 (chatbot에서 수집)
        lora_models = settings.get("sd_model", {}).get("lora_models", [])

        # 아트 스타일 정보 (chatbot에서 수집)
        art_style = settings.get("art_style", {})
        art_style_prefix = art_style.get("prefix", "")

        # forced_style 구축 (sd_positive + art_style_prefix 기반)
        sd_positive = prompts.get("sd_positive", "masterpiece, best quality")
        sd_negative = prompts.get("sd_negative", "(worst quality:1.4), (low quality:1.4)")

        forced_style = {
            "force_positive": sd_positive,
            "force_negative": sd_negative,
        }

        # 비주얼 캐릭터 (2단계 Gemini에서 생성)
        visual_characters = prompts.get("visual_characters", {})

        # 씬 분석기 (2단계 Gemini에서 생성)
        scene_analyzer = prompts.get("scene_analyzer", {})

        # 시나리오 풀 (2단계 Gemini에서 생성)
        scenario_pools = prompts.get("scenario_pools", {})

        # 썸네일 배경, 안전 폴백 (2단계 Gemini에서 생성)
        thumbnail_backgrounds = prompts.get("thumbnail_backgrounds", [])
        safe_fallbacks = prompts.get("safe_fallbacks", [])
        safe_fallback_prompt = prompts.get("safe_fallback_prompt", "")

        # 화자 색상 (2단계 Gemini에서 생성)
        speaker_colors = prompts.get("speaker_colors", {
            "나레이션": "#CCCCCC",
            "narrator": "#CCCCCC",
        })

        # 인트로 스크립트 (2단계 Gemini에서 생성)
        intro_scripts = prompts.get("intro_scripts", [])

        # Hook 스타일 자동 생성
        hook_style = self._generate_hook_style(settings, genre_defaults)

        # === v59 팩 데이터 조립 (horror_default.json 구조) ===
        pack_data = {
            # 기본 정보
            "pack_id": settings.get("pack_id", "unknown"),
            "pack_name": settings.get("pack_name", "New Pack"),
            "version": self.version_input.text(),
            "author": self.author_input.text(),
            "description": settings.get("pack_name", "New Pack"),
            "genre": genre,

            # TTS 설정
            "tts": {
                "narrator": narrator_gender,
                "character_mapping": character_mapping,
                "default_emotion": genre_defaults.get("default_emotion", "calm"),
                "allowed_emotions": prompts.get("allowed_emotions",
                    ["scared", "angry", "sad", "happy", "calm", "whisper"]),
                "emotion_weights": prompts.get("emotion_weights",
                    prompts.get("emotion_policy", {"calm": 5})),
            },

            # BGM / SFX
            "bgm": {
                "folder": bgm_folder,
            },
            "sfx": {
                "folder": sfx_folder,
                "enabled": True,
                "category": genre_defaults.get("sfx_category", "horror"),
                "intensity": genre_defaults.get("sfx_intensity", "medium"),
                # v60: 팩-클라이언트 아키텍처 — SFX 가이드/키워드맵
                "category_guide": prompts.get("sfx_config", {}).get("category_guide", ""),
                "keyword_map": prompts.get("sfx_config", {}).get("keyword_map", {}),
            },

            # SD 설정 (레거시 호환 — visual_storytelling.sd_model이 우선)
            "sd": {
                "positive": sd_positive,
                "negative": sd_negative,
                "style": art_style.get("description", ""),
                "model": genre,
                "cfg_scale": genre_defaults.get("cfg_scale", 7.0),     # v59.5.15
                "steps": genre_defaults.get("steps", 20),               # v59.5.15
                "image_style": settings.get("content", {}).get("image_style", ""),
            },

            # Visual 설정 (캐릭터 + 스타일)
            "visual": {
                "character_system_enabled": False,
                "characters": visual_characters,
                "forced_style": forced_style,
                "thumbnail_backgrounds": thumbnail_backgrounds,
                "safe_fallbacks": safe_fallbacks,
                "safe_fallback_prompt": safe_fallback_prompt,
            },

            # 프롬프트 (sd_positive/sd_negative도 포함 — pack_config.py가 여기서 읽음)
            "prompts": {
                "pd_system": prompts.get("pd_system", ""),
                "writer_system": prompts.get("writer_system", ""),
                "sd_positive": sd_positive,
                "sd_negative": sd_negative,
                # v60: 팩-클라이언트 아키텍처 — 새 프롬프트 필드
                "topic_generation": prompts.get("topic_generation", ""),
                "topic_enhanced": prompts.get("topic_enhanced", ""),
                "hook_generation": prompts.get("hook_generation", ""),
                "hook_enhanced": prompts.get("hook_enhanced", ""),
                "metadata_generation": prompts.get("metadata_generation", ""),
                "thumbnail_style_guide": prompts.get("thumbnail_style_guide", ""),
                "story_bible": prompts.get("story_bible", ""),
                "story_bible_improve": prompts.get("story_bible_improve", ""),
                "story_summarize": prompts.get("story_summarize", ""),
                "structural_outline": prompts.get("structural_outline", ""),
                "craft_rules": prompts.get("craft_rules", ""),
                "pacing_part1": prompts.get("pacing_part1", ""),
                "pacing_part2": prompts.get("pacing_part2", ""),
                "pacing_part3": prompts.get("pacing_part3", ""),
                "image_style": prompts.get("image_style", ""),
                "image_llm_prompt": prompts.get("image_llm_prompt", ""),
            },

            # v60: 분위기/비상 설정
            "atmosphere": prompts.get("atmosphere_config", {}),
            "emergency": {
                "template_sequence": prompts.get("emergency_sequence", []),
            },

            # 콘텐츠 설정
            "content": {
                "duration_minutes": settings.get("content", {}).get("duration_minutes", 5),
                "min_turns": settings.get("content", {}).get("min_turns", 80),
                "max_turns": settings.get("content", {}).get("max_turns", 150),
                "image_style": settings.get("content", {}).get("image_style", ""),
            },

            # 비디오 설정
            "video": {
                "pause_duration": genre_defaults.get("pause_duration", 0.4),
                "zoom_speed": 1.0,
            },

            # Hook 스타일
            "hook_style": hook_style,

            # 썸네일 설정
            "thumbnail": {
                "text_default": genre_defaults.get("thumbnail_text", "실화"),
                "style_guide": genre_defaults.get("thumbnail_style", ""),
            },

            # 시나리오 풀
            "scenario": {
                "tone_pool": scenario_pools.get("tone_pool", []),
                "twist_pool": scenario_pools.get("twist_pool", []),
                "relationship_pool": scenario_pools.get("relationship_pool", []),
                "place_pool": scenario_pools.get("place_pool", []),
                # v59.5.15: safe_templates = thumbnail_backgrounds + safe_fallbacks (30~40개)
                # horror_default는 80+개이므로 8개만으로는 부족
                "safe_templates": list(dict.fromkeys(thumbnail_backgrounds + safe_fallbacks)),
            },

            # 토픽 & 태그
            "topic_templates": prompts.get("topic_templates", []),
            "tags": prompts.get("tags", []),

            # 인트로 스크립트
            "intro_scripts": intro_scripts,

            # === v59 핵심: Visual Storytelling (필수) ===
            "visual_storytelling": {
                "enabled": True,
                "version": "v59.5.14",

                "image_generation": {
                    "target_images": 120,
                    "min_images": 100,
                    "max_images": 150,
                    "reuse_threshold": 0.85,
                    "quality_threshold": 0.7,
                },

                "scene_analysis": {
                    "use_gemini": True,
                    "context_window": 5,
                    "emotion_detection": True,
                    "action_detection": True,
                },

                "character_consistency": {
                    "enabled": True,
                    "similarity_threshold": 0.8,
                    "expression_swap": True,
                    "pose_library": True,
                },

                "sd_model": {
                    "checkpoint": sd_checkpoint,
                    "vae": "",
                    "sampler": "DPM++ 2M Karras",
                    "scheduler": "Normal",
                    "steps": genre_defaults.get("steps", 20),         # v59.5.15: 장르별
                    "cfg_scale": genre_defaults.get("cfg_scale", 7.0), # v59.5.15: 장르별
                    "width": 768,
                    "height": 432,
                    "clip_skip": 2,
                    "positive_base": sd_positive,
                    "negative_base": sd_negative,
                    "lora_models": lora_models,
                },

                "subtitle_style": {
                    "font_family": "NanumSquareRoundEB",
                    "font_size": 42,
                    "position": "bottom",
                    "background_opacity": 0.7,
                    "text_color": "#FFFFFF",
                    "speaker_colors": speaker_colors,
                },

                "visual_effects": {
                    "vignette": {
                        "enabled": True,
                        "intensity": 0.4 if genre == "horror" else 0.3,
                    },
                    "color_filter": {
                        "type": genre_defaults.get("color_filter_type", genre),  # v59.5.15: "horror"→"horror", "senior"→"drama"
                        "saturation": 0.7 if genre == "horror" else 0.85,
                        "contrast": 1.1,
                    },
                    "film_grain": {
                        "enabled": True,
                        "intensity": 0.15 if genre == "horror" else 0.08,
                    },
                    "transitions": {
                        "default": "crossfade",
                        "duration": 0.5,
                    },
                },
            },

            # 씬 분석기
            "scene_analyzer": scene_analyzer,
        }

        return pack_data

    def _write_file(self, file_path: Path, data: Dict, encrypt: bool):
        """JSON 파일 저장 (암호화 옵션)"""
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        content_bytes = json_str.encode('utf-8')

        if encrypt:
            # v57.7.1: 암호화 저장 (.enc 확장자 추가)
            encrypted = encrypt_content(content_bytes)
            enc_path = file_path.with_suffix(file_path.suffix + '.enc')
            with open(enc_path, 'wb') as f:
                f.write(encrypted)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(json_str)

    def _write_text_file(self, file_path: Path, content: str, encrypt: bool):
        """텍스트 파일 저장 (암호화 옵션)"""
        content_bytes = content.encode('utf-8')

        if encrypt:
            # v57.7.1: 암호화 저장 (.enc 확장자 추가)
            encrypted = encrypt_content(content_bytes)
            enc_path = file_path.with_suffix(file_path.suffix + '.enc')
            with open(enc_path, 'wb') as f:
                f.write(encrypted)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

    def _write_pack_files(self, temp_dir: Path, pack_data: Dict):
        """v59.5.14: 패키지 파일들 저장 (레거시 .revpack 호환, 안전가드 적용)"""

        # 암호화 여부 확인
        use_encryption = self.encrypt_check.isChecked()

        # 1. manifest.json (메인 설정)
        manifest = {
            "pack_id": pack_data.get("pack_id", "unknown"),
            "pack_name": pack_data.get("pack_name", "New Pack"),
            "version": pack_data.get("version", "1.0.0"),
            "author": pack_data.get("author", "Reverie Studio"),
            "created_at": datetime.now().isoformat(),
            "reverie_version_min": self.studio_version.text(),
            "genre": pack_data.get("genre", ""),
            "encrypted": use_encryption,
        }
        self._write_file(temp_dir / "manifest.json", manifest, use_encryption)

        # 2. settings.json (상세 설정 — v59 구조에서 안전하게 추출)
        settings = {
            "content": pack_data.get("content", {}),
            # v59: TTS/Visual/Hook/SD/Thumbnail/Video/Scenario 모두 .get()으로 안전 접근
            "tts": pack_data.get("tts", {}),
            "visual": pack_data.get("visual", {}),
            "hook_style": pack_data.get("hook_style", {}),
            "sd": pack_data.get("sd", {}),
            "thumbnail": pack_data.get("thumbnail", {}),
            "video": pack_data.get("video", {}),
            "bgm": pack_data.get("bgm", {}),
            "sfx": pack_data.get("sfx", {}),
            # v60: 분위기/비상 설정 (팩-클라이언트 아키텍처)
            "atmosphere": pack_data.get("atmosphere", {}),
            "emergency": pack_data.get("emergency", {}),
            # v59: Visual Storytelling
            "visual_storytelling": pack_data.get("visual_storytelling", {}),
            "scene_analyzer": pack_data.get("scene_analyzer", {}),
        }
        self._write_file(temp_dir / "settings.json", settings, use_encryption)

        # 3. prompts/ 폴더
        prompts_dir = temp_dir / "prompts"
        prompts_dir.mkdir(exist_ok=True)

        prompts_data = pack_data.get("prompts", {})

        self._write_text_file(
            prompts_dir / "pd_system.txt",
            prompts_data.get("pd_system", ""),
            use_encryption
        )

        self._write_text_file(
            prompts_dir / "writer_system.txt",
            prompts_data.get("writer_system", ""),
            use_encryption
        )

        sd_prompts = {
            "positive": prompts_data.get("sd_positive", ""),
            "negative": prompts_data.get("sd_negative", ""),
        }
        self._write_file(prompts_dir / "sd_prompts.json", sd_prompts, use_encryption)

        # 3.5 v60: 새 프롬프트 파일들 (팩-클라이언트 아키텍처)
        NEW_PROMPT_FILES = {
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
        }
        for field_name, file_name in NEW_PROMPT_FILES.items():
            content = prompts_data.get(field_name, "")
            if content:
                self._write_text_file(prompts_dir / file_name, content, use_encryption)

        # 4. topics.json (시나리오 풀 포함)
        topics = {
            "templates": pack_data.get("topic_templates", []),
            "tags": pack_data.get("tags", []),
            "scenario": pack_data.get("scenario", {}),
            "intro_scripts": pack_data.get("intro_scripts", []),
        }
        with open(temp_dir / "topics.json", 'w', encoding='utf-8') as f:
            json.dump(topics, f, indent=2, ensure_ascii=False)

        # 5. assets/ 폴더 구조
        (temp_dir / "assets" / "bgm").mkdir(parents=True, exist_ok=True)
        (temp_dir / "assets" / "sfx").mkdir(parents=True, exist_ok=True)

        # 6. README.md
        topic_list = pack_data.get("topic_templates", [])[:5]
        tags_list = pack_data.get("tags", [])
        readme = f"""# {pack_data.get("pack_name", "New Pack")}

**장르**: {pack_data.get("genre", "")}
**버전**: {pack_data.get("version", "1.0.0")}
**제작자**: {pack_data.get("author", "Reverie Studio")}

## 사용법

1. assets/packs/에 JSON 팩을 넣거나 .revpack을 Import
2. 채널 설정에서 팩 선택
3. BGM/SFX 폴더에 에셋 추가 (선택)

## 토픽 예시

{chr(10).join(f"- {t}" for t in topic_list)}

## 태그

{", ".join(tags_list)}

---

*Reverie Studio Pack Creator v59.5.14로 생성됨*
"""
        with open(temp_dir / "README.md", 'w', encoding='utf-8') as f:
            f.write(readme)


# ============================================================
# v58.2: CLI 모드 - 기존 팩 복제/수정
# ============================================================

def cli_clone_pack(source_pack: str, target_name: str, modifications: Dict = None):
    """
    v58.2: CLI로 기존 팩을 복제하고 수정

    사용법:
        python pack_creator_full.py --clone senior_makjang.revpack --name "my_custom_pack"
    """
    import shutil
    import tempfile

    source_path = Path(source_pack)
    if not source_path.exists():
        # assets/packs 폴더에서 찾기
        source_path = PROJECT_ROOT / "assets" / "packs" / source_pack
        if not source_path.exists():
            print(f"[ERROR] Source pack not found: {source_pack}")
            return None

    print(f"[CLONE] Starting: {source_path.name} -> {target_name}")

    # 임시 폴더에 압축 해제
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # ZIP 해제
        with zipfile.ZipFile(source_path, 'r') as zf:
            zf.extractall(temp_path)

        # manifest.json 수정
        manifest_path = temp_path / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            manifest['pack_name'] = target_name
            manifest['pack_id'] = target_name.lower().replace(' ', '_')
            manifest['created_at'] = datetime.now().isoformat()

            if modifications:
                for key, value in modifications.items():
                    if key in manifest:
                        manifest[key] = value

            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

        # settings.json 수정 (암호화된 경우 처리)
        settings_path = temp_path / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, 'rb') as f:
                    content = f.read()

                # 암호화 여부 확인
                try:
                    settings = json.loads(content.decode('utf-8'))
                except:
                    # 암호화된 파일 복호화
                    decrypted = decrypt_content(content)
                    settings = json.loads(decrypted.decode('utf-8'))

                if modifications:
                    for key, value in modifications.items():
                        if key in settings:
                            settings[key] = value

                # 다시 저장 (암호화 없이)
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)

            except Exception as e:
                print(f"[WARN] settings.json processing error: {e}")

        # 새 팩 생성
        target_path = PROJECT_ROOT / "assets" / "packs" / f"{target_name.lower().replace(' ', '_')}.revpack"
        with zipfile.ZipFile(target_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in temp_path.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(temp_path)
                    zf.write(file_path, arcname)

        print(f"[OK] Pack created: {target_path}")
        return str(target_path)


def cli_list_packs():
    """v58.2: 사용 가능한 팩 목록 출력"""
    packs_dir = PROJECT_ROOT / "assets" / "packs"
    print("\n[PACKS] Available packs:")
    print("-" * 40)

    for pack_file in packs_dir.glob("*.revpack"):
        try:
            with zipfile.ZipFile(pack_file, 'r') as zf:
                if 'manifest.json' in zf.namelist():
                    with zf.open('manifest.json') as f:
                        manifest = json.load(f)
                        print(f"  * {pack_file.name}")
                        print(f"    Name: {manifest.get('pack_name', 'Unknown')}")
                        print(f"    Genre: {manifest.get('genre', 'Unknown')}")
                        print()
        except Exception as e:
            print(f"  * {pack_file.name} (read error: {e})")
    print("-" * 40)


def cli_validate_pack(pack_path: str):
    """v58.2: 팩 유효성 검증"""
    path = Path(pack_path)
    if not path.exists():
        path = PROJECT_ROOT / "assets" / "packs" / pack_path

    if not path.exists():
        print(f"[ERROR] Pack not found: {pack_path}")
        return False

    print(f"\n[VALIDATE] Pack: {path.name}")
    print("-" * 40)

    required_files = ['manifest.json', 'settings.json', 'topics.json']
    optional_files = ['prompts/pd_system.txt', 'prompts/writer_system.txt']

    errors = []
    warnings = []

    try:
        with zipfile.ZipFile(path, 'r') as zf:
            namelist = zf.namelist()

            # 필수 파일 확인
            for req in required_files:
                if req not in namelist:
                    errors.append(f"Required file missing: {req}")
                else:
                    print(f"  [OK] {req}")

            # 선택 파일 확인
            for opt in optional_files:
                if opt not in namelist:
                    warnings.append(f"Optional file missing: {opt}")
                else:
                    print(f"  [OK] {opt}")

            # manifest.json 검증
            if 'manifest.json' in namelist:
                with zf.open('manifest.json') as f:
                    manifest = json.load(f)
                    required_fields = ['pack_name', 'pack_id', 'genre']
                    for field in required_fields:
                        if field not in manifest:
                            errors.append(f"manifest.json required field missing: {field}")

            # settings.json 검증
            if 'settings.json' in namelist:
                with zf.open('settings.json') as f:
                    try:
                        content = f.read()
                        settings = json.loads(content.decode('utf-8'))
                    except:
                        try:
                            settings = json.loads(decrypt_content(content).decode('utf-8'))
                        except:
                            errors.append("settings.json parse failed")
                            settings = {}

                    v58_fields = ['tts', 'visual', 'hook_style', 'sd']
                    for field in v58_fields:
                        if field not in settings:
                            warnings.append(f"v58 field missing: {field} (using default)")

        print("-" * 40)

        if errors:
            print(f"\n[ERROR] {len(errors)} error(s):")
            for e in errors:
                print(f"   - {e}")

        if warnings:
            print(f"\n[WARN] {len(warnings)} warning(s):")
            for w in warnings:
                print(f"   - {w}")

        if not errors:
            print("\n[OK] Pack validation passed!")
            return True
        else:
            return False

    except Exception as e:
        print(f"[ERROR] Validation failed: {e}")
        return False


# ============================================================
# 메인
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="ReveriePack 생성 도구 v58.2")
    parser.add_argument('--clone', type=str, help='복제할 소스 팩 경로')
    parser.add_argument('--name', type=str, help='새 팩 이름')
    parser.add_argument('--list', action='store_true', help='사용 가능한 팩 목록')
    parser.add_argument('--validate', type=str, help='팩 유효성 검증')
    parser.add_argument('--gui', action='store_true', help='GUI 모드 실행 (기본)')

    args = parser.parse_args()

    # CLI 모드
    if args.list:
        cli_list_packs()
        return

    if args.validate:
        cli_validate_pack(args.validate)
        return

    if args.clone:
        if not args.name:
            print("[ERROR] --name option required")
            return
        cli_clone_pack(args.clone, args.name)
        return

    # GUI 모드 (기본)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 다크 테마
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, QColor(220, 220, 220))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = PackCreatorWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
