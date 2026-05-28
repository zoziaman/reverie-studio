# src/utils/package_manager.py
"""
v37 - 채널 패키지 관리 시스템

핵심 개념: "고기가 아니라 레시피다"
- 패키지는 모델 파일(20GB)을 포함하지 않음
- 메타데이터와 설정값만 담은 가벼운 .revpack 파일
- 모델은 참조 정보(이름, 해시, URL)만 저장

기능:
1. 채널 패키지 내보내기 (Export) - Admin용
2. 채널 패키지 가져오기 (Import) - 사용자용
3. 모델 누락 검증 및 안내
4. 버전 호환성 체크
"""

import os
import io
import json
import zipfile
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from enum import Enum

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)

# 현재 Reverie 버전
REVERIE_VERSION = "37"


class ModelType(Enum):
    """모델 타입"""
    SD_CHECKPOINT = "sd_checkpoint"
    LORA = "lora"
    VAE = "vae"
    SOVITS = "sovits"
    GPT = "gpt"


class LicenseType(Enum):
    """라이센스 타입"""
    FREE = "free"
    PAID = "paid"
    TRIAL = "trial"


@dataclass
class RequiredModel:
    """
    필요한 모델 정보

    패키지에는 모델 파일이 포함되지 않고,
    이 메타데이터만 저장됨
    """
    name: str                           # 모델 파일명
    type: str                           # ModelType (checkpoint, lora, sovits 등)
    required: bool = True               # 필수 여부
    hash: str = ""                      # 모델 해시 (검증용)
    download_url: str = ""              # 다운로드 URL (무료 모델)
    note: str = ""                      # 안내 메시지 (유료 모델: "판매자에게 문의하세요")

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'RequiredModel':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CharacterMapping:
    """캐릭터 매핑 정보"""
    role_id: str                        # 역할 ID (grandma, narrator 등)
    display_name: str                   # 표시명 ("할머니", "나레이터")
    voice_model: str = ""               # 음성 모델 이름
    subtitle_color: str = "#FFFFFF"     # 자막 색상
    emotions: List[str] = field(default_factory=lambda: ["calm"])

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'CharacterMapping':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class VoiceGuide:
    """
    목소리 가이드 - TTS 모델 학습/설정 가이드

    Factory에서 팩 생성 시 자동으로 생성되어
    사용자가 어떤 목소리를 학습/사용해야 하는지 안내

    v56.8: Qwen3-TTS VoiceDesign 지원 추가
    - GPT-SoVITS: weights 파일 경로 사용
    - Qwen3-TTS: instruct 텍스트 + seed 값 사용
    """
    role_id: str                        # 캐릭터 역할 ID
    display_name: str                   # 표시명 ("나레이터", "여학생")
    gender: str = "male"                # male, female
    age_range: str = "adult"            # child, teen, adult, senior
    tone_description: str = ""          # 톤 설명 ("차분하고 낮은 목소리")
    reference_style: str = ""           # 참조 스타일 ("한국 공포 라디오 DJ")
    required_emotions: List[str] = field(default_factory=lambda: ["calm"])
    sample_requirements: str = ""       # 샘플 요구사항 ("감정당 3~5초 x 3개")
    post_processing: str = ""           # 권장 후처리 ("리버브 + 피치다운")
    notes: str = ""                     # 추가 메모

    # TTS 엔진 타입 (v56.8)
    tts_engine: str = "sovits"          # "sovits" 또는 "supertonic"

    # GPT-SoVITS용 (팩에 포함될 때 사용)
    has_model: bool = False             # 모델 포함 여부
    gpt_weights_path: str = ""          # gpt_weights.ckpt 상대 경로
    sovits_weights_path: str = ""       # sovits_weights.pth 상대 경로
    ref_audio_paths: Dict[str, str] = field(default_factory=dict)  # 감정별 참조 오디오 경로

    # Qwen3-TTS VoiceDesign용 (v56.8)
    qwen3_instruct: str = ""            # VoiceDesign instruct 텍스트
    qwen3_character_type: str = ""      # 캐릭터 타입 (grandma, narrator 등)
    qwen3_character_seed: int = 0       # 캐릭터 시드 (일관성 보장용)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'VoiceGuide':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PromptConfig:
    """프롬프트 설정"""
    # PD/작가 프롬프트 (AI 시나리오 생성용)
    pd_system_prompt: str = ""          # 총괄 PD 시스템 프롬프트
    writer_system_prompt: str = ""      # 작가 시스템 프롬프트

    # SD 프롬프트
    sd_positive: str = ""               # SD 긍정 프롬프트
    sd_negative: str = ""               # SD 부정 프롬프트

    # 주제 생성 관련
    topic_templates: List[str] = field(default_factory=list)  # 주제 템플릿
    banned_keywords: List[str] = field(default_factory=list)  # 금지 키워드

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'PromptConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ThemeConfig:
    """UI 테마 설정"""
    primary_color: str = "#2196F3"      # 주 색상
    accent_color: str = "#4CAF50"       # 강조 색상
    background_color: str = "#1E1E1E"   # 배경 색상
    subtitle_font_size: int = 24        # 자막 폰트 크기

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ThemeConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class LicenseInfo:
    """라이센스 정보 (향후 유료화 대비)"""
    type: str = "free"                  # free, paid, trial
    key_required: bool = False          # 키 필요 여부
    expires_at: Optional[str] = None    # 만료일 (ISO format)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'LicenseInfo':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ChannelPackage:
    """
    채널 패키지 - .revpack 파일의 핵심 데이터 구조

    manifest + config 통합 구조 (싱크 문제 방지)
    """
    # === Manifest 정보 ===
    package_id: str                     # 패키지 고유 ID
    package_name: str                   # 패키지 이름 ("공포 채널 팩")
    version: str = "1.0.0"              # 패키지 버전
    author: str = ""                    # 제작자
    description: str = ""               # 설명
    created_at: str = ""                # 생성일 (ISO format)

    # === 버전 호환성 ===
    reverie_version_min: str = "37"     # 최소 요구 Reverie 버전
    reverie_version_max: Optional[str] = None  # 최대 호환 버전 (None = 제한 없음)

    # === 라이센스 ===
    license: LicenseInfo = field(default_factory=LicenseInfo)

    # === 채널 설정 ===
    channel_type: str = ""              # horror, senior_touching, senior_makjang, custom
    channel_display_name: str = ""      # 채널 표시명

    # === 필수 모델 (참조만, 파일 미포함) ===
    required_models: Dict[str, RequiredModel] = field(default_factory=dict)

    # === 캐릭터 매핑 ===
    characters: List[CharacterMapping] = field(default_factory=list)

    # === 목소리 가이드 (TTS 모델 학습 안내 + 모델 포함) ===
    voice_guides: List[VoiceGuide] = field(default_factory=list)

    # === 프롬프트 설정 ===
    prompts: PromptConfig = field(default_factory=PromptConfig)

    # === UI 테마 ===
    theme: ThemeConfig = field(default_factory=ThemeConfig)

    # === 오디오 설정 ===
    audio_config: Dict[str, Any] = field(default_factory=dict)

    # === 캐릭터-TTS 매핑 설정 (v57.7.6) ===
    # 역할명 → TTS 모델명 매핑 (예: {"나레이터": "narrator_v2", "아버지": "father_voice"})
    character_config: Dict[str, str] = field(default_factory=dict)

    # === 기타 설정 ===
    extra_config: Dict[str, Any] = field(default_factory=dict)

    # === v59: Visual 설정 (forced_style, thumbnail_backgrounds 등) ===
    visual: Dict[str, Any] = field(default_factory=dict)

    # === v59: Visual Storytelling 설정 ===
    visual_storytelling: Dict[str, Any] = field(default_factory=dict)

    # === v59.5.6: SceneAnalyzer 아트 스타일 (데이터 드리븐) ===
    scene_analyzer: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        return {
            # Manifest
            "package_id": self.package_id,
            "package_name": self.package_name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "created_at": self.created_at,

            # Version
            "reverie_version_min": self.reverie_version_min,
            "reverie_version_max": self.reverie_version_max,

            # License
            "license": self.license.to_dict() if isinstance(self.license, LicenseInfo) else self.license,

            # Channel
            "channel_type": self.channel_type,
            "channel_display_name": self.channel_display_name,

            # Models
            "required_models": {
                k: v.to_dict() if isinstance(v, RequiredModel) else v
                for k, v in self.required_models.items()
            },

            # Characters
            "characters": [
                c.to_dict() if isinstance(c, CharacterMapping) else c
                for c in self.characters
            ],

            # Voice Guides (TTS 모델 가이드 + 포함된 모델 정보)
            "voice_guides": [
                v.to_dict() if isinstance(v, VoiceGuide) else v
                for v in self.voice_guides
            ],

            # Prompts
            "prompts": self.prompts.to_dict() if isinstance(self.prompts, PromptConfig) else self.prompts,

            # Theme
            "theme": self.theme.to_dict() if isinstance(self.theme, ThemeConfig) else self.theme,

            # Audio
            "audio_config": self.audio_config,

            # Character-TTS Mapping (v57.7.6)
            "character_config": self.character_config,

            # Extra
            "extra_config": self.extra_config,

            # v59: Visual 설정 (forced_style, thumbnail_backgrounds 등)
            "visual": self.visual,

            # v59: Visual Storytelling
            "visual_storytelling": self.visual_storytelling,

            # v59.5.6: SceneAnalyzer 아트 스타일
            "scene_analyzer": self.scene_analyzer,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ChannelPackage':
        """딕셔너리에서 생성"""
        # 중첩 객체 변환
        license_data = data.get("license", {})
        if isinstance(license_data, dict):
            license_obj = LicenseInfo.from_dict(license_data)
        else:
            license_obj = LicenseInfo()

        models_data = data.get("required_models", {})
        models_obj = {
            k: RequiredModel.from_dict(v) if isinstance(v, dict) else v
            for k, v in models_data.items()
        }

        chars_data = data.get("characters", [])
        chars_obj = [
            CharacterMapping.from_dict(c) if isinstance(c, dict) else c
            for c in chars_data
        ]

        voice_guides_data = data.get("voice_guides", [])
        voice_guides_obj = [
            VoiceGuide.from_dict(v) if isinstance(v, dict) else v
            for v in voice_guides_data
        ]

        prompts_data = data.get("prompts", {})
        prompts_obj = PromptConfig.from_dict(prompts_data) if isinstance(prompts_data, dict) else PromptConfig()

        theme_data = data.get("theme", {})
        theme_obj = ThemeConfig.from_dict(theme_data) if isinstance(theme_data, dict) else ThemeConfig()

        return cls(
            package_id=data.get("package_id", ""),
            package_name=data.get("package_name", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            reverie_version_min=data.get("reverie_version_min", "37"),
            reverie_version_max=data.get("reverie_version_max"),
            license=license_obj,
            channel_type=data.get("channel_type", ""),
            channel_display_name=data.get("channel_display_name", ""),
            required_models=models_obj,
            characters=chars_obj,
            voice_guides=voice_guides_obj,
            prompts=prompts_obj,
            theme=theme_obj,
            audio_config=data.get("audio_config", {}),
            character_config=data.get("character_config", {}),  # v57.7.6: 캐릭터-TTS 매핑
            extra_config=data.get("extra_config", {}),
            visual=data.get("visual", {}),  # v59.1.5: Visual 설정 (forced_style 등)
            visual_storytelling=data.get("visual_storytelling", {}),  # v59: Visual Storytelling
            scene_analyzer=data.get("scene_analyzer", {}),  # v59.5.6: SceneAnalyzer 아트 스타일
        )


@dataclass
class ModelValidationResult:
    """모델 검증 결과"""
    model_key: str
    model_info: RequiredModel
    found: bool
    local_path: Optional[str] = None

    @property
    def is_critical(self) -> bool:
        """필수 모델인데 없으면 critical"""
        return self.model_info.required and not self.found


@dataclass
class ImportResult:
    """패키지 Import 결과"""
    success: bool
    package: Optional[ChannelPackage] = None
    channel_id: str = ""
    missing_models: List[ModelValidationResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: str = ""


class PackageManager:
    """
    채널 패키지 관리자

    - .revpack 파일 생성/로드
    - GUI 상태 → 패키지 변환 (Export)
    - 패키지 → 채널 설정 적용 (Import)
    - 모델 누락 검증
    """

    PACKAGE_EXTENSION = ".revpack"
    CONFIG_FILENAME = "channel_config.json"
    ENCRYPTED_CONFIG_FILENAME = "channel_config.enc"  # 암호화된 설정 파일
    ASSETS_FOLDER = "assets"

    def __init__(self):
        from config.settings import config
        self.config = config

        # v63: 팩 암호화/서명/라이선스 제거 (개인용) — 평문 팩만 사용
        self.security = None
        self.license_validator = None

        # 패키지 저장 경로
        self.packages_dir = Path(config.DATA_DIR) / "packages"
        self.packages_dir.mkdir(parents=True, exist_ok=True)

        # 설치된 채널 설정 경로
        self.channels_dir = Path(config.DATA_DIR) / "channels"
        self.channels_dir.mkdir(parents=True, exist_ok=True)

        # 로드된 패키지 캐시
        self._loaded_packages: Dict[str, ChannelPackage] = {}

    def _open_package_zip(self, package_path: str) -> Tuple[Optional[zipfile.ZipFile], Optional[io.BytesIO]]:
        """
        Open a .revpack as ZipFile.

        Supports both plain zip-based revpacks and Fernet-wrapped whole-file revpacks.
        Returns the opened ZipFile and optional in-memory buffer that must be kept alive
        while the ZipFile is in use.
        """
        path = Path(package_path)
        buffer: Optional[io.BytesIO] = None

        with open(path, "rb") as f:
            header = f.read(6)

        if header == b"gAAAAA":
            from config.pack_config import (
                CRYPTO_AVAILABLE,
                _decrypt_content,
                _decrypt_content_with_password,
                fetch_pack_key_from_server,
            )

            if not CRYPTO_AVAILABLE:
                raise zipfile.BadZipFile("Encrypted revpack requires cryptography")

            encrypted_data = path.read_bytes()
            decrypted_zip = None
            server_key = fetch_pack_key_from_server(path.stem)

            if server_key:
                decrypted_zip = _decrypt_content_with_password(
                    encrypted_data,
                    server_key.encode("utf-8"),
                )

            if not decrypted_zip:
                decrypted_zip = _decrypt_content(encrypted_data)

            if not decrypted_zip:
                raise zipfile.BadZipFile("Failed to decrypt revpack wrapper")

            buffer = io.BytesIO(decrypted_zip)
            return zipfile.ZipFile(buffer, "r"), buffer

        return zipfile.ZipFile(path, "r"), None

    # ==================== Export (내보내기) ====================

    def export_package(
        self,
        package: ChannelPackage,
        output_path: str,
        include_preview: bool = True,
        preview_image_path: Optional[str] = None,
        require_license: bool = False,
        bind_hardware: bool = False
    ) -> Tuple[bool, str]:
        """
        패키지 내보내기 (Admin용) - 암호화 지원

        현재 GUI 설정 상태를 .revpack 파일로 저장
        보안 옵션 활성화 시 암호화된 바이너리로 저장

        Args:
            package: 패키지 데이터
            output_path: 출력 파일 경로 (.revpack)
            include_preview: 미리보기 이미지 포함 여부
            preview_image_path: 미리보기 이미지 경로
            require_license: 라이선스 키 필요 여부
            bind_hardware: 하드웨어 바인딩 여부

        Returns:
            (성공여부, 메시지)
        """
        try:
            # 생성일 자동 설정
            if not package.created_at:
                package.created_at = datetime.now().isoformat()

            # 라이선스 정보 업데이트
            if require_license:
                if isinstance(package.license, LicenseInfo):
                    package.license.key_required = True
                    package.license.type = "paid"
                else:
                    package.license = LicenseInfo(type="paid", key_required=True)

            # 임시 폴더 생성
            temp_dir = Path(output_path).parent / f"_temp_{package.package_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                # 1. 패키지 데이터 준비
                package_data = package.to_dict()

                # 2. 보안 처리 (암호화)
                if self.security:
                    encrypted_data = self.security.secure_package_data(
                        package_data,
                        require_license=require_license,
                        bind_hardware=bind_hardware
                    )
                    # 암호화된 바이너리 파일로 저장
                    config_path = temp_dir / self.ENCRYPTED_CONFIG_FILENAME
                    with open(config_path, 'wb') as f:
                        f.write(encrypted_data)
                    logger.info("[PackageManager] 암호화된 패키지 생성")
                else:
                    # 보안 모듈 없으면 평문 저장
                    config_path = temp_dir / self.CONFIG_FILENAME
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(package_data, f, ensure_ascii=False, indent=2)
                    logger.warning("[PackageManager] 보안 모듈 없음, 평문 저장")

                # 3. assets 폴더 생성
                assets_dir = temp_dir / self.ASSETS_FOLDER
                assets_dir.mkdir(exist_ok=True)

                # 4. 미리보기 이미지 복사
                if include_preview and preview_image_path:
                    preview_src = Path(preview_image_path)
                    if preview_src.exists():
                        preview_dst = assets_dir / "preview.png"
                        shutil.copy(preview_src, preview_dst)

                # 5. TTS 모델 및 참조 오디오 복사 (voice_guides에 포함된 모델)
                self._copy_voice_models_to_package(package, temp_dir)

                # 6. Zip으로 압축 (.revpack)
                output_file = Path(output_path)
                if not output_file.suffix:
                    output_file = output_file.with_suffix(self.PACKAGE_EXTENSION)

                with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for file_path in temp_dir.rglob('*'):
                        if file_path.is_file():
                            arcname = file_path.relative_to(temp_dir)
                            zf.write(file_path, arcname)

                logger.info(f"[PackageManager] 패키지 내보내기 완료: {output_file}")
                return True, f"패키지 저장 완료: {output_file.name}"

            finally:
                # 임시 폴더 정리
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[PackageManager] 패키지 내보내기 실패: {safe_error}")
            return False, f"내보내기 실패: {safe_error}"

    def _copy_voice_models_to_package(self, package: ChannelPackage, temp_dir: Path) -> None:
        """
        TTS 모델 및 참조 오디오를 패키지 임시 폴더로 복사

        voice_guides에서 has_model=True인 항목의 모델 파일을 복사
        """
        if not package.voice_guides:
            return

        models_dir = temp_dir / "models"
        audio_dir = temp_dir / "audio" / "ref_samples"

        for guide in package.voice_guides:
            if not isinstance(guide, VoiceGuide):
                guide = VoiceGuide.from_dict(guide)

            if not guide.has_model:
                continue

            role_id = guide.role_id

            # 1. GPT weights 복사
            if guide.gpt_weights_path:
                src_path = Path(guide.gpt_weights_path)
                if src_path.exists():
                    dst_dir = models_dir / role_id
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    dst_path = dst_dir / "gpt_weights.ckpt"
                    shutil.copy(src_path, dst_path)
                    logger.info(f"[PackageManager] GPT 모델 복사: {role_id}")

            # 2. SoVITS weights 복사
            if guide.sovits_weights_path:
                src_path = Path(guide.sovits_weights_path)
                if src_path.exists():
                    dst_dir = models_dir / role_id
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    dst_path = dst_dir / "sovits_weights.pth"
                    shutil.copy(src_path, dst_path)
                    logger.info(f"[PackageManager] SoVITS 모델 복사: {role_id}")

            # 3. 참조 오디오 복사 (감정별)
            if guide.ref_audio_paths:
                for emotion, audio_path in guide.ref_audio_paths.items():
                    src_path = Path(audio_path)
                    if src_path.exists():
                        dst_dir = audio_dir / role_id
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        dst_path = dst_dir / f"{emotion}.wav"
                        shutil.copy(src_path, dst_path)
                        logger.info(f"[PackageManager] 참조 오디오 복사: {role_id}/{emotion}")

    def generate_license_key(self, package_id: str, expires_at: Optional[str] = None) -> str:
        """
        패키지용 라이선스 키 생성

        Args:
            package_id: 패키지 ID
            expires_at: 만료일 (ISO format, None=영구)

        Returns:
            라이선스 키 (XXXX-XXXX-XXXX-XXXX 형식)
        """
        if self.security:
            return self.security.generate_license_for_package(package_id, expires_at)
        else:
            logger.warning("[PackageManager] 보안 모듈 없음, 키 생성 불가")
            return ""

    def create_package_from_current_settings(
        self,
        package_name: str,
        channel_type: str,
        author: str = "",
        description: str = ""
    ) -> ChannelPackage:
        """
        현재 GUI 설정에서 패키지 생성

        GUI의 현재 상태를 읽어서 ChannelPackage 객체 생성
        """
        import uuid

        package = ChannelPackage(
            package_id=str(uuid.uuid4())[:8],
            package_name=package_name,
            author=author,
            description=description,
            channel_type=channel_type,
            channel_display_name=package_name,
        )

        # 현재 설정에서 프로필 로드
        profile = self.config.PROFILES.get(channel_type, {})

        # SD 프롬프트 설정
        package.prompts.sd_positive = profile.get("sd_positive", "")
        package.prompts.sd_negative = profile.get("sd_negative", "")

        # 필수 모델 설정
        if channel_type == "horror":
            package.required_models["sd_checkpoint"] = RequiredModel(
                name=self.config.SD_MODEL_HORROR,
                type=ModelType.SD_CHECKPOINT.value,
                required=True,
                note="Civitai에서 다운로드 가능"
            )
            package.required_models["voice_narrator"] = RequiredModel(
                name="narrator",
                type=ModelType.SOVITS.value,
                required=True,
                note="패키지 판매자에게 문의하세요"
            )

            # 캐릭터 설정
            package.characters = [
                CharacterMapping(
                    role_id="narrator",
                    display_name="나레이터",
                    subtitle_color="#FFFFFF",
                    emotions=["calm", "fear", "sad"]
                )
            ]

            # v59.1.5: visual 기본 설정 (forced_style 포함)
            package.visual = {
                "character_system_enabled": False,
                "forced_style": {
                    "force_positive": "",
                    "force_negative": ""
                },
                "thumbnail_backgrounds": [],
                "safe_fallbacks": []
            }

        elif channel_type in ["daily_life_toon", "mystery_toon", "videotoon", "senior_touching", "senior_makjang", "senior"]:
            package.required_models["sd_checkpoint"] = RequiredModel(
                name=self.config.SD_MODEL_SENIOR,
                type=ModelType.SD_CHECKPOINT.value,
                required=True
            )

            # 시니어 캐릭터들
            colors = self.config.SENIOR_COLORS
            package.characters = [
                CharacterMapping(role_id="grandma", display_name="할머니",
                               subtitle_color=colors.get("grandma", "#FFD700")),
                CharacterMapping(role_id="grandpa", display_name="할아버지",
                               subtitle_color=colors.get("grandpa", "#00BFFF")),
                CharacterMapping(role_id="narrator", display_name="나레이터",
                               subtitle_color=colors.get("narrator", "#FFFFFF")),
            ]

            # v59.1.5: visual 기본 설정 (forced_style 포함)
            package.visual = {
                "character_system_enabled": False,
                "forced_style": {
                    "force_positive": "",
                    "force_negative": ""
                },
                "thumbnail_backgrounds": [],
                "safe_fallbacks": []
            }

        return package

    # ==================== Import (가져오기) ====================

    def import_package(self, package_path: str, license_key: Optional[str] = None) -> ImportResult:
        """
        패키지 가져오기 (사용자용) - 보안 검증 지원

        .revpack 파일을 읽어서 새 채널로 설치
        1. 패키지 소유권 확인 (Firebase 구독 시스템)
        2. 암호화된 패키지는 복호화 후 설치

        Args:
            package_path: .revpack 파일 경로
            license_key: 라이선스 키 (레거시, 현재 미사용)

        Returns:
            ImportResult
        """
        result = ImportResult(success=False)

        try:
            # 0. 패키지 ID 먼저 확인 (메타데이터만 읽기)
            pack_id = self._get_pack_id_from_file(package_path)

            if pack_id:
                # 패키지 소유권 확인 (Firebase)
                ownership_valid, ownership_msg = self._check_package_ownership(pack_id)
                if not ownership_valid:
                    result.error = ownership_msg
                    return result
                logger.info(f"[PackageManager] 패키지 소유권 확인됨: {pack_id}")

            # 1. 패키지 로드 (암호화된 경우 복호화)
            package = self._load_package_file(package_path, license_key)
            if not package:
                # 라이선스 키가 필요한 경우
                if self._check_if_license_required(package_path):
                    result.error = "LICENSE_REQUIRED"  # 특수 에러 코드
                else:
                    result.error = "패키지 파일을 읽을 수 없습니다."
                return result

            result.package = package

            # 2. 버전 호환성 체크
            version_ok, version_msg = self._check_version_compatibility(package)
            if not version_ok:
                result.error = version_msg
                return result
            if version_msg:
                result.warnings.append(version_msg)

            # 3. 라이센스 체크
            license_ok, license_msg = self._check_license(package)
            if not license_ok:
                result.error = license_msg
                return result

            # 4. 필수 모델 검증
            missing_models = self._validate_required_models(package)
            result.missing_models = missing_models

            # 필수 모델 중 누락된 것이 있으면 경고 (설치는 진행)
            critical_missing = [m for m in missing_models if m.is_critical]
            if critical_missing:
                result.warnings.append(
                    f"{len(critical_missing)}개의 필수 모델이 누락되었습니다. "
                    "기능이 제한될 수 있습니다."
                )

            # 5. TTS 모델 및 참조 오디오 설치 (패키지에 포함된 경우)
            installed_models = self._install_voice_models_from_package(package_path, package)
            if installed_models:
                logger.info(f"[PackageManager] TTS 모델 {len(installed_models)}개 설치됨")

            # 6. 채널 설정 저장
            channel_id = self._save_channel_config(package)
            result.channel_id = channel_id

            # 7. 캐시 업데이트
            self._loaded_packages[channel_id] = package

            result.success = True
            logger.info(f"[PackageManager] 패키지 가져오기 완료: {package.package_name}")

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[PackageManager] 패키지 가져오기 실패: {safe_error}")
            result.error = safe_error

        return result

    def _install_voice_models_from_package(
        self,
        package_path: str,
        package: ChannelPackage
    ) -> List[str]:
        """
        패키지에 포함된 TTS 모델 및 참조 오디오를 설치

        Args:
            package_path: .revpack 파일 경로
            package: 로드된 패키지 객체

        Returns:
            설치된 모델 role_id 목록
        """
        installed = []

        try:
            # 설치 대상 디렉토리
            models_base = Path(self.config.ASSETS_DIR) / "models" / package.channel_type

            zf, _zip_buffer = self._open_package_zip(package_path)
            with zf:
                namelist = zf.namelist()

                for guide in package.voice_guides:
                    if not isinstance(guide, VoiceGuide):
                        guide = VoiceGuide.from_dict(guide)

                    if not guide.has_model:
                        continue

                    role_id = guide.role_id
                    model_dir = models_base / role_id
                    model_dir.mkdir(parents=True, exist_ok=True)

                    # 1. GPT weights 추출
                    gpt_path_in_zip = f"models/{role_id}/gpt_weights.ckpt"
                    if gpt_path_in_zip in namelist:
                        dst_path = model_dir / "gpt_weights.ckpt"
                        with zf.open(gpt_path_in_zip) as src, open(dst_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        logger.info(f"[PackageManager] GPT 모델 설치: {role_id}")

                    # 2. SoVITS weights 추출
                    sovits_path_in_zip = f"models/{role_id}/sovits_weights.pth"
                    if sovits_path_in_zip in namelist:
                        dst_path = model_dir / "sovits_weights.pth"
                        with zf.open(sovits_path_in_zip) as src, open(dst_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        logger.info(f"[PackageManager] SoVITS 모델 설치: {role_id}")

                    # 3. 참조 오디오 추출
                    ref_audio_prefix = f"audio/ref_samples/{role_id}/"
                    ref_audio_files = [n for n in namelist if n.startswith(ref_audio_prefix)]

                    if ref_audio_files:
                        ref_dir = model_dir / "ref_samples"
                        ref_dir.mkdir(parents=True, exist_ok=True)

                        for audio_file in ref_audio_files:
                            filename = Path(audio_file).name
                            dst_path = ref_dir / filename
                            with zf.open(audio_file) as src, open(dst_path, 'wb') as dst:
                                shutil.copyfileobj(src, dst)
                        logger.info(f"[PackageManager] 참조 오디오 {len(ref_audio_files)}개 설치: {role_id}")

                    installed.append(role_id)

        except Exception as e:
            logger.error(f"[PackageManager] TTS 모델 설치 실패: {e}")

        return installed

    def _check_if_license_required(self, package_path: str) -> bool:
        """패키지가 라이선스 필요한지 확인 (복호화 없이 헤더만 체크)"""
        try:
            path = Path(package_path)
            zf, _zip_buffer = self._open_package_zip(package_path)
            with zf:
                # 암호화된 파일이 있는지 확인
                if self.ENCRYPTED_CONFIG_FILENAME in zf.namelist():
                    with zf.open(self.ENCRYPTED_CONFIG_FILENAME) as f:
                        data = f.read()
                        if self.security:
                            return self.security.check_license_required(data)
            return False
        except Exception:
            return False

    def _get_pack_id_from_file(self, package_path: str) -> Optional[str]:
        """
        패키지 파일에서 pack_id 추출 (소유권 검증용)

        암호화되지 않은 메타데이터에서 pack_id를 읽음
        """
        try:
            path = Path(package_path)
            zf, _zip_buffer = self._open_package_zip(package_path)
            with zf:
                namelist = zf.namelist()

                # 1. 암호화된 파일 - 보안 매니저로 헤더만 파싱
                if self.ENCRYPTED_CONFIG_FILENAME in namelist:
                    with zf.open(self.ENCRYPTED_CONFIG_FILENAME) as f:
                        data = f.read()
                        if self.security:
                            try:
                                # 복호화하여 pack_id 추출
                                decrypted = self.security.encryption.decrypt(data)
                                return decrypted.get('package_id') or decrypted.get('pack_id')
                            except Exception as e:
                                logger.warning(f"[PackageManager] 팩 복호화 실패: {e}")

                # 2. 평문 파일
                elif self.CONFIG_FILENAME in namelist:
                    with zf.open(self.CONFIG_FILENAME) as f:
                        data = json.load(f)
                        return data.get('package_id') or data.get('pack_id')

        except Exception as e:
            logger.debug(f"[PackageManager] pack_id 추출 실패: {e}")

        return None

    def _check_package_ownership(self, pack_id: str) -> Tuple[bool, str]:
        """
        패키지 소유권 확인 (Firebase 구독 시스템 연동)

        사용자의 구독 정보에서 owned_packs 배열 확인

        Args:
            pack_id: 패키지 ID

        Returns:
            (소유 여부, 메시지)
        """
        if not self.license_validator:
            # 라이선스 모듈 없으면 통과 (개발 모드)
            logger.warning("[PackageManager] 라이선스 모듈 없음, 소유권 검증 스킵")
            return True, "검증 스킵 (개발 모드)"

        try:
            return self.license_validator.check_package_ownership(pack_id)
        except Exception as e:
            logger.error(f"[PackageManager] 소유권 확인 오류: {e}")
            # 오류 시 실패 처리 (보안을 위해)
            return False, f"소유권 확인 중 오류 발생: {e}"

    def _load_package_file(self, package_path: str, license_key: Optional[str] = None) -> Optional[ChannelPackage]:
        """
        패키지 파일 로드 - 암호화 지원

        암호화된 패키지(.enc)와 평문 패키지(.json) 모두 지원
        """
        try:
            path = Path(package_path)

            if not path.exists():
                logger.error(f"[PackageManager] 파일 없음: {path}")
                return None

            # Zip 파일 열기
            zf, _zip_buffer = self._open_package_zip(package_path)
            with zf:
                namelist = zf.namelist()

                # 1. 암호화된 설정 파일 우선 확인
                if self.ENCRYPTED_CONFIG_FILENAME in namelist:
                    with zf.open(self.ENCRYPTED_CONFIG_FILENAME) as f:
                        encrypted_data = f.read()

                    if self.security:
                        # 보안 검증 및 복호화
                        success, msg, data = self.security.verify_and_decrypt(
                            encrypted_data,
                            license_key=license_key
                        )
                        if success and data:
                            logger.info("[PackageManager] 암호화된 패키지 복호화 성공")
                            package = ChannelPackage.from_dict(data)
                            if not isinstance(package.extra_config, dict):
                                package.extra_config = {}
                            package.extra_config["source_revpack"] = str(path)
                            return package
                        else:
                            logger.error(f"[PackageManager] 복호화 실패: {msg}")
                            return None
                    else:
                        logger.error("[PackageManager] 보안 모듈 없음, 암호화된 패키지 로드 불가")
                        return None

                # 2. 평문 설정 파일 확인 (레거시 호환)
                elif self.CONFIG_FILENAME in namelist:
                    with zf.open(self.CONFIG_FILENAME) as f:
                        data = json.load(f)
                        logger.info("[PackageManager] 평문 패키지 로드")
                        package = ChannelPackage.from_dict(data)
                        if not isinstance(package.extra_config, dict):
                            package.extra_config = {}
                        package.extra_config["source_revpack"] = str(path)
                        return package

                # 3. v57.7.1: 새로운 팩 형식 (manifest.json 기반)
                elif "manifest.json" in namelist or "manifest.json.enc" in namelist:
                    package = self._load_new_format_package(zf, namelist)
                    if package:
                        if not isinstance(package.extra_config, dict):
                            package.extra_config = {}
                        package.extra_config["source_revpack"] = str(path)
                    return package

                else:
                    logger.error(f"[PackageManager] config 파일 없음")
                    return None

        except zipfile.BadZipFile:
            logger.error(f"[PackageManager] 잘못된 패키지 파일: {package_path}")
        except json.JSONDecodeError as e:
            logger.error(f"[PackageManager] JSON 파싱 실패: {e}")
        except Exception as e:
            logger.error(f"[PackageManager] 패키지 로드 실패: {e}")

        return None

    def _load_new_format_package(self, zf: zipfile.ZipFile, namelist: list) -> Optional[ChannelPackage]:
        """
        v57.7.1: 새로운 팩 형식 로드 (pack_creator_full.py로 생성된 팩)

        manifest.json 기반 팩을 ChannelPackage로 변환
        """
        try:
            from config.pack_config import _decrypt_content, CRYPTO_AVAILABLE

            # 암호화 여부 감지
            is_encrypted = "manifest.json.enc" in namelist

            def read_file(filename: str) -> Optional[bytes]:
                """파일 읽기 (암호화 자동 처리)"""
                enc_name = filename + ".enc"
                if is_encrypted and enc_name in namelist:
                    if not CRYPTO_AVAILABLE:
                        logger.error("[PackageManager] 암호화 라이브러리 없음")
                        return None
                    encrypted = zf.read(enc_name)
                    return _decrypt_content(encrypted)
                elif filename in namelist:
                    return zf.read(filename)
                return None

            # 1. manifest.json 로드
            manifest_data = read_file("manifest.json")
            if not manifest_data:
                logger.error("[PackageManager] manifest.json 로드 실패")
                return None
            manifest = json.loads(manifest_data.decode('utf-8'))

            # 2. settings.json 로드
            settings_data = read_file("settings.json")
            settings = json.loads(settings_data.decode('utf-8')) if settings_data else {}

            # 3. topics.json 로드 (암호화 안 함)
            topics = {}
            if "topics.json" in namelist:
                topics = json.loads(zf.read("topics.json").decode('utf-8'))

            # 4. prompts 로드
            prompts = {}
            pd_data = read_file("prompts/pd_system.txt")
            if pd_data:
                prompts["pd_system"] = pd_data.decode('utf-8')

            writer_data = read_file("prompts/writer_system.txt")
            if writer_data:
                prompts["writer_system"] = writer_data.decode('utf-8')

            sd_data = read_file("prompts/sd_prompts.json")
            if sd_data:
                prompts["sd_prompts"] = json.loads(sd_data.decode('utf-8'))

            # 5. ChannelPackage 형식으로 변환
            pack_id = manifest.get("pack_id", "unknown")
            pack_name = manifest.get("pack_name", "Unknown Pack")
            channel_type = manifest.get("channel_type") or manifest.get("genre", "custom")

            # ChannelPackage 생성을 위한 데이터
            package_data = {
                "package_id": pack_id,
                "package_name": pack_name,
                "channel_type": channel_type,
                "channel_display_name": manifest.get("channel_display_name", pack_name),
                "version": manifest.get("version", "1.0.0"),
                "author": manifest.get("author", "Unknown"),
                # v59.1.2: 두 가지 키 이름 모두 지원 (min_reverie_version, reverie_version_min)
                "reverie_version_min": manifest.get("min_reverie_version") or manifest.get("reverie_version_min", "1"),
                "license": manifest.get("license", {"type": "free", "key_required": False}),

                # 프롬프트
                "prompts": {
                    "pd_system": prompts.get("pd_system", ""),
                    "writer_system": prompts.get("writer_system", ""),
                    "sd_prompts": prompts.get("sd_prompts", {}),
                    "topics": topics,
                },

                # 스타일/설정
                "style": settings.get("style", {}),
                "content": settings.get("content", {}),
                "characters": settings.get("characters", {}),
                "character_config": settings.get("character_config", {}),

                # 새 형식 표시
                "_new_format": True,
            }

            logger.info(f"[PackageManager] 새 형식 팩 로드 완료: {pack_name}")
            return ChannelPackage.from_dict(package_data)

        except Exception as e:
            logger.error(f"[PackageManager] 새 형식 팩 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _check_version_compatibility(self, package: ChannelPackage) -> Tuple[bool, str]:
        """버전 호환성 체크 (v59.1.2: 버전 문자열 파싱 개선)"""
        def parse_version(ver_str: str) -> int:
            """버전 문자열에서 주 버전 번호 추출 (예: "59.1.0" -> 59, "37" -> 37)"""
            if not ver_str:
                return 0
            # 첫 번째 숫자 부분만 추출
            parts = ver_str.replace("-", ".").split(".")
            try:
                return int(parts[0])
            except (ValueError, IndexError):
                return 0

        current = parse_version(REVERIE_VERSION)
        min_ver = parse_version(package.reverie_version_min or "0")
        max_ver = parse_version(package.reverie_version_max) if package.reverie_version_max else None

        if current < min_ver:
            return False, f"이 패키지는 Reverie v{min_ver} 이상이 필요합니다. (현재: v{current})"

        if max_ver and current > max_ver:
            return True, f"이 패키지는 v{max_ver}까지 테스트되었습니다. 일부 기능이 다르게 작동할 수 있습니다."

        return True, ""

    def _check_license(self, package: ChannelPackage) -> Tuple[bool, str]:
        """라이센스 체크"""
        license_info = package.license

        if isinstance(license_info, dict):
            license_type = license_info.get("type", "free")
            key_required = license_info.get("key_required", False)
            expires_at = license_info.get("expires_at")
        else:
            license_type = license_info.type
            key_required = license_info.key_required
            expires_at = license_info.expires_at

        # 무료 패키지는 바로 통과
        if license_type == "free":
            return True, ""

        # 유료/체험판 키 체크 (향후 구현)
        if key_required:
            pass

        # 만료일 체크
        if expires_at:
            try:
                expire_date = datetime.fromisoformat(expires_at)
                if datetime.now() > expire_date:
                    return False, "패키지 라이센스가 만료되었습니다."
            except ValueError:
                pass

        return True, ""

    def _validate_required_models(self, package: ChannelPackage) -> List[ModelValidationResult]:
        """필수 모델 검증"""
        results = []

        for model_key, model_info in package.required_models.items():
            if isinstance(model_info, dict):
                model_info = RequiredModel.from_dict(model_info)

            found = False
            local_path = None

            # 모델 타입에 따라 검색 경로 결정
            model_type = model_info.type

            if model_type == ModelType.SD_CHECKPOINT.value:
                # SD WebUI 모델 폴더 검색
                found, local_path = self._find_sd_model(model_info.name)

            elif model_type == ModelType.LORA.value:
                found, local_path = self._find_lora_model(model_info.name)

            elif model_type in [ModelType.SOVITS.value, ModelType.GPT.value]:
                # 음성 모델 검색
                found, local_path = self._find_voice_model(model_info.name)

            results.append(ModelValidationResult(
                model_key=model_key,
                model_info=model_info,
                found=found,
                local_path=local_path
            ))

        return results

    def _find_sd_model(self, model_name: str) -> Tuple[bool, Optional[str]]:
        """SD 모델 찾기"""
        try:
            from utils.sd_model_manager import get_sd_model_manager
            manager = get_sd_model_manager()
            models = manager.get_models()

            for model in models:
                if model.filename == model_name or model.title == model_name:
                    return True, model.filename

        except Exception as e:
            logger.debug(f"[PackageManager] SD 모델 검색 실패: {e}")

        return False, None

    def _find_lora_model(self, model_name: str) -> Tuple[bool, Optional[str]]:
        """LoRA 모델 찾기"""
        try:
            from utils.sd_model_manager import get_sd_model_manager
            manager = get_sd_model_manager()
            loras = manager.get_loras()

            for lora in loras:
                if lora.filename == model_name or lora.name == model_name:
                    return True, lora.filename

        except Exception as e:
            logger.debug(f"[PackageManager] LoRA 검색 실패: {e}")

        return False, None

    def _find_voice_model(self, model_name: str) -> Tuple[bool, Optional[str]]:
        """음성 모델 찾기"""
        # assets/models 하위에서 검색
        models_dir = Path(self.config.ASSETS_DIR) / "models"

        if not models_dir.exists():
            return False, None

        # 재귀적으로 모델 폴더 검색
        for model_dir in models_dir.rglob("*"):
            if model_dir.is_dir() and model_dir.name == model_name:
                # gpt_weights.ckpt 또는 sovits_weights.pth 존재 확인
                if (model_dir / "gpt_weights.ckpt").exists() or \
                   (model_dir / "sovits_weights.pth").exists():
                    return True, str(model_dir)

        return False, None

    def _sanitize_for_filename(self, name: str) -> str:
        """
        v57.7.6: 파일명에 사용할 수 없는 문자 제거/변환

        Windows 금지 문자: \ / : * ? " < > |
        추가로 # 등 특수문자도 안전하게 치환

        Args:
            name: 원본 문자열

        Returns:
            파일명에 안전한 문자열
        """
        import re
        # Windows 금지 문자 + # 등 특수문자를 _로 치환
        safe_name = re.sub(r'[\\/*?:"<>|#]', '_', name)
        # 연속된 _ 를 하나로
        safe_name = re.sub(r'_+', '_', safe_name)
        # 앞뒤 _ 제거
        safe_name = safe_name.strip('_')
        return safe_name if safe_name else "unknown"

    def _save_channel_config(self, package: ChannelPackage) -> str:
        """
        채널 설정 저장

        v57.7.6: channel_type에 특수문자(/, \, # 등)가 있어도 안전하게 저장
        """
        # v57.7.6: channel_type sanitize (공포/미스터리 → 공포_미스터리)
        safe_type = self._sanitize_for_filename(package.channel_type)
        channel_id = f"{safe_type}_{package.package_id}"

        config_path = self.channels_dir / f"{channel_id}.json"

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(package.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"[PackageManager] 채널 설정 저장: {config_path}")
        return channel_id

    # ==================== 채널 관리 ====================

    def get_installed_channels(self) -> List[Tuple[str, ChannelPackage]]:
        """설치된 채널 목록"""
        channels = []

        for config_file in self.channels_dir.glob("*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    package = ChannelPackage.from_dict(data)
                    channel_id = config_file.stem
                    channels.append((channel_id, package))
            except Exception as e:
                logger.warning(f"[PackageManager] 채널 로드 실패: {config_file}, {e}")

        return channels

    def list_installed_packages(self) -> Dict[str, Dict[str, Any]]:
        """설치된 패키지 목록 (간단한 딕셔너리 형태)"""
        packages = {}
        package_best = {}

        for config_file in self.channels_dir.glob("*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    channel_id = config_file.stem
                    package_info = {
                        "channel_id": channel_id,
                        "package_id": data.get("package_id", channel_id),
                        "package_name": data.get("package_name", channel_id),
                        "version": data.get("version", "1.0.0"),
                        "author": data.get("author", ""),
                        "channel_type": data.get("channel_type", "unknown"),
                        "description": data.get("description", ""),
                    }

                    extra_config = data.get("extra_config", {}) or {}
                    package_info["source_revpack"] = extra_config.get("source_revpack", "")

                    score = 0
                    if package_info["source_revpack"]:
                        score += 10
                    if package_info["channel_type"] == package_info["package_id"]:
                        score += 3
                    if package_info["channel_id"].startswith(f"{package_info['channel_type']}_"):
                        score += 1

                    existing = package_best.get(package_info["package_id"])
                    if not existing or score >= existing["score"]:
                        package_best[package_info["package_id"]] = {
                            "score": score,
                            "info": package_info,
                        }
            except Exception as e:
                logger.warning(f"[PackageManager] 패키지 정보 로드 실패: {config_file}, {e}")

        for entry in package_best.values():
            info = entry["info"]
            channel_id = info.pop("channel_id")
            packages[channel_id] = info

        return packages

    def get_channel(self, channel_id: str) -> Optional[ChannelPackage]:
        """특정 채널 정보 조회"""
        def _repair_package(package: ChannelPackage) -> ChannelPackage:
            if not isinstance(package.extra_config, dict):
                package.extra_config = {}

            if not package.extra_config.get("source_revpack") and package.package_id:
                candidate = Path(self.config.ASSETS_DIR) / "packs" / f"{package.package_id}.revpack"
                if candidate.exists():
                    package.extra_config["source_revpack"] = str(candidate)
            return package

        # 캐시 확인
        if channel_id in self._loaded_packages:
            return _repair_package(self._loaded_packages[channel_id])

        # 파일에서 로드
        config_path = self.channels_dir / f"{channel_id}.json"
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    package = _repair_package(ChannelPackage.from_dict(data))
                    self._loaded_packages[channel_id] = package
                    return package
            except Exception as e:
                logger.error(f"[PackageManager] 채널 로드 실패: {e}")

        return None

    def delete_channel(self, channel_id: str) -> bool:
        """채널 삭제"""
        config_path = self.channels_dir / f"{channel_id}.json"

        if config_path.exists():
            try:
                config_path.unlink()
                self._loaded_packages.pop(channel_id, None)
                logger.info(f"[PackageManager] 채널 삭제: {channel_id}")
                return True
            except Exception as e:
                logger.error(f"[PackageManager] 채널 삭제 실패: {e}")

        return False


# 싱글톤 인스턴스
_manager_instance: Optional[PackageManager] = None

def get_package_manager() -> PackageManager:
    """PackageManager 싱글톤 인스턴스 반환"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PackageManager()
    return _manager_instance
