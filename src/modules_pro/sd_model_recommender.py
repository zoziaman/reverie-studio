# src/modules_pro/sd_model_recommender.py
# ============================================================
# v59: SD Model Recommender
# 장르/스타일에 맞는 SD 모델 자동 추천 및 다운로드 관리
# ============================================================
# 설계서: docs/V59_VISUAL_STORYTELLING_DESIGN.md 섹션 3.1
# ============================================================

import os
import json
import logging
import hashlib
import requests
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from utils.secret_redaction import redact_sensitive_text

try:
    from utils.logger import get_logger
    logger = get_logger("sd_model_recommender")
except ImportError:
    logger = logging.getLogger(__name__)


# ============================================================
# 스타일 카테고리
# ============================================================

class StyleCategory(Enum):
    """이미지 스타일 카테고리"""
    REALISTIC = "realistic"           # 실사풍
    ANIME = "anime"                   # 애니메이션
    ILLUSTRATION = "illustration"     # 일러스트
    INK_PAINTING = "ink_painting"     # 수묵화
    OIL_PAINTING = "oil_painting"     # 유화
    WATERCOLOR = "watercolor"         # 수채화
    COMIC = "comic"                   # 만화
    SILHOUETTE = "silhouette"         # 실루엣


# ============================================================
# 모델 추천 데이터
# ============================================================

@dataclass
class ModelRecommendation:
    """모델 추천 정보"""
    name: str                           # 모델 파일명
    display_name: str                   # 표시 이름
    style_category: StyleCategory       # 스타일 카테고리
    description: str = ""               # 설명
    civitai_url: str = ""              # Civitai 다운로드 URL
    huggingface_url: str = ""          # HuggingFace 다운로드 URL
    file_size_mb: int = 0              # 파일 크기 (MB)
    license: str = "unknown"           # 라이선스 (commercial, personal, unknown)
    recommended_cfg: float = 7.0       # 권장 CFG
    recommended_steps: int = 15        # 권장 스텝 (v59.5.17: 28→15)
    recommended_sampler: str = "DPM++ 2M Karras"
    clip_skip: int = 2
    triggers: List[str] = field(default_factory=list)  # 트리거 단어


@dataclass
class LoRARecommendation:
    """LoRA 추천 정보"""
    name: str                           # 파일명
    display_name: str
    trigger: str = ""                   # 트리거 단어
    weight: float = 0.7                 # 권장 가중치
    civitai_url: str = ""
    huggingface_url: str = ""
    file_size_mb: int = 0
    compatible_models: List[str] = field(default_factory=list)


@dataclass
class VAERecommendation:
    """VAE 추천 정보"""
    name: str
    display_name: str
    civitai_url: str = ""
    huggingface_url: str = ""
    file_size_mb: int = 0


# ============================================================
# 장르별 추천 모델 데이터베이스
# ============================================================

# 공포/괴담 장르
HORROR_MODELS = {
    "checkpoints": [
        ModelRecommendation(
            name="ghostmix_v20Bakedvae.safetensors",
            display_name="GhostMix v2.0",
            style_category=StyleCategory.REALISTIC,
            description="공포/미스터리에 최적화된 실사풍 모델",
            civitai_url="https://civitai.com/api/download/models/76907",
            file_size_mb=2000,
            license="commercial",
            recommended_cfg=7.0,
            recommended_steps=28,
        ),
        ModelRecommendation(
            name="deliberate_v3.safetensors",
            display_name="Deliberate v3",
            style_category=StyleCategory.REALISTIC,
            description="고품질 실사풍 모델, 어두운 분위기 표현 우수",
            civitai_url="https://civitai.com/api/download/models/90854",
            file_size_mb=2000,
            license="commercial",
            recommended_cfg=7.5,
            recommended_steps=30,
        ),
    ],
    "loras": [
        LoRARecommendation(
            name="koreanDollLikeness_v20.safetensors",
            display_name="Korean Doll Likeness v2.0",
            trigger="korean doll",
            weight=0.5,
            civitai_url="https://civitai.com/api/download/models/31284",
            file_size_mb=144,
            compatible_models=["ghostmix", "deliberate"],
        ),
        LoRARecommendation(
            name="epiNoiseoffset_v2.safetensors",
            display_name="EPI Noise Offset v2",
            trigger="",
            weight=0.3,
            civitai_url="https://civitai.com/api/download/models/16576",
            file_size_mb=36,
            compatible_models=["*"],
        ),
    ],
    "vae": VAERecommendation(
        name="vae-ft-mse-840000-ema-pruned.safetensors",
        display_name="VAE FT MSE 840k",
        civitai_url="https://huggingface.co/stabilityai/sd-vae-ft-mse/resolve/main/vae-ft-mse-840000-ema-pruned.safetensors",
        file_size_mb=335,
    ),
}

# 야담/전래동화 장르
YADAM_MODELS = {
    "checkpoints": [
        ModelRecommendation(
            name="majicmixRealistic_v7.safetensors",
            display_name="MajicMix Realistic v7",
            style_category=StyleCategory.REALISTIC,
            description="한국 전통 분위기에 적합한 고품질 실사 모델",
            civitai_url="https://civitai.com/api/download/models/176425",
            file_size_mb=2000,
            license="commercial",
            recommended_cfg=7.0,
            recommended_steps=30,
        ),
        ModelRecommendation(
            name="chilloutmix_NiPrunedFp32Fix.safetensors",
            display_name="ChilloutMix",
            style_category=StyleCategory.REALISTIC,
            description="아시아 인물 표현에 최적화",
            civitai_url="https://civitai.com/api/download/models/11745",
            file_size_mb=2000,
            license="personal",
            recommended_cfg=7.0,
            recommended_steps=28,
        ),
    ],
    "loras": [
        LoRARecommendation(
            name="hanbok_v1.safetensors",
            display_name="Hanbok Style v1",
            trigger="hanbok, korean traditional dress",
            weight=0.7,
            file_size_mb=144,
            compatible_models=["majicmix", "chilloutmix"],
        ),
        LoRARecommendation(
            name="koreanDollLikeness_v20.safetensors",
            display_name="Korean Doll Likeness v2.0",
            trigger="korean doll",
            weight=0.5,
            civitai_url="https://civitai.com/api/download/models/31284",
            file_size_mb=144,
            compatible_models=["*"],
        ),
    ],
    "vae": VAERecommendation(
        name="vae-ft-mse-840000-ema-pruned.safetensors",
        display_name="VAE FT MSE 840k",
        file_size_mb=335,
    ),
}

# 시니어/감동 장르
SENIOR_MODELS = {
    "checkpoints": [
        ModelRecommendation(
            name="realisticVisionV60B1_v51VAE.safetensors",
            display_name="Realistic Vision V5.1",
            style_category=StyleCategory.REALISTIC,
            description="노인 캐릭터 표현에 적합한 사실적 모델",
            civitai_url="https://civitai.com/api/download/models/130072",
            file_size_mb=2000,
            license="commercial",
            recommended_cfg=7.0,
            recommended_steps=28,
        ),
    ],
    "loras": [
        LoRARecommendation(
            name="add_detail.safetensors",
            display_name="Add Detail",
            trigger="",
            weight=0.5,
            civitai_url="https://civitai.com/api/download/models/62833",
            file_size_mb=36,
            compatible_models=["*"],
        ),
    ],
    "vae": VAERecommendation(
        name="vae-ft-mse-840000-ema-pruned.safetensors",
        display_name="VAE FT MSE 840k",
        file_size_mb=335,
    ),
}

# 실루엣/미니멀 스타일
SILHOUETTE_MODELS = {
    "checkpoints": [
        ModelRecommendation(
            name="deliberate_v3.safetensors",
            display_name="Deliberate v3",
            style_category=StyleCategory.SILHOUETTE,
            description="실루엣 스타일에 적합, 프롬프트로 제어",
            civitai_url="https://civitai.com/api/download/models/90854",
            file_size_mb=2000,
            license="commercial",
            recommended_cfg=8.0,
            recommended_steps=30,
        ),
    ],
    "loras": [],
    "vae": VAERecommendation(
        name="vae-ft-mse-840000-ema-pruned.safetensors",
        display_name="VAE FT MSE 840k",
        file_size_mb=335,
    ),
}

# 장르별 모델 매핑
GENRE_MODELS = {
    "horror": HORROR_MODELS,
    "mystery": HORROR_MODELS,
    "thriller": HORROR_MODELS,
    "yadam": YADAM_MODELS,
    "traditional": YADAM_MODELS,
    "senior": SENIOR_MODELS,
    "touching": SENIOR_MODELS,
    "makjang": SENIOR_MODELS,  # v62.14: makjang 누락 → HORROR_MODELS 폴백 버그 수정
    "family": SENIOR_MODELS,
    "romance": SENIOR_MODELS,
    "silhouette": SILHOUETTE_MODELS,
    "minimal": SILHOUETTE_MODELS,
}


# ============================================================
# SDModelRecommender 클래스
# ============================================================

class SDModelRecommender:
    """
    v59: SD 모델 추천 시스템

    기능:
    - 장르에 맞는 체크포인트/LoRA/VAE 추천
    - 설치된 모델 감지
    - 모델 다운로드 URL 제공
    - 추천 설정값 제공
    """

    def __init__(self, sd_models_path: str = None):
        """
        Args:
            sd_models_path: SD WebUI 모델 경로 (자동 감지 시도)
        """
        self.sd_models_path = sd_models_path or self._detect_sd_models_path()
        self.installed_checkpoints: List[str] = []
        self.installed_loras: List[str] = []
        self.installed_vaes: List[str] = []

        if self.sd_models_path:
            self._scan_installed_models()

        logger.info(f"[SDModelRecommender] 초기화 완료: {self.sd_models_path}")

    def _detect_sd_models_path(self) -> Optional[str]:
        """SD WebUI 모델 경로 자동 감지"""
        common_paths = [
            "C:/sd-webui/models",
            "D:/sd-webui/models",
            "C:/stable-diffusion-webui/models",
            "D:/stable-diffusion-webui/models",
            os.path.expanduser("~/stable-diffusion-webui/models"),
        ]

        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"[SDModelRecommender] SD 경로 감지: {path}")
                return path

        return None

    def _scan_installed_models(self):
        """설치된 모델 스캔"""
        if not self.sd_models_path:
            return

        # Checkpoints
        ckpt_path = Path(self.sd_models_path) / "Stable-diffusion"
        if ckpt_path.exists():
            self.installed_checkpoints = [
                f.name for f in ckpt_path.iterdir()
                if f.suffix in ['.safetensors', '.ckpt']
            ]

        # LoRAs
        lora_path = Path(self.sd_models_path) / "Lora"
        if lora_path.exists():
            self.installed_loras = [
                f.name for f in lora_path.iterdir()
                if f.suffix in ['.safetensors', '.pt']
            ]

        # VAEs
        vae_path = Path(self.sd_models_path) / "VAE"
        if vae_path.exists():
            self.installed_vaes = [
                f.name for f in vae_path.iterdir()
                if f.suffix in ['.safetensors', '.pt']
            ]

        logger.info(f"[SDModelRecommender] 감지된 모델 - "
                   f"Checkpoints: {len(self.installed_checkpoints)}, "
                   f"LoRAs: {len(self.installed_loras)}, "
                   f"VAEs: {len(self.installed_vaes)}")

    def is_model_installed(self, model_name: str, model_type: str = "checkpoint") -> bool:
        """모델 설치 여부 확인"""
        if model_type == "checkpoint":
            return any(model_name.lower() in m.lower() for m in self.installed_checkpoints)
        elif model_type == "lora":
            return any(model_name.lower() in m.lower() for m in self.installed_loras)
        elif model_type == "vae":
            return any(model_name.lower() in m.lower() for m in self.installed_vaes)
        return False

    def get_recommendations(self, genre: str) -> Dict[str, Any]:
        """
        장르에 맞는 모델 추천

        Args:
            genre: 장르 (horror, touching, makjang, senior 등)

        Returns:
            {
                "checkpoints": [ModelRecommendation],
                "loras": [LoRARecommendation],
                "vae": VAERecommendation,
                "missing_models": {"checkpoints": [...], "loras": [...], "vae": ...}
            }
        """
        genre_lower = genre.lower()

        # 장르 매핑
        models = GENRE_MODELS.get(genre_lower, HORROR_MODELS)

        # 누락된 모델 확인
        missing = {
            "checkpoints": [],
            "loras": [],
            "vae": None,
        }

        for ckpt in models["checkpoints"]:
            if not self.is_model_installed(ckpt.name, "checkpoint"):
                missing["checkpoints"].append(ckpt)

        for lora in models["loras"]:
            if not self.is_model_installed(lora.name, "lora"):
                missing["loras"].append(lora)

        if models["vae"] and not self.is_model_installed(models["vae"].name, "vae"):
            missing["vae"] = models["vae"]

        return {
            "checkpoints": models["checkpoints"],
            "loras": models["loras"],
            "vae": models["vae"],
            "missing_models": missing,
            "all_installed": (
                len(missing["checkpoints"]) == 0 and
                len(missing["loras"]) == 0 and
                missing["vae"] is None
            ),
        }

    def get_best_checkpoint(self, genre: str) -> Optional[ModelRecommendation]:
        """장르에 가장 적합한 (설치된) 체크포인트 반환"""
        recs = self.get_recommendations(genre)

        # 설치된 모델 중 첫 번째 반환
        for ckpt in recs["checkpoints"]:
            if self.is_model_installed(ckpt.name, "checkpoint"):
                return ckpt

        # 설치된 게 없으면 첫 번째 추천
        if recs["checkpoints"]:
            return recs["checkpoints"][0]

        return None

    def get_sd_config_for_pack(self, genre: str) -> Dict[str, Any]:
        """
        팩용 SD 설정 생성

        Returns:
            SDModelConfig에 사용할 딕셔너리
        """
        best_ckpt = self.get_best_checkpoint(genre)
        recs = self.get_recommendations(genre)

        config = {
            "checkpoint": best_ckpt.name if best_ckpt else "",
            "vae": recs["vae"].name if recs["vae"] else "",
            "sampler": best_ckpt.recommended_sampler if best_ckpt else "DPM++ 2M Karras",
            "scheduler": "Karras",
            "steps": best_ckpt.recommended_steps if best_ckpt else 15,
            "cfg_scale": best_ckpt.recommended_cfg if best_ckpt else 7.0,
            "width": 1024,
            "height": 576,
            "clip_skip": best_ckpt.clip_skip if best_ckpt else 2,
            "lora_models": [],
        }

        # LoRA 추가
        for lora in recs["loras"]:
            if self.is_model_installed(lora.name, "lora"):
                config["lora_models"].append({
                    "name": lora.name,
                    "weight": lora.weight,
                    "trigger": lora.trigger,
                })

        return config

    def scan_sd_webui_models(self, sd_api_url: str = None) -> Dict[str, List[str]]:
        """
        v59: SD WebUI API로 설치된 모델 스캔

        Returns:
            {'checkpoints': [...], 'loras': [...], 'vaes': [...]}
        """
        result = {'checkpoints': [], 'loras': [], 'vaes': []}
        # v60.1.0: config에서 SD URL 참조 (하드코딩 방지)
        if sd_api_url is None:
            try:
                from config.settings import config
                sd_api_url = getattr(config, 'SD_URL', 'http://127.0.0.1:7860')
            except ImportError:
                sd_api_url = 'http://127.0.0.1:7860'

        try:
            # 체크포인트 목록
            resp = requests.get(f"{sd_api_url}/sdapi/v1/sd-models", timeout=10)
            if resp.status_code == 200:
                models = resp.json()
                result['checkpoints'] = [m.get('model_name', m.get('title', '')) for m in models]
                logger.info(f"[SDModelRecommender] SD WebUI 체크포인트: {len(result['checkpoints'])}개")

            # LoRA 목록
            try:
                resp = requests.get(f"{sd_api_url}/sdapi/v1/loras", timeout=10)
                if resp.status_code == 200:
                    loras = resp.json()
                    result['loras'] = [l.get('name', '') for l in loras]
            except (requests.RequestException, ValueError):
                pass

            # VAE 목록
            try:
                resp = requests.get(f"{sd_api_url}/sdapi/v1/sd-vae", timeout=10)
                if resp.status_code == 200:
                    vaes = resp.json()
                    result['vaes'] = [v.get('model_name', '') for v in vaes]
            except (requests.RequestException, ValueError):
                pass

            # 내부 캐시 업데이트
            self.installed_checkpoints = result['checkpoints']
            self.installed_loras = result['loras']
            self.installed_vaes = result['vaes']

        except Exception as e:
            logger.warning(f"[SDModelRecommender] SD WebUI 모델 스캔 실패: {e}")

        return result

    @staticmethod
    def _normalize_model_name(name: str) -> str:
        if not name:
            return ""
        normalized = str(name).strip().lower()
        normalized = normalized.split("[", 1)[0].strip()
        normalized = Path(normalized).name
        if normalized.endswith((".safetensors", ".ckpt", ".pt")):
            normalized = Path(normalized).stem
        return normalized

    def check_required_models_for_pack(
        self,
        pack_checkpoint: str,
        pack_vae: str = None,
        pack_loras: List[str] = None,
        sd_api_url: str = None
    ) -> Dict[str, Any]:
        """
        v59: 팩에서 요구하는 모델이 설치되어 있는지 확인

        Returns:
            {
                'all_installed': bool,
                'missing': {'checkpoint': str or None, 'vae': str or None, 'loras': [...]},
                'installed': {'checkpoint': bool, 'vae': bool, 'loras': [...]},
            }
        """
        # SD WebUI에서 설치된 모델 스캔
        installed = self.scan_sd_webui_models(sd_api_url)

        result = {
            'all_installed': True,
            'missing': {'checkpoint': None, 'vae': None, 'loras': []},
            'installed': {'checkpoint': False, 'vae': True, 'loras': []},
        }

        # 체크포인트 확인
        if pack_checkpoint:
            ckpt_lower = self._normalize_model_name(pack_checkpoint)
            result['installed']['checkpoint'] = any(
                ckpt_lower == self._normalize_model_name(m) for m in installed['checkpoints']
            )
            if not result['installed']['checkpoint']:
                result['missing']['checkpoint'] = pack_checkpoint
                result['all_installed'] = False

        # "Automatic"/"auto"는 WebUI 기본 선택을 뜻하므로 설치 체크 대상이 아니다.
        normalized_pack_vae = self._normalize_model_name(pack_vae) if pack_vae else ""
        if normalized_pack_vae and normalized_pack_vae not in {"automatic", "auto"}:
            vae_lower = self._normalize_model_name(pack_vae)
            result['installed']['vae'] = any(
                vae_lower == self._normalize_model_name(v) for v in installed['vaes']
            )
            if not result['installed']['vae']:
                result['missing']['vae'] = pack_vae
                result['all_installed'] = False

        # LoRA 확인
        if pack_loras:
            for lora in pack_loras:
                lora_lower = self._normalize_model_name(lora)
                is_installed = any(
                    lora_lower == self._normalize_model_name(l) for l in installed['loras']
                )
                result['installed']['loras'].append({'name': lora, 'installed': is_installed})
                if not is_installed:
                    result['missing']['loras'].append(lora)
                    result['all_installed'] = False

        return result

    def get_v59_model_guide(self, genre: str, pack_checkpoint: str = None) -> str:
        """
        v59: 상세 모델 설치 가이드 생성

        콘솔에 출력할 상세 안내 메시지
        """
        recs = self.get_recommendations(genre)

        lines = [
            "",
            "=" * 60,
            "[!!] v59 Visual Storytelling 필수 모델 안내",
            "=" * 60,
            "",
        ]

        # 요구 모델 표시
        if pack_checkpoint:
            lines.append(f"[PACK] 팩 요구 체크포인트: {pack_checkpoint}")

        lines.append("")
        lines.append("[DOWNLOAD] 추천 모델 다운로드:")
        lines.append("")

        # 체크포인트
        for i, ckpt in enumerate(recs["checkpoints"][:2], 1):  # 상위 2개만
            installed = "[O] 설치됨" if self.is_model_installed(ckpt.name) else "[X] 미설치"
            lines.append(f"  [{i}] {ckpt.display_name} ({installed})")
            lines.append(f"      파일명: {ckpt.name}")
            lines.append(f"      크기: {ckpt.file_size_mb}MB")
            if ckpt.civitai_url:
                lines.append(f"      다운로드: {ckpt.civitai_url}")
            if ckpt.huggingface_url:
                lines.append(f"      (대체) {ckpt.huggingface_url}")
            lines.append(f"      권장 설정: CFG={ckpt.recommended_cfg}, Steps={ckpt.recommended_steps}")
            lines.append("")

        # VAE
        if recs["vae"]:
            vae = recs["vae"]
            installed = "[O] 설치됨" if self.is_model_installed(vae.name, "vae") else "[X] 미설치"
            lines.append(f"  [VAE] {vae.display_name} ({installed})")
            lines.append(f"      파일명: {vae.name}")
            if vae.civitai_url:
                lines.append(f"      다운로드: {vae.civitai_url}")
            lines.append("")

        # 설치 경로 안내
        lines.append("[PATH] 설치 경로:")
        lines.append("  체크포인트: SD WebUI/models/Stable-diffusion/")
        lines.append("  VAE: SD WebUI/models/VAE/")
        lines.append("  LoRA: SD WebUI/models/Lora/")
        lines.append("")
        lines.append("=" * 60)
        lines.append("")

        return "\n".join(lines)

    def get_download_instructions(self, genre: str) -> str:
        """다운로드 안내 메시지 생성"""
        recs = self.get_recommendations(genre)
        missing = recs["missing_models"]

        if recs["all_installed"]:
            return "모든 추천 모델이 설치되어 있습니다."

        lines = ["다음 모델을 다운로드해주세요:\n"]

        if missing["checkpoints"]:
            lines.append("📦 체크포인트:")
            for ckpt in missing["checkpoints"]:
                url = ckpt.civitai_url or ckpt.huggingface_url or "URL 없음"
                lines.append(f"  - {ckpt.display_name} ({ckpt.file_size_mb}MB)")
                lines.append(f"    다운로드: {url}")

        if missing["loras"]:
            lines.append("\n🎨 LoRA:")
            for lora in missing["loras"]:
                url = lora.civitai_url or lora.huggingface_url or "URL 없음"
                lines.append(f"  - {lora.display_name} ({lora.file_size_mb}MB)")
                lines.append(f"    다운로드: {url}")

        if missing["vae"]:
            lines.append("\n🖼️ VAE:")
            url = missing["vae"].civitai_url or missing["vae"].huggingface_url or "URL 없음"
            lines.append(f"  - {missing['vae'].display_name} ({missing['vae'].file_size_mb}MB)")
            lines.append(f"    다운로드: {url}")

        return "\n".join(lines)

    def download_model(self, url: str, save_path: str,
                       progress_callback: callable = None) -> Tuple[bool, str]:
        """
        모델 다운로드

        Args:
            url: 다운로드 URL
            save_path: 저장 경로
            progress_callback: 진행 콜백 (downloaded_mb, total_mb)

        Returns:
            (성공 여부, 메시지)
        """
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            total_mb = total_size / (1024 * 1024)

            downloaded = 0
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback:
                            downloaded_mb = downloaded / (1024 * 1024)
                            progress_callback(downloaded_mb, total_mb)

            logger.info(f"[SDModelRecommender] 다운로드 완료: {save_path}")
            return True, f"다운로드 완료: {os.path.basename(save_path)}"

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[SDModelRecommender] 다운로드 실패: {safe_error}")
            return False, f"다운로드 실패: {safe_error}"

    def get_style_prompts(self, genre: str) -> Dict[str, str]:
        """장르별 스타일 프롬프트"""
        style_prompts = {
            "horror": {
                "positive": "dark atmosphere, horror, dramatic lighting, eerie, mysterious, cinematic",
                "negative": "bright colors, happy, cheerful, cartoon, anime",
            },
            "yadam": {
                "positive": "korean traditional, hanbok, historical, atmospheric, cinematic, detailed",
                "negative": "modern clothes, western, cartoon, low quality",
            },
            "senior": {
                "positive": "warm lighting, emotional, realistic, detailed, cinematic",
                "negative": "cartoon, anime, oversaturated, low quality",
            },
            "silhouette": {
                "positive": "silhouette, dark background, dramatic lighting, high contrast, minimalist",
                "negative": "detailed face, colorful, busy background",
            },
        }

        return style_prompts.get(genre.lower(), style_prompts["horror"])


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== SDModelRecommender Test ===\n")

    recommender = SDModelRecommender()

    # 1. 장르별 추천
    for genre in ["horror", "touching", "makjang", "senior"]:
        print(f"\n{'='*50}")
        print(f"장르: {genre}")
        print('='*50)

        recs = recommender.get_recommendations(genre)

        print("\n추천 체크포인트:")
        for ckpt in recs["checkpoints"]:
            installed = "✓" if recommender.is_model_installed(ckpt.name) else "✗"
            print(f"  [{installed}] {ckpt.display_name}")
            print(f"      파일: {ckpt.name}")
            print(f"      CFG: {ckpt.recommended_cfg}, Steps: {ckpt.recommended_steps}")

        print("\n추천 LoRA:")
        for lora in recs["loras"]:
            installed = "✓" if recommender.is_model_installed(lora.name, "lora") else "✗"
            print(f"  [{installed}] {lora.display_name} (weight: {lora.weight})")
            if lora.trigger:
                print(f"      트리거: {lora.trigger}")

        print("\n추천 VAE:")
        if recs["vae"]:
            installed = "✓" if recommender.is_model_installed(recs["vae"].name, "vae") else "✗"
            print(f"  [{installed}] {recs['vae'].display_name}")

        print(f"\n모든 모델 설치됨: {recs['all_installed']}")

    # 2. 팩용 설정
    print(f"\n{'='*50}")
    print("팩용 SD 설정 (horror):")
    print('='*50)
    config = recommender.get_sd_config_for_pack("horror")
    for key, value in config.items():
        print(f"  {key}: {value}")

    # 3. 다운로드 안내
    print(f"\n{'='*50}")
    print("다운로드 안내:")
    print('='*50)
    print(recommender.get_download_instructions("horror"))

    print("\n[OK] Test completed!")
