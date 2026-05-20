# src/gui/settings_manager.py
"""
GUI 설정 저장/불러오기 관리자
"""
import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class SettingsManager:
    """
    자막/썸네일 설정을 JSON 파일로 저장/불러오기
    """
    
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.settings_path = os.path.join(config_dir, "gui_settings.json")
        self.settings = self._load_settings()
    
    def _load_settings(self) -> Dict[str, Any]:
        """설정 파일 로드"""
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"설정 JSON 로드 실패: {e}")

        # 기본 설정
        return self._get_default_settings()
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """기본 설정 반환"""
        return {
            "subtitle": {
                "daily_life_toon": {
                    "hook": {
                        "y_ratio": 0.50,
                        "font_size": 76,
                        "color": "#F2C078",
                        "stroke": 8,
                        "shadow": 5
                    },
                    "narrator": {
                        "y_ratio": 0.80,
                        "font_size": 42,
                        "color": "#FFFFFF",
                        "stroke": 6,
                        "shadow": 4
                    },
                    "dialogue": {
                        "y_ratio": 0.84,
                        "font_size": 42,
                        "color": "#FFE0A8",
                        "stroke": 6,
                        "shadow": 4
                    }
                },
                "mystery_toon": {
                    "hook": {
                        "y_ratio": 0.50,
                        "font_size": 74,
                        "color": "#9BC1FF",
                        "stroke": 8,
                        "shadow": 5
                    },
                    "narrator": {
                        "y_ratio": 0.80,
                        "font_size": 40,
                        "color": "#FFFFFF",
                        "stroke": 6,
                        "shadow": 4
                    },
                    "dialogue": {
                        "y_ratio": 0.84,
                        "font_size": 40,
                        "color": "#CFE0FF",
                        "stroke": 6,
                        "shadow": 4
                    }
                }
            },
            "thumbnail": {
                "daily_life_toon": {
                    "top_text": {
                        "content": "일상툰",
                        "x": 640,
                        "y": 80,
                        "font_size": 70,
                        "color": "#F2C078"
                    },
                    "main_title": {
                        "content": "그날의 한마디",
                        "x": 640,
                        "y": 200,
                        "font_size": 118,
                        "color": "#FFFFFF",
                        "wrap_width": 10
                    },
                    "brightness": 0.55
                },
                "mystery_toon": {
                    "top_text": {
                        "content": "미스터리툰",
                        "x": 640,
                        "y": 80,
                        "font_size": 70,
                        "color": "#9BC1FF"
                    },
                    "main_title": {
                        "content": "복도 끝 불빛",
                        "x": 640,
                        "y": 200,
                        "font_size": 118,
                        "color": "#FFFFFF",
                        "wrap_width": 10
                    },
                    "brightness": 0.45
                }
            },
            "window": {
                "width": 1400,
                "height": 900
            }
        }
    
    def save(self):
        """현재 설정을 파일로 저장"""
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)
    
    def get_subtitle_settings(self, channel: str, mode: str = "") -> Dict[str, Any]:
        """자막 설정 가져오기"""
        key = channel or "daily_life_toon"
        if key in {"horror", "senior", "senior_touching", "senior_makjang", "senior_scam_alert"}:
            key = "daily_life_toon"
        
        return self.settings.get("subtitle", {}).get(key, {})
    
    def set_subtitle_settings(self, channel: str, mode: str, settings: Dict[str, Any]):
        """자막 설정 저장"""
        key = channel or "daily_life_toon"
        
        if "subtitle" not in self.settings:
            self.settings["subtitle"] = {}
        
        self.settings["subtitle"][key] = settings
        self.save()
    
    def get_thumbnail_settings(self, channel: str, mode: str = "") -> Dict[str, Any]:
        """썸네일 설정 가져오기"""
        key = channel or "daily_life_toon"
        if key in {"horror", "senior", "senior_touching", "senior_makjang", "senior_scam_alert"}:
            key = "daily_life_toon"
        
        return self.settings.get("thumbnail", {}).get(key, {})
    
    def set_thumbnail_settings(self, channel: str, mode: str, settings: Dict[str, Any]):
        """썸네일 설정 저장"""
        key = channel or "daily_life_toon"
        
        if "thumbnail" not in self.settings:
            self.settings["thumbnail"] = {}
        
        self.settings["thumbnail"][key] = settings
        self.save()
    
    def get_window_size(self) -> tuple:
        """창 크기 가져오기"""
        w = self.settings.get("window", {}).get("width", 1400)
        h = self.settings.get("window", {}).get("height", 900)
        return (w, h)
    
    def set_window_size(self, width: int, height: int):
        """창 크기 저장"""
        if "window" not in self.settings:
            self.settings["window"] = {}
        
        self.settings["window"]["width"] = width
        self.settings["window"]["height"] = height
        self.save()
    
    def reset_to_default(self):
        """설정 초기화"""
        self.settings = self._get_default_settings()
        self.save()

    # ============================================================
    # 백업/복구 기능
    # ============================================================
    def create_backup(self, backup_name: str = None) -> str:
        """
        현재 설정을 백업 파일로 저장

        Args:
            backup_name: 백업 파일명 (None이면 자동 생성)

        Returns:
            str: 생성된 백업 파일 경로
        """
        import shutil
        from datetime import datetime

        backup_dir = os.path.join(self.config_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        if not backup_name:
            backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        backup_path = os.path.join(backup_dir, f"{backup_name}.json")

        # 모든 설정 파일을 하나의 백업으로 통합
        backup_data = {
            "created_at": datetime.now().isoformat(),
            "gui_settings": self.settings,
            "branding": self._load_json_file(os.path.join(self.config_dir, "branding.json")),
            "api_settings": self._load_json_file(os.path.join(self.config_dir, "api_settings.json")),
        }

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        return backup_path

    def restore_backup(self, backup_path: str) -> tuple:
        """
        백업 파일에서 설정 복구

        Args:
            backup_path: 백업 파일 경로

        Returns:
            tuple: (성공 여부, 메시지)
        """
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                backup_data = json.load(f)

            # GUI 설정 복구
            if "gui_settings" in backup_data:
                self.settings = backup_data["gui_settings"]
                self.save()

            # 브랜딩 설정 복구
            if "branding" in backup_data and backup_data["branding"]:
                branding_path = os.path.join(self.config_dir, "branding.json")
                with open(branding_path, "w", encoding="utf-8") as f:
                    json.dump(backup_data["branding"], f, ensure_ascii=False, indent=2)

            # API 설정 복구
            if "api_settings" in backup_data and backup_data["api_settings"]:
                api_path = os.path.join(self.config_dir, "api_settings.json")
                with open(api_path, "w", encoding="utf-8") as f:
                    json.dump(backup_data["api_settings"], f, ensure_ascii=False, indent=2)

            return True, "설정이 성공적으로 복구되었습니다."

        except FileNotFoundError:
            return False, "백업 파일을 찾을 수 없습니다."
        except json.JSONDecodeError:
            return False, "백업 파일이 손상되었습니다."
        except Exception as e:
            return False, f"복구 중 오류 발생: {e}"

    def list_backups(self) -> list:
        """
        사용 가능한 백업 목록 반환

        Returns:
            list: 백업 파일 정보 리스트 [{path, name, created_at}, ...]
        """
        backup_dir = os.path.join(self.config_dir, "backups")

        if not os.path.exists(backup_dir):
            return []

        backups = []
        for filename in os.listdir(backup_dir):
            if filename.endswith(".json"):
                path = os.path.join(backup_dir, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    created_at = data.get("created_at", "알 수 없음")
                except Exception:
                    created_at = "알 수 없음"

                backups.append({
                    "path": path,
                    "name": filename[:-5],  # .json 제거
                    "created_at": created_at
                })

        # 최신순 정렬
        backups.sort(key=lambda x: x["created_at"], reverse=True)
        return backups

    def delete_backup(self, backup_path: str) -> tuple:
        """
        백업 파일 삭제

        Args:
            backup_path: 삭제할 백업 파일 경로

        Returns:
            tuple: (성공 여부, 메시지)
        """
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
                return True, "백업이 삭제되었습니다."
            return False, "백업 파일을 찾을 수 없습니다."
        except Exception as e:
            return False, f"삭제 중 오류 발생: {e}"

    def _load_json_file(self, path: str) -> dict:
        """JSON 파일 로드 (없으면 빈 딕셔너리)"""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"JSON 파일 로드 실패 ({path}): {e}")
        return {}

    # ============================================================
    # 썸네일/자막 스타일 프리셋 기능
    # ============================================================
    def get_thumbnail_presets(self) -> Dict[str, Any]:
        """저장된 썸네일 프리셋 목록 반환"""
        return self.settings.get("thumbnail_presets", {})

    def save_thumbnail_preset(self, name: str, preset_data: Dict[str, Any]):
        """썸네일 프리셋 저장"""
        if "thumbnail_presets" not in self.settings:
            self.settings["thumbnail_presets"] = {}

        # 데이터 복사 (참조 문제 방지)
        import copy
        self.settings["thumbnail_presets"][name] = copy.deepcopy(preset_data)
        self.save()

    def delete_thumbnail_preset(self, name: str):
        """썸네일 프리셋 삭제"""
        if "thumbnail_presets" in self.settings and name in self.settings["thumbnail_presets"]:
            del self.settings["thumbnail_presets"][name]
            self.save()

    def get_subtitle_presets(self) -> Dict[str, Any]:
        """저장된 자막 프리셋 목록 반환"""
        return self.settings.get("subtitle_presets", {})

    def save_subtitle_preset(self, name: str, preset_data: Dict[str, Any]):
        """자막 프리셋 저장"""
        if "subtitle_presets" not in self.settings:
            self.settings["subtitle_presets"] = {}

        import copy
        self.settings["subtitle_presets"][name] = copy.deepcopy(preset_data)
        self.save()

    def delete_subtitle_preset(self, name: str):
        """자막 프리셋 삭제"""
        if "subtitle_presets" in self.settings and name in self.settings["subtitle_presets"]:
            del self.settings["subtitle_presets"][name]
            self.save()

    # ============================================================
    # TTS 엔진 설정 (v56.5)
    # ============================================================
    def get_tts_settings(self) -> Dict[str, Any]:
        """
        TTS 엔진 설정 가져오기

        Returns:
            Dict: TTS 설정 {engine, fallback_enabled, qwen3_model}
        """
        return self.settings.get("tts", {
            "engine": "sovits",
            "fallback_enabled": True,
            "qwen3_model": "Qwen/Qwen3-TTS-12Hz-0.6B"
        })

    def set_tts_engine(self, engine: str):
        """
        TTS 엔진 변경

        Args:
            engine: "sovits" 또는 "supertonic"
        """
        normalized = (engine or "sovits").strip().lower()
        if normalized not in {"sovits", "supertonic"}:
            logger.warning("지원하지 않는 TTS 엔진 '%s', sovits로 저장합니다.", engine)
            normalized = "sovits"
        if "tts" not in self.settings:
            self.settings["tts"] = {}

        self.settings["tts"]["engine"] = normalized
        self.save()

    def set_tts_settings(self, settings: Dict[str, Any]):
        """
        TTS 설정 전체 저장

        Args:
            settings: TTS 설정 딕셔너리
        """
        self.settings["tts"] = settings
        self.save()

    def get_tts_engine(self) -> str:
        """현재 TTS 엔진 반환"""
        engine = self.settings.get("tts", {}).get("engine", "sovits")
        engine = (engine or "sovits").strip().lower()
        return engine if engine in {"sovits", "supertonic"} else "sovits"

    # ============================================================
    # v59: Visual Storytelling 설정
    # ============================================================

    def get_visual_storytelling_enabled(self) -> bool:
        """v59 Visual Storytelling 활성화 여부 반환"""
        return self.settings.get("visual_storytelling", {}).get("enabled", False)

    def set_visual_storytelling_enabled(self, enabled: bool):
        """v59 Visual Storytelling 활성화 설정"""
        if "visual_storytelling" not in self.settings:
            self.settings["visual_storytelling"] = {}
        self.settings["visual_storytelling"]["enabled"] = enabled
        self.save()

    def get_motiontoon_render_mode(self) -> str:
        """모션툰 렌더 모드 반환."""
        return self.settings.get("motiontoon", {}).get("render_mode", "videotoon_layered")

    def set_motiontoon_render_mode(self, render_mode: str):
        """모션툰 렌더 모드 저장."""
        if "motiontoon" not in self.settings:
            self.settings["motiontoon"] = {}
        self.settings["motiontoon"]["render_mode"] = render_mode
        self.save()

    def get_videotoon_local_enabled(self) -> bool:
        """Return whether the GUI has opted into local VideoToon generation."""
        return bool(self.settings.get("videotoon", {}).get("local_enabled", False))

    def set_videotoon_local_enabled(self, enabled: bool):
        """Persist the GUI opt-in for local VideoToon generation."""
        if "videotoon" not in self.settings:
            self.settings["videotoon"] = {}
        self.settings["videotoon"]["local_enabled"] = bool(enabled)
        self.save()

    def get_videotoon_generation_backend(self) -> str:
        """Return the preferred local VideoToon image backend."""
        backend = str(self.settings.get("videotoon", {}).get("generation_backend", "comfyui") or "comfyui")
        return backend if backend in {"comfyui", "sd_webui"} else "comfyui"

    def set_videotoon_generation_backend(self, backend: str):
        """Persist the local VideoToon image backend."""
        normalized = str(backend or "comfyui").strip().lower()
        if normalized not in {"comfyui", "sd_webui"}:
            normalized = "comfyui"
        if "videotoon" not in self.settings:
            self.settings["videotoon"] = {}
        self.settings["videotoon"]["generation_backend"] = normalized
        self.save()

    # ============================================================
    # 렌더링 엔진 설정 (v57.5 Remotion 전용 모드)
    # ============================================================
    # v57.5: GPU/CPU/AUTO 선택 제거 - Remotion이 유일한 렌더 엔진
    # v60.1.0: MoviePy 폴백 완전 제거

    def get_render_engine(self) -> str:
        """
        현재 렌더링 엔진 반환

        v57.5: 항상 "remotion" 반환 (Remotion 전용 모드)
        """
        return "remotion"

    # ============================================================
    # 채널별 스타일 설정 (v57.5 - Remotion CHANNEL_STYLES 연동)
    # ============================================================
    def get_channel_style(self, channel: str) -> Dict[str, Any]:
        """
        채널별 스타일 설정 가져오기 (Remotion 연동)

        Args:
            channel: "horror" | "senior"

        Returns:
            Dict: {bgm_volume, subtitle_size, speaker_size}
        """
        # v57.6.8: RemotionAssembler CHANNEL_STYLES_DEFAULT와 동기화
        defaults = {
            "horror": {
                "bgm_volume": 0.35,      # v57.6.8: 0.20 → 0.35 (소리 작음 이슈 해결)
                "subtitle_size": 36,
                "speaker_size": 28,
            },
            "senior": {
                "bgm_volume": 0.30,      # v57.6.8: 0.18 → 0.30 (소리 작음 이슈 해결)
                "subtitle_size": 42,
                "speaker_size": 32,
            },
            "default": {
                "bgm_volume": 0.25,      # v57.6.8 추가
                "subtitle_size": 36,
                "speaker_size": 28,
            },
        }

        # 사용자 커스텀 설정 우선, 없으면 기본값
        custom = self.settings.get("channel_styles", {}).get(channel, {})
        default = defaults.get(channel, defaults["senior"])

        return {
            "bgm_volume": custom.get("bgm_volume", default["bgm_volume"]),
            "subtitle_size": custom.get("subtitle_size", default["subtitle_size"]),
            "speaker_size": custom.get("speaker_size", default["speaker_size"]),
        }

    def set_channel_style(self, channel: str, style: Dict[str, Any]):
        """
        채널별 스타일 설정 저장

        Args:
            channel: "horror" | "senior"
            style: {bgm_volume, subtitle_size, speaker_size}
        """
        if "channel_styles" not in self.settings:
            self.settings["channel_styles"] = {}

        self.settings["channel_styles"][channel] = style
        self.save()

    # ============================================================
    # Auto-SFX 설정 (v57.6.5)
    # ============================================================
    def get_sfx_enabled(self) -> bool:
        """
        Auto-SFX 활성화 여부 가져오기

        Returns:
            bool: True면 효과음 자동 삽입 활성화
        """
        return self.settings.get("sfx_enabled", True)  # 기본값: 활성화

    def set_sfx_enabled(self, enabled: bool):
        """
        Auto-SFX 활성화 여부 설정

        Args:
            enabled: True면 효과음 자동 삽입 활성화
        """
        self.settings["sfx_enabled"] = enabled
        self.save()

    def get_sfx_settings(self) -> Dict[str, Any]:
        """
        Auto-SFX 상세 설정 가져오기

        Returns:
            Dict: {enabled, intensity, master_volume}
        """
        defaults = {
            "enabled": True,
            "intensity": "medium",  # low/medium/high
            "master_volume": 0.7,   # 효과음 볼륨 (0.0 ~ 1.0)
        }
        custom = self.settings.get("sfx_settings", {})
        return {
            "enabled": custom.get("enabled", defaults["enabled"]),
            "intensity": custom.get("intensity", defaults["intensity"]),
            "master_volume": custom.get("master_volume", defaults["master_volume"]),
        }

    def set_sfx_settings(self, settings: Dict[str, Any]):
        """
        Auto-SFX 상세 설정 저장

        Args:
            settings: {enabled, intensity, master_volume}
        """
        self.settings["sfx_settings"] = settings
        self.save()

    # v57.6.8: FFmpeg 경로 설정 추가
    def get_ffmpeg_path(self) -> str:
        """외부 FFmpeg 경로 가져오기"""
        return self.settings.get("ffmpeg_path", "")

    def set_ffmpeg_path(self, path: str):
        """외부 FFmpeg 경로 저장"""
        self.settings["ffmpeg_path"] = path
        self.save()
