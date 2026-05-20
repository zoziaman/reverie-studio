"""Local VideoToon integration primitives.

This module keeps the new layered video-toon direction behind a narrow
contract. Existing image generation and Remotion code can adopt this contract
incrementally without turning the completed production pipeline inside out.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_REQUIRED_MODEL_PATHS = (
    "models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
    "models/ipadapter/ip-adapter-plus_sd15.safetensors",
    "models/ipadapter/ip-adapter-plus-face_sd15.safetensors",
    "models/controlnet/control_v11p_sd15_openpose.pth",
    "models/controlnet/control_v11f1p_sd15_depth.pth",
)

SUPPORTED_VIDEO_TOON_BACKENDS = {"comfyui", "sd_webui"}
SUPPORTED_SCENE_STATUSES = {
    "pending",
    "submitted",
    "background_generated",
    "generated",
    "finalized",
    "failed",
    "skipped",
}
TERMINAL_SCENE_STATUSES = {"generated", "finalized", "failed", "skipped"}
CORE_COMFYUI_TEMPLATE = "sd15_core_txt2img_v1"
ADVANCED_COMFYUI_TEMPLATE = "sd15_ipadapter_openpose_depth_v1"
COMFYUI_TEMPLATE_REQUIRED_NODES = {
    CORE_COMFYUI_TEMPLATE: {
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    },
    ADVANCED_COMFYUI_TEMPLATE: {
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "SaveImage",
        "VHS_LoadImagePath",
        "CLIPVisionLoader",
        "IPAdapterUnifiedLoader",
        "IPAdapterAdvanced",
        "OpenposePreprocessor",
        "ControlNetLoader",
        "ControlNetApplyAdvanced",
        "DepthAnythingV2Preprocessor",
    },
}


def _default_workspace_root() -> str:
    """Use a repo-local placeholder workspace instead of a personal D: drive path."""
    return str(Path(__file__).resolve().parents[2] / "data" / "videotoon_workspace")


@dataclass(frozen=True)
class VideoToonStackConfig:
    """Runtime settings for the local layered video-toon stack."""

    workspace_root: str
    image_backend: str = "comfyui"
    generation_width: int = 1024
    generation_height: int = 576
    max_parallel_image_jobs: int = 1
    layer_tool_python: str = ""
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_root: str = ""

    @classmethod
    def from_settings(cls, settings: Any) -> "VideoToonStackConfig":
        if hasattr(settings, "get_videotoon_config"):
            data = dict(settings.get_videotoon_config())
        else:
            data = {
                "workspace_root": getattr(settings, "VIDEOTOON_WORKSPACE_ROOT", ""),
                "image_backend": getattr(settings, "VIDEOTOON_IMAGE_BACKEND", "comfyui"),
                "generation_width": getattr(settings, "VIDEOTOON_GENERATION_WIDTH", 1024),
                "generation_height": getattr(settings, "VIDEOTOON_GENERATION_HEIGHT", 576),
                "max_parallel_image_jobs": getattr(settings, "VIDEOTOON_MAX_PARALLEL_IMAGE_JOBS", 1),
                "layer_tool_python": getattr(settings, "VIDEOTOON_LAYER_TOOL_PYTHON", ""),
                "comfyui_url": getattr(settings, "COMFYUI_URL", "http://127.0.0.1:8188"),
                "comfyui_root": getattr(settings, "COMFYUI_ROOT", ""),
            }
        return cls(
            workspace_root=str(data.get("workspace_root") or _default_workspace_root()),
            image_backend=str(data.get("image_backend") or "comfyui"),
            generation_width=int(data.get("generation_width") or 1024),
            generation_height=int(data.get("generation_height") or 576),
            max_parallel_image_jobs=max(1, int(data.get("max_parallel_image_jobs") or 1)),
            layer_tool_python=str(data.get("layer_tool_python") or ""),
            comfyui_url=str(data.get("comfyui_url") or "http://127.0.0.1:8188"),
            comfyui_root=str(data.get("comfyui_root") or ""),
        )


@dataclass(frozen=True)
class VideoToonCharacterCue:
    """Character state required by the video-toon storyboard contract."""

    id: str
    name: str = ""
    emotion: str = "neutral"
    action: str = ""
    is_speaker: bool = False


@dataclass(frozen=True)
class VideoToonSceneSpec:
    """Scene-level contract between story analysis and local image generation."""

    scene_id: str
    dialogue_index: int = 0
    text: str = ""
    speaker: str = ""
    characters: List[VideoToonCharacterCue] = field(default_factory=list)
    location: str = ""
    location_detail: str = ""
    time_of_day: str = ""
    weather: str = ""
    atmosphere: str = ""
    story_beat: str = ""
    camera_shot: str = ""
    key_props: List[str] = field(default_factory=list)
    outfit_hint: str = ""
    sd_prompt: str = ""
    continuity_hint: str = ""
    character_reference_path: str = ""
    pose_reference_path: str = ""
    depth_reference_path: str = ""
    required_outputs: List[str] = field(
        default_factory=lambda: [
            "background_plate",
            "character_foreground_alpha",
            "mouth_closed",
            "mouth_open",
            "composite_preview",
        ]
    )

    @classmethod
    def from_scene_result(cls, scene: Any) -> "VideoToonSceneSpec":
        characters: List[VideoToonCharacterCue] = []
        for char in list(getattr(scene, "characters", []) or []):
            characters.append(
                VideoToonCharacterCue(
                    id=str(getattr(char, "id", "") or getattr(char, "name", "") or ""),
                    name=str(getattr(char, "name", "") or ""),
                    emotion=str(getattr(char, "emotion", "neutral") or "neutral"),
                    action=str(getattr(char, "action", "") or ""),
                    is_speaker=bool(getattr(char, "is_speaker", False)),
                )
            )

        return cls(
            scene_id=str(getattr(scene, "scene_id", "") or f"scene_{int(getattr(scene, 'dialogue_index', 0)):04d}"),
            dialogue_index=int(getattr(scene, "dialogue_index", 0) or 0),
            text=str(getattr(scene, "original_dialogue", "") or ""),
            speaker=str(getattr(scene, "speaker", "") or ""),
            characters=characters,
            location=str(getattr(scene, "location", "") or ""),
            location_detail=str(getattr(scene, "location_detail", "") or ""),
            time_of_day=str(getattr(scene, "time_of_day", "") or ""),
            weather=str(getattr(scene, "weather", "") or ""),
            atmosphere=str(getattr(scene, "atmosphere", "") or ""),
            story_beat=str(getattr(scene, "story_beat", "") or ""),
            camera_shot=str(getattr(scene, "camera_shot", "") or ""),
            key_props=[str(p) for p in list(getattr(scene, "key_props", []) or [])],
            outfit_hint=str(getattr(scene, "outfit_hint", "") or ""),
            sd_prompt=str(getattr(scene, "sd_prompt", "") or ""),
            continuity_hint=str(getattr(scene, "continuity_hint", "") or ""),
            character_reference_path=str(getattr(scene, "character_reference_path", "") or ""),
            pose_reference_path=str(getattr(scene, "pose_reference_path", "") or ""),
            depth_reference_path=str(getattr(scene, "depth_reference_path", "") or ""),
        )

    def to_generation_request(self, config: VideoToonStackConfig) -> Dict[str, Any]:
        """Return the backend-neutral image generation request for this scene."""
        return {
            "scene_id": self.scene_id,
            "backend": config.image_backend,
            "size": {
                "width": config.generation_width,
                "height": config.generation_height,
            },
            "character_reference_mode": "ip_adapter_plus_face_sd15",
            "pose_control_mode": "controlnet_openpose_sd15",
            "depth_control_mode": "controlnet_depth_sd15",
            "layer_outputs": list(self.required_outputs),
            "prompt": self.sd_prompt,
            "negative_prompt_policy": "pack_default_plus_video_toon_safety",
            "reference_assets": {
                "character_reference_path": self.character_reference_path,
                "pose_reference_path": self.pose_reference_path,
                "depth_reference_path": self.depth_reference_path,
            },
            "storyboard": asdict(self),
        }


def _prompt_to_text(prompt: Any) -> str:
    if isinstance(prompt, dict):
        return str(
            prompt.get("prompt")
            or prompt.get("sd_prompt")
            or prompt.get("positive")
            or prompt.get("description")
            or ""
        )
    return str(prompt or "")


def build_scene_specs_from_production(
    script_list: Iterable[Dict[str, Any]],
    image_prompts: Iterable[Any],
    scene_analysis_cache: Optional[Any] = None,
) -> List[VideoToonSceneSpec]:
    """Build VideoToon scene specs from the current production payload.

    Existing production runs may have rich SceneAnalysisResult objects, simple
    image prompt strings, or prompt dictionaries. This adapter normalizes those
    sources into the VideoToon storyboard contract without changing legacy
    generation behavior.
    """
    scripts = list(script_list or [])
    prompts = list(image_prompts or [])

    analyzed: Dict[int, Any] = {}
    if isinstance(scene_analysis_cache, dict):
        analyzed = {int(k): v for k, v in scene_analysis_cache.items()}
    elif isinstance(scene_analysis_cache, list):
        analyzed = {idx: scene for idx, scene in enumerate(scene_analysis_cache)}

    count = max(len(prompts), len(analyzed), len(scripts) if not prompts else 0)
    scenes: List[VideoToonSceneSpec] = []
    for index in range(count):
        turn = scripts[index] if index < len(scripts) and isinstance(scripts[index], dict) else {}
        prompt_obj = prompts[index] if index < len(prompts) else {}
        prompt_text = _prompt_to_text(prompt_obj)

        if index in analyzed:
            scene = VideoToonSceneSpec.from_scene_result(analyzed[index])
            updates: Dict[str, Any] = {}
            if not scene.text and turn.get("text"):
                updates["text"] = str(turn.get("text") or "")
            if not scene.speaker and (turn.get("role") or turn.get("speaker")):
                updates["speaker"] = str(turn.get("role") or turn.get("speaker") or "")
            if prompt_text and not scene.sd_prompt:
                updates["sd_prompt"] = prompt_text
            if updates:
                scene = replace(scene, **updates)
            scenes.append(scene)
            continue

        prompt_data = prompt_obj if isinstance(prompt_obj, dict) else {}
        scenes.append(
            VideoToonSceneSpec(
                scene_id=str(prompt_data.get("scene_id") or f"scene_{index:04d}"),
                dialogue_index=index,
                text=str(turn.get("text") or ""),
                speaker=str(turn.get("role") or turn.get("speaker") or ""),
                location=str(prompt_data.get("location") or ""),
                location_detail=str(prompt_data.get("location_detail") or ""),
                time_of_day=str(prompt_data.get("time_of_day") or ""),
                weather=str(prompt_data.get("weather") or ""),
                atmosphere=str(prompt_data.get("atmosphere") or ""),
                story_beat=str(prompt_data.get("story_beat") or ""),
                camera_shot=str(prompt_data.get("camera_shot") or ""),
                key_props=[str(p) for p in list(prompt_data.get("key_props") or [])] if isinstance(prompt_data, dict) else [],
                sd_prompt=prompt_text,
                continuity_hint=str(prompt_data.get("continuity_hint") or ""),
            )
        )
    return scenes


@dataclass(frozen=True)
class VideoToonArtifactPaths:
    """Canonical local artifact paths for one video-toon scene."""

    scene_id: str
    scene_dir: str
    generation_request_path: str
    background_generation_request_path: str
    comfyui_submission_path: str
    comfyui_result_path: str
    composite_path: str
    background_path: str
    foreground_path: str
    mouth_closed_path: str
    mouth_open_path: str
    eyes_open_path: str
    eyes_closed_path: str
    mouth_cues_path: str
    status_path: str
    qc_report_path: str

    def to_remotion_layer_fields(self) -> Dict[str, str]:
        return {
            "background_path": self.background_path,
            "foreground_path": self.foreground_path,
            "eyes_open_path": self.eyes_open_path,
            "eyes_closed_path": self.eyes_closed_path,
            "mouth_closed_path": self.mouth_closed_path,
            "mouth_open_path": self.mouth_open_path,
        }


class VideoToonLocalWorkspace:
    """Filesystem and helper-tool adapter for the local VideoToon stack."""

    def __init__(self, config: VideoToonStackConfig):
        self.config = config
        self.root = Path(config.workspace_root)

    @classmethod
    def from_settings(cls, settings: Any) -> "VideoToonLocalWorkspace":
        return cls(VideoToonStackConfig.from_settings(settings))

    def ensure_layout(self) -> None:
        for relative in (
            "characters/refs",
            "characters/puppets",
            "backgrounds",
            "storyboards",
            "workflows",
            "layers/backgrounds",
            "layers/foregrounds",
            "layers/mouth",
            "layers/eyes",
            "props",
            "qc",
            "outputs/videos",
            "outputs/previews",
            "cache/comfyui",
            "cache/remotion",
            "temp",
            "logs",
            "models/checkpoints",
            "models/loras",
            "models/controlnet",
            "models/ipadapter",
            "models/clip_vision",
            "models/segmentation",
            "tools",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def validate_required_assets(self) -> Dict[str, Any]:
        missing = [path for path in DEFAULT_REQUIRED_MODEL_PATHS if not (self.root / path).exists()]
        tools = {
            "layer_tool_python": bool(self.config.layer_tool_python and Path(self.config.layer_tool_python).exists()),
            "remove_background": (self.root / "tools" / "remove_background.py").exists(),
            "mouth_cues": (self.root / "tools" / "audio_rms_mouth_cues.py").exists(),
        }
        return {
            "ready": not missing and all(tools.values()),
            "missing_models": missing,
            "tools": tools,
        }

    def build_status(self, motiontoon_config: Optional[Any] = None) -> Dict[str, Any]:
        """Return GUI-friendly readiness for pack opt-in plus local stack assets."""
        asset_status = self.validate_required_assets()
        backend = str(
            getattr(motiontoon_config, "video_toon_generation_backend", self.config.image_backend)
            or self.config.image_backend
        )
        pack_enabled = bool(getattr(motiontoon_config, "video_toon_local_enabled", False))
        layered_required = bool(getattr(motiontoon_config, "video_toon_layered_assets_required", False))
        workflow_template = str(
            getattr(motiontoon_config, "video_toon_workflow_template", "sd15_ipadapter_openpose_v1")
            or "sd15_ipadapter_openpose_v1"
        )
        backend_supported = backend in SUPPORTED_VIDEO_TOON_BACKENDS
        backend_matches_runtime = backend == self.config.image_backend
        stack_ready = bool(asset_status["ready"])

        reason = "ready"
        if not pack_enabled:
            reason = "pack_disabled"
        elif not backend_supported:
            reason = "unsupported_backend"
        elif not backend_matches_runtime:
            reason = "backend_mismatch"
        elif not stack_ready:
            reason = "missing_local_assets"

        return {
            "ready": pack_enabled and backend_supported and backend_matches_runtime and stack_ready,
            "reason": reason,
            "pack_enabled": pack_enabled,
            "stack_ready": stack_ready,
            "backend": backend,
            "runtime_backend": self.config.image_backend,
            "backend_supported": backend_supported,
            "backend_matches_runtime": backend_matches_runtime,
            "layered_assets_required": layered_required,
            "workflow_template": workflow_template,
            "workspace_root": str(self.root),
            "missing_models": list(asset_status["missing_models"]),
            "tools": dict(asset_status["tools"]),
        }

    def _manifest_has_usable_reference_images(self, manifest_path: Path) -> bool:
        if not manifest_path.exists():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        characters = list(manifest.get("characters") or [])
        if not characters:
            return False
        return any(Path(str(entry.get("reference_image") or "")).exists() for entry in characters)

    def default_character_manifest_path(self) -> Path:
        """Prefer approved golden references, but never select an empty manifest."""
        candidates = (
            self.root / "characters" / "refs" / "golden_cast_v1" / "golden_cast_manifest.json",
            self.root / "characters" / "refs" / "webtoon_cast_v3" / "webtoon_cast_manifest.json",
            self.root / "characters" / "refs" / "cheap_cast_v2" / "cheap_cast_manifest.json",
        )
        for candidate in candidates:
            if self._manifest_has_usable_reference_images(candidate):
                return candidate
        return candidates[-1]

    def load_character_reference_manifest(self, manifest_path: str = "") -> Dict[str, Any]:
        """Load the reusable VideoToon character reference manifest."""
        path = Path(manifest_path) if manifest_path else self.default_character_manifest_path()
        if not path.exists():
            return {"schema": "reverie.videotoon.character_manifest.missing", "characters": []}
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema": "reverie.videotoon.character_manifest.invalid", "characters": []}
        manifest["manifest_path"] = str(path)
        return manifest

    def apply_character_reference(
        self,
        scene: VideoToonSceneSpec,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> VideoToonSceneSpec:
        """Attach a reusable character reference image to a scene when possible."""
        if scene.character_reference_path:
            return scene

        data = manifest if manifest is not None else self.load_character_reference_manifest()
        characters = list((data or {}).get("characters") or [])
        if not characters:
            return scene

        lookup_tokens = {str(scene.speaker or "").strip().lower()}
        for cue in scene.characters:
            lookup_tokens.add(str(cue.id or "").strip().lower())
            lookup_tokens.add(str(cue.name or "").strip().lower())
        lookup_tokens = {token for token in lookup_tokens if token}

        for entry in characters:
            character_id = str(entry.get("character_id") or "").strip()
            korean_name = str(entry.get("korean_name") or "").strip()
            aliases = {character_id.lower(), korean_name.lower()}
            if lookup_tokens.isdisjoint({alias for alias in aliases if alias}):
                continue

            ref_path = str(entry.get("reference_image") or "").strip()
            if not ref_path or not Path(ref_path).exists():
                continue
            hint = scene.continuity_hint
            reference_hint = f"character_reference:{character_id or korean_name}"
            if reference_hint not in hint:
                hint = f"{hint}; {reference_hint}" if hint else reference_hint
            return replace(scene, character_reference_path=ref_path, continuity_hint=hint)

        return scene

    def scene_artifacts(self, production_id: str, scene_id: str) -> VideoToonArtifactPaths:
        safe_production_id = _safe_name(production_id)
        safe_scene_id = _safe_name(scene_id)
        scene_dir = self.root / "layers" / safe_production_id / safe_scene_id
        return VideoToonArtifactPaths(
            scene_id=scene_id,
            scene_dir=str(scene_dir),
            generation_request_path=str(scene_dir / "generation_request.json"),
            background_generation_request_path=str(scene_dir / "background_generation_request.json"),
            comfyui_submission_path=str(scene_dir / "comfyui_submission.json"),
            comfyui_result_path=str(scene_dir / "comfyui_result.json"),
            composite_path=str(scene_dir / "composite.png"),
            background_path=str(scene_dir / "background.png"),
            foreground_path=str(scene_dir / "foreground.png"),
            mouth_closed_path=str(scene_dir / "mouth_closed.png"),
            mouth_open_path=str(scene_dir / "mouth_open.png"),
            eyes_open_path=str(scene_dir / "eyes_open.png"),
            eyes_closed_path=str(scene_dir / "eyes_closed.png"),
            mouth_cues_path=str(scene_dir / "mouth_cues.json"),
            status_path=str(scene_dir / "scene_status.json"),
            qc_report_path=str(scene_dir / "qc_report.json"),
        )

    def write_storyboard(self, production_id: str, scenes: Iterable[VideoToonSceneSpec]) -> Path:
        self.ensure_layout()
        storyboard_path = self.root / "storyboards" / f"{_safe_name(production_id)}.json"
        payload = {
            "production_id": production_id,
            "schema": "reverie.videotoon.storyboard.v1",
            "config": asdict(self.config),
            "scenes": [asdict(scene) for scene in scenes],
        }
        storyboard_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return storyboard_path

    def write_generation_request(self, production_id: str, scene: VideoToonSceneSpec) -> VideoToonArtifactPaths:
        self.ensure_layout()
        scene = self.apply_character_reference(scene)
        artifacts = self.scene_artifacts(production_id, scene.scene_id)
        scene_dir = Path(artifacts.scene_dir)
        scene_dir.mkdir(parents=True, exist_ok=True)
        request = scene.to_generation_request(self.config)
        request["production_id"] = production_id
        request["artifacts"] = asdict(artifacts)
        Path(artifacts.generation_request_path).write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return artifacts

    def build_background_plate_prompt(self, scene: VideoToonSceneSpec) -> str:
        """Create a character-free background prompt for layer-safe video-toon scenes."""
        location_bits = [
            scene.location,
            scene.location_detail,
            scene.time_of_day,
            scene.weather,
            scene.atmosphere,
            scene.story_beat,
            scene.camera_shot,
        ]
        location_text = ", ".join(str(bit).strip() for bit in location_bits if str(bit or "").strip())
        if not location_text:
            location_text = scene.sd_prompt or "ordinary Korean interior"
        return (
            "empty background plate, no characters, no people, no faces, no bodies, "
            "Korean video-toon background, thick clean outlines, flat cel shading, "
            "consistent perspective, clear foreground space for a separate character layer, "
            f"{location_text}"
        )

    def write_background_plate_request(self, production_id: str, scene: VideoToonSceneSpec) -> VideoToonArtifactPaths:
        """Write a background-only generation request for clean layer composition."""
        self.ensure_layout()
        artifacts = self.scene_artifacts(production_id, scene.scene_id)
        scene_dir = Path(artifacts.scene_dir)
        scene_dir.mkdir(parents=True, exist_ok=True)
        request = {
            "schema": "reverie.videotoon.background_plate_request.v1",
            "production_id": production_id,
            "scene_id": scene.scene_id,
            "backend": self.config.image_backend,
            "layer_role": "background_plate",
            "target_artifact": "background_path",
            "target_artifact_path": artifacts.background_path,
            "size": {
                "width": self.config.generation_width,
                "height": self.config.generation_height,
            },
            "prompt": self.build_background_plate_prompt(scene),
            "negative_prompt": (
                "no people, no person, no character, no face, no body, no hands, "
                "no text, no watermark, no logo, no cropped subject"
            ),
            "artifacts": asdict(artifacts),
            "storyboard": asdict(scene),
        }
        Path(artifacts.background_generation_request_path).write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return artifacts

    def bundle_progress_path(self, production_id: str) -> Path:
        return self.root / "qc" / f"{_safe_name(production_id)}_progress.json"

    def bundle_execution_summary_path(self, production_id: str) -> Path:
        return self.root / "qc" / f"{_safe_name(production_id)}_execution_summary.json"

    def _write_scene_status_file(
        self,
        production_id: str,
        artifacts: VideoToonArtifactPaths,
        *,
        status: str,
        stage: str = "",
        reason: str = "",
        retry_count: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if status not in SUPPORTED_SCENE_STATUSES:
            raise ValueError(
                f"Unsupported VideoToon scene status: {status}. "
                f"Supported: {', '.join(sorted(SUPPORTED_SCENE_STATUSES))}"
            )
        payload = {
            "schema": "reverie.videotoon.scene_status.v1",
            "production_id": production_id,
            "scene_id": artifacts.scene_id,
            "status": status,
            "stage": stage,
            "reason": reason,
            "retry_count": max(0, int(retry_count or 0)),
            "details": dict(details or {}),
            "artifacts": asdict(artifacts),
        }
        status_path = Path(artifacts.status_path)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def write_scene_status(
        self,
        production_id: str,
        artifacts: VideoToonArtifactPaths,
        *,
        status: str,
        stage: str = "",
        reason: str = "",
        retry_count: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record one scene state and refresh the aggregate production progress."""
        scene_status = self._write_scene_status_file(
            production_id,
            artifacts,
            status=status,
            stage=stage,
            reason=reason,
            retry_count=retry_count,
            details=details,
        )
        self.write_bundle_progress(production_id)
        return scene_status

    def write_bundle_progress(self, production_id: str) -> Dict[str, Any]:
        """Write a GUI-readable progress summary for a VideoToon production bundle."""
        self.ensure_layout()
        safe_production_id = _safe_name(production_id)
        manifest_path = self.root / "storyboards" / f"{safe_production_id}_bundle_manifest.json"
        scene_entries: List[Dict[str, Any]] = []

        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            scene_entries = list(manifest.get("scenes") or [])
        else:
            layers_dir = self.root / "layers" / safe_production_id
            if layers_dir.exists():
                for scene_dir in sorted(path for path in layers_dir.iterdir() if path.is_dir()):
                    status_path = scene_dir / "scene_status.json"
                    scene_entries.append(
                        {
                            "scene_id": scene_dir.name,
                            "status_path": str(status_path),
                            "scene_dir": str(scene_dir),
                        }
                    )

        scene_statuses: List[Dict[str, Any]] = []
        status_counts: Dict[str, int] = {}
        failed_scenes: List[Dict[str, str]] = []
        for entry in scene_entries:
            status_path = Path(str(entry.get("status_path") or ""))
            if status_path.exists():
                scene_status = json.loads(status_path.read_text(encoding="utf-8"))
            else:
                scene_status = {
                    "scene_id": str(entry.get("scene_id") or ""),
                    "status": "pending",
                    "stage": "",
                    "reason": "",
                    "retry_count": 0,
                    "details": {},
                }
            status = str(scene_status.get("status") or "pending")
            if status not in SUPPORTED_SCENE_STATUSES:
                status = "failed"
                scene_status["status"] = status
                scene_status["reason"] = scene_status.get("reason") or "unknown_status_in_status_file"
            status_counts[status] = status_counts.get(status, 0) + 1
            scene_statuses.append(scene_status)
            if status == "failed":
                failed_scenes.append(
                    {
                        "scene_id": str(scene_status.get("scene_id") or entry.get("scene_id") or ""),
                        "stage": str(scene_status.get("stage") or ""),
                        "reason": str(scene_status.get("reason") or ""),
                    }
                )

        total_scenes = len(scene_entries)
        completed_scenes = sum(
            1 for scene_status in scene_statuses if str(scene_status.get("status") or "") in TERMINAL_SCENE_STATUSES
        )
        progress = {
            "schema": "reverie.videotoon.bundle_progress.v1",
            "production_id": production_id,
            "manifest_path": str(manifest_path),
            "total_scenes": total_scenes,
            "completed_scenes": completed_scenes,
            "progress_ratio": round(completed_scenes / total_scenes, 4) if total_scenes else 0.0,
            "status_counts": status_counts,
            "failed_scenes": failed_scenes,
            "scenes": [
                {
                    "scene_id": str(scene_status.get("scene_id") or ""),
                    "status": str(scene_status.get("status") or "pending"),
                    "stage": str(scene_status.get("stage") or ""),
                    "reason": str(scene_status.get("reason") or ""),
                    "retry_count": int(scene_status.get("retry_count") or 0),
                }
                for scene_status in scene_statuses
            ],
        }
        progress_path = self.bundle_progress_path(production_id)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        return progress

    def read_latest_bundle_progress(self) -> Optional[Dict[str, Any]]:
        """Return the newest aggregate progress report, if one exists."""
        progress_dir = self.root / "qc"
        if not progress_dir.exists():
            return None
        progress_files = sorted(
            progress_dir.glob("*_progress.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not progress_files:
            return None
        progress_path = progress_files[0]
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        progress["progress_path"] = str(progress_path)
        return progress

    def write_production_bundle(
        self,
        production_id: str,
        scenes: Iterable[VideoToonSceneSpec],
    ) -> Dict[str, Any]:
        """Write storyboard, per-scene generation requests, and a bundle manifest."""
        self.ensure_layout()
        character_manifest = self.load_character_reference_manifest()
        scene_list = [self.apply_character_reference(scene, character_manifest) for scene in list(scenes or [])]
        storyboard_path = self.write_storyboard(production_id, scene_list)
        scene_entries: List[Dict[str, Any]] = []
        for scene in scene_list:
            artifacts = self.write_generation_request(production_id, scene)
            scene_entries.append(
                {
                    "scene_id": scene.scene_id,
                    "scene_dir": artifacts.scene_dir,
                    "generation_request_path": artifacts.generation_request_path,
                    "background_generation_request_path": artifacts.background_generation_request_path,
                    "comfyui_submission_path": artifacts.comfyui_submission_path,
                    "comfyui_result_path": artifacts.comfyui_result_path,
                    "status_path": artifacts.status_path,
                    "qc_report_path": artifacts.qc_report_path,
                    "remotion_layer_fields": artifacts.to_remotion_layer_fields(),
                }
            )
            self.write_background_plate_request(production_id, scene)
            if not Path(artifacts.status_path).exists():
                self._write_scene_status_file(
                    production_id,
                    artifacts,
                    status="pending",
                    stage="bundle",
                    reason="awaiting_generation",
                )

        manifest_path = self.root / "storyboards" / f"{_safe_name(production_id)}_bundle_manifest.json"
        progress_path = self.bundle_progress_path(production_id)
        manifest = {
            "schema": "reverie.videotoon.production_bundle.v1",
            "production_id": production_id,
            "scene_count": len(scene_list),
            "storyboard_path": str(storyboard_path),
            "manifest_path": str(manifest_path),
            "progress_path": str(progress_path),
            "config": asdict(self.config),
            "scenes": scene_entries,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.write_bundle_progress(production_id)
        return manifest

    def compile_comfyui_prompt(
        self,
        generation_request: Dict[str, Any],
        checkpoint: str = "counterfeitV30_v30.safetensors",
        seed: int = -1,
        steps: int = 28,
        cfg: float = 6.0,
        template: str = CORE_COMFYUI_TEMPLATE,
    ) -> Dict[str, Any]:
        """Compile a generation request into a ComfyUI prompt graph."""
        import random

        size = dict(generation_request.get("size") or {})
        width = int(size.get("width") or self.config.generation_width)
        height = int(size.get("height") or self.config.generation_height)
        prompt = str(generation_request.get("prompt") or "").strip()
        scene_id = str(generation_request.get("scene_id") or "scene")
        production_id = str(generation_request.get("production_id") or "production")
        if seed == -1:
            seed = random.randint(0, 2**32 - 1)

        negative = str(generation_request.get("negative_prompt") or "").strip()
        default_negative = (
            "worst quality, low quality, blurry, jpeg artifacts, watermark, text, logo, "
            "bad anatomy, bad hands, extra fingers, missing fingers, cropped face, cropped body"
        )
        full_negative = f"{negative}, {default_negative}" if negative else default_negative
        filename_prefix = f"reverie_videotoon/{_safe_name(production_id)}/{_safe_name(scene_id)}"

        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": full_negative, "clip": ["1", 1]},
            },
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": ["4", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["7", 0], "vae": ["1", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"images": ["8", 0], "filename_prefix": filename_prefix},
            },
        }

        if template == CORE_COMFYUI_TEMPLATE:
            return workflow
        if template != ADVANCED_COMFYUI_TEMPLATE:
            raise ValueError(f"Unsupported ComfyUI VideoToon template: {template}")

        references = dict(generation_request.get("reference_assets") or {})
        character_ref = str(references.get("character_reference_path") or "").strip()
        pose_ref = str(references.get("pose_reference_path") or "").strip()
        depth_ref = str(references.get("depth_reference_path") or pose_ref or "").strip()
        missing_refs = []
        if not character_ref:
            missing_refs.append("character_reference_path")
        if not pose_ref:
            missing_refs.append("pose_reference_path")
        if not depth_ref:
            missing_refs.append("depth_reference_path")
        if missing_refs:
            raise ValueError(f"Missing reference asset(s) for {template}: {', '.join(missing_refs)}")

        workflow.update(
            {
                "10": {
                    "class_type": "VHS_LoadImagePath",
                    "inputs": {"image": character_ref, "custom_width": 0, "custom_height": 0},
                },
                "11": {
                    "class_type": "CLIPVisionLoader",
                    "inputs": {"clip_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"},
                },
                "12": {
                    "class_type": "IPAdapterUnifiedLoader",
                    "inputs": {"model": ["1", 0], "preset": "PLUS FACE (portraits)"},
                },
                "13": {
                    "class_type": "IPAdapterAdvanced",
                    "inputs": {
                        "model": ["12", 0],
                        "ipadapter": ["12", 1],
                        "image": ["10", 0],
                        "weight": 0.75,
                        "weight_type": "linear",
                        "combine_embeds": "concat",
                        "start_at": 0.0,
                        "end_at": 0.85,
                        "embeds_scaling": "V only",
                        "clip_vision": ["11", 0],
                    },
                },
                "20": {
                    "class_type": "VHS_LoadImagePath",
                    "inputs": {"image": pose_ref, "custom_width": width, "custom_height": height},
                },
                "21": {
                    "class_type": "OpenposePreprocessor",
                    "inputs": {
                        "image": ["20", 0],
                        "detect_hand": "enable",
                        "detect_body": "enable",
                        "detect_face": "disable",
                        "resolution": 512,
                        "scale_stick_for_xinsr_cn": "disable",
                    },
                },
                "22": {
                    "class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": "control_v11p_sd15_openpose.pth"},
                },
                "23": {
                    "class_type": "ControlNetApplyAdvanced",
                    "inputs": {
                        "positive": ["5", 0],
                        "negative": ["6", 0],
                        "control_net": ["22", 0],
                        "image": ["21", 0],
                        "strength": 0.72,
                        "start_percent": 0.0,
                        "end_percent": 0.85,
                    },
                },
                "30": {
                    "class_type": "VHS_LoadImagePath",
                    "inputs": {"image": depth_ref, "custom_width": width, "custom_height": height},
                },
                "31": {
                    "class_type": "DepthAnythingV2Preprocessor",
                    "inputs": {
                        "image": ["30", 0],
                        "ckpt_name": "depth_anything_v2_vitl.pth",
                        "resolution": 512,
                    },
                },
                "32": {
                    "class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": "control_v11f1p_sd15_depth.pth"},
                },
                "33": {
                    "class_type": "ControlNetApplyAdvanced",
                    "inputs": {
                        "positive": ["23", 0],
                        "negative": ["23", 1],
                        "control_net": ["32", 0],
                        "image": ["31", 0],
                        "strength": 0.32,
                        "start_percent": 0.0,
                        "end_percent": 0.65,
                    },
                },
            }
        )
        workflow["7"]["inputs"]["model"] = ["13", 0]
        workflow["7"]["inputs"]["positive"] = ["33", 0]
        workflow["7"]["inputs"]["negative"] = ["33", 1]
        return workflow

    def submit_generation_request(
        self,
        generation_request_path: str,
        client: Optional[Any] = None,
        checkpoint: str = "counterfeitV30_v30.safetensors",
        seed: int = -1,
        template: str = CORE_COMFYUI_TEMPLATE,
    ) -> Dict[str, Any]:
        """Submit one generation request to ComfyUI and record the exact prompt payload."""
        request_path = Path(generation_request_path)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        prompt = self.compile_comfyui_prompt(request, checkpoint=checkpoint, seed=seed, template=template)

        if client is None:
            from modules_pro.comfyui_client import get_comfyui_client

            client = get_comfyui_client()

        prompt_id = client.queue_prompt(prompt)
        artifacts = dict(request.get("artifacts") or {})
        submission_path = Path(
            artifacts.get("comfyui_submission_path")
            or request_path.with_name("comfyui_submission.json")
        )
        submission_path.write_text(
            json.dumps(
                {
                    "prompt_id": prompt_id,
                    "generation_request_path": str(request_path),
                    "prompt": prompt,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "prompt_id": prompt_id,
            "submission_path": str(submission_path),
            "prompt": prompt,
        }

    @staticmethod
    def extract_comfyui_image_outputs(history_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten ComfyUI history outputs into image descriptors."""
        outputs = dict((history_result or {}).get("outputs") or {})
        images: List[Dict[str, Any]] = []
        for node_id in sorted(outputs.keys(), key=str):
            node_output = dict(outputs.get(node_id) or {})
            for image in list(node_output.get("images") or []):
                if not isinstance(image, dict) or not image.get("filename"):
                    continue
                images.append(
                    {
                        "node_id": str(node_id),
                        "filename": str(image.get("filename") or ""),
                        "subfolder": str(image.get("subfolder") or ""),
                        "type": str(image.get("type") or "output"),
                    }
                )
        return images

    def ingest_comfyui_result(
        self,
        production_id: str,
        artifacts: VideoToonArtifactPaths,
        history_result: Dict[str, Any],
        *,
        client: Optional[Any] = None,
        selected_index: int = 0,
        target_artifact: str = "composite_path",
    ) -> Dict[str, Any]:
        """Download a completed ComfyUI image output into the scene artifact bundle."""
        if client is None:
            from modules_pro.comfyui_client import get_comfyui_client

            client = get_comfyui_client()

        images = self.extract_comfyui_image_outputs(history_result)
        result_path = Path(artifacts.comfyui_result_path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        target_path = str(getattr(artifacts, target_artifact, "") or artifacts.composite_path)
        success_status = "background_generated" if target_artifact == "background_path" else "generated"

        if not images:
            report = {
                "schema": "reverie.videotoon.comfyui_result.v1",
                "production_id": production_id,
                "scene_id": artifacts.scene_id,
                "status": "failed",
                "reason": "no_image_outputs",
                "image_count": 0,
                "selected_image": None,
                "target_artifact": target_artifact,
                "target_artifact_path": target_path,
                "composite_path": artifacts.composite_path,
                "history_outputs": dict((history_result or {}).get("outputs") or {}),
            }
            result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            self.write_scene_status(
                production_id,
                artifacts,
                status="failed",
                stage="comfyui_result",
                reason="no_image_outputs",
                details={"comfyui_result_path": str(result_path)},
            )
            return report

        selected = images[min(max(0, selected_index), len(images) - 1)]
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        client.save_output(
            selected["filename"],
            target_path,
            subfolder=selected.get("subfolder", ""),
            output_type=selected.get("type", "output"),
        )
        report = {
            "schema": "reverie.videotoon.comfyui_result.v1",
            "production_id": production_id,
            "scene_id": artifacts.scene_id,
            "status": success_status,
            "image_count": len(images),
            "selected_image": selected,
            "target_artifact": target_artifact,
            "target_artifact_path": target_path,
            "composite_path": artifacts.composite_path,
            "history_outputs": dict((history_result or {}).get("outputs") or {}),
        }
        result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.write_scene_status(
            production_id,
            artifacts,
            status=success_status,
            stage="comfyui_result",
            details={
                "comfyui_result_path": str(result_path),
                "target_artifact": target_artifact,
                "target_artifact_path": target_path,
                "selected_image": selected,
            },
        )
        return report

    def execute_generation_request(
        self,
        generation_request_path: str,
        *,
        client: Optional[Any] = None,
        checkpoint: str = "counterfeitV30_v30.safetensors",
        seed: int = -1,
        template: str = CORE_COMFYUI_TEMPLATE,
        timeout: Optional[int] = None,
        progress_callback: Optional[Any] = None,
        finalize_layers: bool = False,
        use_composite_as_background: bool = False,
        background_source_path: str = "",
        audio_path: str = "",
        fps: int = 30,
        background_removal_runner: Optional[Any] = None,
        mouth_cue_runner: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Queue one generation request, wait for ComfyUI, and ingest its first image."""
        request_path = Path(generation_request_path)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        production_id = str(request.get("production_id") or "production")
        scene_id = str(request.get("scene_id") or request_path.parent.name or "scene")
        artifacts = self.scene_artifacts(production_id, scene_id)
        target_artifact = str(request.get("target_artifact") or "composite_path")

        if client is None:
            from modules_pro.comfyui_client import get_comfyui_client

            client = get_comfyui_client()

        try:
            submission = self.submit_generation_request(
                str(request_path),
                client=client,
                checkpoint=checkpoint,
                seed=seed,
                template=template,
            )
            prompt_id = str(submission.get("prompt_id") or "")
            self.write_scene_status(
                production_id,
                artifacts,
                status="submitted",
                stage="comfyui_queue",
                reason="queued",
                details={"prompt_id": prompt_id, "submission_path": submission.get("submission_path")},
            )
            history = client.wait_for_completion(prompt_id, progress_callback=progress_callback, timeout=timeout)
            result = self.ingest_comfyui_result(
                production_id,
                artifacts,
                history,
                client=client,
                target_artifact=target_artifact,
            )
            if finalize_layers and result.get("status") == "generated":
                final_background_source = background_source_path
                if not final_background_source and use_composite_as_background:
                    final_background_source = artifacts.composite_path
                layer_qc = self.finalize_scene_layers(
                    artifacts,
                    composite_source_path=artifacts.composite_path,
                    background_source_path=final_background_source,
                    audio_path=audio_path,
                    fps=fps,
                    background_removal_runner=background_removal_runner,
                    mouth_cue_runner=mouth_cue_runner,
                )
                result["layer_qc"] = layer_qc
                if layer_qc.get("ready_for_remotion"):
                    self.write_scene_status(
                        production_id,
                        artifacts,
                        status="finalized",
                        stage="layer_finalize",
                        details={
                            "qc_report_path": artifacts.qc_report_path,
                            "composite_path": artifacts.composite_path,
                        },
                    )
                    result["status"] = "finalized"
            result["prompt_id"] = prompt_id
            result["submission_path"] = submission.get("submission_path")
            return result
        except Exception as exc:
            self.write_scene_status(
                production_id,
                artifacts,
                status="failed",
                stage="comfyui_execute",
                reason=str(exc),
                details={"generation_request_path": str(request_path)},
            )
            raise

    def execute_production_bundle(
        self,
        manifest_path: str,
        *,
        client: Optional[Any] = None,
        checkpoint: str = "counterfeitV30_v30.safetensors",
        seed: int = -1,
        template: str = CORE_COMFYUI_TEMPLATE,
        timeout: Optional[int] = None,
        progress_callback: Optional[Any] = None,
        stop_on_error: bool = False,
        finalize_layers: bool = False,
        use_composite_as_background: bool = False,
        background_source_path: str = "",
        audio_path_by_scene: Optional[Dict[str, str]] = None,
        fps: int = 30,
        background_removal_runner: Optional[Any] = None,
        mouth_cue_runner: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Sequentially execute every scene request in a VideoToon production bundle."""
        manifest_file = Path(manifest_path)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        production_id = str(manifest.get("production_id") or manifest_file.stem.replace("_bundle_manifest", ""))
        scenes = list(manifest.get("scenes") or [])
        results: List[Dict[str, Any]] = []
        generated_count = 0
        failed_count = 0

        if client is None:
            from modules_pro.comfyui_client import get_comfyui_client

            client = get_comfyui_client()

        for index, scene_entry in enumerate(scenes):
            scene_id = str(scene_entry.get("scene_id") or f"scene_{index:04d}")
            request_path = str(scene_entry.get("generation_request_path") or "")
            scene_seed = seed + index if seed != -1 else -1
            try:
                result = self.execute_generation_request(
                    request_path,
                    client=client,
                    checkpoint=checkpoint,
                    seed=scene_seed,
                    template=template,
                    timeout=timeout,
                    progress_callback=progress_callback,
                    finalize_layers=finalize_layers,
                    use_composite_as_background=use_composite_as_background,
                    background_source_path=background_source_path,
                    audio_path=str((audio_path_by_scene or {}).get(scene_id) or ""),
                    fps=fps,
                    background_removal_runner=background_removal_runner,
                    mouth_cue_runner=mouth_cue_runner,
                )
                results.append(
                    {
                        "scene_id": scene_id,
                        "status": result.get("status", "generated"),
                        "prompt_id": result.get("prompt_id"),
                        "composite_path": result.get("composite_path"),
                    }
                )
                if result.get("status") in {"background_generated", "generated", "finalized"}:
                    generated_count += 1
                else:
                    failed_count += 1
            except Exception as exc:
                failed_count += 1
                results.append(
                    {
                        "scene_id": scene_id,
                        "status": "failed",
                        "reason": str(exc),
                        "generation_request_path": request_path,
                    }
                )
                if stop_on_error:
                    raise

        progress = self.write_bundle_progress(production_id)
        summary_path = self.bundle_execution_summary_path(production_id)
        summary = {
            "schema": "reverie.videotoon.execution_summary.v1",
            "production_id": production_id,
            "manifest_path": str(manifest_file),
            "summary_path": str(summary_path),
            "progress_path": str(self.bundle_progress_path(production_id)),
            "scene_count": len(scenes),
            "generated_count": generated_count,
            "failed_count": failed_count,
            "results": results,
            "progress": progress,
        }
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    @staticmethod
    def validate_comfyui_template_contract(
        object_info: Dict[str, Any],
        template: str = CORE_COMFYUI_TEMPLATE,
    ) -> Dict[str, Any]:
        """Validate that active ComfyUI exposes the nodes required by a template."""
        required_nodes = COMFYUI_TEMPLATE_REQUIRED_NODES.get(template)
        if required_nodes is None:
            return {
                "ready": False,
                "template": template,
                "missing_nodes": [],
                "error": "unsupported_template",
            }
        available = set(object_info or {})
        missing = sorted(required_nodes - available)
        return {
            "ready": not missing,
            "template": template,
            "missing_nodes": missing,
            "required_nodes": sorted(required_nodes),
        }

    def run_background_removal(self, input_path: str, output_path: str, timeout: int = 600) -> subprocess.CompletedProcess:
        tool = self.root / "tools" / "remove_background.py"
        if not self.config.layer_tool_python or not Path(self.config.layer_tool_python).exists():
            raise FileNotFoundError(f"Layer tool Python not found: {self.config.layer_tool_python}")
        if not tool.exists():
            raise FileNotFoundError(f"Background removal tool not found: {tool}")
        return subprocess.run(
            [self.config.layer_tool_python, str(tool), "--input", input_path, "--output", output_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def finalize_scene_layers(
        self,
        artifacts: VideoToonArtifactPaths,
        *,
        composite_source_path: str = "",
        background_source_path: str = "",
        audio_path: str = "",
        fps: int = 30,
        background_removal_runner: Optional[Any] = None,
        mouth_cue_runner: Optional[Any] = None,
        synthesize_face_fallback: bool = True,
    ) -> Dict[str, Any]:
        """Materialize one generated scene into Remotion-ready layer files."""
        scene_dir = Path(artifacts.scene_dir)
        scene_dir.mkdir(parents=True, exist_ok=True)
        warnings: List[str] = []

        if composite_source_path:
            _copy_file(composite_source_path, artifacts.composite_path)
        elif not Path(artifacts.composite_path).exists():
            warnings.append("missing_composite_source")

        if background_source_path:
            _copy_file(background_source_path, artifacts.background_path)
        elif Path(artifacts.background_path).exists():
            pass
        else:
            warnings.append("missing_background_source")

        composite_for_foreground = artifacts.composite_path if Path(artifacts.composite_path).exists() else composite_source_path
        if composite_for_foreground:
            if background_removal_runner is not None:
                background_removal_runner(composite_for_foreground, artifacts.foreground_path)
            else:
                self.run_background_removal(composite_for_foreground, artifacts.foreground_path)

        if audio_path:
            if mouth_cue_runner is not None:
                mouth_cue_runner(audio_path, artifacts.mouth_cues_path, fps)
            else:
                self.run_mouth_cue_extraction(audio_path, artifacts.mouth_cues_path, fps=fps)

        face_paths = (
            artifacts.eyes_open_path,
            artifacts.eyes_closed_path,
            artifacts.mouth_closed_path,
            artifacts.mouth_open_path,
        )
        if synthesize_face_fallback and not all(Path(path).exists() for path in face_paths):
            fallback_source = artifacts.foreground_path if Path(artifacts.foreground_path).exists() else composite_for_foreground
            fallback_report = self.synthesize_face_sprite_fallback(artifacts, source_path=str(fallback_source or ""))
            if "synthetic_face_sprite_fallback" in fallback_report.get("warnings", []):
                warnings.append("synthetic_face_sprite_fallback")

        return self.write_layer_qc_report(artifacts, warnings=warnings)

    def write_layer_qc_report(
        self,
        artifacts: VideoToonArtifactPaths,
        *,
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Write a deterministic QC report for one scene's layer artifacts."""
        path_fields = asdict(artifacts)
        required_for_remotion = ("background_path", "foreground_path")
        optional_layer_fields = (
            "composite_path",
            "eyes_open_path",
            "eyes_closed_path",
            "mouth_closed_path",
            "mouth_open_path",
            "mouth_cues_path",
        )
        missing_required = [
            key
            for key in required_for_remotion
            if not str(path_fields.get(key) or "") or not Path(str(path_fields.get(key))).exists()
        ]
        missing_optional = [
            key
            for key in optional_layer_fields
            if not str(path_fields.get(key) or "") or not Path(str(path_fields.get(key))).exists()
        ]
        face_sprite_keys = ("eyes_open_path", "eyes_closed_path", "mouth_closed_path", "mouth_open_path")
        face_sprites_ready = all(Path(str(path_fields.get(key) or "")).exists() for key in face_sprite_keys)
        report = {
            "schema": "reverie.videotoon.layer_qc.v1",
            "scene_id": artifacts.scene_id,
            "ready_for_remotion": not missing_required,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "face_sprites_ready": face_sprites_ready,
            "mouth_cues_ready": Path(artifacts.mouth_cues_path).exists(),
            "warnings": list(warnings or []),
            "remotion_layer_fields": artifacts.to_remotion_layer_fields(),
            "artifacts": path_fields,
        }
        qc_path = Path(artifacts.qc_report_path)
        qc_path.parent.mkdir(parents=True, exist_ok=True)
        qc_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def attach_face_sprite_assets(
        self,
        artifacts: VideoToonArtifactPaths,
        face_parts: Dict[str, str],
    ) -> Dict[str, Any]:
        """Copy validated reusable face sprites into the scene artifact bundle."""
        scene_dir = Path(artifacts.scene_dir)
        scene_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for key, target_path in (
            ("eyes_open_path", artifacts.eyes_open_path),
            ("eyes_closed_path", artifacts.eyes_closed_path),
            ("mouth_closed_path", artifacts.mouth_closed_path),
            ("mouth_open_path", artifacts.mouth_open_path),
        ):
            source_path = str(face_parts.get(key) or "")
            if source_path:
                _copy_file(source_path, target_path)
                copied.append(key)
        warnings = []
        if copied and len(copied) < 4:
            warnings.append("partial_face_sprite_bundle")
        elif not copied:
            warnings.append("missing_face_sprite_bundle")
        return self.write_layer_qc_report(artifacts, warnings=warnings)

    def synthesize_face_sprite_fallback(
        self,
        artifacts: VideoToonArtifactPaths,
        *,
        source_path: str = "",
        face_box: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Create full-frame transparent eye/mouth sprites when no face bundle exists.

        This is a safety fallback, not a substitute for character-specific sprites.
        Remotion expects face sprites to align to the full scene frame, so the fallback
        writes transparent canvases with simple facial marks at a conservative default
        face position.
        """
        from PIL import Image, ImageDraw

        scene_dir = Path(artifacts.scene_dir)
        scene_dir.mkdir(parents=True, exist_ok=True)

        source = Path(source_path or artifacts.foreground_path or artifacts.composite_path)
        alpha_bbox: Optional[Tuple[int, int, int, int]] = None
        if source.exists():
            with Image.open(source) as image:
                if image.mode == "RGBA":
                    alpha_bbox = image.getchannel("A").getbbox()
                width, height = image.size
        else:
            width = int(self.config.generation_width or 1024)
            height = int(self.config.generation_height or 576)

        box = dict(face_box or {})
        if alpha_bbox and not face_box:
            left, top, right, bottom = alpha_bbox
            subject_w = max(1, right - left)
            subject_h = max(1, bottom - top)
            defaults: Dict[str, float] = {
                "cx": (left + subject_w * 0.50) / width,
                "eye_y": (top + subject_h * 0.105) / height,
                "mouth_y": (top + subject_h * 0.145) / height,
                "eye_dx": (subject_w * 0.060) / width,
                "eye_rx": (subject_w * 0.012) / width,
                "eye_ry": (subject_h * 0.0038) / height,
                "mouth_w": (subject_w * 0.030) / width,
                "mouth_h": (subject_h * 0.007) / height,
            }
        else:
            defaults = {
                "cx": 0.50,
                "eye_y": 0.36,
                "mouth_y": 0.48,
                "eye_dx": 0.045,
                "eye_rx": 0.012,
                "eye_ry": 0.012,
                "mouth_w": 0.055,
                "mouth_h": 0.020,
            }
        cx = int(width * float(box.get("cx", defaults["cx"])))
        eye_y = int(height * float(box.get("eye_y", defaults["eye_y"])))
        mouth_y = int(height * float(box.get("mouth_y", defaults["mouth_y"])))
        eye_dx = max(4, int(width * float(box.get("eye_dx", defaults["eye_dx"]))))
        eye_rx = max(2, int(width * float(box.get("eye_rx", defaults["eye_rx"]))))
        eye_ry = max(1, int(height * float(box.get("eye_ry", defaults["eye_ry"]))))
        mouth_w = max(5, int(width * float(box.get("mouth_w", defaults["mouth_w"]))))
        mouth_h = max(2, int(height * float(box.get("mouth_h", defaults["mouth_h"]))))

        def canvas() -> Image.Image:
            return Image.new("RGBA", (width, height), (0, 0, 0, 0))

        created: List[str] = []

        targets = {
            "eyes_open_path": Path(artifacts.eyes_open_path),
            "eyes_closed_path": Path(artifacts.eyes_closed_path),
            "mouth_closed_path": Path(artifacts.mouth_closed_path),
            "mouth_open_path": Path(artifacts.mouth_open_path),
        }
        for target in targets.values():
            target.parent.mkdir(parents=True, exist_ok=True)

        if not targets["eyes_open_path"].exists():
            image = canvas()
            draw = ImageDraw.Draw(image)
            for x in (cx - eye_dx, cx + eye_dx):
                draw.ellipse(
                    (x - eye_rx, eye_y - eye_ry, x + eye_rx, eye_y + eye_ry),
                    fill=(24, 18, 14, 230),
                    outline=(255, 255, 255, 120),
                    width=max(1, eye_rx // 3),
                )
            image.save(targets["eyes_open_path"])
            created.append("eyes_open_path")

        if not targets["eyes_closed_path"].exists():
            image = canvas()
            draw = ImageDraw.Draw(image)
            line_w = max(1, int(height * 0.006))
            for x in (cx - eye_dx, cx + eye_dx):
                draw.line(
                    (x - eye_rx * 2, eye_y, x + eye_rx * 2, eye_y),
                    fill=(24, 18, 14, 230),
                    width=line_w,
                )
            image.save(targets["eyes_closed_path"])
            created.append("eyes_closed_path")

        if not targets["mouth_closed_path"].exists():
            image = canvas()
            draw = ImageDraw.Draw(image)
            line_w = max(1, int(height * 0.006))
            draw.line(
                (cx - mouth_w, mouth_y, cx + mouth_w, mouth_y),
                fill=(80, 28, 28, 230),
                width=line_w,
            )
            image.save(targets["mouth_closed_path"])
            created.append("mouth_closed_path")

        if not targets["mouth_open_path"].exists():
            image = canvas()
            draw = ImageDraw.Draw(image)
            draw.ellipse(
                (cx - mouth_w, mouth_y - mouth_h, cx + mouth_w, mouth_y + mouth_h),
                fill=(70, 16, 20, 230),
                outline=(210, 88, 82, 190),
                width=max(1, mouth_h // 2),
            )
            image.save(targets["mouth_open_path"])
            created.append("mouth_open_path")

        warnings = ["synthetic_face_sprite_fallback"] if created else []
        return self.write_layer_qc_report(artifacts, warnings=warnings)

    def run_mouth_cue_extraction(self, wav_path: str, output_path: str, fps: int = 30, timeout: int = 120) -> subprocess.CompletedProcess:
        tool = self.root / "tools" / "audio_rms_mouth_cues.py"
        if not tool.exists():
            raise FileNotFoundError(f"Mouth cue tool not found: {tool}")
        return subprocess.run(
            ["python", str(tool), "--wav", wav_path, "--out", output_path, "--fps", str(fps)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value).strip())
    return safe or "untitled"


def _copy_file(source_path: str, target_path: str) -> None:
    source = Path(source_path)
    target = Path(target_path)
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)


__all__ = [
    "ADVANCED_COMFYUI_TEMPLATE",
    "COMFYUI_TEMPLATE_REQUIRED_NODES",
    "CORE_COMFYUI_TEMPLATE",
    "DEFAULT_REQUIRED_MODEL_PATHS",
    "SUPPORTED_VIDEO_TOON_BACKENDS",
    "VideoToonArtifactPaths",
    "VideoToonCharacterCue",
    "VideoToonLocalWorkspace",
    "VideoToonSceneSpec",
    "VideoToonStackConfig",
    "build_scene_specs_from_production",
]
