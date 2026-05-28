# Reverie Insight - .revpack Generator
# Version: 1.5.0

"""
.revpack 생성 및 로드 모듈

CloneRecipe (분석 결과) → ChannelPackage (패키지 구조) → .revpack (암호화 파일)

주요 기능:
1. CloneRecipe → ChannelPackage 변환
2. style_guide.json 생성 (SD 프롬프트, 색상 등)
3. prompts/ 폴더 (장르별 프롬프트)
4. emotions.json 생성 (감정 목록)
5. TTS 가이드 문서 번들링
6. AES-256 암호화 + HMAC 검증
7. v1.5.0: .revpack 로드 기능 (Studio 연동)
"""

import os
import json
import uuid
import zipfile
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)

# ============================================================
# Import: 기존 패키지 시스템
# ============================================================

try:
    from utils.package_manager import (
        ChannelPackage,
        RequiredModel,
        CharacterMapping,
        VoiceGuide,
        PromptConfig,
        ThemeConfig,
        LicenseInfo,
        ModelType,
    )
    # v63: 팩 암호화/서명 제거 (개인용) — package_security 의존 삭제
    PACKAGE_SYSTEM_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[RevpackGenerator] 패키지 시스템 Import 실패: {e}")
    PACKAGE_SYSTEM_AVAILABLE = False

# Import: 스타일 분석기 데이터 클래스
try:
    from insight.style_analyzer import (
        CloneRecipe,
        TTSGuide,
        ColorPalette,
        SDModelRecommendation,
        TTS_PRESETS,
    )
    STYLE_ANALYZER_AVAILABLE = True
except ImportError:
    STYLE_ANALYZER_AVAILABLE = False


# ============================================================
# 장르별 프롬프트 템플릿
# ============================================================

GENRE_PROMPT_TEMPLATES = {
    "horror": {
        "pd_system_prompt": """당신은 공포 콘텐츠 전문 PD입니다.
시청자가 몰입할 수 있는 긴장감 있는 스토리를 구성하세요.
- 서서히 고조되는 공포 분위기
- 예상치 못한 반전
- 감각적 묘사 (소리, 어둠, 냄새)
- 화자의 심리적 불안감 표현""",

        "writer_system_prompt": """공포 이야기 전문 작가입니다.
문장 스타일:
- 짧고 강렬한 문장으로 긴장감 유지
- "..." 사용하여 불안감 조성
- 감각적 묘사 중시 (싸늘한 손길, 축축한 공기)
- 1인칭 또는 2인칭 시점 권장""",

        "topic_templates": [
            "폐가에서 발견된 일기장의 비밀",
            "매일 밤 3시에 울리는 초인종",
            "거울 속에서 나를 바라보는 또 다른 나",
            "할머니가 절대 열지 말라던 다락방",
            "엘리베이터에서 함께 탄 그 사람",
        ],

        "banned_keywords": ["자살", "자해", "아동학대", "성범죄"],
    },

    "mystery": {
        "pd_system_prompt": """당신은 미스터리/사건 콘텐츠 PD입니다.
시청자가 함께 추리할 수 있는 구조로 구성하세요.
- 명확한 단서 제시
- 논리적인 전개
- 적절한 반전 배치
- 사실적인 디테일""",

        "writer_system_prompt": """미스터리 전문 작가입니다.
문장 스타일:
- 객관적이고 다큐멘터리 스타일
- 정확한 시간/장소 표기
- 의문을 유발하는 질문형 문장
- 중립적 톤 유지""",

        "topic_templates": [
            "20년 미제 사건의 새로운 증거",
            "온라인에서 사라진 사람들",
            "범인이 남긴 암호 메시지",
            "CCTV에 찍힌 의문의 인물",
        ],

        "banned_keywords": ["실제 피해자 이름", "허위 사실"],
    },

    "entertainment": {
        "pd_system_prompt": """당신은 예능/재미 콘텐츠 PD입니다.
시청자가 즐겁게 볼 수 있는 가벼운 콘텐츠를 만드세요.
- 밝고 경쾌한 분위기
- 공감되는 상황
- 적절한 유머
- 트렌디한 소재""",

        "writer_system_prompt": """예능 콘텐츠 작가입니다.
문장 스타일:
- 친근하고 캐주얼한 말투
- 이모티콘/효과음 활용
- 짧은 문장 위주
- 리액션 강조""",

        "topic_templates": [
            "요즘 핫한 밈 총정리",
            "직장인 공감 에피소드",
            "반려동물 귀여운 순간들",
            "요리 초보의 도전기",
        ],

        "banned_keywords": ["비하", "혐오", "정치적 편향"],
    },

    "education": {
        "pd_system_prompt": """당신은 교육 콘텐츠 PD입니다.
복잡한 내용을 쉽게 전달하는 구조를 만드세요.
- 단계별 설명
- 실생활 예시
- 핵심 포인트 강조
- 시각 자료 활용 포인트""",

        "writer_system_prompt": """교육 콘텐츠 작가입니다.
문장 스타일:
- 명확하고 간결한 문장
- 전문 용어는 쉽게 풀어서 설명
- 예시와 비유 적극 활용
- 요약 제공""",

        "topic_templates": [
            "10분 안에 배우는 기초 경제",
            "알기 쉬운 역사 이야기",
            "생활 속 과학 원리",
            "쉽게 배우는 IT 상식",
        ],

        "banned_keywords": ["허위 정보", "의료 오진"],
    },

    "news": {
        "pd_system_prompt": """당신은 뉴스 콘텐츠 PD입니다.
정확한 정보를 신속하게 전달하세요.
- 6하원칙 준수
- 출처 명시
- 균형 잡힌 시각
- 핵심 사실 우선""",

        "writer_system_prompt": """뉴스 콘텐츠 작가입니다.
문장 스타일:
- 객관적이고 간결한 문체
- 사실과 의견 구분
- 인용문 정확히 표기
- 결론 먼저, 상세 후""",

        "topic_templates": [
            "오늘의 주요 뉴스 요약",
            "주간 경제 동향",
            "기술 업계 최신 소식",
        ],

        "banned_keywords": ["가짜뉴스", "선정적 표현", "특정 정당 옹호"],
    },
}

# 기본 네거티브 프롬프트
DEFAULT_NEGATIVE_PROMPT = """(worst quality:1.4), (low quality:1.4), (normal quality:1.4),
lowres, bad anatomy, bad hands, text, error, missing fingers,
extra digit, fewer digits, cropped, jpeg artifacts, signature,
watermark, username, blurry, artist name, nsfw"""


# ============================================================
# RevpackGenerator 클래스
# ============================================================

class RevpackGenerator:
    """
    .revpack 생성기

    CloneRecipe → ChannelPackage → .revpack
    """

    PACKAGE_VERSION = "1.4.0"
    REVERIE_VERSION_MIN = "37"

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Args:
            output_dir: .revpack 출력 디렉토리 (기본: data/exports)
        """
        if output_dir is None:
            try:
                from config.settings import config as app_config

                output_dir = Path(app_config.EXPORTS_DIR)
            except Exception:
                output_dir = Path("data/exports")

        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # v63: 팩 암호화/서명 제거 (개인용) — 평문 팩만 생성
        self.security = None

    # ============================================================
    # CloneRecipe → ChannelPackage 변환
    # ============================================================

    def recipe_to_package(
        self,
        recipe: 'CloneRecipe',
        package_name: Optional[str] = None,
        author: str = "Reverie Insight",
        description: Optional[str] = None,
        license_type: str = "paid"
    ) -> 'ChannelPackage':
        """
        CloneRecipe를 ChannelPackage로 변환

        Args:
            recipe: 클론 레시피 (분석 결과)
            package_name: 패키지 이름 (기본: 영상 제목 기반)
            author: 제작자
            description: 설명
            license_type: 라이센스 타입 (free, paid, trial)

        Returns:
            ChannelPackage 객체
        """
        if not PACKAGE_SYSTEM_AVAILABLE:
            raise RuntimeError("패키지 시스템을 사용할 수 없습니다.")

        # 패키지 ID 생성
        package_id = str(uuid.uuid4())[:8]

        # 패키지 이름 결정
        if not package_name:
            # 채널명 기반 or 스타일 기반
            channel = recipe.channel_title or "Unknown"
            style = recipe.style_type or "general"
            package_name = f"{channel} - {style.replace('_', ' ').title()} Pack"

        # 설명 자동 생성
        if not description:
            description = self._generate_description(recipe)

        # 채널 타입 결정 (TTS 프리셋의 채널 장르)
        channel_type = self._determine_channel_type(recipe)

        # ChannelPackage 생성
        package = ChannelPackage(
            package_id=package_id,
            package_name=package_name,
            version=self.PACKAGE_VERSION,
            author=author,
            description=description,
            created_at=datetime.now().isoformat(),
            reverie_version_min=self.REVERIE_VERSION_MIN,
            license=LicenseInfo(
                type=license_type,
                key_required=(license_type == "paid"),
            ),
            channel_type=channel_type,
            channel_display_name=package_name,
        )

        # === 필수 모델 설정 ===
        package.required_models = self._build_required_models(recipe)

        # === 캐릭터 매핑 ===
        package.characters = self._build_characters(recipe)

        # === 목소리 가이드 ===
        package.voice_guides = self._build_voice_guides(recipe)

        # === 프롬프트 설정 ===
        package.prompts = self._build_prompts(recipe, channel_type)

        # === 테마 설정 ===
        package.theme = self._build_theme(recipe)

        # === 오디오 설정 ===
        package.audio_config = self._build_audio_config(recipe)

        # === 추가 설정 (분석 메타데이터) ===
        package.extra_config = self._build_extra_config(recipe)

        return package

    def _generate_description(self, recipe: 'CloneRecipe') -> str:
        """자동 설명 생성"""
        lines = [
            f"AI 분석 기반 자동 생성 패키지",
            f"원본 스타일: {recipe.style_type}",
            f"복제 난이도: {recipe.clone_difficulty}",
            f"복제 가능성: {recipe.feasibility_score}/100",
        ]

        if recipe.sd_models:
            lines.append(f"추천 모델: {recipe.sd_models[0].model_name}")

        return " | ".join(lines)

    def _determine_channel_type(self, recipe: 'CloneRecipe') -> str:
        """채널 타입 결정"""
        # TTS 가이드에서 힌트 추출
        if recipe.tts_guide:
            tone = recipe.tts_guide.voice_tone.lower()

            if any(k in tone for k in ["scary", "mysterious", "whisper", "horror"]):
                return "horror"
            elif any(k in tone for k in ["serious", "detective", "investigation"]):
                return "mystery"
            elif any(k in tone for k in ["energetic", "fun", "casual", "friendly"]):
                return "entertainment"
            elif any(k in tone for k in ["professional", "clear", "educational"]):
                return "education"
            elif any(k in tone for k in ["neutral", "news", "anchor"]):
                return "news"

        # 스타일 기반 추측
        style = recipe.style_type.lower()

        if style in ["silhouette", "ai_generated"]:
            return "horror"
        elif style in ["slideshow", "stock_footage"]:
            return "education"
        elif style in ["2d_anime", "lo-fi"]:
            return "entertainment"

        return "entertainment"  # 기본값

    def _build_required_models(self, recipe: 'CloneRecipe') -> Dict[str, 'RequiredModel']:
        """필수 모델 설정"""
        models = {}

        # SD 체크포인트
        if recipe.sd_models:
            primary_model = recipe.sd_models[0]
            models["sd_checkpoint"] = RequiredModel(
                name=primary_model.model_name,
                type=ModelType.SD_CHECKPOINT.value,
                required=True,
                download_url=primary_model.civitai_url or "",
                note=primary_model.match_reason,
            )

        # LoRA
        for i, lora_name in enumerate(recipe.lora_recommendations[:3]):
            models[f"lora_{i+1}"] = RequiredModel(
                name=lora_name,
                type=ModelType.LORA.value,
                required=False,
                note="추천 LoRA (선택사항)",
            )

        # TTS 모델 (가이드만 제공, 실제 모델은 사용자가 학습)
        models["voice_narrator"] = RequiredModel(
            name="narrator",
            type=ModelType.SOVITS.value,
            required=True,
            note="TTS 가이드 참조하여 학습 필요",
        )

        return models

    def _build_characters(self, recipe: 'CloneRecipe') -> List['CharacterMapping']:
        """캐릭터 매핑"""
        characters = []

        # 나레이터 기본 생성
        emotions = []
        if recipe.tts_guide:
            emotions = recipe.tts_guide.required_emotions[:5]

        # v56.8: Qwen3-TTS 7가지 감정으로 기본값 변경
        narrator = CharacterMapping(
            role_id="narrator",
            display_name="나레이터",
            voice_model="narrator",
            subtitle_color="#FFFFFF",
            emotions=emotions or ["calm", "sad", "scared", "happy"],
        )
        characters.append(narrator)

        return characters

    def _build_voice_guides(self, recipe: 'CloneRecipe') -> List['VoiceGuide']:
        """
        목소리 가이드 생성

        v56.8: Qwen3-TTS VoiceDesign 지원 추가
        - GPT-SoVITS: weights 경로 + 참조 오디오
        - Qwen3-TTS: instruct 텍스트 + 캐릭터 시드
        """
        guides = []

        if recipe.tts_guide:
            tts = recipe.tts_guide
            age_range = self._map_age_range(tts.voice_age)

            # v56.8: Qwen3-TTS 설정 자동 생성
            qwen3_char_type, qwen3_instruct = self._build_qwen3_config(
                tts.voice_gender, age_range, tts.voice_tone
            )
            qwen3_seed = self._generate_character_seed(
                f"narrator_{recipe.channel_title}"
            )

            guide = VoiceGuide(
                role_id="narrator",
                display_name="나레이터",
                gender=tts.voice_gender,
                age_range=age_range,
                tone_description=tts.voice_tone,
                reference_style=f"{recipe.channel_title} 스타일",
                required_emotions=tts.required_emotions,
                sample_requirements="감정당 3~5초 x 3개 샘플 녹음",
                post_processing="채널 스타일에 맞게 조정",
                notes=tts.elevenlabs_hints,
                has_model=False,  # GPT-SoVITS 모델은 사용자가 학습
                # Qwen3 path is retained for legacy imports only; new packs use SoVITS by default.
                tts_engine="sovits",
                qwen3_character_type=qwen3_char_type,
                qwen3_instruct=qwen3_instruct,
                qwen3_character_seed=qwen3_seed,
            )
            guides.append(guide)

        return guides

    def _build_qwen3_config(
        self, gender: str, age_range: str, tone: str
    ) -> Tuple[str, str]:
        """
        Qwen3-TTS VoiceDesign 설정 자동 생성

        Args:
            gender: male/female
            age_range: child/teen/adult/senior
            tone: 톤 설명

        Returns:
            (character_type, instruct)
        """
        # 캐릭터 타입 매핑
        char_map = {
            ("male", "senior"): "grandpa",
            ("female", "senior"): "grandma",
            ("male", "adult"): "man",
            ("female", "adult"): "woman",
            ("male", "teen"): "young_man",
            ("female", "teen"): "young_woman",
            ("male", "child"): "young_man",
            ("female", "child"): "young_woman",
        }
        char_type = char_map.get((gender, age_range), "narrator")

        # instruct 템플릿
        age_desc = {
            "senior": "70+ years old",
            "adult": "40-50 years old",
            "teen": "20-30 years old",
            "child": "10-15 years old",
        }.get(age_range, "30-40 years old")

        gender_desc = "male" if gender == "male" else "female"
        nationality = "Korean"

        instruct = (
            f"A {nationality} {gender_desc} voice, {age_desc}. "
            f"{tone}. "
            f"Clear and natural speaking style for storytelling."
        )

        return char_type, instruct

    def _generate_character_seed(self, character_id: str) -> int:
        """
        캐릭터 ID → 시드 값 변환 (일관성 보장)

        동일 character_id → 동일 시드 → 동일 목소리
        """
        import hashlib
        hash_bytes = hashlib.md5(character_id.encode('utf-8')).digest()[:8]
        return int.from_bytes(hash_bytes, byteorder='big') % (2**31)

    def _map_age_range(self, voice_age: str) -> str:
        """voice_age → age_range 매핑"""
        mapping = {
            "child": "child",
            "young": "teen",
            "adult": "adult",
            "elderly": "senior",
        }
        return mapping.get(voice_age, "adult")

    def _build_prompts(self, recipe: 'CloneRecipe', channel_type: str) -> 'PromptConfig':
        """프롬프트 설정"""
        # 장르 템플릿 가져오기
        genre_template = GENRE_PROMPT_TEMPLATES.get(
            channel_type,
            GENRE_PROMPT_TEMPLATES["entertainment"]
        )

        # SD 프롬프트
        sd_positive = recipe.prompt_template or ""
        sd_negative = recipe.negative_prompt or DEFAULT_NEGATIVE_PROMPT

        # 색상 팔레트 정보 추가
        if recipe.color_palette:
            palette = recipe.color_palette
            color_hint = f"({palette.mood} atmosphere:1.2), ({palette.brightness} lighting:1.1)"
            sd_positive = f"{color_hint}, {sd_positive}"

        return PromptConfig(
            pd_system_prompt=genre_template["pd_system_prompt"],
            writer_system_prompt=genre_template["writer_system_prompt"],
            sd_positive=sd_positive,
            sd_negative=sd_negative,
            topic_templates=genre_template["topic_templates"],
            banned_keywords=genre_template["banned_keywords"],
        )

    def _build_theme(self, recipe: 'CloneRecipe') -> 'ThemeConfig':
        """테마 설정 (색상 팔레트 기반)"""
        theme = ThemeConfig()

        if recipe.color_palette and recipe.color_palette.dominant_colors:
            colors = recipe.color_palette.dominant_colors

            # 첫 번째 색상 → 주 색상
            if len(colors) > 0:
                r, g, b = colors[0]
                theme.primary_color = f"#{r:02X}{g:02X}{b:02X}"

            # 두 번째 색상 → 강조 색상
            if len(colors) > 1:
                r, g, b = colors[1]
                theme.accent_color = f"#{r:02X}{g:02X}{b:02X}"

            # 밝기에 따른 배경색
            if recipe.color_palette.brightness == "dark":
                theme.background_color = "#121212"
            elif recipe.color_palette.brightness == "bright":
                theme.background_color = "#FAFAFA"
            else:
                theme.background_color = "#1E1E1E"

        return theme

    def _build_audio_config(self, recipe: 'CloneRecipe') -> Dict:
        """오디오 설정"""
        config = {
            "default_emotion": "calm",
            "speech_rate": 1.0,
            "pitch_shift": 0,
        }

        # 장르별 조정
        channel_type = self._determine_channel_type(recipe)

        if channel_type == "horror":
            config["speech_rate"] = 0.9
            config["default_emotion"] = "whisper"
        elif channel_type == "news":
            config["speech_rate"] = 1.1
            config["default_emotion"] = "neutral"
        elif channel_type == "entertainment":
            config["speech_rate"] = 1.05
            config["default_emotion"] = "happy"

        return config

    def _build_extra_config(self, recipe: 'CloneRecipe') -> Dict:
        """추가 설정 (분석 메타데이터)"""
        extra = {
            "source_video": {
                "video_id": recipe.video_id,
                "video_title": recipe.video_title,
                "channel_title": recipe.channel_title,
            },
            "analysis": {
                "content_type": recipe.content_type,
                "style_type": recipe.style_type,
                "feasibility_score": recipe.feasibility_score,
                "clone_difficulty": recipe.clone_difficulty,
                "analyzed_at": recipe.analyzed_at,
                "analyzer_version": recipe.analysis_version,
            },
            "sd_models": [
                {
                    "name": m.model_name,
                    "type": m.model_type,
                    "url": m.civitai_url,
                    "reason": m.match_reason,
                }
                for m in recipe.sd_models
            ],
            "lora_recommendations": recipe.lora_recommendations,
        }

        # 색상 팔레트
        if recipe.color_palette:
            extra["color_palette"] = {
                "dominant_colors": [
                    f"#{r:02X}{g:02X}{b:02X}"
                    for r, g, b in recipe.color_palette.dominant_colors
                ],
                "color_names": recipe.color_palette.color_names,
                "brightness": recipe.color_palette.brightness,
                "saturation": recipe.color_palette.saturation,
                "mood": recipe.color_palette.mood,
            }

        return extra

    # ============================================================
    # .revpack 생성
    # ============================================================

    def generate_revpack(
        self,
        recipe: 'CloneRecipe',
        output_path: Optional[Path] = None,
        package_name: Optional[str] = None,
        author: str = "Reverie Insight",
        encrypt: bool = True,
        require_license: bool = True,
        include_tts_guide: bool = True,
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        .revpack 파일 생성

        Args:
            recipe: 클론 레시피
            output_path: 출력 경로 (없으면 자동 생성)
            package_name: 패키지 이름
            author: 제작자
            encrypt: 암호화 여부
            require_license: 라이선스 필요 여부
            include_tts_guide: TTS 가이드 마크다운 포함

        Returns:
            (성공여부, 메시지, 파일경로)
        """
        if not PACKAGE_SYSTEM_AVAILABLE:
            return False, "패키지 시스템을 사용할 수 없습니다.", None

        try:
            # 1. CloneRecipe → ChannelPackage
            license_type = "paid" if require_license else "free"
            package = self.recipe_to_package(
                recipe,
                package_name=package_name,
                author=author,
                license_type=license_type,
            )

            # 2. 출력 경로 결정
            if not output_path:
                safe_name = self._safe_filename(package.package_name)
                output_path = self.output_dir / f"{safe_name}_{package.package_id}.revpack"
            else:
                output_path = Path(output_path)
                if not output_path.suffix:
                    output_path = output_path.with_suffix(".revpack")

            # 3. 임시 폴더 생성
            temp_dir = output_path.parent / f"_temp_{package.package_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                # 4. 패키지 데이터 저장
                self._write_package_data(temp_dir, package, encrypt, require_license)

                # 5. 추가 파일 생성
                self._write_style_guide(temp_dir, recipe, package)
                self._write_emotions_json(temp_dir, recipe)
                self._write_prompts_folder(temp_dir, package)

                # 6. TTS 가이드 (마크다운)
                if include_tts_guide:
                    self._write_tts_guide_md(temp_dir, recipe)

                # 7. 에셋 폴더
                assets_dir = temp_dir / "assets"
                assets_dir.mkdir(exist_ok=True)

                # 8. Zip으로 압축
                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for file_path in temp_dir.rglob('*'):
                        if file_path.is_file():
                            arcname = file_path.relative_to(temp_dir)
                            zf.write(file_path, arcname)

                logger.info(f"[RevpackGenerator] .revpack 생성 완료: {output_path}")
                return True, f"패키지 생성 완료: {output_path.name}", output_path

            finally:
                # 임시 폴더 정리
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[RevpackGenerator] .revpack 생성 실패: {safe_error}")
            return False, f"생성 실패: {safe_error}", None

    def _safe_filename(self, name: str) -> str:
        """안전한 파일명 생성"""
        # 특수문자 제거
        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
        # 공백 → 언더스코어
        safe = safe.replace(" ", "_")
        # 연속 언더스코어 정리
        while "__" in safe:
            safe = safe.replace("__", "_")
        return safe[:50]  # 최대 50자

    def _write_package_data(
        self,
        temp_dir: Path,
        package: 'ChannelPackage',
        encrypt: bool,
        require_license: bool,
    ):
        """패키지 데이터 저장 (암호화 옵션)"""
        package_data = package.to_dict()

        if encrypt and self.security:
            # 암호화된 바이너리로 저장
            encrypted_data = self.security.secure_package_data(
                package_data,
                require_license=require_license,
                bind_hardware=False,
            )
            config_path = temp_dir / "channel_config.enc"
            with open(config_path, 'wb') as f:
                f.write(encrypted_data)
            logger.info("[RevpackGenerator] 암호화된 설정 저장")
        else:
            # 평문 JSON
            config_path = temp_dir / "channel_config.json"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(package_data, f, ensure_ascii=False, indent=2)
            logger.info("[RevpackGenerator] 평문 설정 저장")

    def _write_style_guide(
        self,
        temp_dir: Path,
        recipe: 'CloneRecipe',
        package: 'ChannelPackage',
    ):
        """style_guide.json 생성 (SD 프롬프트, 색상 등)"""
        style_data = {
            "version": "1.4.0",
            "style_type": recipe.style_type,
            "content_type": recipe.content_type,

            # SD 설정
            "sd": {
                "positive_prompt": package.prompts.sd_positive,
                "negative_prompt": package.prompts.sd_negative,
                "recommended_models": [
                    {
                        "name": m.model_name,
                        "type": m.model_type,
                        "civitai_url": m.civitai_url,
                    }
                    for m in recipe.sd_models
                ],
                "recommended_loras": recipe.lora_recommendations,
            },

            # 색상 팔레트
            "color_palette": None,

            # 복제 정보
            "clone_info": {
                "difficulty": recipe.clone_difficulty,
                "feasibility_score": recipe.feasibility_score,
                "tips": recipe.sd_models[0].match_reason if recipe.sd_models else "",
            }
        }

        # 색상 팔레트
        if recipe.color_palette:
            style_data["color_palette"] = {
                "dominant_colors_hex": [
                    f"#{r:02X}{g:02X}{b:02X}"
                    for r, g, b in recipe.color_palette.dominant_colors
                ],
                "color_names": recipe.color_palette.color_names,
                "brightness": recipe.color_palette.brightness,
                "saturation": recipe.color_palette.saturation,
                "mood": recipe.color_palette.mood,
            }

        style_path = temp_dir / "style_guide.json"
        with open(style_path, 'w', encoding='utf-8') as f:
            json.dump(style_data, f, ensure_ascii=False, indent=2)

    def _write_emotions_json(self, temp_dir: Path, recipe: 'CloneRecipe'):
        """emotions.json 생성"""
        emotions_data = {
            "version": "1.4.0",
            "default_emotion": "calm",
            "emotions": {},
        }

        if recipe.tts_guide:
            for emotion in recipe.tts_guide.required_emotions:
                sample = recipe.tts_guide.sample_scripts.get(emotion, "")
                emotions_data["emotions"][emotion] = {
                    "display_name": self._emotion_display_name(emotion),
                    "sample_script": sample,
                    "description": self._emotion_description(emotion),
                }

        emotions_path = temp_dir / "emotions.json"
        with open(emotions_path, 'w', encoding='utf-8') as f:
            json.dump(emotions_data, f, ensure_ascii=False, indent=2)

    def _emotion_display_name(self, emotion: str) -> str:
        """감정 표시명"""
        names = {
            "calm": "차분",
            "whisper": "속삭임",
            "fear": "두려움",
            "shock": "충격",
            "crying": "울음",
            "happy": "행복",
            "excited": "신남",
            "sad": "슬픔",
            "angry": "분노",
            "neutral": "중립",
            "serious": "진지",
            "curious": "호기심",
            "dramatic": "극적",
            "surprised": "놀람",
            "casual": "편안",
            "explain": "설명",
            "emphasis": "강조",
            "friendly": "친근",
            "urgent": "긴급",
            "closing": "마무리",
        }
        return names.get(emotion, emotion.capitalize())

    def _emotion_description(self, emotion: str) -> str:
        """감정 설명"""
        descriptions = {
            "calm": "평온하고 안정된 톤",
            "whisper": "작고 조용한 속삭임",
            "fear": "두려움이 느껴지는 떨리는 목소리",
            "shock": "놀라고 충격받은 상태",
            "crying": "울먹이거나 흐느끼는 목소리",
            "happy": "밝고 즐거운 톤",
            "excited": "흥분되고 들뜬 상태",
            "sad": "슬프고 가라앉은 톤",
            "angry": "화나고 격앙된 목소리",
            "neutral": "감정 없이 중립적인 톤",
            "serious": "진지하고 무거운 분위기",
            "curious": "궁금해하는 톤",
            "dramatic": "극적이고 과장된 연기",
            "surprised": "예상치 못한 상황에 놀란 상태",
            "casual": "편안하고 일상적인 말투",
        }
        return descriptions.get(emotion, f"{emotion} 감정")

    def _write_prompts_folder(self, temp_dir: Path, package: 'ChannelPackage'):
        """prompts/ 폴더 생성"""
        prompts_dir = temp_dir / "prompts"
        prompts_dir.mkdir(exist_ok=True)

        # pd_system.txt
        pd_path = prompts_dir / "pd_system.txt"
        with open(pd_path, 'w', encoding='utf-8') as f:
            f.write(package.prompts.pd_system_prompt)

        # writer_system.txt
        writer_path = prompts_dir / "writer_system.txt"
        with open(writer_path, 'w', encoding='utf-8') as f:
            f.write(package.prompts.writer_system_prompt)

        # topics.json
        topics_data = {
            "templates": package.prompts.topic_templates,
            "banned_keywords": package.prompts.banned_keywords,
        }
        topics_path = prompts_dir / "topics.json"
        with open(topics_path, 'w', encoding='utf-8') as f:
            json.dump(topics_data, f, ensure_ascii=False, indent=2)

        # sd_prompts.json
        sd_data = {
            "positive": package.prompts.sd_positive,
            "negative": package.prompts.sd_negative,
        }
        sd_path = prompts_dir / "sd_prompts.json"
        with open(sd_path, 'w', encoding='utf-8') as f:
            json.dump(sd_data, f, ensure_ascii=False, indent=2)

    def _write_tts_guide_md(self, temp_dir: Path, recipe: 'CloneRecipe'):
        """TTS 가이드 마크다운 생성"""
        if not recipe.tts_guide:
            return

        tts = recipe.tts_guide

        content = f"""# TTS 녹음 가이드

> 이 문서는 ElevenLabs v3로 목소리를 클론한 후 GPT-SoVITS로 재학습하기 위한 가이드입니다.
> 패키지 버전: {self.PACKAGE_VERSION}

---

## 1. 타겟 스타일 정보

- **원본 영상**: {recipe.video_title}
- **원본 채널**: {recipe.channel_title}
- **스타일**: {recipe.style_type}
- **난이도**: {recipe.clone_difficulty}
- **복제 가능성**: {recipe.feasibility_score}/100

---

## 2. 목소리 스펙

| 항목 | 값 |
|------|-----|
| 성별 | {tts.voice_gender} |
| 연령대 | {tts.voice_age} |
| 톤 | {tts.voice_tone} |

---

## 3. 필요한 감정 목록

"""

        for emotion in tts.required_emotions:
            display = self._emotion_display_name(emotion)
            desc = self._emotion_description(emotion)
            content += f"- **{emotion}** ({display}): {desc}\n"

        content += """
---

## 4. 샘플 대사 스크립트

각 감정당 3~5초 분량으로 녹음하세요.

"""

        for emotion, script in tts.sample_scripts.items():
            display = self._emotion_display_name(emotion)
            content += f"""### {emotion.upper()} ({display})

> "{script}"

"""

        content += """---

## 5. 녹음 팁

"""
        for i, tip in enumerate(tts.recording_tips, 1):
            content += f"{i}. {tip}\n"

        content += f"""
---

## 6. ElevenLabs v3 힌트

```
{tts.elevenlabs_hints}
```

이 힌트를 ElevenLabs Voice Design에서 참고하세요.

---

## 7. 재학습 순서

1. ElevenLabs에서 위 스펙에 맞는 목소리 검색 또는 Voice Design으로 생성
2. 샘플 대사 녹음 (감정당 3개 이상, 각 3~5초)
3. GPT-SoVITS 학습 마법사에서 모델 학습
4. 학습 완료된 모델을 이 패키지와 함께 사용

---

*이 문서는 Reverie Insight {self.PACKAGE_VERSION}에서 자동 생성되었습니다.*
"""

        guide_path = temp_dir / "TTS_GUIDE.md"
        with open(guide_path, 'w', encoding='utf-8') as f:
            f.write(content)

    # ============================================================
    # .revpack 로드 (v1.5.0)
    # ============================================================

    def load_revpack(
        self,
        revpack_path: Path,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        .revpack 파일 로드

        Args:
            revpack_path: .revpack 파일 경로

        Returns:
            (성공여부, 메시지, 로드된 데이터)

        로드된 데이터 구조:
        {
            "package_info": {...},      # channel_config.json 또는 복호화된 데이터
            "style_guide": {...},       # style_guide.json
            "emotions": {...},          # emotions.json
            "prompts": {                # prompts/ 폴더 내용
                "pd_system": "...",
                "writer_system": "...",
                "topics": {...},
                "sd_prompts": {...},
            },
            "tts_guide": "...",         # TTS_GUIDE.md (마크다운 텍스트)
        }
        """
        revpack_path = Path(revpack_path)

        if not revpack_path.exists():
            return False, f"파일을 찾을 수 없습니다: {revpack_path}", None

        if not revpack_path.suffix.lower() == ".revpack":
            return False, "지원하지 않는 파일 형식입니다. .revpack 파일만 지원됩니다.", None

        try:
            result = {
                "package_info": None,
                "style_guide": None,
                "emotions": None,
                "prompts": {},
                "tts_guide": None,
                "source_path": str(revpack_path),
            }

            with zipfile.ZipFile(revpack_path, 'r') as zf:
                file_list = zf.namelist()

                # v57.7.1: 새로운 팩 형식 감지 (manifest.json 기반)
                is_new_format = "manifest.json" in file_list or "manifest.json.enc" in file_list

                if is_new_format:
                    # ========== 새로운 팩 형식 (pack_creator_full.py) ==========
                    return self._load_new_format_pack(zf, file_list, revpack_path)

                # ========== 기존 팩 형식 (channel_config.json 기반) ==========
                # 1. channel_config 로드 (암호화 또는 평문)
                if "channel_config.enc" in file_list:
                    # 암호화된 설정
                    if self.security:
                        enc_data = zf.read("channel_config.enc")
                        result["package_info"] = self.security.verify_and_decrypt(enc_data)
                        logger.info("[RevpackLoader] 암호화된 설정 복호화 완료")
                    else:
                        return False, "보안 매니저 없이 암호화된 패키지를 열 수 없습니다.", None
                elif "channel_config.json" in file_list:
                    # 평문 설정
                    config_data = zf.read("channel_config.json")
                    result["package_info"] = json.loads(config_data.decode('utf-8'))
                    logger.info("[RevpackLoader] 평문 설정 로드 완료")
                else:
                    return False, "패키지 설정 파일을 찾을 수 없습니다.", None

                # 2. style_guide.json 로드
                if "style_guide.json" in file_list:
                    style_data = zf.read("style_guide.json")
                    result["style_guide"] = json.loads(style_data.decode('utf-8'))

                # 3. emotions.json 로드
                if "emotions.json" in file_list:
                    emotions_data = zf.read("emotions.json")
                    result["emotions"] = json.loads(emotions_data.decode('utf-8'))

                # 4. prompts/ 폴더 로드
                for filename in file_list:
                    if filename.startswith("prompts/"):
                        name = filename.replace("prompts/", "")
                        if name:
                            content = zf.read(filename).decode('utf-8')

                            if name == "pd_system.txt":
                                result["prompts"]["pd_system"] = content
                            elif name == "writer_system.txt":
                                result["prompts"]["writer_system"] = content
                            elif name == "topics.json":
                                result["prompts"]["topics"] = json.loads(content)
                            elif name == "sd_prompts.json":
                                result["prompts"]["sd_prompts"] = json.loads(content)

                # 5. TTS_GUIDE.md 로드
                if "TTS_GUIDE.md" in file_list:
                    tts_data = zf.read("TTS_GUIDE.md")
                    result["tts_guide"] = tts_data.decode('utf-8')

            logger.info(f"[RevpackLoader] .revpack 로드 완료: {revpack_path.name}")
            return True, f"패키지 로드 완료: {revpack_path.name}", result

        except zipfile.BadZipFile:
            return False, "손상된 패키지 파일입니다.", None
        except json.JSONDecodeError as e:
            return False, f"JSON 파싱 오류: {e}", None
        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[RevpackLoader] 로드 실패: {safe_error}")
            return False, f"로드 실패: {safe_error}", None

    def _load_new_format_pack(
        self,
        zf: zipfile.ZipFile,
        file_list: list,
        revpack_path: Path,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        v57.7.1: 새로운 팩 형식 로드 (pack_creator_full.py로 생성된 팩)

        새 형식 구조:
        - manifest.json(.enc): 기본 정보
        - settings.json(.enc): 상세 설정
        - topics.json: 토픽 템플릿
        - prompts/pd_system.txt(.enc)
        - prompts/writer_system.txt(.enc)
        - prompts/sd_prompts.json(.enc)
        """
        try:
            # v63: 평문 팩만 지원 (암호화 .enc 제거됨)
            is_encrypted = False

            def read_file(filename: str) -> Optional[bytes]:
                """파일 읽기 (평문)"""
                if filename in file_list:
                    return zf.read(filename)
                return None

            # 1. manifest.json 로드
            manifest_data = read_file("manifest.json")
            if not manifest_data:
                return False, "manifest.json을 찾을 수 없습니다.", None
            manifest = json.loads(manifest_data.decode('utf-8'))

            # 2. settings.json 로드
            settings_data = read_file("settings.json")
            settings = json.loads(settings_data.decode('utf-8')) if settings_data else {}

            # 3. topics.json 로드 (암호화 안 함)
            topics = {}
            if "topics.json" in file_list:
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

            # topics도 prompts에 포함
            prompts["topics"] = topics

            # 기존 형식과 호환되는 결과 구조 생성
            result = {
                "package_info": {
                    "pack_id": manifest.get("pack_id", ""),
                    "pack_name": manifest.get("pack_name", ""),
                    "display_name": manifest.get("pack_name", ""),
                    "channel_type": manifest.get("genre", "custom"),
                    "version": manifest.get("version", "1.0.0"),
                    "author": manifest.get("author", ""),
                    "genre": manifest.get("genre", ""),
                    # settings에서 추가 정보
                    "style": settings.get("style", {}),
                    "content": settings.get("content", {}),
                    "characters": settings.get("characters", {}),
                    "character_config": settings.get("character_config", {}),
                },
                "style_guide": settings.get("style", {}),
                "emotions": None,
                "prompts": prompts,
                "tts_guide": None,
                "source_path": str(revpack_path),
                # 새 형식 표시
                "_new_format": True,
                "_encrypted": is_encrypted,
            }

            logger.info(f"[RevpackLoader] 새 형식 팩 로드 완료: {manifest.get('pack_name', revpack_path.name)}")
            return True, f"패키지 로드 완료: {manifest.get('pack_name', revpack_path.name)}", result

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[RevpackLoader] 새 형식 팩 로드 실패: {safe_error}")
            return False, f"새 형식 팩 로드 실패: {safe_error}", None

    def revpack_to_plan_data(
        self,
        revpack_data: Dict[str, Any],
        topic: str = "",
    ) -> Dict[str, Any]:
        """
        .revpack 데이터를 ScenarioEditor/ScriptPreview에서 사용할
        plan_data 형식으로 변환

        Args:
            revpack_data: load_revpack()에서 반환된 데이터
            topic: 사용할 주제 (없으면 기본 토픽에서 선택)

        Returns:
            plan_data 딕셔너리 (script_preview_dialog 호환)
        """
        package_info = revpack_data.get("package_info") or {}
        style_guide = revpack_data.get("style_guide") or {}
        emotions = revpack_data.get("emotions") or {}
        prompts = revpack_data.get("prompts") or {}

        # 기본 토픽 선택
        if not topic:
            topics_data = prompts.get("topics", {})
            templates = topics_data.get("templates", [])
            topic = templates[0] if templates else "기본 주제"

        # 감정 목록 추출
        emotion_list = list(emotions.get("emotions", {}).keys())
        if not emotion_list:
            emotion_list = ["calm", "fear", "sad"]

        # plan_data 구조 생성
        plan_data = {
            # 기본 정보
            "project_name": package_info.get("package_name", "revpack_project"),
            "channel": package_info.get("channel_type", "horror"),
            "mode": package_info.get("channel_type", "horror"),
            "topic": topic,
            "title": f"[{package_info.get('channel_display_name', 'Revpack')}] {topic}",

            # 메타데이터
            "tags": "",
            "thumbnail_title": topic[:20],
            "hook": "",

            # 대본 (초기 빈 리스트 - ScenarioEditor에서 생성)
            "script_list": [],

            # 프롬프트 설정
            "prompts": {
                "pd_system": prompts.get("pd_system", ""),
                "writer_system": prompts.get("writer_system", ""),
                "sd_positive": prompts.get("sd_prompts", {}).get("positive", ""),
                "sd_negative": prompts.get("sd_prompts", {}).get("negative", ""),
            },

            # 스타일 정보 (스튜디오에서 활용)
            "style": {
                "style_type": style_guide.get("style_type", "silhouette"),
                "content_type": style_guide.get("content_type", "horror"),
                "color_palette": style_guide.get("color_palette", {}),
                "sd_models": style_guide.get("sd", {}).get("recommended_models", []),
            },

            # 감정 설정
            "emotions": {
                "available": emotion_list,
                "default": emotions.get("default_emotion", "calm"),
            },

            # 원본 revpack 경로
            "source_revpack": revpack_data.get("source_path", ""),

            # 날짜
            "created_at": datetime.now().isoformat(),
        }

        return plan_data

    # ============================================================
    # 배치 생성
    # ============================================================

    def generate_batch(
        self,
        recipes: List['CloneRecipe'],
        author: str = "Reverie Insight",
        encrypt: bool = True,
    ) -> List[Tuple[bool, str, Optional[Path]]]:
        """
        여러 레시피를 한번에 .revpack으로 생성

        Args:
            recipes: 클론 레시피 리스트
            author: 제작자
            encrypt: 암호화 여부

        Returns:
            [(성공여부, 메시지, 파일경로), ...]
        """
        results = []

        for recipe in recipes:
            result = self.generate_revpack(
                recipe,
                author=author,
                encrypt=encrypt,
            )
            results.append(result)

        return results


# ============================================================
# 싱글톤 & 유틸리티
# ============================================================

_generator_instance: Optional[RevpackGenerator] = None

def get_revpack_generator() -> RevpackGenerator:
    """RevpackGenerator 싱글톤"""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = RevpackGenerator()
    return _generator_instance


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print("RevpackGenerator 모듈 로드 완료")
    print(f"패키지 시스템: {'사용 가능' if PACKAGE_SYSTEM_AVAILABLE else '사용 불가'}")
    print(f"스타일 분석기: {'사용 가능' if STYLE_ANALYZER_AVAILABLE else '사용 불가'}")
