# src/modules_pro/tts_supertonic_adapter.py
"""Supertonic 3 adapter for Reverie's selectable TTS backend layer.

Supertonic is a reference-free local TTS engine, so this adapter deliberately
does not consume SoVITS weights or reference audio. It maps Reverie voice roles
onto Supertonic's built-in M1-M5/F1-F5 voice pool and keeps synthesis lazy so
the package/model download is only touched when the engine is selected.
"""
import importlib
import os
from typing import Any, Dict, Optional

try:
    from utils.logger import get_logger
    logger = get_logger("tts_supertonic")
except ImportError:
    import logging

    logger = logging.getLogger("tts_supertonic")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)

from .tts_engine import TTSConfig


BUILTIN_VOICES = {"M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"}

DEFAULT_ROLE_VOICE_MAP = {
    "narrator": "M1",
    "narration": "M1",
    "narrator_male": "M1",
    "narrator_female": "F1",
    "grandpa": "M2",
    "grandma": "F2",
    "old_man": "M2",
    "old_woman": "F2",
    "senior_male": "M2",
    "senior_female": "F2",
    "man": "M3",
    "middle_man": "M3",
    "woman": "F3",
    "middle_woman": "F3",
    "young_man": "M4",
    "young_woman": "F4",
    "child": "F5",
    "boy": "M5",
    "girl": "F5",
    "male_actor": "M4",
    "female_actor": "F4",
}


class SupertonicTTSAdapter:
    """TTSEngine-compatible adapter for Supertonic 3."""

    requires_reference_audio = False

    def __init__(self, config: TTSConfig):
        self.config = config
        self._tts = None
        self._tts_cls = None
        self._last_voice = None
        self._last_duration = None
        self._load_error: Optional[str] = None
        self._available = self._check_package_available()

    def _check_package_available(self) -> bool:
        try:
            module = importlib.import_module("supertonic")
            self._tts_cls = getattr(module, "TTS")
            return True
        except Exception as exc:
            self._load_error = str(exc)
            logger.warning("[Supertonic] supertonic package is not available: %s", exc)
            return False

    def _ensure_tts(self):
        if self._tts is not None:
            return self._tts
        if not self._available and not self._check_package_available():
            raise RuntimeError(f"supertonic package is not available: {self._load_error}")

        kwargs: Dict[str, Any] = {"auto_download": self.config.supertonic_auto_download}
        if self.config.supertonic_intra_op_threads > 0:
            kwargs["intra_op_num_threads"] = self.config.supertonic_intra_op_threads
        if self.config.supertonic_inter_op_threads > 0:
            kwargs["inter_op_num_threads"] = self.config.supertonic_inter_op_threads

        try:
            self._tts = self._tts_cls(**kwargs)
        except TypeError:
            # Older SDK builds may not accept thread kwargs yet.
            self._tts = self._tts_cls(auto_download=self.config.supertonic_auto_download)
        return self._tts

    @staticmethod
    def _normalize_voice_name(value: Optional[str], default: str = "M1") -> str:
        fallback = (default or "M1").strip().upper()
        if fallback not in BUILTIN_VOICES:
            fallback = "M1"
        voice = (value or default or "M1").strip().upper()
        return voice if voice in BUILTIN_VOICES else fallback

    def resolve_voice_name(self, voice_key: Optional[str] = None) -> str:
        merged_map = {**DEFAULT_ROLE_VOICE_MAP, **(self.config.supertonic_voice_map or {})}
        key = (voice_key or "").strip().lower()
        mapped = merged_map.get(key)
        if key and mapped is None:
            logger.warning(
                "[Supertonic] unknown voice key '%s', using default voice %s",
                key,
                self.config.supertonic_default_voice,
            )
        return self._normalize_voice_name(mapped, self.config.supertonic_default_voice)

    def synthesize(
        self,
        text: str,
        ref_audio: str = "",
        ref_text: str = "",
        output_path: str = "",
        language: str = "ko",
        **kwargs,
    ) -> bool:
        clean_text = (text or "").strip()
        if not clean_text:
            logger.warning("[Supertonic] empty text skipped")
            return False
        if not output_path:
            logger.error("[Supertonic] output_path is required")
            return False

        character = kwargs.get("character") or kwargs.get("voice_type") or kwargs.get("role")
        voice_name = self.resolve_voice_name(character)

        try:
            tts = self._ensure_tts()
            style = tts.get_voice_style(voice_name=voice_name)
            wav, duration = tts.synthesize(
                clean_text,
                voice_style=style,
                lang=language or self.config.language or "ko",
                total_steps=self.config.supertonic_total_steps,
                speed=self.config.supertonic_speed,
                max_chunk_length=self.config.supertonic_max_chunk_length,
                silence_duration=self.config.supertonic_silence_duration,
                verbose=False,
            )
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            tts.save_audio(wav, output_path)
            self._last_voice = voice_name
            self._last_duration = duration
            ok = os.path.exists(output_path) and os.path.getsize(output_path) > 44
            if ok:
                logger.info("[Supertonic] generated %s with voice=%s", os.path.basename(output_path), voice_name)
            return ok
        except Exception as exc:
            self._load_error = str(exc)
            logger.error("[Supertonic] synthesis failed: %s", exc)
            return False

    def load_voice(self, config: Dict[str, Any]) -> bool:
        if not config:
            return True
        voice = config.get("voice") or config.get("voice_name") or config.get("character")
        if voice:
            self.config.supertonic_default_voice = self._normalize_voice_name(
                voice, self.config.supertonic_default_voice
            )
        voice_map = config.get("voice_map")
        if isinstance(voice_map, dict):
            if not isinstance(self.config.supertonic_voice_map, dict):
                self.config.supertonic_voice_map = {}
            self.config.supertonic_voice_map.update(voice_map)
        return True

    def get_status(self) -> Dict[str, Any]:
        duration = self._last_duration
        try:
            duration = float(duration[0])
        except Exception:
            try:
                duration = float(duration)
            except Exception:
                duration = None

        return {
            "engine": "Supertonic 3",
            "available": self.is_available,
            "requires_reference_audio": self.requires_reference_audio,
            "default_voice": self.config.supertonic_default_voice,
            "last_voice": self._last_voice,
            "last_duration": duration,
            "load_error": self._load_error,
        }

    def cleanup(self) -> None:
        self._tts = None

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def engine_name(self) -> str:
        return "Supertonic 3"
