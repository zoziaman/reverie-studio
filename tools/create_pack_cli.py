# tools/create_pack_cli.py
# ============================================================
# ReveriePack CLI 생성 스크립트
# Claude가 직접 팩을 생성할 때 사용
# ============================================================
# v57.7.6: 감정/캐릭터 검증 강화 - 유효한 값만 허용
# 실행: python tools/create_pack_cli.py
# ============================================================

import os
import sys
import json
import zipfile
import hashlib
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# 암호화 라이브러리
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import google.generativeai as genai
from dotenv import load_dotenv

# .env 로드
load_dotenv(PROJECT_ROOT / ".env")


# ============================================================
# v57.7.6: 유효성 검증 상수
# ============================================================

# 허용되는 감정 목록 (TTS에서 지원하는 감정들)
VALID_EMOTIONS = frozenset({
    "sad", "angry", "scared", "happy", "calm",
    "excited", "whisper", "worried", "desperate"
})

# v59.5.14: 허용되는 voice_type 목록 (9종 체계 + alias)
VALID_VOICE_TYPES = frozenset({
    "narrator", "man", "woman", "young_man", "young_woman",
    "grandma", "grandpa", "middle_man", "middle_woman"
})


# ============================================================
# 암호화 설정 (pack_creator_full.py와 동일)
# ============================================================

PACK_ENCRYPTION_SALT = b'ReveriePack2024Salt!'
PACK_ENCRYPTION_PASSWORD = b'ReverieStudio_PackEncryption_v57'


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
# 프롬프트 생성 템플릿
# ============================================================

PROMPT_GENERATOR_TEMPLATE = """당신은 YouTube {content_type} 콘텐츠 전문 프로듀서입니다.
아래 설정을 바탕으로 실제 영상 제작에 사용할 프롬프트들을 생성해주세요.

## 입력 설정

{settings_json}

## 생성해야 할 항목

### 1. PD 시스템 프롬프트 (pd_system)
- 영상 기획자 역할
- 이 장르/스타일에 맞는 스토리 구조 지시
- 분위기, 전개 방식, 반전 포인트 가이드
- 300~500자

### 2. 작가 시스템 프롬프트 (writer_system)
- 대사 작성자 역할
- 문장 스타일, 말투, 감정 표현 방식
- 캐릭터별 말투 차이 (예: 할머니는 사투리, 젊은이는 존댓말)
- 이 장르에 맞는 문장 길이, 호흡
- 300~500자

### 3. SD 긍정 프롬프트 (sd_positive)
- Stable Diffusion 이미지 생성용
- 이미지 스타일에 맞는 프롬프트
- 품질 태그 포함 (masterpiece, best quality 등)
- 영어로 작성

### 4. SD 부정 프롬프트 (sd_negative)
- 피해야 할 요소
- 품질 관련 부정 태그
- 영어로 작성

### 5. 토픽 템플릿 (topic_templates)
- 이 팩으로 만들 수 있는 예시 주제 10개
- 구체적이고 흥미로운 제목들
- 한국어로 작성

### 6. 태그 (tags)
- YouTube 검색용 태그 10개
- 한국어로 작성

### 7. 캐릭터 설정 (character_config)
- 역할별 TTS 음성 타입 매핑
- 예: "narrator": "man", "protagonist": "woman"
- 가능한 타입: man, woman, grandpa, grandma, young_man, young_woman, narrator
- 한글 이름도 매핑 필수 (예: "주인공": "woman", "할머니": "grandma")

### 8. 감정 설정 (allowed_emotions, emotion_policy)
- TTS 감정 연기에 사용할 감정 목록
- 가능한 감정: scared, angry, sad, happy, calm, excited, whisper, worried, desperate
- 장르에 맞는 감정만 선택 (공포: scared 필수, 감동: sad/happy 필수)
- emotion_policy: 대본에서 최소 등장 횟수 (예: {{"scared": 3, "calm": 5}})

## 출력 형식

반드시 아래 JSON 형식으로만 출력하세요:

```json
{{
  "pd_system": "PD 시스템 프롬프트 전문...",
  "writer_system": "작가 시스템 프롬프트 전문...",
  "sd_positive": "masterpiece, best quality, ...",
  "sd_negative": "(worst quality:1.4), ...",
  "topic_templates": ["주제1", "주제2", ...],
  "tags": ["태그1", "태그2", ...],
  "character_config": {{
    "narrator": "man",
    "protagonist": "woman",
    "나레이션": "narrator",
    "주인공": "woman"
  }},
  "allowed_emotions": ["scared", "angry", "sad", "happy", "calm", "whisper"],
  "emotion_policy": {{"scared": 3, "calm": 5}}
}}
```
"""


# ============================================================
# 팩 생성 클래스
# ============================================================

class RevPackCreatorCLI:
    """CLI 기반 ReveriePack 생성기"""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name="gemini-2.0-flash")

    def generate_prompts(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Gemini로 프롬프트 생성"""
        print("[AI] Gemini API로 프롬프트 생성 중...")

        settings_json = json.dumps(settings, indent=2, ensure_ascii=False)

        # 콘텐츠 타입 결정
        duration = settings.get("content", {}).get("duration_minutes", 5)
        content_type = "숏폼" if duration <= 5 else "롱폼"

        prompt = PROMPT_GENERATOR_TEMPLATE.format(
            content_type=content_type,
            settings_json=settings_json
        )

        response = self.model.generate_content(prompt)
        response_text = response.text

        # JSON 추출
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        if start > 6 and end > start:
            json_str = response_text[start:end].strip()
            prompts = json.loads(json_str)
        else:
            prompts = json.loads(response_text)

        # v57.7.6: 생성된 프롬프트 검증 및 정제
        prompts = self._validate_and_sanitize_prompts(prompts)
        return prompts

    def _validate_and_sanitize_prompts(self, prompts: Dict[str, Any]) -> Dict[str, Any]:
        """
        v57.7.6: Gemini가 생성한 프롬프트의 감정/캐릭터를 검증하고 정제

        - 유효하지 않은 감정은 제거
        - 유효하지 않은 voice_type은 기본값으로 대체
        """
        print("[검증] 감정 및 캐릭터 설정 검증 중...")

        # 1. 감정 검증
        raw_emotions = prompts.get("allowed_emotions", [])
        valid_emotions = [e for e in raw_emotions if e in VALID_EMOTIONS]
        invalid_emotions = [e for e in raw_emotions if e not in VALID_EMOTIONS]

        if invalid_emotions:
            print(f"  [경고] 무효 감정 제거됨: {invalid_emotions}")

        # 최소 2개 감정 보장
        if len(valid_emotions) < 2:
            valid_emotions = ["calm", "scared"]  # 기본 폴백
            print(f"  [경고] 감정 부족 → 기본값 적용: {valid_emotions}")

        prompts["allowed_emotions"] = valid_emotions

        # 2. 감정 정책 검증
        raw_policy = prompts.get("emotion_policy", {})
        valid_policy = {k: v for k, v in raw_policy.items() if k in valid_emotions}
        prompts["emotion_policy"] = valid_policy if valid_policy else {"calm": 5}

        # 3. 캐릭터 설정 검증
        raw_char_config = prompts.get("character_config", {})
        valid_char_config = {}
        invalid_chars = []

        for role, voice_type in raw_char_config.items():
            if voice_type in VALID_VOICE_TYPES:
                valid_char_config[role] = voice_type
            else:
                # 무효한 voice_type → narrator로 대체
                valid_char_config[role] = "narrator"
                invalid_chars.append((role, voice_type))

        if invalid_chars:
            print(f"  [경고] 무효 voice_type 대체됨:")
            for role, vt in invalid_chars:
                print(f"    - {role}: '{vt}' → 'narrator'")

        # 필수 역할 보장
        if "narrator" not in valid_char_config and "나레이션" not in valid_char_config:
            valid_char_config["narrator"] = "narrator"
            valid_char_config["나레이션"] = "narrator"

        prompts["character_config"] = valid_char_config

        print(f"  [OK] 감정: {valid_emotions}")
        print(f"  [OK] 캐릭터: {list(valid_char_config.keys())}")

        return prompts

    def assemble_pack_data(self, settings: Dict, prompts: Dict) -> Dict:
        """패키지 데이터 조립"""
        pack_data = {
            "pack_id": settings.get("pack_id", "unknown"),
            "pack_name": settings.get("pack_name", "New Pack"),
            "version": "1.0.0",
            "author": "Claude (Reverie Studio)",
            "created_at": datetime.now().isoformat(),
            "reverie_version_min": "37",
            "channel_type": settings.get("channel_type", "horror"),  # 중요: 슬래시 없는 타입

            "genre": settings.get("genre", ""),
            "style": settings.get("style", {}),
            "content": settings.get("content", {}),
            "restrictions": settings.get("restrictions", {}),

            "prompts": {
                "pd_system": prompts.get("pd_system", ""),
                "writer_system": prompts.get("writer_system", ""),
                "sd_positive": prompts.get("sd_positive", ""),
                "sd_negative": prompts.get("sd_negative", ""),
            },

            "topic_templates": prompts.get("topic_templates", []),
            "tags": prompts.get("tags", []),

            "characters": settings.get("characters", {}),
            "character_config": prompts.get("character_config", {}),

            # v57.7.5: 감정 설정
            "allowed_emotions": prompts.get("allowed_emotions", ["scared", "angry", "sad", "happy", "calm"]),
            "emotion_policy": prompts.get("emotion_policy", {"calm": 5}),

            "license": {
                "type": "paid",
                "key_required": True,
            },

            "assets": {
                "bgm_path": f"assets/bgm/{settings.get('pack_id', 'default')}/",
                "sfx_path": f"assets/sfx/{settings.get('pack_id', 'default')}/",
                "use_channel_bgm": settings.get("use_channel_bgm", "horror"),
                "use_channel_sfx": settings.get("use_channel_sfx", "horror"),
                "use_channel_tts": settings.get("use_channel_tts", "horror"),
            }
        }
        return pack_data

    def _write_file(self, file_path: Path, data: Dict, encrypt: bool):
        """JSON 파일 저장"""
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        content_bytes = json_str.encode('utf-8')

        if encrypt:
            encrypted = encrypt_content(content_bytes)
            enc_path = file_path.with_suffix(file_path.suffix + '.enc')
            with open(enc_path, 'wb') as f:
                f.write(encrypted)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(json_str)

    def _write_text_file(self, file_path: Path, content: str, encrypt: bool):
        """텍스트 파일 저장"""
        content_bytes = content.encode('utf-8')

        if encrypt:
            encrypted = encrypt_content(content_bytes)
            enc_path = file_path.with_suffix(file_path.suffix + '.enc')
            with open(enc_path, 'wb') as f:
                f.write(encrypted)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

    def write_pack_files(self, temp_dir: Path, pack_data: Dict, encrypt: bool = True):
        """패키지 파일들 저장"""
        # 1. manifest.json
        manifest = {
            "pack_id": pack_data["pack_id"],
            "pack_name": pack_data["pack_name"],
            "version": pack_data["version"],
            "author": pack_data["author"],
            "created_at": pack_data["created_at"],
            "reverie_version_min": pack_data["reverie_version_min"],
            "genre": pack_data["genre"],
            "license": pack_data["license"],
            "encrypted": encrypt,
        }
        self._write_file(temp_dir / "manifest.json", manifest, encrypt)

        # 2. settings.json
        settings = {
            "style": pack_data["style"],
            "content": pack_data["content"],
            "restrictions": pack_data["restrictions"],
            "characters": pack_data["characters"],
            "character_config": pack_data["character_config"],
            "allowed_emotions": pack_data.get("allowed_emotions", []),
            "emotion_policy": pack_data.get("emotion_policy", {}),
            "assets": pack_data["assets"],
        }
        self._write_file(temp_dir / "settings.json", settings, encrypt)

        # 3. prompts/ 폴더
        prompts_dir = temp_dir / "prompts"
        prompts_dir.mkdir(exist_ok=True)

        self._write_text_file(prompts_dir / "pd_system.txt", pack_data["prompts"]["pd_system"], encrypt)
        self._write_text_file(prompts_dir / "writer_system.txt", pack_data["prompts"]["writer_system"], encrypt)

        sd_prompts = {
            "positive": pack_data["prompts"]["sd_positive"],
            "negative": pack_data["prompts"]["sd_negative"],
        }
        self._write_file(prompts_dir / "sd_prompts.json", sd_prompts, encrypt)

        # 4. topics.json (암호화 안 함)
        topics = {
            "templates": pack_data["topic_templates"],
            "tags": pack_data["tags"],
        }
        with open(temp_dir / "topics.json", 'w', encoding='utf-8') as f:
            json.dump(topics, f, indent=2, ensure_ascii=False)

        # 5. assets/ 폴더 구조
        (temp_dir / "assets" / "bgm").mkdir(parents=True, exist_ok=True)
        (temp_dir / "assets" / "sfx").mkdir(parents=True, exist_ok=True)

        # 6. README.md
        readme = f"""# {pack_data["pack_name"]}

**장르**: {pack_data["genre"]}
**버전**: {pack_data["version"]}
**제작자**: {pack_data["author"]}
**생성일**: {pack_data["created_at"]}

## 사용법

1. Reverie Studio v{pack_data["reverie_version_min"]} 이상 필요
2. 관리자 GUI에서 이 .revpack 파일 Import
3. 채널 설정에서 팩 선택
4. BGM/SFX 폴더에 에셋 추가 (선택)

## 토픽 예시

{chr(10).join(f"- {t}" for t in pack_data["topic_templates"][:5])}

## 태그

{", ".join(pack_data["tags"])}

## 감정 설정

- **허용 감정**: {", ".join(pack_data.get("allowed_emotions", []))}
- **감정 정책**: {json.dumps(pack_data.get("emotion_policy", {}), ensure_ascii=False)}

---

*Reverie Studio Pack Creator (Claude CLI)로 생성됨*
"""
        with open(temp_dir / "README.md", 'w', encoding='utf-8') as f:
            f.write(readme)

    def create_revpack(self, settings: Dict, output_path: str = None, encrypt: bool = True) -> str:
        """ReveriePack 생성 메인 함수"""
        import shutil

        # 1. pack_id 생성
        settings["pack_id"] = hashlib.md5(
            settings.get("pack_name", "pack").encode()
        ).hexdigest()[:8]

        print(f"[PACK] 팩 생성 시작: {settings.get('pack_name')}")
        print(f"   Pack ID: {settings['pack_id']}")

        # 2. 프롬프트 생성
        prompts = self.generate_prompts(settings)
        print("[OK] 프롬프트 생성 완료")

        # 3. 패키지 데이터 조립
        pack_data = self.assemble_pack_data(settings, prompts)
        print("[OK] 패키지 데이터 조립 완료")

        # 4. 출력 경로 결정
        if output_path is None:
            default_name = settings.get("pack_name", "new_pack").replace(" ", "_")
            output_path = str(PROJECT_ROOT / "data" / "exports" / f"{default_name}.revpack")

        # exports 폴더 생성
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 5. 임시 폴더 생성
        temp_dir = Path(output_path).parent / f"_temp_{pack_data['pack_id']}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 6. 파일들 저장
            self.write_pack_files(temp_dir, pack_data, encrypt)
            print("[OK] 파일 저장 완료")

            # 7. ZIP으로 압축
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_path_item in temp_dir.rglob('*'):
                    if file_path_item.is_file():
                        arcname = file_path_item.relative_to(temp_dir)
                        zf.write(file_path_item, arcname)

            print(f"[OK] .revpack 생성 완료: {output_path}")

            # 생성된 프롬프트 일부 출력
            print("\n[INFO] 생성된 프롬프트 미리보기:")
            print(f"   토픽 템플릿 (처음 3개):")
            for i, topic in enumerate(pack_data["topic_templates"][:3], 1):
                print(f"   {i}. {topic}")
            print(f"   감정: {', '.join(pack_data.get('allowed_emotions', []))}")

            return output_path

        finally:
            # 임시 폴더 삭제
            shutil.rmtree(temp_dir, ignore_errors=True)


# ============================================================
# 메인 실행
# ============================================================

if __name__ == "__main__":
    # "소름돋는 실화 괴담" 팩 설정
    horror_settings = {
        "pack_name": "소름돋는 실화 괴담",
        "channel_type": "horror",  # 채널 타입 (슬래시 금지! horror, senior, comedy 등)
        "genre": "공포/미스터리",
        "style": {
            "setting": "한국 현대 배경, 일상적인 장소 (아파트, 회사, 학교, 지하철 등)",
            "mood": ["소름", "긴장감", "불안함", "미스터리", "반전"],
            "intensity": 7  # 공포 수위 (1~10)
        },
        "characters": {
            "types": ["일반인 화자", "목격자", "피해자"],
            "count": "2~4",
            "special": "실제 경험을 이야기하는 듯한 1인칭 화자 필수"
        },
        "content": {
            "duration_minutes": 10,  # 10분 롱폼 (광고 수익 최적화)
            "min_turns": 100,
            "max_turns": 150,
            "image_style": "어둡고 불안한 분위기의 실사풍 일러스트, 한국 현대 배경"
        },
        "restrictions": {
            "forbidden": ["과도한 고어", "성인 콘텐츠", "정치적 내용"],
            "required": ["반전 엔딩", "소름돋는 마무리", "실화 느낌", "이건 제가 직접 겪은 일입니다 식의 도입"]
        },
        "use_channel_bgm": "horror",
        "use_channel_sfx": "horror",
        "use_channel_tts": "horror"
    }

    # 팩 생성
    creator = RevPackCreatorCLI()
    output = creator.create_revpack(horror_settings, encrypt=True)

    print(f"\n[DONE] 완료! 생성된 파일: {output}")
