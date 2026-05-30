# src/modules_pro/character_library_manager.py
# ============================================================
# v59: Character Library Manager - 완전 구현
# 캐릭터 이미지 라이브러리 관리 및 자동 생성
# ============================================================
# 설계서: docs/V59_VISUAL_STORYTELLING_DESIGN.md 섹션 3.2-3.3, 4.1
# ============================================================

import os
import io
import json
import logging
import hashlib
import base64
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat
from utils.layered_cutout import (
    attach_layered_cutout_assets,
    build_layered_cutout_assets,
    clone_layered_cutout_assets,
    load_layered_cutout_assets,
    load_layered_cutout_metadata,
)
from utils.videotoon_contract import actor_identity_candidates_from_slot

try:
    from utils.logger import get_logger
    logger = get_logger("character_library_manager")
except ImportError:
    logger = logging.getLogger(__name__)


# ============================================================
# 데이터 클래스 (설계서 3.2 CharacterDefinition 확장)
# ============================================================

class ImageAction(Enum):
    """이미지 액션 타입"""
    NEW = "new"                  # 새 이미지 생성
    EXPRESSION = "expression"    # 표정 변경
    POSE = "pose"                # 포즈 변경
    REUSE = "reuse"              # 재사용


@dataclass
class CharacterImage:
    """개별 캐릭터 이미지 정보"""
    path: str = ""                        # 이미지 경로
    expression: str = "neutral"           # 표정
    pose: str = "standing"                # 포즈
    seed: int = -1                        # SD 시드
    prompt: str = ""                      # 사용된 프롬프트
    negative_prompt: str = ""             # 네거티브 프롬프트
    created_at: str = ""                  # 생성 시간
    quality_score: float = 0.0            # 품질 점수 (0~1)
    face_detected: bool = True            # 얼굴 감지 여부
    blur_score: float = 0.0               # 블러 점수 (낮을수록 선명)
    file_size_kb: int = 0                 # 파일 크기


@dataclass
class CharacterLibraryEntry:
    """캐릭터 라이브러리 엔트리 (설계서 3.3)"""
    character_id: str = ""                # 캐릭터 ID
    character_name: str = ""              # 표시 이름
    base_prompt: str = ""                 # 기본 프롬프트
    negative_prompt: str = ""             # 기본 네거티브

    # 표정/포즈별 이미지 목록
    images: Dict[str, List[CharacterImage]] = field(default_factory=dict)
    # images["neutral_standing"] = [CharacterImage, ...]

    # 역할 매핑 (시나리오 역할 → 이 캐릭터)
    role_aliases: List[str] = field(default_factory=list)

    # 통계
    total_images: int = 0
    last_generated: str = ""
    generation_seed: int = -1             # 일관성용 고정 시드


@dataclass
class LibraryConfig:
    """라이브러리 설정 (설계서 3.3)"""
    enabled: bool = True
    auto_generate: bool = True            # 없으면 자동 생성
    auto_generate_count: int = 3          # 표정/포즈당 생성 수
    min_quality_score: float = 0.5        # 최소 품질 점수
    max_retries: int = 3                  # 생성 실패 시 재시도
    use_fixed_seed: bool = True           # 일관성용 시드 고정
    face_detection_required: bool = True  # 얼굴 감지 필수
    preferred_expressions: List[str] = field(default_factory=list)
    preferred_poses: List[str] = field(default_factory=list)
    required_variant_keys: List[str] = field(default_factory=list)
    required_variant_keys_by_slot: Dict[str, List[str]] = field(default_factory=dict)
    face_part_boxes_by_character: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    checkpoint_override: str = ""
    max_face_count: int = 1


# ============================================================
# 기본 표정/포즈 정의
# ============================================================

DEFAULT_EXPRESSIONS = {
    "neutral": {
        "prompt": "calm expression, neutral face, relaxed",
        "weight": 1.0,
    },
    "happy": {
        "prompt": "smiling, happy expression, bright eyes, joyful",
        "weight": 0.8,
    },
    "sad": {
        "prompt": "sad expression, teary eyes, sorrowful, melancholic",
        "weight": 0.6,
    },
    "fear": {
        "prompt": "frightened, scared expression, wide eyes, terrified, pale face",
        "weight": 0.7,
    },
    "anger": {
        "prompt": "angry expression, furrowed brows, intense gaze, furious",
        "weight": 0.5,
    },
    "surprise": {
        "prompt": "surprised, shocked expression, wide eyes, open mouth, gasping",
        "weight": 0.6,
    },
    "talking": {
        "prompt": "speaking, open mouth, expressive, talking",
        "weight": 0.9,
    },
    "blink": {
        "prompt": "closed eyes, relaxed eyelids, same face, no mouth change",
        "weight": 0.5,
    },
}

DEFAULT_POSES = {
    "standing": {
        "prompt": "standing pose, full body, upright posture",
        "weight": 1.0,
    },
    "sitting": {
        "prompt": "sitting pose, seated, relaxed posture",
        "weight": 0.8,
    },
    "walking": {
        "prompt": "walking pose, in motion, dynamic",
        "weight": 0.5,
    },
    "running": {
        "prompt": "running pose, motion blur, dynamic movement",
        "weight": 0.3,
    },
}

EXPRESSION_ALIASES = {
    "calm": "neutral",
    "worried": "fear",
    "scared": "fear",
    "afraid": "fear",
    "desperate": "sad",
    "crying": "sad",
    "whisper": "talking",
    "shouting": "anger",
    "furious": "anger",
    "angry": "anger",
    "happy": "happy",
    "surprised": "surprise",
    "shock": "surprise",
    "shocked": "surprise",
    "speaking": "talking",
    "talk": "talking",
    "blink": "blink",
}

POSE_ALIASES = {
    "idle": "standing",
    "neutral": "standing",
    "listening": "standing",
    "talking": "standing",
    "speak": "standing",
    "walking": "walking",
    "walk": "walking",
    "running": "running",
    "run": "running",
    "sitting": "sitting",
    "sit": "sitting",
    "kneeling": "sitting",
    "bowing": "standing",
    "pointing": "standing",
}

EXPRESSION_FALLBACKS = {
    "fear": ["surprise", "talking", "neutral"],
    "sad": ["talking", "neutral"],
    "anger": ["talking", "neutral"],
    "surprise": ["fear", "talking", "neutral"],
    "talking": ["neutral"],
    "happy": ["neutral"],
    "neutral": [],
}

POSE_FALLBACKS = {
    "walking": ["standing"],
    "running": ["walking", "standing"],
    "sitting": ["standing"],
    "standing": [],
}


# ============================================================
# CharacterLibraryManager 클래스 (설계서 4.1)
# ============================================================

class CharacterLibraryManager:
    """
    v59: 캐릭터 이미지 라이브러리 관리자

    설계서 4.1 주요 메서드:
    - get_character(character_id) -> CharacterDefinition
    - get_character_image(character_id, emotion) -> str
    - generate_character_library(sd_api, character, count) -> List[str]
    - validate_image(image_path, character) -> bool
    """

    def __init__(self,
                 pack_id: str,
                 library_base_path: str = None,
                 sd_api_url: str = None,
                 prompt_composer: Any = None,
                 config: LibraryConfig = None):
        """
        Args:
            pack_id: 팩 ID
            library_base_path: 라이브러리 기본 경로
            sd_api_url: SD WebUI API URL
            prompt_composer: PromptComposer 인스턴스
            config: 라이브러리 설정
        """
        self.pack_id = pack_id
        self.sd_api_url = sd_api_url
        self.prompt_composer = prompt_composer
        self.config = config or self._bootstrap_library_config(pack_id, library_base_path) or LibraryConfig()

        # 경로 설정
        if library_base_path:
            self.library_path = Path(library_base_path)
        else:
            self.library_path = Path(f"assets/characters/{pack_id}")

        self.library_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.library_path / "library.json"

        # 라이브러리 데이터
        self.library: Dict[str, CharacterLibraryEntry] = {}
        self._load_library()

        logger.info(f"[CharacterLibraryManager] 초기화: {pack_id}")
        logger.info(f"  경로: {self.library_path}")
        logger.info(f"  캐릭터 수: {len(self.library)}")

    @staticmethod
    def _bootstrap_library_config(pack_id: str, library_base_path: str = None) -> Optional[LibraryConfig]:
        try:
            from config.pack_config import ACTIVE_PACK

            if not getattr(ACTIVE_PACK, "is_loaded", False):
                return None

            active_pack_id = str(getattr(ACTIVE_PACK, "pack_id", "") or "").strip().lower()
            requested_pack_id = str(pack_id or "").strip().lower()
            requested_path = str(library_base_path or "").replace("\\", "/").lower()

            char_lib_cfg = getattr(getattr(ACTIVE_PACK, "visual_storytelling", None), "character_library", None)
            if not char_lib_cfg:
                return None

            cfg_library_path = str(getattr(char_lib_cfg, "library_path", "") or "").replace("\\", "/").lower()
            same_pack = bool(active_pack_id and requested_pack_id and active_pack_id == requested_pack_id)
            same_path = bool(cfg_library_path and requested_path and requested_path.endswith(cfg_library_path))
            if not same_pack and not same_path:
                return None

            return LibraryConfig(
                enabled=bool(getattr(char_lib_cfg, "enabled", True)),
                auto_generate=bool(getattr(char_lib_cfg, "auto_generate", True)),
                auto_generate_count=int(getattr(char_lib_cfg, "auto_generate_count", 3) or 3),
                min_quality_score=float(getattr(char_lib_cfg, "min_quality_score", 0.5) or 0.5),
                max_retries=int(getattr(char_lib_cfg, "max_retries", 3) or 3),
                use_fixed_seed=bool(getattr(char_lib_cfg, "use_fixed_seed", True)),
                face_detection_required=bool(getattr(char_lib_cfg, "face_detection_required", True)),
                preferred_expressions=list(getattr(char_lib_cfg, "preferred_expressions", []) or []),
                preferred_poses=list(getattr(char_lib_cfg, "preferred_poses", []) or []),
                required_variant_keys=list(getattr(char_lib_cfg, "required_variant_keys", []) or []),
                required_variant_keys_by_slot=dict(getattr(char_lib_cfg, "required_variant_keys_by_slot", {}) or {}),
                face_part_boxes_by_character=dict(getattr(char_lib_cfg, "face_part_boxes_by_character", {}) or {}),
                checkpoint_override=str(getattr(char_lib_cfg, "checkpoint_override", "") or ""),
                max_face_count=int(getattr(char_lib_cfg, "max_face_count", 1) or 1),
            )
        except Exception:
            return None

    # =========================================================
    # 라이브러리 로드/저장
    # =========================================================

    def _load_library(self):
        """라이브러리 매니페스트 로드"""
        if not self.manifest_path.exists():
            logger.info(f"[CharacterLibraryManager] 새 라이브러리 생성")
            return

        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for char_id, char_data in data.get('characters', {}).items():
                entry = CharacterLibraryEntry(
                    character_id=char_id,
                    character_name=char_data.get('name', ''),
                    base_prompt=char_data.get('base_prompt', ''),
                    negative_prompt=char_data.get('negative_prompt', ''),
                    role_aliases=char_data.get('role_aliases', []),
                    total_images=char_data.get('total_images', 0),
                    last_generated=char_data.get('last_generated', ''),
                    generation_seed=char_data.get('generation_seed', -1),
                )

                # 이미지 목록 로드
                for key, images in char_data.get('images', {}).items():
                    entry.images[key] = [
                        CharacterImage(**img) for img in images
                    ]

                self.library[char_id] = entry

            logger.info(f"[CharacterLibraryManager] 로드 완료: {len(self.library)}개 캐릭터")

        except Exception as e:
            logger.error(f"[CharacterLibraryManager] 로드 실패: {e}")

    def _save_library(self):
        """라이브러리 매니페스트 저장"""
        try:
            data = {
                "pack_id": self.pack_id,
                "version": "59.0.0",
                "updated_at": datetime.now().isoformat(),
                "config": asdict(self.config),
                "characters": {}
            }

            for char_id, entry in self.library.items():
                char_data = {
                    "name": entry.character_name,
                    "base_prompt": entry.base_prompt,
                    "negative_prompt": entry.negative_prompt,
                    "role_aliases": entry.role_aliases,
                    "total_images": entry.total_images,
                    "last_generated": entry.last_generated,
                    "generation_seed": entry.generation_seed,
                    "images": {}
                }

                for key, images in entry.images.items():
                    char_data["images"][key] = [asdict(img) for img in images]

                data["characters"][char_id] = char_data

            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"[CharacterLibraryManager] 저장 완료")

        except Exception as e:
            logger.error(f"[CharacterLibraryManager] 저장 실패: {e}")

    # =========================================================
    # 캐릭터 조회 (설계서 4.1)
    # =========================================================

    def get_character(self, character_id: str) -> Optional[CharacterLibraryEntry]:
        """캐릭터 정보 조회"""
        return self.library.get(character_id)

    @staticmethod
    def _stable_seed(value: str) -> int:
        """세션마다 달라지는 Python hash 대신 고정 seed를 사용한다."""
        normalized = (value or "").strip().lower().encode("utf-8")
        digest = hashlib.sha256(normalized).digest()
        return (int.from_bytes(digest[:8], "big") % 2147483646) + 1

    @staticmethod
    def _sort_images_for_consistency(images: List[CharacterImage]) -> List[CharacterImage]:
        """매번 같은 대표 컷을 고르도록 정렬 우선순위를 고정한다."""
        return sorted(
            images,
            key=lambda img: (
                -float(getattr(img, "quality_score", 0.0) or 0.0),
                float(getattr(img, "blur_score", 0.0) or 0.0),
                0 if getattr(img, "face_detected", True) else 1,
                int(getattr(img, "seed", -1) if getattr(img, "seed", -1) >= 0 else 2147483647),
                getattr(img, "path", ""),
            ),
        )

    def _pick_consistent_image(self, images: List[CharacterImage]) -> Optional[str]:
        for candidate in self._sort_images_for_consistency(images):
            if candidate.path and os.path.exists(candidate.path):
                return candidate.path
        return None

    def _pick_consistent_character_image(
        self,
        character_id: str,
        images: List[CharacterImage],
    ) -> Tuple[str, Optional[CharacterImage]]:
        """Return the first usable candidate plus its metadata after path normalization."""
        for candidate in self._sort_images_for_consistency(images):
            candidate_path = self._canonicalize_character_image_path(
                character_id,
                getattr(candidate, "path", ""),
            )
            if candidate_path and os.path.exists(candidate_path):
                return candidate_path, candidate
        return "", None

    def _canonicalize_character_image_path(self, character_id: str, image_path: str) -> str:
        """Prefer the current character folder over stale or mojibake duplicate paths."""
        raw = str(image_path or "").strip()
        if not raw:
            return ""

        path = Path(raw)
        local_dir = self.library_path / character_id
        basename = path.name

        if basename:
            local_candidate = local_dir / basename
            if local_candidate.exists():
                return str(local_candidate)

            try:
                recursive_match = next(local_dir.rglob(basename))
                if recursive_match.exists():
                    return str(recursive_match)
            except StopIteration:
                pass

        if path.exists():
            return str(path)

        try:
            resolved = (Path.cwd() / path).resolve()
            if resolved.exists():
                return str(resolved)
        except Exception:
            pass

        return raw

    def _load_external_videotoon_manifest(self) -> Dict[str, Any]:
        """Load the optional D-drive VideoToon character manifest advertised by assets/characters/library.json."""
        cached = getattr(self, "_external_videotoon_manifest_cache", None)
        if isinstance(cached, dict):
            return cached

        manifest_pointer_candidates = [
            self.library_path.parent / "library.json",
            Path("assets/characters/library.json"),
        ]
        pointer: Dict[str, Any] = {}
        for candidate in manifest_pointer_candidates:
            try:
                if candidate.exists():
                    pointer = json.loads(candidate.read_text(encoding="utf-8"))
                    if pointer.get("manifest_path"):
                        break
            except Exception:
                pointer = {}

        manifest_path = Path(str(pointer.get("manifest_path", "") or ""))
        if not manifest_path.exists():
            self._external_videotoon_manifest_cache = {}
            return {}

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] external videotoon manifest load failed: {e}")
            manifest = {}
        self._external_videotoon_manifest_cache = manifest
        return manifest

    def _find_external_videotoon_character(self, character_id: str) -> Dict[str, Any]:
        manifest = self._load_external_videotoon_manifest()
        raw_characters = manifest.get("characters", {}) if isinstance(manifest, dict) else {}
        normalized = str(character_id or "").strip().lower()
        if not normalized:
            return {}
        if isinstance(raw_characters, dict):
            candidate = raw_characters.get(normalized) or raw_characters.get(character_id)
            return dict(candidate or {}) if isinstance(candidate, dict) else {}
        if isinstance(raw_characters, list):
            for candidate in raw_characters:
                if not isinstance(candidate, dict):
                    continue
                if str(candidate.get("character_id", "") or "").strip().lower() == normalized:
                    return dict(candidate)
        return {}

    def _derive_external_halfbody_sprite(self, character_id: str, source_path: str) -> str:
        """Create a waist-up alpha sprite from a full-body golden-cast reference."""
        source = Path(str(source_path or ""))
        if not source.exists():
            return ""

        out_dir = source.parent / "halfbody_sprites"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{character_id}_halfbody_alpha.png"
        try:
            if out_path.exists() and out_path.stat().st_mtime >= source.stat().st_mtime:
                return str(out_path)
        except Exception:
            pass

        try:
            image = Image.open(source).convert("RGBA")
            alpha = image.getchannel("A")
            bbox = alpha.getbbox()
            if not bbox:
                return str(source)
            left, top, right, bottom = bbox
            width = right - left
            height = bottom - top
            pad_x = int(width * 0.10)
            pad_top = int(height * 0.02)
            crop_left = max(0, left - pad_x)
            crop_top = max(0, top - pad_top)
            # Waist-to-thigh crop: large enough to avoid floating heads, tight enough for readable acting.
            crop_bottom = min(image.height, top + int(height * 0.68))
            crop_right = min(image.width, right + pad_x)
            if crop_bottom <= crop_top + 64 or crop_right <= crop_left + 64:
                return str(source)
            image.crop((crop_left, crop_top, crop_right, crop_bottom)).save(out_path)
            return str(out_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] halfbody sprite derive failed ({source}): {e}")
            return str(source)

    @staticmethod
    def _normalize_external_expression_id(expression: str) -> str:
        normalized = str(expression or "neutral").strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "neutral": "neutral",
            "default": "neutral",
            "calm": "neutral",
            "fear": "worried",
            "afraid": "worried",
            "anxiety": "worried",
            "anxious": "worried",
            "worried": "worried",
            "tense": "worried",
            "sad": "crying",
            "sadness": "crying",
            "cry": "crying",
            "crying": "crying",
            "tears": "crying",
            "shock": "shocked",
            "shocked": "shocked",
            "surprise": "shocked",
            "surprised": "shocked",
            "panic": "shocked",
            "angry": "angry",
            "anger": "angry",
            "mad": "angry",
            "furious": "angry",
            "relief": "relieved",
            "relieved": "relieved",
            "happy": "relieved",
            "smile": "relieved",
            "smiling": "relieved",
        }
        if normalized in alias_map:
            return alias_map[normalized]
        for key, value in alias_map.items():
            if key and key in normalized:
                return value
        return "neutral"

    def _select_external_expression_entry(self, character: Dict[str, Any], expression: str) -> Dict[str, Any]:
        expression_set = character.get("expression_set", []) if isinstance(character, dict) else []
        if not isinstance(expression_set, list):
            return {}
        by_id: Dict[str, Dict[str, Any]] = {}
        for entry in expression_set:
            if not isinstance(entry, dict):
                continue
            emotion_id = str(entry.get("emotion_id", "") or "").strip().lower()
            if emotion_id:
                by_id[emotion_id] = dict(entry)
        wanted = self._normalize_external_expression_id(expression)
        return by_id.get(wanted) or by_id.get("neutral") or (dict(expression_set[0]) if expression_set else {})

    @staticmethod
    def _estimate_edge_background_color(image: Image.Image) -> Tuple[int, int, int]:
        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = rgb.load()
        samples: List[Tuple[int, int, int]] = []
        step = max(1, min(width, height) // 64)
        for x in range(0, width, step):
            samples.append(pixels[x, 0])
            samples.append(pixels[x, height - 1])
        for y in range(0, height, step):
            samples.append(pixels[0, y])
            samples.append(pixels[width - 1, y])
        if not samples:
            return (236, 220, 190)
        return tuple(int(sorted(channel)[len(channel) // 2]) for channel in zip(*samples))  # type: ignore[return-value]

    @staticmethod
    def _remove_connected_edge_background(image: Image.Image) -> Image.Image:
        """Turn a plain studio background into alpha without touching interior skin tones."""
        rgba = image.convert("RGBA")
        rgb = rgba.convert("RGB")
        width, height = rgb.size
        bg = CharacterLibraryManager._estimate_edge_background_color(rgb)
        pixels = rgb.load()
        alpha = Image.new("L", (width, height), 255)
        alpha_px = alpha.load()
        visited = bytearray(width * height)
        queue: deque[Tuple[int, int]] = deque()
        threshold_sq = 58 * 58

        def _idx(x: int, y: int) -> int:
            return y * width + x

        def _near_background(x: int, y: int) -> bool:
            r, g, b = pixels[x, y]
            return (r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2 <= threshold_sq

        def _push(x: int, y: int) -> None:
            if not (0 <= x < width and 0 <= y < height):
                return
            pos = _idx(x, y)
            if visited[pos] or not _near_background(x, y):
                return
            visited[pos] = 1
            alpha_px[x, y] = 0
            queue.append((x, y))

        for x in range(width):
            _push(x, 0)
            _push(x, height - 1)
        for y in range(height):
            _push(0, y)
            _push(width - 1, y)

        while queue:
            x, y = queue.popleft()
            _push(x - 1, y)
            _push(x + 1, y)
            _push(x, y - 1)
            _push(x, y + 1)

        alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
        rgba.putalpha(alpha)
        return rgba

    def _derive_external_expression_portrait_sprite(
        self,
        character_id: str,
        expression_entry: Dict[str, Any],
    ) -> str:
        """Create an alpha portrait sprite from the golden-cast expression sheet cell."""
        if not expression_entry:
            return ""
        source_path = Path(str(expression_entry.get("transparent_image", "") or ""))
        if not source_path.exists():
            source_path = Path(str(expression_entry.get("reference_image", "") or ""))
        if not source_path.exists():
            return ""

        emotion_id = str(expression_entry.get("emotion_id", "") or "neutral").strip().lower() or "neutral"
        out_dir = source_path.parent / "_portrait_sprites_v1" / character_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{emotion_id}_portrait_alpha.png"
        try:
            if out_path.exists() and out_path.stat().st_mtime >= source_path.stat().st_mtime:
                return str(out_path)
        except Exception:
            pass

        try:
            image = Image.open(source_path).convert("RGBA")
            existing_alpha = image.getchannel("A")
            alpha_bbox = existing_alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
            uses_real_alpha = bool(alpha_bbox and alpha_bbox != (0, 0, image.width, image.height))
            prepared = image if uses_real_alpha else self._remove_connected_edge_background(image)
            alpha = prepared.getchannel("A").point(lambda value: 255 if value > 12 else 0)
            bbox = alpha.getbbox()
            if not bbox:
                return ""
            left, top, right, bottom = bbox
            subject_w = right - left
            subject_h = bottom - top
            pad_x = max(18, int(subject_w * 0.10))
            pad_top = max(10, int(subject_h * 0.05))
            pad_bottom = max(16, int(subject_h * 0.08))
            crop_box = (
                max(0, left - pad_x),
                max(0, top - pad_top),
                min(prepared.width, right + pad_x),
                min(prepared.height, bottom + pad_bottom),
            )
            prepared.crop(crop_box).save(out_path)
            return str(out_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] expression portrait derive failed ({source_path}): {e}")
            return ""

    def _derive_expression_mouth_sprite_bundle(
        self,
        character_id: str,
        character: Dict[str, Any],
        expression_entry: Dict[str, Any],
    ) -> Tuple[Dict[str, str], Dict[str, float]]:
        """Build mouth layers from real expression portrait pixels, not code-drawn stickers."""
        closed_sprite = self._derive_external_expression_portrait_sprite(character_id, expression_entry)
        open_entry = self._select_external_expression_entry(character, "shocked")
        if not open_entry or open_entry == expression_entry:
            open_entry = self._select_external_expression_entry(character, "crying")
        open_sprite = self._derive_external_expression_portrait_sprite(character_id, open_entry)
        if not closed_sprite or not open_sprite:
            return {}, {}

        closed_path = Path(closed_sprite)
        open_path = Path(open_sprite)
        out_dir = closed_path.parent / "_native_mouth_parts_v1" / str(expression_entry.get("emotion_id", "neutral") or "neutral")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_closed = out_dir / "mouth_closed.png"
        output_open = out_dir / "mouth_open.png"

        try:
            closed_image = Image.open(closed_path).convert("RGBA")
            open_image = Image.open(open_path).convert("RGBA")
            if open_image.size != closed_image.size:
                open_image = open_image.resize(closed_image.size, Image.Resampling.LANCZOS)

            width, height = closed_image.size
            face_box = (
                int(width * 0.18),
                int(height * 0.08),
                int(width * 0.82),
                int(height * 0.68),
            )
            face_width = max(1, face_box[2] - face_box[0])
            face_height = max(1, face_box[3] - face_box[1])

            def _mouth_layer(source: Image.Image, target: Path) -> None:
                if target.exists() and target.stat().st_mtime >= closed_path.stat().st_mtime:
                    return
                face_crop = source.crop(face_box)
                mask = Image.new("L", (face_width, face_height), 0)
                draw = ImageDraw.Draw(mask)
                cx = face_width * 0.50
                cy = face_height * 0.72
                rx = face_width * 0.23
                ry = face_height * 0.17
                draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
                mask = mask.filter(ImageFilter.GaussianBlur(max(2, int(face_width * 0.018))))
                alpha = ImageChops.multiply(face_crop.getchannel("A"), mask)
                face_crop.putalpha(alpha)
                face_crop.save(target)

            _mouth_layer(closed_image, output_closed)
            _mouth_layer(open_image, output_open)
            return (
                {
                    "mouth_closed_path": str(output_closed),
                    "mouth_open_path": str(output_open),
                },
                {
                    "face_anchor_x": round(((face_box[0] + face_box[2]) / 2) / max(1, width), 4),
                    "face_anchor_y": round(((face_box[1] + face_box[3]) / 2) / max(1, height), 4),
                    "face_scale": 1.0,
                },
            )
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] expression mouth bundle derive failed ({closed_path}): {e}")
            return {}, {}

    def _normalize_external_face_sprite_bundle(
        self,
        character_id: str,
        bundle: Dict[str, Any],
    ) -> Dict[str, str]:
        """Crop golden-cast face sprites into one shared face-local canvas.

        The manifest stores full-canvas transparent face sprites. Remotion expects
        face-local canvases, so keep the real drawn pixels but remove the unrelated
        transparent stage space. This prevents the synthetic sticker fallback from
        being used for ImageGen characters.
        """
        source_paths = {
            key: Path(str(bundle.get(key, "") or ""))
            for key in ("eyes_open_path", "eyes_closed_path", "mouth_closed_path", "mouth_open_path")
        }
        required = ("mouth_closed_path", "mouth_open_path")
        if any(not source_paths[key].exists() for key in required):
            return {}

        loaded: Dict[str, Tuple[Path, Tuple[int, int], Tuple[int, int, int, int]]] = {}
        for key, source in source_paths.items():
            if not source.exists():
                continue
            try:
                with Image.open(source).convert("RGBA") as image:
                    alpha = image.getchannel("A")
                    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
                    if not bbox:
                        continue
                    loaded[key] = (source, image.size, bbox)
            except Exception as e:
                logger.debug(f"[CharacterLibraryManager] external face sprite read failed ({source}): {e}")

        if any(key not in loaded for key in required):
            return {}

        first_size = next(iter(loaded.values()))[1]
        if any(size != first_size for _source, size, _bbox in loaded.values()):
            return {}

        left = min(bbox[0] for _source, _size, bbox in loaded.values())
        top = min(bbox[1] for _source, _size, bbox in loaded.values())
        right = max(bbox[2] for _source, _size, bbox in loaded.values())
        bottom = max(bbox[3] for _source, _size, bbox in loaded.values())
        width, height = first_size
        union_w = max(1, right - left)
        union_h = max(1, bottom - top)
        pad_x = max(48, int(union_w * 0.85))
        pad_top = max(18, int(union_h * 0.30))
        pad_bottom = max(24, int(union_h * 0.55))
        face_box = (
            max(0, left - pad_x),
            max(0, top - pad_top),
            min(width, right + pad_x),
            min(height, bottom + pad_bottom),
        )
        if face_box[2] <= face_box[0] + 24 or face_box[3] <= face_box[1] + 24:
            return {}

        out_dir = next(iter(loaded.values()))[0].parent / "_normalized_face_canvas_v2" / character_id
        out_dir.mkdir(parents=True, exist_ok=True)

        normalized: Dict[str, str] = {}
        for key, (source, _size, _bbox) in loaded.items():
            output_path = out_dir / f"{key.replace('_path', '')}.png"
            try:
                if output_path.exists() and output_path.stat().st_mtime >= source.stat().st_mtime:
                    normalized[key] = str(output_path)
                    continue
            except Exception:
                pass
            try:
                with Image.open(source).convert("RGBA") as image:
                    image.crop(face_box).save(output_path)
                normalized[key] = str(output_path)
            except Exception as e:
                logger.debug(f"[CharacterLibraryManager] external face sprite normalize failed ({source}): {e}")

        for key in ("eyes_open_path", "eyes_closed_path", "mouth_closed_path", "mouth_open_path"):
            candidate = normalized.get(key, "")
            if candidate:
                try:
                    with Image.open(candidate).convert("RGBA") as image:
                        bbox = image.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
                    if not bbox:
                        normalized[key] = ""
                except Exception:
                    normalized[key] = ""

        if not (normalized.get("mouth_closed_path") and normalized.get("mouth_open_path")):
            return {}
        return normalized

    def get_external_videotoon_sprite_variant(
        self,
        character_id: str,
        expression: str = "neutral",
        pose: str = "standing",
    ) -> Dict[str, Any]:
        """Return the preferred ImageGen golden-cast sprite for VideoToon compositing."""
        character = self._find_external_videotoon_character(character_id)
        if not character:
            return {}

        expression_entry = self._select_external_expression_entry(character, expression)
        normalized_expression = str(expression_entry.get("emotion_id", "") or "").strip().lower()
        requested_expression = self._normalize_external_expression_id(expression)
        expression_sprite_path = ""
        if requested_expression != "neutral":
            expression_sprite_path = self._derive_external_expression_portrait_sprite(
                character_id,
                expression_entry,
            )

        source_path = (
            str(character.get("transparent_image", "") or "")
            or str(character.get("foreground_seed_image", "") or "")
            or str(character.get("reference_image", "") or "")
        )
        halfbody_path = self._derive_external_halfbody_sprite(character_id, source_path)
        foreground_path = expression_sprite_path or halfbody_path
        if not foreground_path or not Path(foreground_path).exists():
            return {}
        bundled_face_parts = self._normalize_external_face_sprite_bundle(
            character_id,
            dict(character.get("face_sprite_bundle", {}) or {}),
        )
        sprite_kind = "expression_portrait" if expression_sprite_path else "halfbody"
        expression_face_parts: Dict[str, str] = {}
        expression_face_rig: Dict[str, float] = {}
        if expression_sprite_path:
            expression_face_parts, expression_face_rig = self._derive_expression_mouth_sprite_bundle(
                character_id,
                character,
                expression_entry,
            )
        face_parts = expression_face_parts or bundled_face_parts
        face_part_source = (
            "native_expression_sprite"
            if expression_face_parts
            else ("native_golden_cast" if face_parts else "none")
        )
        face_anchor_y = 0.34 if expression_sprite_path else 0.14
        face_scale = 1.04 if expression_sprite_path else 0.96
        if expression_face_rig:
            face_anchor_y = expression_face_rig.get("face_anchor_y", face_anchor_y)
            face_scale = expression_face_rig.get("face_scale", face_scale)

        return {
            "variant_key": f"external_golden_cast_{sprite_kind}",
            "expression": normalized_expression or str(expression or "neutral"),
            "pose": str(pose or "standing"),
            "image_path": foreground_path,
            "parts": {"foreground_path": foreground_path},
            "face_parts": face_parts,
            "rig": {
                "external_videotoon_sprite": True,
                "sprite_kind": sprite_kind,
                "character_expression_sprite": bool(expression_sprite_path),
                "face_part_source": face_part_source,
                "allow_synthetic_face_parts": False,
                "face_rig_requested": bool(
                    face_parts.get("mouth_closed_path") and face_parts.get("mouth_open_path")
                ),
                "face_anchor_x": expression_face_rig.get("face_anchor_x", 0.5),
                "face_anchor_y": face_anchor_y,
                "face_scale": face_scale,
            },
        }

    def get_character_image(self,
                            character_id: str,
                            expression: str = "neutral",
                            pose: str = "standing",
                            angle: str = "front",
                            fallback: bool = True) -> Optional[str]:
        """
        캐릭터 이미지 경로 반환 (설계서 4.1)

        Args:
            character_id: 캐릭터 ID
            expression: 표정
            pose: 포즈
            fallback: 없으면 유사 이미지로 폴백

        Returns:
            이미지 경로 또는 None
        """
        entry = self.library.get(character_id)
        if not entry:
            logger.warning(f"[CharacterLibraryManager] 캐릭터 없음: {character_id}")
            return None

        # v63: 각도(턴어라운드) 우선 키 → 각도 없는 레거시 키로 폴백 (하위호환)
        angle = str(angle or "front").strip().lower()
        candidate_keys = []
        if angle and angle != "front":
            candidate_keys.append(f"{expression}_{pose}_{angle}")
        candidate_keys.append(f"{expression}_{pose}_front")
        candidate_keys.append(f"{expression}_{pose}")
        key = f"{expression}_{pose}"
        images = []
        for _ck in candidate_keys:
            _imgs = entry.images.get(_ck, [])
            if _imgs:
                key, images = _ck, _imgs
                break

        if images:
            # 품질 순 정렬 후 랜덤 선택 (상위 50%)
            sorted_images = sorted(images, key=lambda x: x.quality_score, reverse=True)
            top_half = sorted_images[:max(1, len(sorted_images) // 2)]
            selected_path, _ = self._pick_consistent_character_image(character_id, top_half)
            if selected_path:
                return selected_path

        if not fallback:
            return None

        # 폴백 1: 같은 표정 다른 포즈
        for k, imgs in entry.images.items():
            if k.startswith(f"{expression}_") and imgs:
                logger.debug(f"[CharacterLibraryManager] 폴백(표정): {key} → {k}")
                selected_path, _ = self._pick_consistent_character_image(character_id, imgs)
                if selected_path:
                    return selected_path

        # 폴백 2: 같은 포즈 다른 표정
        for k, imgs in entry.images.items():
            if k.endswith(f"_{pose}") and imgs:
                logger.debug(f"[CharacterLibraryManager] 폴백(포즈): {key} → {k}")
                selected_path, _ = self._pick_consistent_character_image(character_id, imgs)
                if selected_path:
                    return selected_path

        # 폴백 3: neutral_standing
        default_imgs = entry.images.get("neutral_standing", [])
        if default_imgs:
            logger.debug(f"[CharacterLibraryManager] 폴백(기본): {key} → neutral_standing")
            selected_path, _ = self._pick_consistent_character_image(character_id, default_imgs)
            if selected_path:
                return selected_path

        # 폴백 4: 아무 이미지나
        for imgs in entry.images.values():
            if imgs:
                logger.debug(f"[CharacterLibraryManager] 폴백(임의)")
                selected_path, _ = self._pick_consistent_character_image(character_id, imgs)
                if selected_path:
                    return selected_path

        return None

    def normalize_expression(self, character_id: str, expression: str) -> str:
        normalized = str(expression or "neutral").strip().lower() or "neutral"
        normalized = EXPRESSION_ALIASES.get(normalized, normalized)
        entry = self.library.get(character_id)
        if not entry:
            return normalized

        available = {
            img.expression.strip().lower()
            for images in entry.images.values()
            for img in images
            if getattr(img, "expression", "")
        }
        if normalized in available:
            return normalized
        if "neutral" in available:
            return "neutral"
        return normalized

    @staticmethod
    def normalize_requested_expression(expression: str) -> str:
        normalized = str(expression or "neutral").strip().lower() or "neutral"
        return EXPRESSION_ALIASES.get(normalized, normalized)

    def normalize_pose(self, character_id: str, pose: str) -> str:
        normalized = str(pose or "standing").strip().lower() or "standing"
        normalized = POSE_ALIASES.get(normalized, normalized)
        entry = self.library.get(character_id)
        if not entry:
            return normalized

        available = {
            img.pose.strip().lower()
            for images in entry.images.values()
            for img in images
            if getattr(img, "pose", "")
        }
        if normalized in available:
            return normalized
        if "standing" in available:
            return "standing"
        return normalized

    @staticmethod
    def normalize_requested_pose(pose: str) -> str:
        normalized = str(pose or "standing").strip().lower() or "standing"
        return POSE_ALIASES.get(normalized, normalized)

    def resolve_variant(self, character_id: str, expression: str, pose: str) -> Tuple[str, str]:
        return (
            self.normalize_expression(character_id, expression),
            self.normalize_pose(character_id, pose),
        )

    def prime_motiontoon_parts(self,
                               image_path: str,
                               *,
                               overlay_kind: str = "document",
                               rig_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """Motiontoon 렌더 전에 컷아웃 파츠를 미리 생성한다."""
        try:
            if not image_path or not os.path.exists(image_path):
                return {}
            parts = build_layered_cutout_assets(
                image_path,
                overlay_kind=overlay_kind,
                strength=0.82,
                force=False,
                rig_overrides=rig_overrides,
            )
            return self._validate_motiontoon_parts(parts)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] motiontoon part prime failed ({image_path}): {e}")
            return {}

    def get_character_parts(self,
                            character_id: str,
                            expression: str = "neutral",
                            pose: str = "standing",
                            angle: str = "front",
                            fallback: bool = True) -> Dict[str, str]:
        """Return motiontoon part assets for the selected character variant."""
        image_path = self.get_character_image(
            character_id=character_id,
            expression=expression,
            pose=pose,
            angle=angle,
            fallback=fallback,
        )
        if not image_path or not os.path.exists(image_path):
            return {}

        parts = self._validate_motiontoon_parts(load_layered_cutout_assets(image_path))
        if parts:
            return parts
        return self.prime_motiontoon_parts(image_path)

    @staticmethod
    def _validate_motiontoon_parts(parts: Dict[str, str]) -> Dict[str, str]:
        if not isinstance(parts, dict):
            return {}
        normalized = {key: str(value or "") for key, value in parts.items() if str(value or "")}
        if not normalized:
            return {}
        for value in normalized.values():
            if not os.path.exists(value):
                return {}
        if not normalized.get("background_path") and not normalized.get("foreground_path"):
            return {}
        return normalized

    def _character_sheet_path(self, character_id: str) -> Path:
        return self.library_path / character_id / "sheet_manifest.json"

    def _character_face_parts_dir(self, character_id: str, variant_key: str) -> Path:
        return self.library_path / character_id / "_face_parts" / variant_key

    def _character_face_portraits_dir(self, character_id: str) -> Path:
        return self.library_path / character_id / "_face_portraits"

    def _get_character_face_part_boxes(self, character_id: str) -> Dict[str, List[float]]:
        config_boxes = dict(getattr(self.config, "face_part_boxes_by_character", {}) or {})
        raw = config_boxes.get(character_id, {})
        if not isinstance(raw, dict):
            return {}

        normalized: Dict[str, List[float]] = {}
        for key in ("face", "eyes", "mouth"):
            value = raw.get(key)
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                continue
            try:
                box = [float(v) for v in value]
            except Exception:
                continue
            if all(0.0 <= v <= 1.0 for v in box) and box[2] > box[0] and box[3] > box[1]:
                normalized[key] = box
        return normalized

    @staticmethod
    def _detect_face_bbox(source: Image.Image) -> Optional[Tuple[int, int, int, int]]:
        try:
            import cv2
            import numpy as np

            rgb = source.convert("RGB")
            frame = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2GRAY)
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            faces = face_cascade.detectMultiScale(
                frame,
                scaleFactor=1.05,
                minNeighbors=4,
                minSize=(24, 24),
            )
            if len(faces) == 0:
                return None
            x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
            return int(x), int(y), int(x + w), int(y + h)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] face detect failed: {e}")
            return None

    @staticmethod
    def _detect_face_bbox_in_subject(
        source: Image.Image,
        subject_bbox: Tuple[int, int, int, int],
    ) -> Optional[Tuple[int, int, int, int]]:
        left, top, right, bottom = subject_bbox
        subject_w = max(1, right - left)
        subject_h = max(1, bottom - top)
        head_box = (
            max(0, int(left + subject_w * 0.08)),
            max(0, top),
            min(source.width, int(right - subject_w * 0.08)),
            min(source.height, int(top + subject_h * 0.34)),
        )
        if head_box[2] - head_box[0] < 24 or head_box[3] - head_box[1] < 24:
            return CharacterLibraryManager._detect_face_bbox(source)

        with source.crop(head_box) as head_crop:
            detected = CharacterLibraryManager._detect_face_bbox(head_crop)
            if not detected:
                return CharacterLibraryManager._detect_face_bbox(source)
            crop_left, crop_top, crop_right, crop_bottom = detected
            return (
                head_box[0] + crop_left,
                head_box[1] + crop_top,
                head_box[0] + crop_right,
                head_box[1] + crop_bottom,
            )

    @staticmethod
    def _part_box_from_face_bbox(
        face_bbox: Tuple[int, int, int, int],
        source_size: Tuple[int, int],
        part_kind: str,
    ) -> Tuple[int, int, int, int]:
        width, height = source_size
        left, top, right, bottom = face_bbox
        face_w = max(1, right - left)
        face_h = max(1, bottom - top)

        if part_kind == "eyes":
            crop = (
                int(left + face_w * 0.08),
                int(top + face_h * 0.10),
                int(right - face_w * 0.08),
                int(top + face_h * 0.38),
            )
        elif part_kind == "mouth":
            crop = (
                int(left + face_w * 0.20),
                int(top + face_h * 0.64),
                int(right - face_w * 0.20),
                int(bottom - face_h * 0.06),
            )
        else:
            crop = (
                int(left - face_w * 0.08),
                int(top - face_h * 0.08),
                int(right + face_w * 0.08),
                int(bottom + face_h * 0.12),
            )

        return (
            max(0, crop[0]),
            max(0, crop[1]),
            min(width, crop[2]),
            min(height, crop[3]),
        )

    @staticmethod
    def _box_iou(
        box_a: Tuple[int, int, int, int],
        box_b: Tuple[int, int, int, int],
    ) -> float:
        left = max(box_a[0], box_b[0])
        top = max(box_a[1], box_b[1])
        right = min(box_a[2], box_b[2])
        bottom = min(box_a[3], box_b[3])
        if right <= left or bottom <= top:
            return 0.0
        intersection = float((right - left) * (bottom - top))
        area_a = float(max(1, box_a[2] - box_a[0]) * max(1, box_a[3] - box_a[1]))
        area_b = float(max(1, box_b[2] - box_b[0]) * max(1, box_b[3] - box_b[1]))
        union = area_a + area_b - intersection
        if union <= 0:
            return 0.0
        return intersection / union

    def _resolve_generation_override_path(self, char_path: Path, raw_path: str, label: str) -> str:
        path_value = str(raw_path or "").strip()
        if not path_value:
            return ""
        try:
            override_path = Path(path_value)
            if not override_path.is_absolute():
                override_path = (char_path / override_path).resolve()
            if override_path.exists():
                return str(override_path)
            logger.warning(f"[CharacterLibraryManager] generation override {label} missing: {path_value}")
        except Exception as e:
            logger.warning(
                f"[CharacterLibraryManager] failed to resolve generation override {label} ({path_value}): {e}"
            )
        return ""

    def _apply_consistency_reference_payload(
        self,
        payload: Dict[str, Any],
        consistency_image_path: Optional[str] = None,
        consistency_mode: str = "",
        consistency_weight: Optional[float] = None,
        consistency_control_mode: str = "",
        consistency_start_step: Optional[float] = None,
        consistency_end_step: Optional[float] = None,
    ) -> Dict[str, Any]:
        image_path = str(consistency_image_path or "").strip()
        if not image_path:
            return payload
        try:
            from core.ip_adapter_bridge import IPAdapterConfig, IPAdapterMode, get_ip_adapter_bridge

            mode_key = str(consistency_mode or "").strip().lower()
            mode_map = {
                "face": IPAdapterMode.FACE,
                "full": IPAdapterMode.FULL,
                "face_plus": IPAdapterMode.FACE_PLUS,
            }
            config = IPAdapterConfig(
                enabled=True,
                mode=mode_map.get(mode_key, IPAdapterMode.FACE_PLUS),
                weight=float(consistency_weight) if consistency_weight is not None else 0.72,
                reference_images=[image_path],
            )
            if consistency_control_mode:
                config.control_mode = str(consistency_control_mode)
            if consistency_start_step is not None:
                config.start_step = float(consistency_start_step)
            if consistency_end_step is not None:
                config.end_step = float(consistency_end_step)
            bridge = get_ip_adapter_bridge(self.sd_api_url)
            return bridge.enhance_payload(payload, config, reference_image_path=image_path)
        except Exception as e:
            logger.warning(f"[CharacterLibraryManager] failed to apply consistency reference: {e}")
            return payload

    def _append_pose_reference_payload(
        self,
        payload: Dict[str, Any],
        pose_image_path: Optional[str] = None,
        pose_module: str = "reference_only",
        pose_weight: Optional[float] = None,
        pose_control_mode: str = "",
        pose_start_step: Optional[float] = None,
        pose_end_step: Optional[float] = None,
    ) -> Dict[str, Any]:
        image_path = str(pose_image_path or "").strip()
        if not image_path:
            return payload
        try:
            with open(image_path, "rb") as fh:
                encoded_image = base64.b64encode(fh.read()).decode("utf-8")

            unit = {
                "enabled": True,
                "module": str(pose_module or "reference_only").strip() or "reference_only",
                "model": "None",
                "weight": float(pose_weight) if pose_weight is not None else 0.6,
                "image": encoded_image,
                "resize_mode": "Crop and Resize",
                "control_mode": str(pose_control_mode or "").strip() or "My prompt is more important",
                "guidance_start": float(pose_start_step) if pose_start_step is not None else 0.0,
                "guidance_end": float(pose_end_step) if pose_end_step is not None else 0.9,
            }

            result = dict(payload)
            alwayson_scripts = dict(result.get("alwayson_scripts") or {})
            controlnet = dict(alwayson_scripts.get("controlnet") or {})
            controlnet_args = list(controlnet.get("args") or [])
            controlnet_args.append(unit)
            controlnet["args"] = controlnet_args
            alwayson_scripts["controlnet"] = controlnet
            result["alwayson_scripts"] = alwayson_scripts
            return result
        except Exception as e:
            logger.warning(f"[CharacterLibraryManager] failed to append pose reference: {e}")
            return payload

    def _append_openpose_angle_payload(self, payload: Dict[str, Any], angle: str = "front") -> Dict[str, Any]:
        """v63: 각도별 OpenPose 스켈레톤을 ControlNet 유닛으로 추가 (턴어라운드 정밀 생성).

        스켈레톤: assets/actor_models/_openpose/<angle>.png (사전 렌더). 없으면 프롬프트만으로 폴백.
        """
        angle = str(angle or "front").strip().lower() or "front"
        try:
            from config.settings import config as _cfg
            root = Path(getattr(_cfg, "PROJECT_ROOT", "") or getattr(_cfg, "BASE_DIR", "") or ".")
        except Exception:
            root = Path(".")
        skeleton = root / "assets" / "actor_models" / "_openpose" / f"{angle}.png"
        if not skeleton.exists():
            return payload  # 스켈레톤 없으면 프롬프트만으로 생성 (안전 폴백)
        try:
            with open(skeleton, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("utf-8")
            model = os.environ.get("REVERIE_OPENPOSE_CONTROLNET_MODEL", "control_v11p_sd15_openpose")
            unit = {
                "enabled": True,
                "module": "none",  # 사전 렌더된 스켈레톤 → 전처리 불필요
                "model": model,
                "weight": 1.0,
                "image": encoded,
                "resize_mode": "Crop and Resize",
                "control_mode": "Balanced",
                "guidance_start": 0.0,
                "guidance_end": 0.9,
            }
            result = dict(payload)
            alwayson = dict(result.get("alwayson_scripts") or {})
            controlnet = dict(alwayson.get("controlnet") or {})
            args = list(controlnet.get("args") or [])
            args.append(unit)
            controlnet["args"] = args
            alwayson["controlnet"] = controlnet
            result["alwayson_scripts"] = alwayson
            logger.info(f"[CharacterLibraryManager] OpenPose 각도 ControlNet 적용: {angle}")
            return result
        except Exception as e:
            logger.warning(f"[CharacterLibraryManager] openpose angle payload 실패: {e}")
            return payload

    @staticmethod
    def _get_variant_face_crop_box(image_path: str,
                                   variant: Dict[str, Any],
                                   part_kind: str = "face") -> Optional[Tuple[int, int, int, int]]:
        try:
            parts = dict(variant.get("parts", {}) or {})
            source_path = str(image_path or parts.get("foreground_path") or "")
            if not source_path or not os.path.exists(source_path):
                return None

            with Image.open(source_path).convert("RGBA") as source:
                normalized_source_path = source_path.replace("\\", "/").lower()
                is_face_portrait = (
                    "/_face_portraits/" in normalized_source_path
                    or (
                        not variant
                        and source.width >= 256
                        and source.height >= 256
                        and abs(source.width - source.height) <= 48
                    )
                )
                if is_face_portrait:
                    portrait_meta_path = CharacterLibraryManager._portrait_meta_path(Path(source_path))
                    if portrait_meta_path.exists():
                        try:
                            portrait_meta = json.loads(portrait_meta_path.read_text(encoding="utf-8"))
                            box = portrait_meta.get(f"{part_kind}_box")
                            if isinstance(box, list) and len(box) == 4:
                                return (
                                    max(0, int(box[0])),
                                    max(0, int(box[1])),
                                    min(source.width, int(box[2])),
                                    min(source.height, int(box[3])),
                                )
                        except Exception:
                            pass
                    detected_portrait_box = CharacterLibraryManager._detect_feature_box_in_portrait(source, part_kind)
                    if detected_portrait_box:
                        return detected_portrait_box
                    width = source.width
                    height = source.height
                    if part_kind == "eyes":
                        crop = (
                            int(width * 0.18),
                            int(height * 0.22),
                            int(width * 0.82),
                            int(height * 0.48),
                        )
                    elif part_kind == "mouth":
                        crop = (
                            int(width * 0.30),
                            int(height * 0.52),
                            int(width * 0.70),
                            int(height * 0.74),
                        )
                    else:
                        crop = (
                            int(width * 0.12),
                            int(height * 0.08),
                            int(width * 0.88),
                            int(height * 0.84),
                        )
                    return (
                        max(0, crop[0]),
                        max(0, crop[1]),
                        min(width, crop[2]),
                        min(height, crop[3]),
                    )

                alpha = source.getchannel("A")
                bbox = alpha.getbbox()
                if not bbox:
                    bbox = (0, 0, source.width, source.height)

                left, top, right, bottom = bbox
                subject_w = max(1, right - left)
                subject_h = max(1, bottom - top)
                detected_face = CharacterLibraryManager._detect_face_bbox_in_subject(source, bbox)
                sane_detected_face = False
                if detected_face:
                    face_left, face_top, face_right, face_bottom = detected_face
                    face_w = max(1, face_right - face_left)
                    face_h = max(1, face_bottom - face_top)
                    sane_detected_face = (
                        face_left >= left - int(subject_w * 0.05) and
                        face_right <= right + int(subject_w * 0.05) and
                        face_top >= top - int(subject_h * 0.04) and
                        face_top <= top + int(subject_h * 0.32) and
                        face_w <= int(subject_w * 0.58) and
                        face_h <= int(subject_h * 0.34)
                    )

                is_sheet_sprite = (
                    (
                        "/assets/characters/" in normalized_source_path
                        or normalized_source_path.startswith("assets/characters/")
                    )
                    and "/_face_portraits/" not in normalized_source_path
                )
                if is_sheet_sprite:
                    face_part_boxes = dict(variant.get("face_part_boxes", {}) or {})
                    face_override = face_part_boxes.get("face")
                    eyes_override = face_part_boxes.get("eyes")
                    mouth_override = face_part_boxes.get("mouth")
                    if (
                        isinstance(face_override, (list, tuple))
                        and len(face_override) == 4
                        and all(isinstance(v, (int, float)) for v in face_override)
                    ):
                        override_face = (
                            int(left + subject_w * float(face_override[0])),
                            int(top + subject_h * float(face_override[1])),
                            int(left + subject_w * float(face_override[2])),
                            int(top + subject_h * float(face_override[3])),
                        )
                        resolved_face = override_face
                        using_override_face = True
                        if sane_detected_face and detected_face:
                            override_center_x = (override_face[0] + override_face[2]) / 2.0
                            override_center_y = (override_face[1] + override_face[3]) / 2.0
                            detected_center_x = (detected_face[0] + detected_face[2]) / 2.0
                            detected_center_y = (detected_face[1] + detected_face[3]) / 2.0
                            center_dx = abs(override_center_x - detected_center_x) / max(1.0, float(subject_w))
                            center_dy = abs(override_center_y - detected_center_y) / max(1.0, float(subject_h))
                            if (
                                CharacterLibraryManager._box_iou(override_face, detected_face) < 0.14
                                or center_dx > 0.12
                                or center_dy > 0.08
                            ):
                                resolved_face = detected_face
                                using_override_face = False

                        face_left, face_top, face_right, face_bottom = resolved_face
                        face_w = max(1, face_right - face_left)
                        face_h = max(1, face_bottom - face_top)
                        if part_kind == "face":
                            crop = resolved_face
                        elif part_kind == "eyes":
                            if (
                                using_override_face and
                                isinstance(eyes_override, (list, tuple))
                                and len(eyes_override) == 4
                                and all(isinstance(v, (int, float)) for v in eyes_override)
                            ):
                                crop = (
                                    int(left + subject_w * float(eyes_override[0])),
                                    int(top + subject_h * float(eyes_override[1])),
                                    int(left + subject_w * float(eyes_override[2])),
                                    int(top + subject_h * float(eyes_override[3])),
                                )
                            else:
                                detected = CharacterLibraryManager._detect_dark_feature_box(
                                    source,
                                    (
                                        int(face_left + face_w * 0.08),
                                        int(face_top + face_h * 0.18),
                                        int(face_left + face_w * 0.92),
                                        int(face_top + face_h * 0.58),
                                    ),
                                    darkness_ratio=0.88,
                                    min_pixels=max(12, (face_w * face_h) // 1100),
                                    expand_x=max(4, face_w // 18),
                                    expand_y=max(4, face_h // 24),
                                )
                                crop = detected or CharacterLibraryManager._part_box_from_face_bbox(
                                    resolved_face,
                                    (source.width, source.height),
                                    "eyes",
                                )
                        elif part_kind == "mouth":
                            if (
                                using_override_face and
                                isinstance(mouth_override, (list, tuple))
                                and len(mouth_override) == 4
                                and all(isinstance(v, (int, float)) for v in mouth_override)
                            ):
                                crop = (
                                    int(left + subject_w * float(mouth_override[0])),
                                    int(top + subject_h * float(mouth_override[1])),
                                    int(left + subject_w * float(mouth_override[2])),
                                    int(top + subject_h * float(mouth_override[3])),
                                )
                            else:
                                detected = CharacterLibraryManager._detect_dark_feature_box(
                                    source,
                                    (
                                        int(face_left + face_w * 0.18),
                                        int(face_top + face_h * 0.48),
                                        int(face_left + face_w * 0.82),
                                        int(face_top + face_h * 0.86),
                                    ),
                                    darkness_ratio=0.86,
                                    min_pixels=max(10, (face_w * face_h) // 1500),
                                    expand_x=max(4, face_w // 20),
                                    expand_y=max(4, face_h // 20),
                                )
                                crop = detected or CharacterLibraryManager._part_box_from_face_bbox(
                                    resolved_face,
                                    (source.width, source.height),
                                    "mouth",
                                )
                        else:
                            crop = (
                                int(face_left + face_w * 0.08),
                                int(face_top + face_h * 0.12),
                                int(face_left + face_w * 0.92),
                                int(face_top + face_h * 0.92),
                            )
                    elif part_kind == "eyes":
                        crop = (
                            int(left + subject_w * 0.33),
                            int(top + subject_h * 0.10),
                            int(left + subject_w * 0.67),
                            int(top + subject_h * 0.16),
                        )
                    elif part_kind == "mouth":
                        crop = (
                            int(left + subject_w * 0.40),
                            int(top + subject_h * 0.15),
                            int(left + subject_w * 0.60),
                            int(top + subject_h * 0.20),
                        )
                    else:
                        crop = (
                            int(left + subject_w * 0.30),
                            int(top + subject_h * 0.03),
                            int(left + subject_w * 0.70),
                            int(top + subject_h * 0.24),
                        )
                    return (
                        max(0, crop[0]),
                        max(0, crop[1]),
                        min(source.width, crop[2]),
                        min(source.height, crop[3]),
                    )

                if sane_detected_face and detected_face:
                    face_left, face_top, face_right, face_bottom = detected_face
                    face_w = max(1, face_right - face_left)
                    face_h = max(1, face_bottom - face_top)
                    crop = CharacterLibraryManager._part_box_from_face_bbox(
                        detected_face,
                        (source.width, source.height),
                        part_kind,
                    )
                    if crop[2] - crop[0] >= 12 and crop[3] - crop[1] >= 12:
                        return crop

                rig = dict(variant.get("rig", {}) or {})
                center_x = left + subject_w * float(rig.get("face_anchor_x", 0.5) or 0.5)
                fallback_anchor_y = 0.16 if part_kind in {"eyes", "mouth", "face"} else 0.25
                center_y = top + subject_h * float(rig.get("face_anchor_y", fallback_anchor_y) or fallback_anchor_y)
                face_scale = float(rig.get("face_scale", 1.0) or 1.0)

                if part_kind == "eyes":
                    crop_w = max(24, int(subject_w * 0.26 * face_scale))
                    crop_h = max(16, int(subject_h * 0.09 * face_scale))
                    center_y -= int(subject_h * 0.03)
                elif part_kind == "mouth":
                    crop_w = max(20, int(subject_w * 0.18 * face_scale))
                    crop_h = max(14, int(subject_h * 0.07 * face_scale))
                    center_y += int(subject_h * 0.05)
                else:
                    crop_w = max(24, int(subject_w * 0.30 * face_scale))
                    crop_h = max(24, int(subject_h * 0.18 * face_scale))
                crop_left = max(0, int(center_x - crop_w / 2))
                crop_top = max(0, int(center_y - crop_h / 2))
                crop_right = min(source.width, crop_left + crop_w)
                crop_bottom = min(source.height, crop_top + crop_h)
                if crop_right - crop_left < 16 or crop_bottom - crop_top < 16:
                    return None
                return crop_left, crop_top, crop_right, crop_bottom
        except Exception:
            return None

    @staticmethod
    def _detect_dark_feature_box(
        image: Image.Image,
        search_box: Tuple[int, int, int, int],
        *,
        darkness_ratio: float,
        min_pixels: int,
        expand_x: int,
        expand_y: int,
    ) -> Optional[Tuple[int, int, int, int]]:
        left, top, right, bottom = search_box
        crop = image.crop(search_box).convert("RGBA")
        gray = crop.convert("L")
        alpha = crop.getchannel("A")
        width, height = crop.size
        gray_px = gray.load()
        alpha_px = alpha.load()
        values: List[int] = []
        for y in range(height):
            for x in range(width):
                if alpha_px[x, y] > 12:
                    values.append(gray_px[x, y])
        if not values:
            return None
        threshold = max(24, min(170, int((sum(values) / len(values)) * darkness_ratio)))
        xs: List[int] = []
        ys: List[int] = []
        for y in range(height):
            for x in range(width):
                if alpha_px[x, y] > 12 and gray_px[x, y] <= threshold:
                    xs.append(x)
                    ys.append(y)
        if len(xs) < min_pixels:
            return None
        return (
            max(0, left + min(xs) - expand_x),
            max(0, top + min(ys) - expand_y),
            min(image.width, left + max(xs) + expand_x),
            min(image.height, top + max(ys) + expand_y),
        )

    @staticmethod
    def _detect_feature_box_in_portrait(
        image: Image.Image,
        part_kind: str,
    ) -> Optional[Tuple[int, int, int, int]]:
        width, height = image.size
        if part_kind == "mouth":
            return CharacterLibraryManager._detect_dark_feature_box(
                image,
                (
                    int(width * 0.24),
                    int(height * 0.38),
                    int(width * 0.76),
                    int(height * 0.82),
                ),
                darkness_ratio=0.82,
                min_pixels=max(18, (width * height) // 3500),
                expand_x=max(6, width // 22),
                expand_y=max(6, height // 28),
            )
        if part_kind == "eyes":
            left_eye = CharacterLibraryManager._detect_dark_feature_box(
                image,
                (
                    int(width * 0.08),
                    int(height * 0.16),
                    int(width * 0.48),
                    int(height * 0.52),
                ),
                darkness_ratio=0.78,
                min_pixels=max(20, (width * height) // 3000),
                expand_x=max(8, width // 24),
                expand_y=max(6, height // 30),
            )
            right_eye = CharacterLibraryManager._detect_dark_feature_box(
                image,
                (
                    int(width * 0.52),
                    int(height * 0.16),
                    int(width * 0.92),
                    int(height * 0.52),
                ),
                darkness_ratio=0.78,
                min_pixels=max(20, (width * height) // 3000),
                expand_x=max(8, width // 24),
                expand_y=max(6, height // 30),
            )
            if left_eye and right_eye:
                return (
                    min(left_eye[0], right_eye[0]),
                    min(left_eye[1], right_eye[1]),
                    max(left_eye[2], right_eye[2]),
                    max(left_eye[3], right_eye[3]),
                )
            return left_eye or right_eye
        return None

    def _save_real_face_part(
        self,
        image_path: str,
        variant: Dict[str, Any],
        output_path: Path,
        part_kind: str = "face",
    ) -> str:
        crop_box = self._get_variant_face_crop_box(image_path, variant, part_kind=part_kind)
        if not crop_box:
            return ""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            source_path = str(image_path or "")
            with Image.open(source_path).convert("RGBA") as source:
                crop = source.crop(crop_box)
                crop.save(output_path)
            return str(output_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] real face part save failed ({output_path.name}): {e}")
            return ""

    @staticmethod
    def _face_part_difference_score(base_path: str, candidate_path: str) -> float:
        try:
            with Image.open(base_path).convert("RGBA") as base_img, Image.open(candidate_path).convert("RGBA") as cand_img:
                width = min(base_img.width, cand_img.width)
                height = min(base_img.height, cand_img.height)
                if width <= 0 or height <= 0:
                    return 0.0
                if base_img.size != (width, height):
                    base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)
                if cand_img.size != (width, height):
                    cand_img = cand_img.resize((width, height), Image.Resampling.LANCZOS)
                diff = ImageChops.difference(base_img, cand_img)
                stat = ImageStat.Stat(diff)
                return float(sum(stat.mean) / max(1, len(stat.mean)))
        except Exception:
            return 0.0

    def _build_part_from_portrait(
        self,
        character_id: str,
        expression: str,
        pose: str,
        source_image_path: str,
        source_variant: Dict[str, Any],
        output_path: Path,
        *,
        part_kind: str,
    ) -> str:
        portrait_path = self._ensure_face_portrait_variant(
            character_id,
            expression,
            pose,
            source_image_path,
            source_variant,
        )
        if portrait_path and os.path.exists(portrait_path):
            saved = self._save_real_face_part(
                portrait_path,
                {},
                output_path,
                part_kind=part_kind,
            )
            if saved and self._is_face_part_sane(saved, part_kind):
                return saved

        saved = self._save_real_face_part(
            source_image_path,
            source_variant,
            output_path,
            part_kind=part_kind,
        )
        if saved and self._is_face_part_sane(saved, part_kind):
            return saved
        return ""

    @staticmethod
    def _is_face_part_sane(image_path: str, part_kind: str) -> bool:
        try:
            with Image.open(image_path).convert("RGBA") as img:
                width, height = img.size
                if width <= 0 or height <= 0:
                    return False

                alpha = img.getchannel("A")
                alpha_bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
                if alpha_bbox:
                    bbox_width = max(1, alpha_bbox[2] - alpha_bbox[0])
                    bbox_height = max(1, alpha_bbox[3] - alpha_bbox[1])
                else:
                    bbox_width = width
                    bbox_height = height

                aspect = bbox_width / max(1, bbox_height)

                if part_kind == "eyes":
                    if bbox_width < 40 or bbox_width > 220:
                        return False
                    if bbox_height < 12 or bbox_height > 90:
                        return False
                    if aspect < 1.4 or aspect > 8.5:
                        return False
                elif part_kind == "mouth":
                    if bbox_width < 28 or bbox_width > 180:
                        return False
                    if bbox_height < 12 or bbox_height > 110:
                        return False
                    if aspect < 0.9 or aspect > 5.5:
                        return False

                rgb = img.convert("RGB")
                crop = rgb.crop(alpha_bbox) if alpha_bbox else rgb
                stat = ImageStat.Stat(crop)
                mean_luma = sum(stat.mean[:3]) / 3.0
                extrema = crop.getextrema()
                avg_range = sum(max_v - min_v for min_v, max_v in extrema[:3]) / 3.0

                if avg_range < 8:
                    return False
                if part_kind == "eyes" and mean_luma > 235:
                    return False
                return True
        except Exception:
            return False

    def _save_face_overlay_part(
        self,
        image_path: str,
        variant: Dict[str, Any],
        output_path: Path,
        *,
        part_kind: str,
    ) -> str:
        face_box = self._get_variant_face_crop_box(image_path, variant, part_kind="face")
        part_box = self._get_variant_face_crop_box(image_path, variant, part_kind=part_kind)
        if not face_box or not part_box:
            return ""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(image_path).convert("RGBA") as source:
                face_w = max(1, face_box[2] - face_box[0])
                face_h = max(1, face_box[3] - face_box[1])
                canvas = Image.new("RGBA", (face_w, face_h), (0, 0, 0, 0))
                crop = source.crop(part_box)
                offset = (
                    max(0, part_box[0] - face_box[0]),
                    max(0, part_box[1] - face_box[1]),
                )
                canvas.paste(crop, offset, crop)
                canvas.save(output_path)
            return str(output_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] face overlay part save failed ({output_path.name}): {e}")
            return ""

    @staticmethod
    def _sample_patch_average(image: Image.Image, box: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        crop = image.crop(box)
        stat = ImageStat.Stat(crop)
        rgba = [int(v) for v in stat.mean[:4]]
        while len(rgba) < 4:
            rgba.append(255)
        return tuple(max(0, min(255, c)) for c in rgba)  # type: ignore[return-value]

    def _synthesize_closed_eyes_part(self, base_path: str, output_path: Path) -> str:
        try:
            with Image.open(base_path).convert("RGBA") as src:
                width, height = src.size
                canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
                line_color = self._sample_patch_average(src, (0, 0, width, max(1, int(height * 0.5))))
                eye_boxes = [
                    self._detect_dark_feature_box(
                        src,
                        (0, 0, width // 2, height),
                        darkness_ratio=0.82,
                        min_pixels=max(10, (width * height) // 5000),
                        expand_x=max(3, width // 50),
                        expand_y=max(3, height // 50),
                    ),
                    self._detect_dark_feature_box(
                        src,
                        (width // 2, 0, width, height),
                        darkness_ratio=0.82,
                        min_pixels=max(10, (width * height) // 5000),
                        expand_x=max(3, width // 50),
                        expand_y=max(3, height // 50),
                    ),
                ]
                if not any(eye_boxes):
                    band_top = max(0, int(height * 0.22))
                    band_bottom = min(height, max(band_top + 12, int(height * 0.78)))
                    eye_boxes = [
                        (
                            max(0, int(width * 0.06)),
                            band_top,
                            min(width, max(int(width * 0.40), int(width * 0.06) + 20)),
                            band_bottom,
                        ),
                        (
                            max(0, int(width * 0.60)),
                            band_top,
                            min(width, max(int(width * 0.94), int(width * 0.60) + 20)),
                            band_bottom,
                        ),
                    ]
                for eye_box in eye_boxes:
                    if not eye_box:
                        continue
                    patch_w = max(1, eye_box[2] - eye_box[0])
                    patch_h = max(1, eye_box[3] - eye_box[1])
                    temp = Image.new("RGBA", (patch_w, patch_h), (0, 0, 0, 0))
                    temp_draw = ImageDraw.Draw(temp)
                    patch_color = self._sample_patch_average(src, eye_box)
                    temp_draw.rounded_rectangle(
                        (
                            max(0, int(patch_w * 0.02)),
                            max(0, int(patch_h * 0.18)),
                            min(patch_w - 1, int(patch_w * 0.98)),
                            min(patch_h - 1, int(patch_h * 0.84)),
                        ),
                        radius=max(2, patch_h // 3),
                        fill=(patch_color[0], patch_color[1], patch_color[2], max(160, patch_color[3])),
                    )
                    center_y = int(patch_h * 0.56)
                    lid_color = (
                        max(0, line_color[0] // 3),
                        max(0, line_color[1] // 3),
                        max(0, line_color[2] // 3),
                        255,
                    )
                    temp_draw.line(
                        [
                            (int(patch_w * 0.10), center_y),
                            (int(patch_w * 0.50), center_y - max(1, patch_h // 10)),
                            (int(patch_w * 0.90), center_y),
                        ],
                        fill=lid_color,
                        width=max(4, patch_h // 4),
                    )
                    temp = temp.filter(ImageFilter.GaussianBlur(radius=max(0.4, patch_w / 80)))
                    canvas.paste(temp, eye_box[:2], temp)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                canvas.save(output_path)
            return str(output_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] synth closed eyes failed ({output_path.name}): {e}")
            return ""

    def _synthesize_open_mouth_part(self, base_path: str, output_path: Path) -> str:
        try:
            with Image.open(base_path).convert("RGBA") as src:
                width, height = src.size
                canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
                bbox = self._detect_dark_feature_box(
                    src,
                    (0, 0, width, height),
                    darkness_ratio=0.86,
                    min_pixels=max(8, (width * height) // 7000),
                    expand_x=max(2, width // 60),
                    expand_y=max(2, height // 60),
                )
                if not bbox:
                    alpha = src.getchannel("A")
                    bbox = alpha.getbbox()
                if not bbox:
                    return ""
                bbox_width = max(1, bbox[2] - bbox[0])
                bbox_height = max(1, bbox[3] - bbox[1])
                if bbox_width < max(24, int(width * 0.34)) or bbox_height < max(16, int(height * 0.38)):
                    bbox = (
                        max(0, int(width * 0.18)),
                        max(0, int(height * 0.16)),
                        min(width, int(width * 0.82)),
                        min(height, int(height * 0.84)),
                    )
                patch = src.crop(bbox)
                patch_w = max(1, bbox[2] - bbox[0])
                patch_h = max(1, bbox[3] - bbox[1])
                temp = Image.new("RGBA", (patch_w, patch_h), (0, 0, 0, 0))
                temp_draw = ImageDraw.Draw(temp)
                inner_box = (
                    int(patch_w * 0.10),
                    int(patch_h * 0.12),
                    int(patch_w * 0.90),
                    int(patch_h * 0.88),
                )
                temp_draw.rounded_rectangle(
                    inner_box,
                    radius=max(2, patch_w // 6),
                    fill=(80, 24, 32, 240),
                    outline=(156, 88, 98, 225),
                    width=max(1, patch_w // 18),
                )
                highlight_box = (
                    int(patch_w * 0.24),
                    int(patch_h * 0.28),
                    int(patch_w * 0.76),
                    int(patch_h * 0.42),
                )
                temp_draw.rounded_rectangle(
                    highlight_box,
                    radius=max(1, patch_w // 12),
                    fill=(198, 124, 136, 170),
                )
                temp = temp.filter(ImageFilter.GaussianBlur(radius=max(0.4, patch_w / 96)))
                canvas.paste(temp, bbox[:2], temp)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                canvas.save(output_path)
            return str(output_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] synth open mouth failed ({output_path.name}): {e}")
            return ""

    @staticmethod
    def _portrait_meta_path(portrait_path: Path) -> Path:
        return portrait_path.with_suffix(".json")

    @staticmethod
    def _default_portrait_part_boxes(portrait_size: Tuple[int, int] = (512, 512)) -> Dict[str, Tuple[int, int, int, int]]:
        width, height = portrait_size
        return {
            "face": (
                int(width * 0.15),
                int(height * 0.10),
                int(width * 0.85),
                int(height * 0.86),
            ),
            "eyes": (
                int(width * 0.18),
                int(height * 0.18),
                int(width * 0.82),
                int(height * 0.42),
            ),
            "mouth": (
                int(width * 0.34),
                int(height * 0.42),
                int(width * 0.66),
                int(height * 0.62),
            ),
        }

    @staticmethod
    def _clamp_portrait_box(
        part_kind: str,
        box: Tuple[int, int, int, int],
        portrait_size: Tuple[int, int] = (512, 512),
    ) -> Tuple[int, int, int, int]:
        width, height = portrait_size
        left, top, right, bottom = box
        if part_kind == "eyes":
            min_left, max_right = int(width * 0.12), int(width * 0.88)
            min_top, max_bottom = int(height * 0.12), int(height * 0.44)
            min_w, max_w = int(width * 0.22), int(width * 0.70)
            min_h, max_h = int(height * 0.08), int(height * 0.24)
        elif part_kind == "mouth":
            min_left, max_right = int(width * 0.24), int(width * 0.76)
            min_top, max_bottom = int(height * 0.34), int(height * 0.72)
            min_w, max_w = int(width * 0.12), int(width * 0.40)
            min_h, max_h = int(height * 0.07), int(height * 0.20)
        else:
            min_left, max_right = int(width * 0.10), int(width * 0.90)
            min_top, max_bottom = int(height * 0.08), int(height * 0.90)
            min_w, max_w = int(width * 0.30), int(width * 0.76)
            min_h, max_h = int(height * 0.26), int(height * 0.84)

        box_w = max(min_w, min(max_w, right - left))
        box_h = max(min_h, min(max_h, bottom - top))
        center_x = max(min_left + box_w / 2, min(max_right - box_w / 2, (left + right) / 2))
        center_y = max(min_top + box_h / 2, min(max_bottom - box_h / 2, (top + bottom) / 2))

        clamped = (
            int(center_x - box_w / 2),
            int(center_y - box_h / 2),
            int(center_x + box_w / 2),
            int(center_y + box_h / 2),
        )
        return (
            max(0, clamped[0]),
            max(0, clamped[1]),
            min(width, clamped[2]),
            min(height, clamped[3]),
        )

    @staticmethod
    def _map_box_into_portrait(
        source_box: Tuple[int, int, int, int],
        init_crop: Tuple[int, int, int, int],
        portrait_size: Tuple[int, int] = (512, 512),
    ) -> Optional[Tuple[int, int, int, int]]:
        if not source_box or not init_crop:
            return None
        crop_left, crop_top, crop_right, crop_bottom = init_crop
        crop_w = max(1, crop_right - crop_left)
        crop_h = max(1, crop_bottom - crop_top)
        target_w, target_h = portrait_size
        left, top, right, bottom = source_box
        mapped = (
            int((left - crop_left) * target_w / crop_w),
            int((top - crop_top) * target_h / crop_h),
            int((right - crop_left) * target_w / crop_w),
            int((bottom - crop_top) * target_h / crop_h),
        )
        return (
            max(0, mapped[0]),
            max(0, mapped[1]),
            min(target_w, mapped[2]),
            min(target_h, mapped[3]),
        )

    def _ensure_face_portrait_variant(
        self,
        character_id: str,
        expression: str,
        pose: str,
        source_image_path: str,
        source_variant: Dict[str, Any],
    ) -> str:
        output_dir = self._character_face_portraits_dir(character_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        portrait_path = output_dir / f"{expression}_{pose}.png"
        portrait_meta_path = self._portrait_meta_path(portrait_path)
        portrait_exists_ok = False
        existing_meta: Dict[str, Any] = {}
        if portrait_meta_path.exists():
            try:
                existing_meta = json.loads(portrait_meta_path.read_text(encoding="utf-8"))
            except Exception:
                existing_meta = {}
        if portrait_path.exists():
            try:
                with Image.open(portrait_path).convert("RGB") as existing:
                    extrema = existing.getextrema()
                    flat_image = all((high - low) <= 3 for low, high in extrema)
                if not flat_image:
                    portrait_exists_ok = True
                else:
                    portrait_path.unlink(missing_ok=True)
                    portrait_meta_path.unlink(missing_ok=True)
                    existing_meta = {}
            except Exception:
                portrait_path.unlink(missing_ok=True)
                portrait_meta_path.unlink(missing_ok=True)
                existing_meta = {}
        if not self.sd_api_url or not source_image_path or not os.path.exists(source_image_path):
            return ""

        init_crop = self._get_variant_face_crop_box(source_image_path, source_variant, part_kind="face")
        if not init_crop:
            return ""

        portrait_meta: Dict[str, Any] = {
            "source_image_path": str(source_image_path),
            "expression": expression,
            "pose": pose,
            "init_crop": list(init_crop),
        }
        default_boxes = self._default_portrait_part_boxes()
        for kind in ("face", "eyes", "mouth"):
            source_box = (
                init_crop
                if kind == "face"
                else self._get_variant_face_crop_box(source_image_path, source_variant, part_kind=kind)
            )
            mapped = self._map_box_into_portrait(source_box, init_crop) if source_box else None
            if mapped:
                portrait_meta[f"{kind}_box"] = list(self._clamp_portrait_box(kind, mapped))
            else:
                portrait_meta[f"{kind}_box"] = list(default_boxes[kind])

        if portrait_exists_ok and existing_meta:
            existing_source = str(existing_meta.get("source_image_path", "") or "")
            existing_crop = list(existing_meta.get("init_crop", []) or [])
            if existing_source != str(source_image_path) or existing_crop != list(init_crop):
                portrait_exists_ok = False
                portrait_path.unlink(missing_ok=True)
                portrait_meta_path.unlink(missing_ok=True)
                existing_meta = {}
            else:
                for kind in ("face", "eyes", "mouth"):
                    if list(existing_meta.get(f"{kind}_box", []) or []) != list(portrait_meta.get(f"{kind}_box", []) or []):
                        portrait_exists_ok = False
                        portrait_path.unlink(missing_ok=True)
                        portrait_meta_path.unlink(missing_ok=True)
                        existing_meta = {}
                        break

        if portrait_exists_ok:
            try:
                portrait_meta_path.write_text(
                    json.dumps(portrait_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return str(portrait_path)

        init_path = output_dir / f"{expression}_{pose}__init.png"
        try:
            with Image.open(source_image_path).convert("RGBA") as source:
                crop = source.crop(init_crop)
                crop = crop.resize((512, 512), Image.Resampling.LANCZOS)
                crop.save(init_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] face portrait init crop failed ({character_id}/{expression}_{pose}): {e}")
            return ""

        prompt = ""
        negative = ""
        checkpoint = ""
        override_settings: Dict[str, Any] | None = None
        sampler = "DPM++ 2M Karras"
        scheduler = ""
        steps = 20
        cfg_scale = 6.2
        checkpoint_override = str(getattr(self.config, "checkpoint_override", "") or "").strip()
        expression_hint = ""
        denoising_strength = 0.28
        normalized_expression = self.normalize_requested_expression(expression)
        if normalized_expression == "blink":
            expression_hint = (
                "eyes fully closed, eyelids shut, no visible irises, no visible pupils, "
                "mouth unchanged, same face angle, same hairstyle"
            )
            denoising_strength = 0.34
        elif normalized_expression == "talking":
            expression_hint = (
                "mouth clearly open for speech, visible inner mouth, lips parted, "
                "eyes unchanged, same face angle, same hairstyle"
            )
            denoising_strength = 0.36
        elif normalized_expression in {"fear", "angry", "sad"}:
            expression_hint = "emotion clearly readable in eyebrows and mouth, same face angle, same hairstyle"
            denoising_strength = 0.32
        if self.prompt_composer and hasattr(self.prompt_composer, "compose_character_library_prompt"):
            try:
                composed = self.prompt_composer.compose_character_library_prompt(
                    char_id=character_id,
                    expression=expression,
                    pose=pose,
                )
                prompt = ", ".join([
                    composed.positive,
                    "same character close-up portrait, head and shoulders only, centered face, plain solid backdrop, no hands, no torso, no extra person",
                    expression_hint,
                ])
                negative = ", ".join([
                    composed.negative,
                    "full body, hands, torso, crowd, second person, duplicate face, duplicate body, background scene",
                ])
                checkpoint = composed.checkpoint
                override_settings = composed.to_api_params().get("override_settings", {})
                sampler = composed.sampler
                scheduler = composed.scheduler
                steps = max(18, int(composed.steps or 20))
                cfg_scale = float(composed.cfg_scale or 6.2)
            except Exception as e:
                logger.debug(f"[CharacterLibraryManager] face portrait prompt build failed ({character_id}/{expression}_{pose}): {e}")

        if checkpoint_override:
            checkpoint = checkpoint_override

        if not prompt:
            prompt = ", ".join([
                "same character close-up portrait, centered face, plain solid backdrop",
                expression_hint,
            ]).strip(", ")
            negative = "full body, hands, torso, background scene, extra person"

        result = self._generate_sd_image(
            prompt=prompt,
            negative_prompt=negative,
            width=512,
            height=512,
            steps=steps,
            cfg_scale=cfg_scale,
            sampler_name=sampler,
            scheduler=scheduler,
            checkpoint=checkpoint,
            override_settings=override_settings,
            init_image_path=str(init_path),
            denoising_strength=denoising_strength,
        )
        if not result or not result.get("images"):
            return ""
        try:
            portrait_path.write_bytes(base64.b64decode(result["images"][0]))
            try:
                portrait_meta_path.write_text(
                    json.dumps(portrait_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return str(portrait_path)
        except Exception as e:
            logger.debug(f"[CharacterLibraryManager] face portrait save failed ({character_id}/{expression}_{pose}): {e}")
            return ""

    def _select_sheet_variant_from_map(
        self,
        variants: Dict[str, Dict[str, Any]],
        expression: str,
        pose: str,
        *,
        fallback: bool = True,
    ) -> Dict[str, Any]:
        normalized_expression, normalized_pose = self.resolve_variant("", expression, pose)
        candidate_keys = self._build_sheet_variant_candidate_keys(
            normalized_expression,
            normalized_pose,
            fallback=fallback,
        )
        for key in candidate_keys:
            candidate = variants.get(key)
            if isinstance(candidate, dict):
                result = dict(candidate)
                result["variant_key"] = key
                return result
        return {}

    def _select_exact_expression_variant_from_map(
        self,
        variants: Dict[str, Dict[str, Any]],
        expression: str,
        pose: str,
    ) -> Dict[str, Any]:
        expr = self.normalize_requested_expression(expression)
        pose_name = self.normalize_requested_pose(pose)
        pose_candidates: List[str] = [pose_name]
        for candidate_pose in POSE_FALLBACKS.get(pose_name, []):
            if candidate_pose not in pose_candidates:
                pose_candidates.append(candidate_pose)
        if "standing" not in pose_candidates:
            pose_candidates.append("standing")
        for candidate_pose in pose_candidates:
            key = f"{expr}_{candidate_pose}"
            candidate = variants.get(key)
            if isinstance(candidate, dict):
                result = dict(candidate)
                result["variant_key"] = key
                return result
        return {}

    def _build_real_face_parts_bundle(
        self,
        character_id: str,
        variant_key: str,
        variant: Dict[str, Any],
        variants: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        image_path = self._canonicalize_character_image_path(
            character_id,
            str(variant.get("image_path", "") or ""),
        )
        if not image_path or not os.path.exists(image_path):
            return {}

        output_dir = self._character_face_parts_dir(character_id, variant_key)
        neutral_variant = self._select_exact_expression_variant_from_map(
            variants,
            "neutral",
            variant.get("pose", "standing"),
        ) or variant
        talking_variant = self._select_exact_expression_variant_from_map(
            variants,
            "talking",
            variant.get("pose", "standing"),
        )
        blink_variant = self._select_exact_expression_variant_from_map(
            variants,
            "blink",
            variant.get("pose", "standing"),
        )

        face_parts = {
            "eyes_open_path": "",
            "eyes_closed_path": "",
            "mouth_closed_path": "",
            "mouth_open_path": "",
        }

        def _cached_face_part(filename: str, part_kind: str) -> str:
            cached_path = output_dir / filename
            if not cached_path.exists():
                return ""
            if not self._is_face_part_sane(str(cached_path), part_kind):
                return ""
            return str(cached_path)

        def _layered_face_part(candidate_variant: Dict[str, Any], part_key: str, part_kind: str) -> str:
            raw_path = str(dict(candidate_variant.get("parts", {}) or {}).get(part_key, "") or "")
            if not raw_path:
                return ""
            resolved_path = self._canonicalize_character_image_path(character_id, raw_path)
            if not resolved_path or not os.path.exists(resolved_path):
                return ""
            if not self._is_face_part_sane(resolved_path, part_kind):
                return ""
            return raw_path

        face_parts["eyes_open_path"] = _cached_face_part("eyes_open.png", "eyes")
        face_parts["eyes_closed_path"] = _cached_face_part("eyes_closed.png", "eyes")
        face_parts["mouth_closed_path"] = _cached_face_part("mouth_closed.png", "mouth")
        face_parts["mouth_open_path"] = _cached_face_part("mouth_open.png", "mouth")

        neutral_image_path = self._canonicalize_character_image_path(
            character_id,
            str(neutral_variant.get("image_path", "") or image_path),
        )

        if not face_parts["eyes_open_path"]:
            face_parts["eyes_open_path"] = _layered_face_part(neutral_variant, "eyes_open_path", "eyes")
        if not face_parts["mouth_closed_path"]:
            face_parts["mouth_closed_path"] = _layered_face_part(neutral_variant, "mouth_closed_path", "mouth")
        if not face_parts["eyes_closed_path"]:
            face_parts["eyes_closed_path"] = _layered_face_part(blink_variant, "eyes_closed_path", "eyes")
        if not face_parts["mouth_open_path"]:
            face_parts["mouth_open_path"] = _layered_face_part(talking_variant, "mouth_open_path", "mouth")

        if neutral_image_path and os.path.exists(neutral_image_path):
            if not face_parts["eyes_open_path"]:
                face_parts["eyes_open_path"] = self._build_part_from_portrait(
                    character_id,
                    str(neutral_variant.get("expression", "neutral") or "neutral"),
                    str(neutral_variant.get("pose", "standing") or "standing"),
                    neutral_image_path,
                    neutral_variant,
                    output_dir / "eyes_open.png",
                    part_kind="eyes",
                )
            if not face_parts["mouth_closed_path"]:
                face_parts["mouth_closed_path"] = self._build_part_from_portrait(
                    character_id,
                    str(neutral_variant.get("expression", "neutral") or "neutral"),
                    str(neutral_variant.get("pose", "standing") or "standing"),
                    neutral_image_path,
                    neutral_variant,
                    output_dir / "mouth_closed.png",
                    part_kind="mouth",
                )

        blink_image_path = self._canonicalize_character_image_path(
            character_id,
            str(blink_variant.get("image_path", "") or ""),
        )
        if not face_parts["eyes_closed_path"] and blink_image_path and os.path.exists(blink_image_path):
            face_parts["eyes_closed_path"] = self._build_part_from_portrait(
                character_id,
                str(blink_variant.get("expression", "blink") or "blink"),
                str(blink_variant.get("pose", "standing") or "standing"),
                blink_image_path,
                blink_variant,
                output_dir / "eyes_closed.png",
                part_kind="eyes",
            )
        if (
            face_parts["eyes_open_path"]
            and (
                not face_parts["eyes_closed_path"]
                or self._face_part_difference_score(face_parts["eyes_open_path"], face_parts["eyes_closed_path"]) < 10.0
            )
        ):
            synthesized = self._synthesize_closed_eyes_part(
                face_parts["eyes_open_path"],
                output_dir / "eyes_closed.png",
            )
            if synthesized and self._is_face_part_sane(synthesized, "eyes"):
                face_parts["eyes_closed_path"] = synthesized

        talking_image_path = self._canonicalize_character_image_path(
            character_id,
            str(talking_variant.get("image_path", "") or ""),
        )
        if not face_parts["mouth_open_path"] and talking_image_path and os.path.exists(talking_image_path):
            face_parts["mouth_open_path"] = self._build_part_from_portrait(
                character_id,
                str(talking_variant.get("expression", "talking") or "talking"),
                str(talking_variant.get("pose", "standing") or "standing"),
                talking_image_path,
                talking_variant,
                output_dir / "mouth_open.png",
                part_kind="mouth",
            )
        if (
            face_parts["mouth_closed_path"]
            and (
                not face_parts["mouth_open_path"]
                or self._face_part_difference_score(face_parts["mouth_closed_path"], face_parts["mouth_open_path"]) < 10.0
            )
        ):
            synthesized = self._synthesize_open_mouth_part(
                face_parts["mouth_closed_path"],
                output_dir / "mouth_open.png",
            )
            if synthesized and self._is_face_part_sane(synthesized, "mouth"):
                face_parts["mouth_open_path"] = synthesized

        for key, kind in (
            ("eyes_open_path", "eyes"),
            ("eyes_closed_path", "eyes"),
            ("mouth_closed_path", "mouth"),
            ("mouth_open_path", "mouth"),
        ):
            candidate = str(face_parts.get(key, "") or "")
            if candidate and not self._is_face_part_sane(candidate, kind):
                face_parts[key] = ""

        if face_parts["eyes_open_path"] and not face_parts["eyes_closed_path"]:
            synthesized = self._synthesize_closed_eyes_part(
                self._canonicalize_character_image_path(character_id, face_parts["eyes_open_path"]),
                output_dir / "eyes_closed.png",
            )
            if synthesized and self._is_face_part_sane(synthesized, "eyes"):
                face_parts["eyes_closed_path"] = synthesized

        if face_parts["mouth_closed_path"] and not face_parts["mouth_open_path"]:
            synthesized = self._synthesize_open_mouth_part(
                self._canonicalize_character_image_path(character_id, face_parts["mouth_closed_path"]),
                output_dir / "mouth_open.png",
            )
            if synthesized and self._is_face_part_sane(synthesized, "mouth"):
                face_parts["mouth_open_path"] = synthesized

        if not any(face_parts.values()):
            return {}
        return face_parts

    def build_character_sheet(self, character_id: str, save: bool = True) -> Dict[str, Any]:
        """Build a reusable character-sheet manifest for motiontoon rendering."""
        entry = self.library.get(character_id)
        if not entry:
            return {}

        sheet_variants: Dict[str, Dict[str, Any]] = {}
        for key, images in entry.images.items():
            expression, pose = key.split("_", 1) if "_" in key else (key, "standing")
            best_path, best_image = self._pick_consistent_character_image(character_id, images)
            if not best_path:
                continue

            parts = load_layered_cutout_assets(best_path)
            meta = load_layered_cutout_metadata(best_path)
            if not parts or not self._has_complete_motiontoon_rig(meta):
                rebuilt_parts = self.prime_motiontoon_parts(best_path)
                if rebuilt_parts:
                    parts = rebuilt_parts
                meta = load_layered_cutout_metadata(best_path)

            sheet_variants[key] = {
                "expression": expression,
                "pose": pose,
                "image_path": best_path,
                "parts": parts,
                "face_parts": {},
                "face_part_boxes": self._get_character_face_part_boxes(character_id),
                "rig": dict(meta.get("rig", {}) or {}) if isinstance(meta, dict) else {},
                "quality_score": float(getattr(best_image, "quality_score", 0.0) or 0.0) if best_image else 0.0,
                "seed": int(getattr(best_image, "seed", -1) or -1) if best_image else -1,
            }

        for key, variant in list(sheet_variants.items()):
            sheet_variants[key]["face_parts"] = self._build_real_face_parts_bundle(
                character_id,
                key,
                variant,
                sheet_variants,
            )

        sheet = {
            "pack_id": self.pack_id,
            "character_id": entry.character_id,
            "character_name": entry.character_name,
            "generated_at": datetime.now().isoformat(),
            "variant_count": len(sheet_variants),
            "variants": sheet_variants,
        }

        if save:
            sheet_path = self._character_sheet_path(character_id)
            sheet_path.parent.mkdir(parents=True, exist_ok=True)
            sheet_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")

        return sheet

    @staticmethod
    def _has_complete_motiontoon_rig(meta_or_rig: Any) -> bool:
        required_keys = (
            "sprite_center_x",
            "sprite_center_y",
            "sprite_width_ratio",
            "sprite_height_ratio",
        )
        rig: Dict[str, Any] = {}
        if isinstance(meta_or_rig, dict):
            if isinstance(meta_or_rig.get("rig"), dict):
                rig = dict(meta_or_rig.get("rig", {}) or {})
            else:
                rig = dict(meta_or_rig)
        return all(rig.get(key) is not None for key in required_keys)

    def get_character_sheet(self, character_id: str) -> Dict[str, Any]:
        sheet_path = self._character_sheet_path(character_id)
        if sheet_path.exists():
            try:
                return json.loads(sheet_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug(f"[CharacterLibraryManager] character sheet load failed ({character_id}): {e}")
        return self.build_character_sheet(character_id, save=True)

    def get_character_sheet_variant(
        self,
        character_id: str,
        expression: str = "neutral",
        pose: str = "standing",
        angle: str = "front",
        fallback: bool = True,
    ) -> Dict[str, Any]:
        sheet = self.get_character_sheet(character_id)
        variants = dict(sheet.get("variants", {}) or {}) if isinstance(sheet, dict) else {}
        if not variants:
            return {}

        normalized_expression, normalized_pose = self.resolve_variant(character_id, expression, pose)
        candidate_keys = self._build_sheet_variant_candidate_keys(
            normalized_expression,
            normalized_pose,
            fallback=fallback,
            angle=angle,
        )

        variant: Dict[str, Any] = {}
        variant_key = ""
        for key in candidate_keys:
            candidate = variants.get(key)
            if isinstance(candidate, dict):
                variant = candidate
                variant_key = key
                break

        if not variant and fallback:
            for key, candidate in variants.items():
                if not isinstance(candidate, dict):
                    continue
                if str(candidate.get("expression", "") or "") == normalized_expression:
                    variant = candidate
                    variant_key = str(key)
                    break

        if not variant:
            return {}

        result = dict(variant)
        result["variant_key"] = variant_key
        result["expression"] = str(result.get("expression", normalized_expression) or normalized_expression)
        result["pose"] = str(result.get("pose", normalized_pose) or normalized_pose)
        return result

    def _build_sheet_variant_candidate_keys(
        self,
        expression: str,
        pose: str,
        *,
        fallback: bool,
        angle: str = "front",
    ) -> List[str]:
        expr = str(expression or "neutral").strip().lower() or "neutral"
        pose_name = str(pose or "standing").strip().lower() or "standing"
        angle_name = str(angle or "front").strip().lower() or "front"
        keys: List[str] = []

        def _add_key(candidate_expression: str, candidate_pose: str) -> None:
            base = f"{candidate_expression}_{candidate_pose}"
            # v63: 각도 키 우선 → front → 각도 없는 레거시(base) 순 (하위호환)
            ordered = []
            if angle_name and angle_name != "front":
                ordered.append(f"{base}_{angle_name}")
            ordered.append(f"{base}_front")
            ordered.append(base)
            for key in ordered:
                if key not in keys:
                    keys.append(key)

        _add_key(expr, pose_name)
        if not fallback:
            return keys

        pose_chain = [pose_name]
        pose_chain.extend(POSE_FALLBACKS.get(pose_name, []))
        if "standing" not in pose_chain:
            pose_chain.append("standing")

        expr_chain = [expr]
        expr_chain.extend(EXPRESSION_FALLBACKS.get(expr, []))
        if "neutral" not in expr_chain:
            expr_chain.append("neutral")

        for candidate_pose in pose_chain[1:]:
            _add_key(expr, candidate_pose)
        for candidate_expr in expr_chain[1:]:
            _add_key(candidate_expr, pose_name)
        for candidate_expr in expr_chain[1:]:
            for candidate_pose in pose_chain[1:]:
                _add_key(candidate_expr, candidate_pose)

        preferred_expressions = [str(v).strip().lower() for v in (getattr(self.config, "preferred_expressions", []) or []) if str(v).strip()]
        preferred_poses = [str(v).strip().lower() for v in (getattr(self.config, "preferred_poses", []) or []) if str(v).strip()]
        for candidate_expr in preferred_expressions:
            _add_key(candidate_expr, pose_name)
        for candidate_pose in preferred_poses:
            _add_key(expr, candidate_pose)
        for candidate_expr in preferred_expressions:
            for candidate_pose in preferred_poses:
                _add_key(candidate_expr, candidate_pose)

        _add_key("neutral", "standing")
        return keys

    def _resolve_pack_cast_slot_names(self, character_id: str) -> List[str]:
        normalized_char = str(character_id or "").strip().lower()
        if not normalized_char:
            return []
        try:
            from config.pack_config import ACTIVE_PACK

            active_pack_id = str(getattr(ACTIVE_PACK, "pack_id", "") or "").strip().lower()
            if active_pack_id and self.pack_id and active_pack_id != str(self.pack_id).strip().lower():
                return []

            motiontoon = getattr(ACTIVE_PACK, "motiontoon", None)
            cast_slots = getattr(motiontoon, "cast_slots", {}) if motiontoon else {}
            if not isinstance(cast_slots, dict):
                return []

            matches: List[str] = []
            for slot_name, slot_data in cast_slots.items():
                if not isinstance(slot_data, dict):
                    continue
                slot_ids = {
                    candidate.strip().lower()
                    for candidate in actor_identity_candidates_from_slot(slot_data)
                    if candidate.strip()
                }
                if normalized_char in slot_ids:
                    normalized_slot = str(slot_name).strip().lower()
                    if normalized_slot and normalized_slot not in matches:
                        matches.append(normalized_slot)
            return matches
        except Exception:
            return []

    def get_required_sheet_variant_keys(
        self,
        character_id: str,
        *,
        available_expressions: Optional[List[str]] = None,
        available_poses: Optional[List[str]] = None,
        required_variant_keys: Optional[List[str]] = None,
    ) -> List[str]:
        slot_names = self._resolve_pack_cast_slot_names(character_id)
        slot_specific_keys = []
        if slot_names:
            required_by_slot = getattr(self.config, "required_variant_keys_by_slot", {}) or {}
            for slot_name in slot_names:
                for value in required_by_slot.get(slot_name, []) or []:
                    normalized_value = str(value).strip().lower()
                    if normalized_value and normalized_value not in slot_specific_keys:
                        slot_specific_keys.append(normalized_value)

        explicit_keys = [
            str(value).strip().lower()
            for value in (
                required_variant_keys
                or slot_specific_keys
                or getattr(self.config, "required_variant_keys", [])
                or []
            )
            if str(value).strip()
        ]
        if explicit_keys:
            dedup_explicit: List[str] = []
            for key in explicit_keys:
                expression_name, pose_name = key.split("_", 1) if "_" in key else (key, "standing")
                normalized_key = (
                    f"{self.normalize_requested_expression(expression_name)}_"
                    f"{self.normalize_requested_pose(pose_name)}"
                )
                if normalized_key not in dedup_explicit:
                    dedup_explicit.append(normalized_key)
            if "neutral_standing" not in dedup_explicit:
                dedup_explicit.append("neutral_standing")
            return dedup_explicit

        expressions = [
            self.normalize_requested_expression(value)
            for value in (available_expressions or getattr(self.config, "preferred_expressions", []) or ["neutral", "talking", "fear", "sad"])
            if str(value).strip()
        ]
        poses = [
            self.normalize_requested_pose(value)
            for value in (available_poses or getattr(self.config, "preferred_poses", []) or ["standing", "sitting"])
            if str(value).strip()
        ]

        dedup_expressions: List[str] = []
        dedup_poses: List[str] = []
        for value in expressions:
            if value not in dedup_expressions:
                dedup_expressions.append(value)
        for value in poses:
            if value not in dedup_poses:
                dedup_poses.append(value)

        keys: List[str] = []
        for expression in dedup_expressions:
            for pose in dedup_poses:
                key = f"{expression}_{pose}"
                if key not in keys:
                    keys.append(key)
        if "neutral_standing" not in keys:
            keys.append("neutral_standing")
        return keys

    def get_character_sheet_coverage(
        self,
        character_id: str,
        *,
        available_expressions: Optional[List[str]] = None,
        available_poses: Optional[List[str]] = None,
        required_variant_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        required_keys = self.get_required_sheet_variant_keys(
            character_id,
            available_expressions=available_expressions,
            available_poses=available_poses,
            required_variant_keys=required_variant_keys,
        )
        sheet = self.get_character_sheet(character_id)
        if not sheet and character_id in self.library:
            sheet = self.build_character_sheet(character_id, save=False)
        variants = dict(sheet.get("variants", {}) or {}) if isinstance(sheet, dict) else {}
        existing_keys = [key for key in required_keys if key in variants]
        missing_keys = [key for key in required_keys if key not in variants]
        coverage_ratio = (len(existing_keys) / len(required_keys)) if required_keys else 1.0
        return {
            "required_keys": required_keys,
            "existing_keys": existing_keys,
            "missing_keys": missing_keys,
            "coverage_ratio": coverage_ratio,
            "is_complete": not missing_keys,
        }

    def audit_character_sheet(
        self,
        character_id: str,
        *,
        sheet: Optional[Dict[str, Any]] = None,
        required_variant_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return a production-readiness audit for a character sheet."""
        resolved_sheet = sheet or self.get_character_sheet(character_id)
        if not resolved_sheet and character_id in self.library:
            resolved_sheet = self.build_character_sheet(character_id, save=False)
        variants = dict(resolved_sheet.get("variants", {}) or {}) if isinstance(resolved_sheet, dict) else {}
        coverage = self.get_character_sheet_coverage(
            character_id,
            required_variant_keys=required_variant_keys,
        )

        issues: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        face_part_keys = ("eyes_open_path", "eyes_closed_path", "mouth_closed_path", "mouth_open_path")
        layered_part_keys = ("background_path", "foreground_path", "head_path", "body_path")
        min_quality = float(getattr(self.config, "min_quality_score", 0.5) or 0.5)

        def _append_issue(
            bucket: List[Dict[str, Any]],
            *,
            code: str,
            message: str,
            variant_key: str = "",
            details: Optional[Dict[str, Any]] = None,
        ) -> None:
            payload: Dict[str, Any] = {"code": code, "message": message}
            if variant_key:
                payload["variant_key"] = variant_key
            if details:
                payload["details"] = details
            bucket.append(payload)

        for key in coverage["missing_keys"]:
            _append_issue(
                issues,
                code="missing_required_variant",
                variant_key=key,
                message=f"Required variant '{key}' is missing from the sheet.",
            )

        for key, variant in variants.items():
            variant_path = self._canonicalize_character_image_path(
                character_id,
                str(variant.get("image_path", "") or ""),
            )
            if not variant_path or not os.path.exists(variant_path):
                _append_issue(
                    issues,
                    code="missing_image_path",
                    variant_key=key,
                    message="Representative image is missing on disk.",
                    details={"image_path": variant.get("image_path", "")},
                )
                continue

            quality_score = float(variant.get("quality_score", 0.0) or 0.0)
            if quality_score < min_quality:
                _append_issue(
                    issues,
                    code="quality_below_threshold",
                    variant_key=key,
                    message=f"Quality score {quality_score:.2f} is below minimum {min_quality:.2f}.",
                    details={"quality_score": quality_score, "min_quality_score": min_quality},
                )

            parts = dict(variant.get("parts", {}) or {})
            missing_layered = []
            for part_key in layered_part_keys:
                raw_path = str(parts.get(part_key, "") or "")
                if not raw_path:
                    missing_layered.append(part_key)
                    continue
                resolved_path = self._canonicalize_character_image_path(character_id, raw_path)
                if not os.path.exists(resolved_path):
                    missing_layered.append(part_key)
            if missing_layered:
                _append_issue(
                    issues,
                    code="missing_layered_parts",
                    variant_key=key,
                    message="Motiontoon layered assets are incomplete.",
                    details={"missing_keys": missing_layered},
                )

            face_parts = dict(variant.get("face_parts", {}) or {})
            missing_face_parts = []
            for face_key in face_part_keys:
                raw_path = str(face_parts.get(face_key, "") or "")
                if not raw_path:
                    missing_face_parts.append(face_key)
                    continue
                resolved_path = self._canonicalize_character_image_path(character_id, raw_path)
                if not os.path.exists(resolved_path):
                    missing_face_parts.append(face_key)
            if missing_face_parts:
                _append_issue(
                    issues,
                    code="missing_face_parts",
                    variant_key=key,
                    message="Face rig assets are incomplete.",
                    details={"missing_keys": missing_face_parts},
                )

            rig = dict(variant.get("rig", {}) or {})
            if not self._has_complete_motiontoon_rig(rig):
                missing_rig_keys = [
                    field
                    for field in ("sprite_center_x", "sprite_center_y", "sprite_width_ratio", "sprite_height_ratio")
                    if rig.get(field) is None
                ]
                _append_issue(
                    warnings,
                    code="missing_rig_metadata",
                    variant_key=key,
                    message="Rig metadata is incomplete; motiontoon placement may drift.",
                    details={"missing_keys": missing_rig_keys},
                )

        status = "pass"
        if issues:
            status = "fail"
        elif warnings:
            status = "warning"

        return {
            "character_id": character_id,
            "variant_count": len(variants),
            "status": status,
            "coverage": coverage,
            "issues": issues,
            "warnings": warnings,
        }

    def bind_character_sheet_variant(
        self,
        target_image_path: str,
        character_id: str,
        expression: str = "neutral",
        pose: str = "standing",
        *,
        fallback: bool = True,
        rig_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        variant = self.get_character_sheet_variant(
            character_id=character_id,
            expression=expression,
            pose=pose,
            fallback=fallback,
        )
        if not variant:
            return {}

        variant_parts = dict(variant.get("parts", {}) or {})
        variant_parts.update({k: v for k, v in dict(variant.get("face_parts", {}) or {}).items() if v})
        variant_image_path = str(variant.get("image_path", "") or "")
        variant_rig = dict(variant.get("rig", {}) or {})
        merged_rig = dict(variant_rig)
        merged_rig.update({k: v for k, v in dict(rig_overrides or {}).items() if v is not None})

        if variant_image_path and os.path.exists(variant_image_path):
            try:
                cloned = clone_layered_cutout_assets(
                    variant_image_path,
                    target_image_path,
                    rig_overrides=merged_rig,
                )
                if cloned:
                    return cloned
            except Exception as e:
                logger.debug(f"[CharacterLibraryManager] character sheet clone failed ({character_id}): {e}")

        if variant_parts:
            try:
                attached = attach_layered_cutout_assets(
                    target_image_path,
                    variant_parts,
                    overlay_kind=str(merged_rig.get("overlay_kind", "") or ""),
                    strength=0.82,
                    rig_overrides=merged_rig,
                )
                if attached:
                    return attached
            except Exception as e:
                logger.debug(f"[CharacterLibraryManager] character sheet attach failed ({character_id}): {e}")

        return {}

    def has_character_sheet_variant(
        self,
        character_id: str,
        expression: str = "neutral",
        pose: str = "standing",
        fallback: bool = True,
    ) -> bool:
        variant = self.get_character_sheet_variant(
            character_id=character_id,
            expression=expression,
            pose=pose,
            fallback=fallback,
        )
        if not variant:
            return False
        image_path = str(variant.get("image_path", "") or "")
        parts = dict(variant.get("parts", {}) or {})
        if image_path and os.path.exists(image_path):
            return True
        return bool(parts)

    def has_character(self,
                      character_id: str,
                      min_expressions: int = 3,
                      min_images_per_expression: int = 1) -> bool:
        """캐릭터 라이브러리가 충분한지 확인"""
        entry = self.library.get(character_id)
        if not entry:
            return False

        expressions_with_images = 0
        for key, images in entry.images.items():
            if len(images) >= min_images_per_expression:
                expressions_with_images += 1

        return expressions_with_images >= min_expressions

    def find_character_by_alias(self, alias: str) -> Optional[str]:
        """별칭으로 캐릭터 ID 찾기"""
        alias_lower = alias.lower()

        for char_id, entry in self.library.items():
            if char_id.lower() == alias_lower:
                return char_id
            if entry.character_name.lower() == alias_lower:
                return char_id
            if alias_lower in [a.lower() for a in entry.role_aliases]:
                return char_id

        return None

    # =========================================================
    # 캐릭터 라이브러리 생성 (설계서 4.1)
    # =========================================================

    def generate_character_library(self,
                                   character_def: Any,
                                   expressions: List[str] = None,
                                   poses: List[str] = None,
                                   variant_keys: List[str] = None,
                                   images_per_combo: int = None,
                                   progress_callback: callable = None,
                                   generation_overrides_by_variant: Optional[Dict[str, Dict[str, Any]]] = None,
                                   include_angles: Optional[bool] = None) -> Tuple[bool, List[str]]:
        """
        캐릭터 이미지 라이브러리 자동 생성 (설계서 4.1)

        Args:
            character_def: CharacterDefinition
            expressions: 생성할 표정 목록
            poses: 생성할 포즈 목록
            images_per_combo: 조합당 이미지 수
            progress_callback: (current, total, message) 콜백
            generation_overrides_by_variant: QA 전용 variant별 생성 override
                예시:
                {
                    "neutral_standing": {
                        "init_image_path": "C:/path/to/anchor.png",
                        "denoising_strength": 0.32,
                        "prompt_suffix": "same face, same outfit"
                    }
                }

        Returns:
            (성공 여부, 생성된 이미지 경로 목록)
        """
        if not self.sd_api_url:
            logger.error("[CharacterLibraryManager] SD API URL 없음")
            return False, []

        # 캐릭터 정보 추출
        char_id = getattr(character_def, 'id', '')
        char_name = getattr(character_def, 'name', char_id)
        base_prompt = getattr(character_def, 'base_prompt', '')
        negative_prompt = getattr(character_def, 'negative_prompt', '')
        char_expressions = getattr(character_def, 'expressions', {})
        char_poses = getattr(character_def, 'poses', {})

        if not char_id:
            logger.error("[CharacterLibraryManager] 캐릭터 ID 없음")
            return False, []

        logger.info(f"[CharacterLibraryManager] 라이브러리 생성 시작: {char_id} ({char_name})")

        # 기본값
        variant_pairs: List[Tuple[str, str, str]] = []
        if variant_keys:
            for raw_key in variant_keys:
                key_str = str(raw_key).strip()
                if not key_str:
                    continue
                # v63: 3-파트 키(표정_포즈_각도) 지원, 각도 누락 시 front
                _parts = key_str.split("_")
                expression_name = _parts[0] if _parts else key_str
                pose_name = _parts[1] if len(_parts) > 1 else "standing"
                angle_name = _parts[2] if len(_parts) > 2 else "front"
                pair = (
                    self.normalize_requested_expression(expression_name),
                    self.normalize_requested_pose(pose_name),
                    angle_name,
                )
                if pair not in variant_pairs:
                    variant_pairs.append(pair)
        expressions = expressions or list(char_expressions.keys()) or list(DEFAULT_EXPRESSIONS.keys())[:4]
        poses = poses or list(char_poses.keys()) or ["standing", "sitting"]
        if getattr(self.config, "preferred_expressions", []):
            merged_expressions: List[str] = []
            for value in list(getattr(self.config, "preferred_expressions", []) or []) + list(expressions):
                normalized = self.normalize_requested_expression(value)
                if normalized not in merged_expressions:
                    merged_expressions.append(normalized)
            expressions = merged_expressions
        if getattr(self.config, "preferred_poses", []):
            merged_poses: List[str] = []
            for value in list(getattr(self.config, "preferred_poses", []) or []) + list(poses):
                normalized = self.normalize_requested_pose(value)
                if normalized not in merged_poses:
                    merged_poses.append(normalized)
            poses = merged_poses
        if not variant_pairs:
            for expression_name in expressions:
                for pose_name in poses:
                    pair = (
                        self.normalize_requested_expression(expression_name),
                        self.normalize_requested_pose(pose_name),
                        "front",
                    )
                    if pair not in variant_pairs:
                        variant_pairs.append(pair)

        # v63: 턴어라운드 — 각 (표정,포즈)를 front/left/right/back 4각도로 확장.
        # include_angles: 명시값 > env REVERIE_TURNAROUND(0이면 끔) > 기본 True.
        # 이미 각도가 지정된 pair(front 외)는 그대로 두고, front pair만 4각도로 곱한다.
        if include_angles is None:
            include_angles = os.environ.get("REVERIE_TURNAROUND", "1").strip().lower() not in ("0", "false", "no", "off")
        if include_angles:
            try:
                from utils.actor_model import DEFAULT_ANGLES
            except Exception:
                DEFAULT_ANGLES = ("front", "left", "right", "back")
            expanded_pairs: List[Tuple[str, str, str]] = []
            for expr_n, pose_n, angle_n in variant_pairs:
                if angle_n != "front":
                    if (expr_n, pose_n, angle_n) not in expanded_pairs:
                        expanded_pairs.append((expr_n, pose_n, angle_n))
                    continue
                for ang in DEFAULT_ANGLES:
                    cand = (expr_n, pose_n, ang)
                    if cand not in expanded_pairs:
                        expanded_pairs.append(cand)
            variant_pairs = expanded_pairs

        images_per_combo = images_per_combo or self.config.auto_generate_count

        # 캐릭터 폴더 생성
        char_path = self.library_path / char_id
        char_path.mkdir(parents=True, exist_ok=True)

        # 엔트리 생성/업데이트
        if char_id not in self.library:
            # 일관성용 시드 생성
            if self.config.use_fixed_seed:
                seed = self._stable_seed(f"{self.pack_id}:{char_id}")
            else:
                seed = -1

            self.library[char_id] = CharacterLibraryEntry(
                character_id=char_id,
                character_name=char_name,
                base_prompt=base_prompt,
                negative_prompt=negative_prompt,
                generation_seed=seed,
            )

        entry = self.library[char_id]

        generated_paths = []
        failed_count = 0
        total_combos = len(variant_pairs) * images_per_combo
        current = 0

        generation_overrides_by_variant = generation_overrides_by_variant or {}

        for expression, pose, angle in variant_pairs:
            key = f"{expression}_{pose}" if angle == "front" else f"{expression}_{pose}_{angle}"

            if key not in entry.images:
                entry.images[key] = []

            for i in range(images_per_combo):
                current += 1

                if True:
                    if progress_callback:
                        progress_callback(
                            current, total_combos,
                            f"{char_name}: {expression} + {pose} ({i+1}/{images_per_combo})"
                        )

                    # 표정/포즈 프롬프트 가져오기
                    exp_prompt = char_expressions.get(expression, DEFAULT_EXPRESSIONS.get(expression, {}).get("prompt", ""))
                    pose_prompt = char_poses.get(pose, DEFAULT_POSES.get(pose, {}).get("prompt", ""))

                    composed = None
                    checkpoint_override = str(getattr(self.config, "checkpoint_override", "") or "").strip()
                    if self.prompt_composer and hasattr(self.prompt_composer, "compose_character_library_prompt"):
                        try:
                            composed = self.prompt_composer.compose_character_library_prompt(
                                char_id=char_id,
                                expression=expression,
                                pose=pose,
                            )
                        except Exception as e:
                            logger.debug(f"[CharacterLibraryManager] PromptComposer 시트 프롬프트 실패 ({char_id}/{expression}/{pose}): {e}")

                    # 최종 프롬프트 조합
                    full_prompt = composed.positive if composed else self._compose_library_prompt(
                        base_prompt, exp_prompt, pose_prompt
                    )
                    # v63: 각도(turnaround) 뷰 프롬프트 추가
                    if angle != "front":
                        try:
                            from utils.actor_model import ANGLE_VIEW_PROMPTS
                            _av = ANGLE_VIEW_PROMPTS.get(angle, "")
                            if _av:
                                full_prompt = f"{full_prompt}, {_av}"
                        except Exception:
                            pass
                    composed_negative = composed.negative if composed else ""
                    full_negative = ", ".join([
                        p for p in [
                            composed_negative,
                            negative_prompt,
                            "(worst quality:1.4), (low quality:1.4), blurry, text, gradient background, sky, scenery, room interior, landscape, lantern, table, animal, crowd, border, panel frame, speech bubble, multiple people, extra person, duplicate character, extra face, twin, two people",
                        ] if p
                    ])

                    reference_variant = self._get_reference_variant_image(entry, pose)
                    img2img_settings = self._get_expression_img2img_settings(expression)
                    variant_override = generation_overrides_by_variant.get(key) or {}
                    override_prompt_suffix = str(variant_override.get("prompt_suffix", "") or "").strip()
                    override_negative_suffix = str(variant_override.get("negative_prompt_suffix", "") or "").strip()
                    override_init_image_path = str(
                        variant_override.get("init_image_path")
                        or variant_override.get("reference_image_path")
                        or ""
                    ).strip()
                    override_consistency_image_path = str(
                        variant_override.get("consistency_image_path") or ""
                    ).strip()
                    override_consistency_mode = str(
                        variant_override.get("consistency_mode", "") or ""
                    ).strip()
                    override_consistency_control_mode = str(
                        variant_override.get("consistency_control_mode", "") or ""
                    ).strip()
                    override_consistency_weight = variant_override.get("consistency_weight", None)
                    override_consistency_start_step = variant_override.get("consistency_start_step", None)
                    override_consistency_end_step = variant_override.get("consistency_end_step", None)
                    override_pose_image_path = str(variant_override.get("pose_image_path") or "").strip()
                    override_pose_module = str(variant_override.get("pose_module", "") or "").strip()
                    override_pose_control_mode = str(variant_override.get("pose_control_mode", "") or "").strip()
                    override_pose_weight = variant_override.get("pose_weight", None)
                    override_pose_start_step = variant_override.get("pose_start_step", None)
                    override_pose_end_step = variant_override.get("pose_end_step", None)
                    override_denoising_strength = variant_override.get("denoising_strength", None)
                    override_width = variant_override.get("width", None)
                    override_height = variant_override.get("height", None)
                    override_steps = variant_override.get("steps", None)
                    override_cfg_scale = variant_override.get("cfg_scale", None)
                    override_sampler = str(variant_override.get("sampler_name", "") or "").strip()
                    override_scheduler = str(variant_override.get("scheduler", "") or "").strip()
                    if reference_variant and img2img_settings:
                        full_prompt = ", ".join([
                            full_prompt,
                            img2img_settings["prompt_suffix"],
                        ])
                    if override_prompt_suffix:
                        full_prompt = ", ".join([p for p in [full_prompt, override_prompt_suffix] if p])
                    if override_negative_suffix:
                        full_negative = ", ".join([p for p in [full_negative, override_negative_suffix] if p])

                    resolved_init_image_path = self._resolve_generation_override_path(
                        char_path,
                        override_init_image_path,
                        "init image",
                    )
                    resolved_consistency_image_path = self._resolve_generation_override_path(
                        char_path,
                        override_consistency_image_path,
                        "consistency image",
                    )
                    resolved_pose_image_path = self._resolve_generation_override_path(
                        char_path,
                        override_pose_image_path,
                        "pose image",
                    )
                    if not resolved_init_image_path and reference_variant and img2img_settings:
                        resolved_init_image_path = self._canonicalize_character_image_path(char_id, reference_variant.path)

                    resolved_denoising_strength = (
                        override_denoising_strength
                        if override_denoising_strength is not None
                        else (img2img_settings.get("denoising_strength") if img2img_settings else None)
                    )

                    # 시드 설정 (일관성)
                    seed = entry.generation_seed if self.config.use_fixed_seed else -1
                    if seed > 0:
                        # 표정/포즈별로 시드 오프셋
                        seed = self._stable_seed(f"{entry.character_id}:{key}:{i}")

                    # 이미지 생성 (재시도 포함)
                    success = False
                    for retry in range(self.config.max_retries):
                        try:
                            result = self._generate_sd_image(
                                prompt=full_prompt,
                                negative_prompt=full_negative,
                                seed=seed if retry == 0 else self._stable_seed(f"{entry.character_id}:{key}:{i}:retry:{retry}"),
                                width=int(override_width) if override_width is not None else (composed.width if composed else 768),
                                height=int(override_height) if override_height is not None else (composed.height if composed else 1024),
                                steps=int(override_steps) if override_steps is not None else (composed.steps if composed else 15),
                                cfg_scale=float(override_cfg_scale) if override_cfg_scale is not None else (composed.cfg_scale if composed else 7.0),
                                sampler_name=override_sampler or (composed.sampler if composed else "DPM++ 2M Karras"),
                                scheduler=override_scheduler or (composed.scheduler if composed else ""),
                                checkpoint=checkpoint_override or (composed.checkpoint if composed else ""),
                                override_settings=composed.to_api_params().get("override_settings", {}) if composed else None,
                                init_image_path=resolved_init_image_path or None,
                                denoising_strength=resolved_denoising_strength,
                                consistency_image_path=resolved_consistency_image_path or None,
                                consistency_mode=override_consistency_mode,
                                consistency_weight=override_consistency_weight,
                                consistency_control_mode=override_consistency_control_mode,
                                consistency_start_step=override_consistency_start_step,
                                consistency_end_step=override_consistency_end_step,
                                pose_image_path=resolved_pose_image_path or None,
                                pose_module=override_pose_module,
                                pose_weight=override_pose_weight,
                                pose_control_mode=override_pose_control_mode,
                                pose_start_step=override_pose_start_step,
                                pose_end_step=override_pose_end_step,
                                angle=angle,
                            )

                            if result and result.get('images'):
                                # 이미지 저장
                                filename = f"{key}_{i+1:02d}.png"
                                image_path = char_path / filename

                                image_data = result['images'][0]
                                with open(image_path, 'wb') as f:
                                    f.write(base64.b64decode(image_data))

                                self.prime_motiontoon_parts(
                                    str(image_path),
                                    overlay_kind="document",
                                )

                                # 품질 검증
                                quality_result = self._validate_image(
                                    str(image_path),
                                    character_def
                                )

                                if quality_result['score'] >= self.config.min_quality_score:
                                    # 성공!
                                    info = result.get('info', {})
                                    if isinstance(info, str):
                                        try:
                                            info = json.loads(info)
                                        except (json.JSONDecodeError, TypeError):
                                            info = {}

                                    char_image = CharacterImage(
                                        path=str(image_path),
                                        expression=expression,
                                        pose=pose,
                                        seed=info.get('seed', seed),
                                        prompt=full_prompt,
                                        negative_prompt=full_negative,
                                        created_at=datetime.now().isoformat(),
                                        quality_score=quality_result['score'],
                                        face_detected=quality_result['face_detected'],
                                        blur_score=quality_result['blur_score'],
                                        file_size_kb=os.path.getsize(image_path) // 1024,
                                    )
                                    entry.images[key].append(char_image)
                                    generated_paths.append(str(image_path))

                                    logger.info(f"[CharacterLibraryManager] 생성: {filename} "
                                              f"(품질: {quality_result['score']:.2f})")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"[CharacterLibraryManager] 품질 미달 (재시도 {retry+1})")
                                    os.remove(image_path)

                        except Exception as e:
                            logger.error(f"[CharacterLibraryManager] 생성 오류: {e}")

                    if not success:
                        failed_count += 1
                        logger.warning(f"[CharacterLibraryManager] 실패: {key}")

        # 저장
        entry.total_images = sum(len(imgs) for imgs in entry.images.values())
        entry.last_generated = datetime.now().isoformat()
        self._save_library()
        self.build_character_sheet(char_id, save=True)

        logger.info(f"[CharacterLibraryManager] 완료: 성공 {len(generated_paths)}, 실패 {failed_count}")

        return len(generated_paths) > 0, generated_paths

    def _compose_library_prompt(self, base: str, expression: str, pose: str) -> str:
        """캐릭터 라이브러리용 프롬프트 조합"""
        parts = [
            "masterpiece, best quality, highly detailed, isolated single character, single full-body sprite, clean cutout silhouette, thick clean outlines, flat cel shading, 2d motiontoon puppet sprite, solid chroma green backdrop, single flat background color, no gradient background, no environment detail",
            base,
            expression,
            pose,
            "simple clean backdrop, centered full body shot, readable silhouette, one person only, no duplicate character, no props, no furniture, no room background, no crowd, no border, no panel frame, no scenery",
        ]
        return ", ".join([p for p in parts if p])

    def _get_reference_variant_image(self,
                                     entry: CharacterLibraryEntry,
                                     pose: str) -> Optional[CharacterImage]:
        for key in (f"neutral_{pose}", "neutral_standing"):
            images = entry.images.get(key) or []
            if images:
                return images[0]
        return None

    def _get_expression_img2img_settings(self, expression: str) -> Optional[Dict[str, Any]]:
        return {
            "blink": {
                "denoising_strength": 0.26,
                "prompt_suffix": "same character, identical face, identical hairstyle, identical outfit, identical pose, eyelids fully closed, no visible pupils, no mouth change, no extra person",
            },
            "talking": {
                "denoising_strength": 0.30,
                "prompt_suffix": "same character, identical face, identical hairstyle, identical outfit, identical pose, mouth clearly open for speech, visible inner mouth, no extra person",
            },
            "fear": {
                "denoising_strength": 0.26,
                "prompt_suffix": "same character, identical face, identical hairstyle, identical outfit, identical pose, frightened expression only, no extra person",
            },
            "sad": {
                "denoising_strength": 0.24,
                "prompt_suffix": "same character, identical face, identical hairstyle, identical outfit, identical pose, sad expression only, no extra person",
            },
        }.get(expression)

    def _generate_sd_image(self,
                           prompt: str,
                           negative_prompt: str,
                           seed: int = -1,
                           width: int = 768,
                           height: int = 1024,
                           steps: int = 15,
                           cfg_scale: float = 7.0,
                           sampler_name: str = "DPM++ 2M Karras",
                           scheduler: str = "",
                           checkpoint: str = "",
                           override_settings: Optional[Dict[str, Any]] = None,
                           init_image_path: Optional[str] = None,
                           denoising_strength: Optional[float] = None,
                           consistency_image_path: Optional[str] = None,
                           consistency_mode: str = "",
                           consistency_weight: Optional[float] = None,
                           consistency_control_mode: str = "",
                           consistency_start_step: Optional[float] = None,
                           consistency_end_step: Optional[float] = None,
                           pose_image_path: Optional[str] = None,
                           pose_module: str = "",
                           pose_weight: Optional[float] = None,
                           pose_control_mode: str = "",
                           pose_start_step: Optional[float] = None,
                           pose_end_step: Optional[float] = None,
                           angle: str = "front") -> Optional[Dict]:
        """SD WebUI API로 이미지 생성. v63: angle(front 외)이면 OpenPose ControlNet 적용."""
        try:
            import requests

            use_img2img = bool(init_image_path)
            url = f"{self.sd_api_url}/sdapi/v1/img2img" if use_img2img else f"{self.sd_api_url}/sdapi/v1/txt2img"
            payload = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "sampler_name": sampler_name,
            }
            if scheduler:
                payload["scheduler"] = scheduler
            if use_img2img and init_image_path:
                with Image.open(init_image_path) as init_img:
                    buffer = io.BytesIO()
                    init_img.save(buffer, format="PNG")
                payload["init_images"] = [base64.b64encode(buffer.getvalue()).decode("utf-8")]
                payload["resize_mode"] = 0
                payload["include_init_images"] = False
                payload["denoising_strength"] = denoising_strength if denoising_strength is not None else 0.22
            merged_override = dict(override_settings or {})
            if checkpoint:
                merged_override["sd_model_checkpoint"] = checkpoint
            if merged_override:
                payload["override_settings"] = merged_override
            payload = self._apply_consistency_reference_payload(
                payload,
                consistency_image_path=consistency_image_path,
                consistency_mode=consistency_mode,
                consistency_weight=consistency_weight,
                consistency_control_mode=consistency_control_mode,
                consistency_start_step=consistency_start_step,
                consistency_end_step=consistency_end_step,
            )
            payload = self._append_pose_reference_payload(
                payload,
                pose_image_path=pose_image_path,
                pose_module=pose_module,
                pose_weight=pose_weight,
                pose_control_mode=pose_control_mode,
                pose_start_step=pose_start_step,
                pose_end_step=pose_end_step,
            )
            # v63: 각도별 OpenPose 스켈레톤 ControlNet (front 외, 스켈레톤 존재 시)
            if str(angle or "front").strip().lower() != "front":
                payload = self._append_openpose_angle_payload(payload, angle)

            response = requests.post(url, json=payload, timeout=420)

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"[CharacterLibraryManager] SD API 오류: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"[CharacterLibraryManager] SD API 호출 실패: {e}")
            return None

    # =========================================================
    # 이미지 품질 검증 (설계서 3.9)
    # =========================================================

    def _validate_image(self, image_path: str, character_def: Any) -> Dict[str, Any]:
        """
        이미지 품질 검증 (설계서 3.9 QualityControl)

        Returns:
            {
                'score': 0.0~1.0,
                'face_detected': bool,
                'blur_score': float,
                'nsfw_detected': bool,
                'artifacts_detected': bool,
            }
        """
        result = {
            'score': 0.0,
            'face_detected': False,
            'face_count': 0,
            'blur_score': 0.0,
            'nsfw_detected': False,
            'artifacts_detected': False,
        }

        if not os.path.exists(image_path):
            return result

        try:
            # 파일 크기 체크 (최소 50KB)
            file_size = os.path.getsize(image_path)
            if file_size < 50000:
                logger.warning(f"[품질검증] 파일 크기 작음: {file_size/1024:.1f}KB")
                return result

            # PIL로 이미지 로드
            try:
                from PIL import Image
                import numpy as np

                img = Image.open(image_path)
                img_array = np.array(img)

                # 1. 블러 감지 (Laplacian variance)
                if len(img_array.shape) == 3:
                    gray = np.mean(img_array, axis=2)
                else:
                    gray = img_array

                # Laplacian 근사
                laplacian_var = np.var(np.diff(np.diff(gray, axis=0), axis=1))
                result['blur_score'] = float(laplacian_var)

                # 블러 점수가 낮으면 흐릿함 (100 이하면 흐릿)
                blur_ok = laplacian_var > 50

                # 2. 얼굴 감지 (OpenCV 사용 가능 시)
                face_detected = True  # 기본적으로 True (OpenCV 없으면)
                try:
                    import cv2
                    face_cascade = cv2.CascadeClassifier(
                        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                    )
                    gray_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
                    faces = face_cascade.detectMultiScale(gray_cv, 1.1, 4)
                    face_detected = len(faces) > 0
                    result['face_count'] = int(len(faces))
                    result['face_detected'] = face_detected
                except ImportError:
                    # OpenCV 없으면 스킵
                    result['face_detected'] = True
                    result['face_count'] = 1
                except Exception as e:
                    logger.debug(f"[품질검증] 얼굴 감지 실패: {e}")
                    result['face_detected'] = True
                    result['face_count'] = 1

                # 3. 기본 품질 체크 (너무 어둡거나 밝은지)
                mean_brightness = np.mean(img_array)
                brightness_ok = 30 < mean_brightness < 240
                face_count_ok = (result['face_count'] <= max(1, int(getattr(self.config, "max_face_count", 1) or 1)))

                # 4. 점수 계산
                score = 0.5  # 기본 점수

                if blur_ok:
                    score += 0.2
                if face_detected or not self.config.face_detection_required:
                    score += 0.2
                if brightness_ok:
                    score += 0.1
                if not face_count_ok:
                    score = min(score, 0.2)

                result['score'] = min(1.0, score)

            except ImportError:
                # PIL 없으면 파일 크기만으로 판단
                result['score'] = 0.7 if file_size > 100000 else 0.5
                result['face_detected'] = True

        except Exception as e:
            logger.error(f"[품질검증] 오류: {e}")
            result['score'] = 0.5

        return result

    # =========================================================
    # 유틸리티
    # =========================================================

    def add_character_from_dict(self, char_dict: Dict[str, Any]) -> bool:
        """
        딕셔너리에서 캐릭터 추가

        Args:
            char_dict: {
                'id': str,
                'name': str,
                'base_prompt': str,
                'negative_prompt': str (optional),
                'role_aliases': List[str] (optional)
            }

        Returns:
            성공 여부
        """
        try:
            char_id = char_dict.get('id', '')
            if not char_id:
                logger.warning("[CharacterLibraryManager] 캐릭터 ID 없음")
                return False

            entry = CharacterLibraryEntry(
                character_id=char_id,
                character_name=char_dict.get('name', char_id),
                base_prompt=char_dict.get('base_prompt', ''),
                negative_prompt=char_dict.get('negative_prompt', ''),
                role_aliases=char_dict.get('role_aliases', []),
                generation_seed=self._stable_seed(f"{self.pack_id}:{char_id}:manual")
            )

            self.library[char_id] = entry
            logger.info(f"[CharacterLibraryManager] 캐릭터 추가: {char_id}")
            return True

        except Exception as e:
            logger.error(f"[CharacterLibraryManager] 캐릭터 추가 실패: {e}")
            return False

    def generate_all_characters(self,
                                sd_api: Any = None,
                                character_definitions: List[Any] = None,
                                progress_callback: callable = None) -> Dict[str, List[str]]:
        """
        모든 캐릭터 라이브러리 생성

        Args:
            sd_api: SD WebUI API (없으면 self.sd_api_url 사용)
            character_definitions: 캐릭터 정의 목록 (없으면 self.library 사용)
            progress_callback: 진행 콜백

        Returns:
            {character_id: [image_paths]}
        """
        # SD API URL 설정
        if sd_api:
            if hasattr(sd_api, 'base_url'):
                self.sd_api_url = sd_api.base_url
            elif isinstance(sd_api, str):
                self.sd_api_url = sd_api

        # 캐릭터 목록 결정
        if character_definitions:
            char_list = character_definitions
        else:
            # self.library에서 가져오기
            char_list = [
                type('CharDef', (), {'id': char_id, **asdict(entry)})()
                for char_id, entry in self.library.items()
            ]

        results = {}
        total_chars = len(char_list)

        for i, char_def in enumerate(char_list):
            char_id = getattr(char_def, 'id', '') or getattr(char_def, 'character_id', '')

            if progress_callback:
                progress_callback(
                    i + 1, total_chars,
                    f"캐릭터 {i+1}/{total_chars}: {char_id}"
                )

            # 이미 충분한 라이브러리가 있으면 스킵
            if self.has_character(char_id):
                logger.info(f"[CharacterLibraryManager] 스킵 (이미 존재): {char_id}")
                results[char_id] = []
                continue

            success, paths = self.generate_character_library(
                character_def=char_def,
                progress_callback=lambda c, t, m: progress_callback(
                    i + 1, total_chars, m
                ) if progress_callback else None
            )

            results[char_id] = paths

        return results

    def get_library_summary(self) -> Dict[str, Any]:
        """라이브러리 요약 정보"""
        total_images = 0
        characters = []

        for char_id, entry in self.library.items():
            char_total = sum(len(imgs) for imgs in entry.images.values())
            total_images += char_total

            expressions = set()
            poses = set()
            for key in entry.images.keys():
                parts = key.split('_', 1)
                if len(parts) == 2:
                    expressions.add(parts[0])
                    poses.add(parts[1])

            # 평균 품질
            all_scores = []
            for imgs in entry.images.values():
                all_scores.extend([img.quality_score for img in imgs])
            avg_quality = sum(all_scores) / len(all_scores) if all_scores else 0

            characters.append({
                "id": char_id,
                "name": entry.character_name,
                "total_images": char_total,
                "expressions": list(expressions),
                "poses": list(poses),
                "avg_quality": round(avg_quality, 2),
            })

        return {
            "pack_id": self.pack_id,
            "library_path": str(self.library_path),
            "total_characters": len(self.library),
            "total_images": total_images,
            "characters": characters,
            "config": asdict(self.config),
        }

    def clear_character(self, character_id: str) -> bool:
        """특정 캐릭터 라이브러리 삭제"""
        if character_id not in self.library:
            return False

        entry = self.library[character_id]

        # 이미지 파일 삭제
        for images in entry.images.values():
            for img in images:
                if os.path.exists(img.path):
                    try:
                        os.remove(img.path)
                    except OSError:
                        pass

        # 폴더 삭제
        char_path = self.library_path / character_id
        if char_path.exists():
            import shutil
            shutil.rmtree(char_path, ignore_errors=True)

        # 라이브러리에서 제거
        del self.library[character_id]
        self._save_library()

        logger.info(f"[CharacterLibraryManager] 캐릭터 삭제: {character_id}")
        return True


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== CharacterLibraryManager Test (v59 완전 구현) ===\n")

    # 테스트용 매니저 생성
    manager = CharacterLibraryManager(
        pack_id="test_pack",
        library_base_path="data/test_char_lib",
        sd_api_url="http://127.0.0.1:7860",
    )

    print("1. 라이브러리 요약:")
    summary = manager.get_library_summary()
    print(f"   Pack ID: {summary['pack_id']}")
    print(f"   경로: {summary['library_path']}")
    print(f"   캐릭터 수: {summary['total_characters']}")
    print(f"   총 이미지: {summary['total_images']}")

    print("\n2. 이미지 조회 테스트:")
    img = manager.get_character_image("test_char", "neutral", "standing")
    print(f"   결과: {img}")

    print("\n3. 캐릭터 존재 확인:")
    has = manager.has_character("test_char")
    print(f"   결과: {has}")

    print("\n[OK] 테스트 완료!")
