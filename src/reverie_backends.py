"""Public backend profile catalog for Reverie Studio.

The profiles describe supported setup shapes without activating services or
reading credentials. They are intentionally declarative so the public demo,
doctor, and onboarding docs can agree on the same names.
"""

from __future__ import annotations

from copy import deepcopy


_BACKEND_PROFILES = [
    {
        "id": "local_dry_run",
        "name": "Local dry-run placeholders",
        "best_for": "Fresh clone validation and CI without AI models.",
        "image": {
            "provider": "placeholder",
            "mode": "plan_only",
            "requires": [],
        },
        "tts": {
            "provider": "placeholder",
            "mode": "plan_only",
            "requires": [],
        },
        "renderer": {
            "provider": "Remotion/FFmpeg",
            "mode": "plan_only",
            "requires": [],
        },
        "upload": {
            "provider": "YouTube Data API",
            "default_mode": "manual_private_review",
            "enabled_by_default": False,
        },
        "safety": {
            "requires_user_credentials": False,
            "calls_external_services_by_default": False,
            "creates_media_by_default": False,
        },
    },
    {
        "id": "local_comfyui_sovits",
        "name": "Local ComfyUI + GPT-SoVITS",
        "best_for": "Windows creator workstation with local image/video and cloned voice models.",
        "image": {
            "provider": "ComfyUI",
            "mode": "local_service",
            "requires": ["ComfyUI", "image/video checkpoints", "optional LoRA files"],
        },
        "tts": {
            "provider": "GPT-SoVITS",
            "mode": "local_service",
            "requires": ["GPT-SoVITS runtime", "user-provided voice data"],
        },
        "renderer": {
            "provider": "Remotion/FFmpeg",
            "mode": "local_process",
            "requires": ["Node.js", "FFmpeg"],
        },
        "upload": {
            "provider": "YouTube Data API",
            "default_mode": "manual_private_review",
            "enabled_by_default": False,
        },
        "safety": {
            "requires_user_credentials": False,
            "calls_external_services_by_default": False,
            "creates_media_by_default": False,
        },
    },
    {
        "id": "local_comfyui_supertonic",
        "name": "Local ComfyUI + Supertonic 3",
        "best_for": "Short-form production with a reference-free local voice pool.",
        "image": {
            "provider": "ComfyUI",
            "mode": "local_service",
            "requires": ["ComfyUI", "image/video checkpoints", "optional LoRA files"],
        },
        "tts": {
            "provider": "Supertonic 3",
            "mode": "local_onnx",
            "requires": ["Supertonic 3 package", "local voice preset selection"],
        },
        "renderer": {
            "provider": "Remotion/FFmpeg",
            "mode": "local_process",
            "requires": ["Node.js", "FFmpeg"],
        },
        "upload": {
            "provider": "YouTube Data API",
            "default_mode": "manual_private_review",
            "enabled_by_default": False,
        },
        "safety": {
            "requires_user_credentials": False,
            "calls_external_services_by_default": False,
            "creates_media_by_default": False,
        },
    },
    {
        "id": "cloud_assisted_private_review",
        "name": "Cloud-assisted draft with private review",
        "best_for": "Users who choose paid APIs for script, TTS, or upload after local dry-run passes.",
        "image": {
            "provider": "user-selected cloud or local backend",
            "mode": "explicit_opt_in",
            "requires": ["user-provided credentials"],
        },
        "tts": {
            "provider": "user-selected cloud or local backend",
            "mode": "explicit_opt_in",
            "requires": ["user-provided credentials"],
        },
        "renderer": {
            "provider": "Remotion/FFmpeg",
            "mode": "local_process",
            "requires": ["Node.js", "FFmpeg"],
        },
        "upload": {
            "provider": "YouTube Data API",
            "default_mode": "manual_private_review",
            "enabled_by_default": False,
        },
        "safety": {
            "requires_user_credentials": True,
            "calls_external_services_by_default": False,
            "creates_media_by_default": False,
        },
    },
]


def list_backend_profiles() -> list[dict]:
    """Return safe, copy-on-read backend profiles."""

    return deepcopy(_BACKEND_PROFILES)


def get_backend_profile(profile_id: str) -> dict:
    """Return one backend profile by id."""

    for profile in _BACKEND_PROFILES:
        if profile["id"] == profile_id:
            return deepcopy(profile)
    available = ", ".join(profile["id"] for profile in _BACKEND_PROFILES)
    raise ValueError(f"unknown backend profile '{profile_id}'. Available profiles: {available}")
