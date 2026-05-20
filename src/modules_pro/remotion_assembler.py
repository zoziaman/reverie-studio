"""
Remotion Assembler for Reverie Studio
MoviePy를 대체하는 Remotion 기반 영상 조립 모듈
v1.0.0 - PoC

기존 video_assembler.py의 MoviePy 로직을 Remotion으로 대체
"""

import json
import subprocess
import sys
import re
from dataclasses import asdict, is_dataclass
# v62.17: Windows 콘솔 창 깜빡임 방지
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
def _hidden_startupinfo():
    if sys.platform == 'win32':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None
import os
import time
import wave
from collections import Counter
try:
    import audioop
except Exception:  # pragma: no cover - Python 3.13+ compatibility guard
    audioop = None
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Callable
from dataclasses import dataclass
import logging
import shutil
import threading
from utils.runtime_utils import get_ffprobe_path
import queue as _queue  # v62.21: C-1 Remotion timeout 비동기 stdout 읽기
from utils.motiontoon import build_scene_motion_directive, normalize_motiontoon_config
from utils.layered_cutout import (
    build_layered_cutout_assets,
    load_layered_cutout_assets,
    load_layered_cutout_metadata,
)

try:
    from utils.logger import get_logger
    logger = get_logger("remotion_assembler")
except ImportError:
    logger = logging.getLogger(__name__)


_WALKING_VARIANT_RE = re.compile(r"(?:^|[_-])walking(?:[_-]|$)", re.IGNORECASE)


def get_audio_duration_ms(audio_path: str) -> int:
    """
    오디오 파일의 길이를 밀리초로 반환
    WAV 파일은 wave 모듈로, 그 외는 ffprobe로 측정
    """
    path = Path(audio_path)
    if not path.exists():
        return 0

    try:
        # WAV 파일은 빠르게 처리
        if path.suffix.lower() == '.wav':
            with wave.open(str(path), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration_sec = frames / float(rate)
                # v58.3.14: int() → round()로 정밀도 향상
                return round(duration_sec * 1000)

        # v60.1.0: config 기반 ffprobe 경로 사용 (시스템 PATH 4.3.2 방지)
        ffprobe_cmd = get_ffprobe_path()
        result = subprocess.run(
            [ffprobe_cmd, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            capture_output=True, text=True,
            creationflags=_NO_WINDOW,
            startupinfo=_hidden_startupinfo(),
        )
        if result.returncode == 0 and result.stdout.strip():
            # v58.3.14: int() → round()로 정밀도 향상
            return round(float(result.stdout.strip()) * 1000)
    except Exception as e:
        logger.warning(f"[RemotionAssembler] 오디오 길이 측정 실패: {audio_path}, {e}")

    return 0


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    """Pydantic/dataclass 설정 객체를 dict로 정규화한다."""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return value.dict()
        except Exception:
            pass
    return {}

# Remotion 프로젝트 경로
REMOTION_PROJECT_PATH = Path(__file__).parent.parent.parent / "remotion-poc"


# v57.5: 채널별 스타일 기본값 (GUI 설정으로 오버라이드 가능)
# v57.6.8: BGM 볼륨 전체 증가 (소리 작음 이슈 해결)
CHANNEL_STYLES_DEFAULT = {
    "horror": {
        "bgm_volume": 0.35,      # v57.6.8: 0.20 → 0.35
        "subtitle_size": 36,     # 자막 크기
        "speaker_size": 28,      # 화자명 크기
    },
    "senior": {
        "bgm_volume": 0.30,      # v57.6.8: 0.18 → 0.30
        "subtitle_size": 42,     # 시니어: 자막 크게 (가독성)
        "speaker_size": 32,      # 화자명도 크게
    },
    "default": {
        "bgm_volume": 0.25,      # v57.6.8: 0.15 → 0.25
        "subtitle_size": 36,
        "speaker_size": 28,
    },
}

# v57.5: 하위 호환성을 위한 별칭
CHANNEL_STYLES = CHANNEL_STYLES_DEFAULT


def get_channel_style(
    channel: str,
    config_dir: str = None,
    style_getter: Callable[[str], dict] = None
) -> dict:
    """
    채널별 스타일 설정 반환

    v57.5: GUI SettingsManager와 연동
    v57.6.8: 의존성 주입 패턴 적용 (레이어 분리)
    - style_getter 콜백이 주어지면 콜백 사용 (우선)
    - config_dir이 주어지면 GUI 설정 사용 (하위호환)
    - 없으면 기본값 사용

    Args:
        channel: "horror" | "senior"
        config_dir: 설정 디렉토리 (하위호환, deprecated)
        style_getter: GUI에서 주입한 스타일 가져오기 콜백 (channel) -> dict

    Returns:
        dict: {bgm_volume, subtitle_size, speaker_size}
    """
    # v57.6.8: 콜백 우선 (레이어 분리)
    if style_getter:
        try:
            return style_getter(channel)
        except Exception as e:
            logging.getLogger(__name__).debug(f"[RemotionAssembler] style_getter 실패: {e}")

    try:
        from config.pack_config import ACTIVE_PACK, get_subtitle_style

        if getattr(ACTIVE_PACK, "is_loaded", False):
            subtitle_style = get_subtitle_style()
            font_size = int(getattr(subtitle_style, "font_size", 0) or 0)
            if font_size > 0:
                base_style = CHANNEL_STYLES_DEFAULT.get(channel, CHANNEL_STYLES_DEFAULT["default"]).copy()
                base_style["subtitle_size"] = font_size
                base_style["speaker_size"] = max(24, int(font_size * 0.76))
                return base_style
    except Exception as e:
        logging.getLogger(__name__).debug(f"[RemotionAssembler] pack subtitle style fallback 실패: {e}")

    # 하위호환: config_dir 직접 사용 (deprecated)
    if config_dir:
        try:
            # lazy import - 호출 시점에만 (하위호환용)
            from gui.settings_manager import SettingsManager
            sm = SettingsManager(config_dir)
            return sm.get_channel_style(channel)
        except ImportError:
            pass  # settings_manager 미설치 환경 — 기본값 사용
        except Exception as e:
            logging.getLogger(__name__).debug(f"[RemotionAssembler] SettingsManager 채널 스타일 조회 실패: {e}")

    # 기본값 사용
    return CHANNEL_STYLES_DEFAULT.get(channel, CHANNEL_STYLES_DEFAULT["default"])


# v57.4: 화자별 색상 매핑 (config.SENIOR_COLORS 기반)
SPEAKER_COLORS = {
    # 역할명 (영어)
    "narrator": "#FFFFFF",
    "narration": "#FFFFFF",
    "grandma": "#DDA0DD",
    "grandpa": "#F0E68C",
    "man": "#87CEEB",
    "woman": "#FFB6C1",
    "ghost": "#FF0000",
    # 역할명 (한글)
    "나레이터": "#FFFFFF",
    "나레이션": "#FFFFFF",
    "할머니": "#DDA0DD",
    "할아버지": "#F0E68C",
    "남자": "#87CEEB",
    "여자": "#FFB6C1",
    # v59: 공포 캐릭터 (빨간색)
    "귀신": "#FF0000",
    "유령": "#FF0000",
    "혼령": "#FF0000",
    # 기본값
    "default": "#FFD700",
}


def get_speaker_color(speaker: str) -> str:
    """화자 이름에 따른 색상 반환"""
    lower = speaker.lower().strip()

    # 직접 매핑
    if lower in SPEAKER_COLORS:
        return SPEAKER_COLORS[lower]
    if speaker in SPEAKER_COLORS:
        return SPEAKER_COLORS[speaker]

    # 키워드 기반 추론
    if "할머니" in speaker or "어머니" in speaker or "엄마" in speaker:
        return "#DDA0DD"  # 핑크/보라
    if "할아버지" in speaker or "아버지" in speaker or "아빠" in speaker:
        return "#F0E68C"  # 골드/카키
    if "나레이" in speaker:
        return "#FFFFFF"  # 흰색

    return SPEAKER_COLORS["default"]


@dataclass
class SceneData:
    """씬 데이터 (기존 MediaFactory 호환)"""
    image_path: str
    audio_path: str
    text: str
    speaker: str
    speaker_color: str  # v57.4: 화자 색상
    duration_ms: int  # 밀리초
    start_ms: int = -1  # v58.3.12: 절대 시작 시간 (밀리초), -1=미설정(누적 사용)
    voice_type: str = ""
    background_path: str = ""
    foreground_path: str = ""
    head_path: str = ""
    body_path: str = ""
    left_arm_path: str = ""
    right_arm_path: str = ""
    eyes_open_path: str = ""
    eyes_closed_path: str = ""
    mouth_closed_path: str = ""
    mouth_open_path: str = ""
    mouth_cues_path: str = ""
    motion_data: Optional[Dict[str, Any]] = None


class RemotionAssembler:
    """
    Remotion 기반 영상 조립기

    기존 MediaFactory._assemble_main()을 대체

    사용법:
        assembler = RemotionAssembler()
        assembler.add_scene(image_path, audio_path, "대사", "나레이터", duration_ms)
        assembler.set_bgm(bgm_path, volume=0.15)
        result = assembler.render(output_path)
    """

    def __init__(
        self,
        fps: int = 30,
        width: int = 1920,
        height: int = 1080,
        concurrency: int = 6,
        channel: str = "senior",  # v57.4: 채널별 스타일
        style_getter: Callable[[str], dict] = None,  # v57.6.8: 의존성 주입
        show_ai_disclosure: bool = True,  # v58.1: AI 제작 표기 (AI법 준수)
        ai_disclosure_duration: float = 3.0,  # v58.1: AI 제작 표기 지속시간 (초)
        tts_volume: float = 2.5,  # v58.3.7: TTS 볼륨 2.5배 (5~10% 볼륨으로도 잘 들리도록)
        # v59: 비주얼 스토리텔링 설정
        visual_effects: Optional[Dict[str, Any]] = None,  # v59: 비주얼 이펙트 (vignette, colorFilter, transition)
        subtitle_style: Optional[Dict[str, Any]] = None,  # v59: 자막 스타일
    ):
        self.fps = fps
        self.width = width
        self.height = height
        self.concurrency = concurrency
        self.channel = channel
        self.scenes: List[SceneData] = []
        self.bgm_path: Optional[str] = None
        self.full_audio_path: Optional[str] = None  # v58.3.3: 전체 TTS 오디오 경로
        self.hook_data: Optional[Dict[str, Any]] = None  # v58.4.0: Hook 데이터
        self.sfx_cues: List[Dict[str, Any]] = []  # v59.3.5: SFX 효과음 큐 (Remotion 통합)
        self.visual_effects: Optional[Dict[str, Any]] = visual_effects  # v59
        self.subtitle_style: Optional[Dict[str, Any]] = subtitle_style  # v59
        self.motiontoon_config: Dict[str, Any] = normalize_motiontoon_config(None)

        # v57.4: 채널별 스타일 적용
        # v57.6.8: 의존성 주입으로 GUI 직접 참조 제거
        style = get_channel_style(channel, style_getter=style_getter)
        self.bgm_volume: float = style["bgm_volume"]
        self.subtitle_size: int = style["subtitle_size"]
        self.speaker_size: int = style["speaker_size"]

        # v58.1: AI 제작 표기 설정 (AI법 준수)
        self.show_ai_disclosure: bool = show_ai_disclosure
        self.ai_disclosure_duration: float = ai_disclosure_duration
        self.tts_volume: float = tts_volume

        # Remotion 프로젝트 확인 (v60.1.0: MoviePy 폴백 제거)
        if not REMOTION_PROJECT_PATH.exists():
            raise FileNotFoundError(
                f"Remotion 프로젝트 없음: {REMOTION_PROJECT_PATH}. "
                "remotion-poc/ 디렉토리가 설치되어 있는지 확인하세요."
            )
        logger.info(f"[RemotionAssembler] Remotion 프로젝트 경로: {REMOTION_PROJECT_PATH}")

    def clear(self):
        """씬 초기화"""
        self.scenes.clear()
        self.bgm_path = None
        self.full_audio_path = None  # v58.3.3
        self.hook_data = None  # v58.4.0
        self.sfx_cues = []  # v59.3.5
        # v59: 비주얼 이펙트/자막 스타일은 clear 시 유지 (인스턴스 설정)

    def _copy_background_plate_with_variant(self, src: Path, dst: Path, scene_index: int) -> None:
        """Copy a reusable background plate with subtle per-scene camera variation."""
        try:
            from PIL import Image, ImageEnhance

            image = Image.open(src).convert("RGB")
            width, height = image.size
            zoom = 1.0 + (scene_index % 5) * 0.008
            if zoom > 1.0:
                resized = image.resize((int(width * zoom), int(height * zoom)), Image.Resampling.LANCZOS)
                max_x = max(0, resized.width - width)
                max_y = max(0, resized.height - height)
                offset_x = int(max_x * ((scene_index * 37) % 100) / 100)
                offset_y = int(max_y * ((scene_index * 53) % 100) / 100)
                image = resized.crop((offset_x, offset_y, offset_x + width, offset_y + height))

            brightness = 0.985 + (scene_index % 7) * 0.006
            contrast = 0.99 + (scene_index % 4) * 0.006
            image = ImageEnhance.Brightness(image).enhance(brightness)
            image = ImageEnhance.Contrast(image).enhance(contrast)
            image.save(dst)
        except Exception:
            shutil.copy2(src, dst)

    def set_motiontoon_config(self, config: Optional[Dict[str, Any]] = None):
        """팩 기반 모션툰 설정을 적용한다."""
        self.motiontoon_config = normalize_motiontoon_config(config)
        if self.motiontoon_config.get("enabled"):
            logger.info(
                "[Motiontoon] 설정 적용: mode=%s, shorts_vertical_ready=%s",
                self.motiontoon_config.get("mode", "screen_space"),
                self.motiontoon_config.get("shorts_vertical_ready", False),
            )

    # v59: 비주얼 이펙트 설정
    def set_visual_effects(
        self,
        config: Optional[Dict[str, Any]] = None,
        # 하위 호환성을 위한 개별 파라미터 (deprecated)
        vignette: str = None,
        color_filter: str = None,
        transition: str = None,
        transition_duration: int = None,
    ):
        """
        v59: 비주얼 이펙트 설정

        Args:
            config: v59 dict 구조 (VisualDirector.get_visual_effects_config() 반환값)
                {
                    'vignette': {'enabled': bool, 'intensity': float, 'color': str},
                    'colorFilter': {'enabled': bool, 'type': str, 'intensity': float},
                    'kenBurns': {'enabled': bool, 'zoomRange': [float, float], 'panEnabled': bool},
                }
            vignette: (deprecated) 비네트 타입 문자열
            color_filter: (deprecated) 색상 필터 타입 문자열
            transition: (deprecated) 장면 전환 타입
            transition_duration: (deprecated) 전환 시간 (프레임)
        """
        if config and isinstance(config, dict):
            # v59 신규 dict 구조
            self.visual_effects = config
            vignette_info = config.get('vignette', {})
            color_info = config.get('colorFilter', {})
            logger.info(f"[v59] 비주얼 이펙트 설정 (dict): vignette={vignette_info.get('enabled')}, colorFilter={color_info.get('type')}")
        else:
            # 하위 호환: 개별 파라미터
            self.visual_effects = {
                "vignette": vignette or "none",
                "colorFilter": color_filter or "none",
                "transition": transition or "fade",
                "transitionDuration": transition_duration or 15,
            }
            logger.info(f"[v59] 비주얼 이펙트 설정 (legacy): vignette={vignette}, filter={color_filter}")

    # v59: 자막 스타일 설정
    def set_subtitle_style(
        self,
        config: Optional[Dict[str, Any]] = None,
        # 하위 호환성을 위한 개별 파라미터 (deprecated)
        font_family: str = None,
        font_size: int = None,
        speaker_font_size: int = None,
        background_color: str = None,
        text_color: str = None,
        speaker_colors: Optional[Dict[str, str]] = None,
        position: str = None,
        style: str = None,
    ):
        """
        v59: 자막 스타일 설정

        Args:
            config: v59 dict 구조 (VisualDirector.get_subtitle_style_config() 반환값)
                {
                    'fontFamily': str, 'fontSize': int, 'fontWeight': str,
                    'textColor': str, 'strokeColor': str, 'strokeWidth': int,
                    'shadowColor': str, 'shadowBlur': int,
                    'backgroundEnabled': bool, 'backgroundColor': str,
                    'backgroundPadding': int, 'backgroundRadius': int,
                    'position': str, 'marginBottom': int, 'textAlign': str,
                    'animationIn': str, 'animationOut': str, 'animationDuration': float,
                }
            font_family: (deprecated) 폰트
            font_size: (deprecated) 자막 크기
            speaker_font_size: (deprecated) 화자명 크기
            background_color: (deprecated) 배경색
            text_color: (deprecated) 텍스트색
            speaker_colors: (deprecated) 화자별 색상 매핑
            position: (deprecated) 자막 위치
            style: (deprecated) 스타일 타입
        """
        if config and isinstance(config, dict):
            # v59 신규 dict 구조
            self.subtitle_style = config
            logger.info(f"[v59] 자막 스타일 설정 (dict): font={config.get('fontFamily')}, position={config.get('position')}")
        else:
            # 하위 호환: 개별 파라미터
            self.subtitle_style = {
                "fontFamily": font_family or "Malgun Gothic, sans-serif",
                "fontSize": font_size or 36,
                "speakerFontSize": speaker_font_size or 28,
                "backgroundColor": background_color or "rgba(0,0,0,0.6)",
                "textColor": text_color or "#FFFFFF",
                "speakerColors": speaker_colors or {},
                "position": position or "bottom",
                "style": style or "default",
            }
            logger.info(f"[v59] 자막 스타일 설정 (legacy): style={style}, position={position}")

    def _convert_visual_effects_to_props(self, ve: Dict[str, Any]) -> Dict[str, Any]:
        """
        v59: VisualDirector dict 구조 → RadioDrama.tsx 호환 형식으로 변환

        입력 (VisualDirector.get_visual_effects_config):
            {
                'vignette': {'enabled': True, 'intensity': 0.3, 'color': '#000000'},
                'colorFilter': {'enabled': True, 'type': 'sepia', 'intensity': 0.5},
                'kenBurns': {'enabled': True, 'zoomRange': [1.0, 1.15], 'panEnabled': True},
            }

        출력 (RadioDrama.tsx VisualEffectsConfig):
            {
                'vignette': 'medium',  # none | light | medium | heavy | horror
                'colorFilter': 'sepia',  # none | sepia | cold | warm | noir | vintage | horror_green
                'transition': 'fade',
                'transitionDuration': 15,
            }
        """
        ve = _coerce_mapping(ve)
        if not ve:
            return {}

        # 이미 legacy 형식이면 그대로 반환
        if 'vignette' in ve and isinstance(ve.get('vignette'), str):
            return ve

        # v59.5.15b: 팩 transition 값 사용 (하드코딩 제거)
        # 팩 TransitionStyle → Remotion TransitionType 매핑
        TRANSITION_MAP = {
            'crossfade': 'fade', 'fade': 'fade', 'fade_black': 'fade',
            'fade_white': 'dissolve', 'dissolve': 'dissolve',
            'slide': 'wipe_left', 'wipe_left': 'wipe_left', 'wipe_right': 'wipe_right',
            'zoom': 'dissolve', 'zoom_blur': 'dissolve',
            'cut': 'cut',
        }
        trans_config = ve.get('transition', {})
        if isinstance(trans_config, dict) and trans_config:
            pack_trans = trans_config.get('default', 'crossfade')
            pack_dur = trans_config.get('duration', 0.5)
            mapped_trans = TRANSITION_MAP.get(pack_trans, 'fade')
            mapped_dur = max(1, int(pack_dur * 30))  # 초 → 프레임 (30fps)
        else:
            mapped_trans = 'fade'
            mapped_dur = 15

        result = {
            'vignette': 'none',
            'colorFilter': 'none',
            'transition': mapped_trans,
            'transitionDuration': mapped_dur,
        }

        # vignette 변환: intensity → 문자열
        vignette_config = ve.get('vignette', {})
        if isinstance(vignette_config, dict) and vignette_config.get('enabled'):
            intensity = vignette_config.get('intensity', 0.3)
            if intensity >= 0.7:
                result['vignette'] = 'horror'
            elif intensity >= 0.5:
                result['vignette'] = 'heavy'
            elif intensity >= 0.3:
                result['vignette'] = 'medium'
            else:
                result['vignette'] = 'light'

        # colorFilter 변환: type 추출
        # v59.5.15: "horror" → "horror_green" 매핑 추가 (3-way mismatch 해결)
        COLOR_FILTER_MAP = {
            'sepia': 'sepia', 'cold': 'cold', 'warm': 'warm',
            'noir': 'noir', 'vintage': 'vintage', 'horror_green': 'horror_green',
            'horror': 'horror_green',  # 팩 JSON에서 "horror" → Remotion "horror_green"
            'drama': 'warm',           # drama 팩 → warm 필터 매핑
            'cool': 'cold',            # "cool" → "cold" 동의어
        }
        color_config = ve.get('colorFilter', {})
        if isinstance(color_config, dict) and color_config.get('enabled'):
            filter_type = color_config.get('type', 'none')
            mapped = COLOR_FILTER_MAP.get(filter_type)
            if mapped:
                result['colorFilter'] = mapped

        return result

    def _convert_subtitle_style_to_props(self, ss: Dict[str, Any]) -> Dict[str, Any]:
        """
        v59: VisualDirector dict 구조 → RadioDrama.tsx 호환 형식으로 변환

        입력 (VisualDirector.get_subtitle_style_config):
            {
                'fontFamily': 'Noto Sans KR', 'fontSize': 48, 'fontWeight': 'bold',
                'textColor': '#FFFFFF', 'strokeColor': '#000000', 'strokeWidth': 3,
                'position': 'bottom', ...
            }

        출력 (RadioDrama.tsx SubtitleStyleConfig):
            {
                'fontFamily': 'Noto Sans KR', 'fontSize': 48,
                'speakerFontSize': 28, 'backgroundColor': 'rgba(0,0,0,0.6)',
                'textColor': '#FFFFFF', 'speakerColors': {},
                'position': 'bottom', 'style': 'default',
            }
        """
        ss = _coerce_mapping(ss)
        if not ss:
            return {}

        # v59 dict → RadioDrama.tsx 형식
        return {
            'fontFamily': ss.get('fontFamily', 'Malgun Gothic, sans-serif'),
            'fontSize': ss.get('fontSize', 36),
            'speakerFontSize': ss.get('fontSize', 36) - 8,  # 자막보다 8px 작게
            'backgroundColor': ss.get('backgroundColor', 'rgba(0,0,0,0.6)'),
            'backgroundPadding': ss.get('backgroundPadding'),
            'backgroundRadius': ss.get('backgroundRadius'),
            'marginBottom': ss.get('marginBottom'),
            'textColor': ss.get('textColor', '#FFFFFF'),
            'speakerColors': ss.get('speakerColors', {}),  # v59.5.15: 팩 speaker_colors 전달
            'position': ss.get('position', 'bottom'),
            'style': 'default',  # NOTE: 스타일 매핑 미사용 (Remotion 측 미처리)
        }

    # v58.4.0: Hook 설정 (재조립 제거, Remotion 통합)
    def set_hook(
        self,
        topic: str,
        channel: str = "daily_life_toon",
        mode: str = "touching",
        duration_sec: float = 4.0,
        hook_style=None,
    ):
        """
        Hook 설정 - 영상 맨 앞에 주제 타이포그래피 표시

        Args:
            topic: 주제 텍스트 (예: "구름포에서 사라진 아이들")
            channel: 채널 타입 ("horror" / "senior")
            mode: 모드 ("touching" / "makjang")
            duration_sec: hook 길이 (초, 기본 4초)
            hook_style: v59.1.6 팩의 PackHookStyle 객체 (있으면 하드코딩 대신 사용)
        """
        # v59.1.6: 팩의 hook_style이 있으면 우선 사용
        if hook_style:
            if hasattr(hook_style, 'top_label'):
                # PackHookStyle 객체
                top_label = hook_style.top_label or "【 이야기 】"
                top_color = hook_style.top_color or "#FFFFFF"
                main_color = hook_style.main_color or "#FFFFFF"
                bg = hook_style.bg_color or [0, 0, 0]
                duration_sec = hook_style.duration or duration_sec
            elif isinstance(hook_style, dict):
                # dict 형태
                top_label = hook_style.get('top_label', "【 이야기 】")
                top_color = hook_style.get('top_color', "#FFFFFF")
                main_color = hook_style.get('main_color', "#FFFFFF")
                bg = hook_style.get('bg_color', [0, 0, 0])
                duration_sec = hook_style.get('duration', duration_sec)
            else:
                top_label = "【 이야기 】"
                top_color = "#FFFFFF"
                main_color = "#FFFFFF"
                bg = [0, 0, 0]

            # bg_color 변환: [R,G,B] → hex string
            if isinstance(bg, (list, tuple)) and len(bg) == 3:
                bg_color = f"#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}"
            else:
                bg_color = str(bg) if bg else "#000000"

            logger.info(f"[RemotionAssembler] Hook 설정 (팩 기반): top_label={top_label}")
        else:
            # v60: 팩에서 hook_style 로딩 시도 (장르 하드코딩 제거)
            try:
                from config.pack_config import ACTIVE_PACK as _AP_HOOK, PACK_CONFIG_AVAILABLE as _PC_HOOK
                if _PC_HOOK and _AP_HOOK.is_loaded and hasattr(_AP_HOOK, 'hook_style'):
                    hs = _AP_HOOK.hook_style
                    top_label = getattr(hs, 'top_label', '') or "【 이야기 】"
                    top_color = getattr(hs, 'top_color', '') or "#87CEEB"
                    main_color = getattr(hs, 'main_color', '') or "#FFFFFF"
                    bg = getattr(hs, 'bg_color', '') or "#0A0A14"
                    # v61.1: bg_color가 [R,G,B] 리스트일 수 있으므로 hex 변환 (방어 코드)
                    if isinstance(bg, (list, tuple)) and len(bg) == 3:
                        bg_color = f"#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}"
                    else:
                        bg_color = str(bg) if bg else "#0A0A14"
                else:
                    top_label = "【 이야기 】"
                    top_color = "#87CEEB"
                    main_color = "#FFFFFF"
                    bg_color = "#0A0A14"
            except ImportError:
                top_label = "【 이야기 】"
                top_color = "#87CEEB"
                main_color = "#FFFFFF"
                bg_color = "#0A0A14"

        self.hook_data = {
            "topLabel": top_label,
            "topColor": top_color,
            "mainText": topic,
            "mainColor": main_color,
            "bgColor": bg_color,
            "durationFrames": round(duration_sec * self.fps),
        }
        logger.info(f"[RemotionAssembler] Hook 설정: {topic[:30]}... ({duration_sec}초)")

    def set_full_audio(self, audio_path: str):
        """
        v58.3.3: 전체 TTS 오디오 파일 설정 (MoviePy 제거용)

        개별 세그먼트 대신 full.wav를 통째로 사용.
        Remotion에서 영상 처음부터 끝까지 재생됨.
        """
        self.full_audio_path = audio_path
        logger.info(f"[RemotionAssembler] 전체 오디오 설정: {audio_path}")

    def add_scene(
        self,
        image_path: str,
        audio_path: str,
        text: str,
        speaker: str,
        duration_ms: Optional[int] = None,
        voice_type: Optional[str] = None,  # v57.6.3: 색상 결정용
        start_ms: Optional[int] = None,  # v58.3.12: 절대 시작 시간 (누적 오차 방지)
        *,
        background_path: str = "",
        foreground_path: str = "",
        head_path: str = "",
        body_path: str = "",
        left_arm_path: str = "",
        right_arm_path: str = "",
        eyes_open_path: str = "",
        eyes_closed_path: str = "",
        mouth_closed_path: str = "",
        mouth_open_path: str = "",
        mouth_cues_path: str = "",
        motion_data: Optional[Dict[str, Any]] = None,
    ):
        """
        씬 추가 (기존 MediaFactory 호환)

        Args:
            duration_ms: 밀리초. None이면 오디오 길이로 자동 측정
            voice_type: 음성 타입 (색상 결정용, 없으면 speaker로 추론)
            start_ms: v58.3.12 - 절대 시작 시간 (밀리초). TTS와 자막 동기화 필수!
        """
        # duration 자동 측정
        if duration_ms is None or duration_ms <= 0:
            if audio_path:
                duration_ms = get_audio_duration_ms(audio_path)
                if duration_ms <= 0:
                    duration_ms = 3000  # 기본값 3초
            else:
                duration_ms = 3000

        # v57.6.3: 색상은 voice_type 우선, 없으면 speaker로 추론
        color_key = voice_type if voice_type else speaker
        self.scenes.append(SceneData(
            image_path=image_path,
            audio_path=audio_path,
            text=text,
            speaker=speaker,
            speaker_color=get_speaker_color(color_key),  # v57.6.3: voice_type 기반 색상
            duration_ms=duration_ms,
            start_ms=start_ms if start_ms is not None else -1,  # v58.3.12: -1=미설정
            voice_type=voice_type or "",
            background_path=background_path or "",
            foreground_path=foreground_path or "",
            head_path=head_path or "",
            body_path=body_path or "",
            left_arm_path=left_arm_path or "",
            right_arm_path=right_arm_path or "",
            eyes_open_path=eyes_open_path or "",
            eyes_closed_path=eyes_closed_path or "",
            mouth_closed_path=mouth_closed_path or "",
            mouth_open_path=mouth_open_path or "",
            mouth_cues_path=mouth_cues_path or "",
            motion_data=dict(motion_data or {}) if motion_data else None,
        ))

    @staticmethod
    def _augment_motion_from_asset_path(motion: Dict[str, Any], image_path: str) -> Dict[str, Any]:
        augmented = dict(motion or {})
        image_name = Path(str(image_path or "")).stem
        if not image_name:
            return augmented

        primitives = list(augmented.get("primitives") or [])
        if _WALKING_VARIANT_RE.search(image_name) and "walk_drift" not in primitives:
            primitives.append("walk_drift")
            augmented["primitives"] = primitives
            augmented.setdefault("pose_hint", "walking")
        return augmented

    def add_scenes_from_segments(
        self,
        image_paths: List[str],
        audio_paths: List[str],
        texts: List[str],
        speakers: List[str],
        durations_ms: List[int],
    ):
        """여러 씬 일괄 추가"""
        for img, audio, text, speaker, dur in zip(
            image_paths, audio_paths, texts, speakers, durations_ms
        ):
            self.add_scene(img, audio, text, speaker, dur)

    def set_bgm(self, path: str, volume: float = None):
        """BGM 설정. volume=None이면 채널별 기본값(생성자 L241에서 설정)을 유지."""
        self.bgm_path = path
        if volume is not None:
            self.bgm_volume = volume
        # v61.1-fix: volume 미전달 시 self.bgm_volume 유지 (채널별 값 보존)

    def set_sfx_cues(self, cues: List[Dict[str, Any]]):
        """
        v59.3.5: SFX 효과음 큐 설정 (Remotion 통합)

        Args:
            cues: SFX 큐 리스트
                [{
                    'sfx_path': str,          # SFX 파일 절대경로
                    'timestamp_ms': int,       # 삽입 시점 (밀리초)
                    'volume': float,           # 볼륨 (0.0~1.0)
                    'duration_ms': int,        # 지속 시간 (밀리초, 0이면 파일 전체)
                    'fade_in_ms': int,         # 페이드 인 (밀리초)
                    'fade_out_ms': int,        # 페이드 아웃 (밀리초)
                }, ...]
        """
        self.sfx_cues = cues or []
        logger.info(f"[v59.3.5] SFX 큐 설정: {len(self.sfx_cues)}개")

    def _ms_to_frames(self, ms: int) -> int:
        """밀리초를 프레임으로 변환 (v58.3.14: round 사용)"""
        return round(ms * self.fps / 1000)

    @staticmethod
    def _load_mouth_cues(cues_path: str) -> List[Dict[str, Any]]:
        if not str(cues_path or "").strip():
            return []
        path = Path(str(cues_path or ""))
        if not path.exists() or path.is_dir():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cues = data.get("cues", data if isinstance(data, list) else [])
            if not isinstance(cues, list):
                return []
            normalized: List[Dict[str, Any]] = []
            for cue in cues:
                if not isinstance(cue, dict) or cue.get("frame") is None:
                    continue
                normalized.append(
                    {
                        "frame": int(cue.get("frame", 0) or 0),
                        "mouth": int(cue.get("mouth", 0) or 0),
                    }
                )
            return normalized
        except Exception as exc:
            logger.warning(f"[RemotionAssembler] mouth cue 로드 실패: {path} ({exc})")
            return []

    @staticmethod
    def _build_mouth_cues_from_audio(audio_path: str, duration_frames: int, fps: int) -> List[Dict[str, Any]]:
        """Create lightweight mouth-open cues from a scene WAV when explicit cues are absent."""
        if audioop is None:
            return []
        path = Path(str(audio_path or ""))
        if not path.exists() or path.suffix.lower() != ".wav":
            return []
        try:
            with wave.open(str(path), "rb") as wf:
                sample_rate = max(1, int(wf.getframerate() or 1))
                sample_width = int(wf.getsampwidth() or 2)
                frames_per_video_frame = max(1, int(sample_rate / max(1, fps)))
                rms_values: List[int] = []
                for _frame_index in range(max(1, int(duration_frames or 1))):
                    chunk = wf.readframes(frames_per_video_frame)
                    if not chunk:
                        break
                    rms_values.append(int(audioop.rms(chunk, sample_width)))
            if not rms_values:
                return []
            peak = max(rms_values)
            if peak <= 0:
                return [{"frame": 0, "mouth": 0}]
            threshold = max(90, peak * 0.18)
            cues: List[Dict[str, Any]] = []
            last_state: Optional[int] = None
            for frame_index, rms in enumerate(rms_values):
                speaking = rms >= threshold
                state = 1 if speaking and ((frame_index // 3) % 2 == 0) else 0
                if state != last_state:
                    cues.append({"frame": frame_index, "mouth": state})
                    last_state = state
            if not cues or cues[0]["frame"] != 0:
                cues.insert(0, {"frame": 0, "mouth": 0})
            return cues
        except Exception as exc:
            logger.debug(f"[RemotionAssembler] mouth cue 자동 생성 스킵: {path} ({exc})")
            return []

    @staticmethod
    def _build_mouth_cues_from_text(text: str, duration_frames: int) -> List[Dict[str, Any]]:
        """Create deterministic fallback mouth cues when full-audio mode hides per-scene WAV paths."""
        if not str(text or "").strip() or duration_frames <= 3:
            return [{"frame": 0, "mouth": 0}]

        active_frames = max(3, min(duration_frames - 1, int(duration_frames * 0.86)))
        cues: List[Dict[str, Any]] = [{"frame": 0, "mouth": 0}]
        last_state = 0
        for frame in range(2, active_frames, 3):
            state = 1 if ((frame // 3) % 2 == 0) else 0
            if state != last_state:
                cues.append({"frame": frame, "mouth": state})
                last_state = state
        if cues[-1]["mouth"] != 0:
            cues.append({"frame": active_frames, "mouth": 0})
        return cues

    @staticmethod
    def _resolve_public_asset(path: str) -> Optional[Path]:
        rel = str(path or "").strip().replace("\\", "/")
        if not rel:
            return None
        candidate = (REMOTION_PROJECT_PATH / "public" / rel).resolve()
        try:
            public_root = (REMOTION_PROJECT_PATH / "public").resolve()
            if public_root not in candidate.parents and candidate != public_root:
                return None
        except Exception:
            return None
        return candidate if candidate.exists() and candidate.is_file() else None

    @staticmethod
    def _average_image_hash(path: Optional[Path]) -> Optional[str]:
        if not path:
            return None
        try:
            from PIL import Image
            with Image.open(path) as img:
                gray = img.convert("L").resize((8, 8))
                pixels = list(gray.getdata())
            avg = sum(pixels) / max(1, len(pixels))
            bits = "".join("1" if px >= avg else "0" for px in pixels)
            return f"{int(bits, 2):016x}"
        except Exception:
            return None

    def _build_render_qc_report(self, props: Dict[str, Any]) -> Dict[str, Any]:
        """Collect render-time QC signals so video-toon regressions are visible before review."""
        images = list(props.get("images") or [])
        subtitles = list(props.get("subtitles") or [])
        sfx_cues = list(props.get("sfxCues") or [])
        issues: List[Dict[str, Any]] = []

        def add_issue(code: str, severity: str, message: str, indices: Optional[List[int]] = None):
            issues.append({
                "code": code,
                "severity": severity,
                "message": message,
                "indices": indices or [],
            })

        empty_subtitles = [
            idx for idx, sub in enumerate(subtitles)
            if not str(sub.get("text") or "").strip()
        ]
        hidden_subtitles = [
            idx for idx, sub in enumerate(subtitles)
            if str(dict(sub.get("motion", {}) or {}).get("subtitle_mode") or "").strip().lower() == "hidden"
        ]
        ribbon_subtitles = [
            idx for idx, sub in enumerate(subtitles)
            if str(dict(sub.get("motion", {}) or {}).get("subtitle_mode") or "").strip().lower() == "ribbon_only"
        ]
        long_subtitles = []
        for idx, sub in enumerate(subtitles):
            lines = [line for line in str(sub.get("text") or "").splitlines() if line.strip()]
            if not lines:
                continue
            if len(lines) > 3 or max(len(line) for line in lines) > 42:
                long_subtitles.append(idx)
        overlapping_subtitles: List[int] = []
        sorted_subtitles = sorted(
            enumerate(subtitles),
            key=lambda item: int(item[1].get("startFrame") or 0),
        )
        for (idx, sub), (_next_idx, next_sub) in zip(sorted_subtitles, sorted_subtitles[1:]):
            end_frame = int(sub.get("startFrame") or 0) + int(sub.get("durationFrames") or 0)
            next_start = int(next_sub.get("startFrame") or 0)
            if end_frame > next_start:
                overlapping_subtitles.append(idx)

        if len(subtitles) < len(images):
            add_issue(
                "subtitle_count_short",
                "error",
                f"Subtitles are fewer than image scenes: {len(subtitles)}/{len(images)}.",
            )
        if empty_subtitles:
            add_issue("subtitle_empty", "error", "Empty subtitle entries exist.", empty_subtitles)
        if hidden_subtitles:
            add_issue("subtitle_hidden", "error", "Spoken subtitles are hidden.", hidden_subtitles)
        if overlapping_subtitles:
            add_issue("subtitle_overlap", "error", "Subtitle frame ranges overlap.", overlapping_subtitles)
        if long_subtitles:
            add_issue(
                "subtitle_long",
                "warn",
                "Some subtitles are long enough to risk covering too much of the frame.",
                long_subtitles[:10],
            )

        simple_sprite_indices = [
            idx for idx, image in enumerate(images)
            if str(dict(image.get("motion", {}) or {}).get("character_layer_mode") or "").strip().lower() == "simple_sprite"
        ]
        missing_foreground = [
            idx for idx in simple_sprite_indices
            if not str(images[idx].get("foregroundPath") or "").strip()
        ]
        missing_background = [
            idx for idx in simple_sprite_indices
            if not str(images[idx].get("backgroundPath") or "").strip()
        ]
        missing_mouth_assets = [
            idx for idx in simple_sprite_indices
            if not str(images[idx].get("mouthClosedPath") or "").strip()
            or not str(images[idx].get("mouthOpenPath") or "").strip()
        ]
        missing_mouth_cues = [
            idx for idx in simple_sprite_indices
            if str(images[idx].get("mouthClosedPath") or "").strip()
            and str(images[idx].get("mouthOpenPath") or "").strip()
            and not images[idx].get("mouthCues")
        ]
        if missing_foreground:
            add_issue("sprite_foreground_missing", "error", "Simple-sprite scenes are missing foreground character layers.", missing_foreground)
        if missing_background:
            add_issue("sprite_background_missing", "warn", "Simple-sprite scenes are missing dedicated background layers.", missing_background)
        if missing_mouth_assets:
            add_issue("mouth_assets_missing", "warn", "Simple-sprite scenes are missing mouth-open/closed assets.", missing_mouth_assets)
        if missing_mouth_cues:
            add_issue("mouth_cues_missing", "warn", "Mouth assets exist but no mouth cues were generated.", missing_mouth_cues)
        synthetic_face_overlays = [
            idx for idx in simple_sprite_indices
            if str(dict(images[idx].get("motion", {}) or {}).get("face_part_source") or "").strip().lower()
            in {"synthetic_overlay", "generated_overlay", "code_generated"}
        ]
        native_face_rigs = [
            idx for idx in simple_sprite_indices
            if str(dict(images[idx].get("motion", {}) or {}).get("face_part_source") or "").strip().lower()
            in {"native_golden_cast", "native_expression_sprite", "provided_face_parts", "native_face_parts"}
            and str(images[idx].get("mouthClosedPath") or "").strip()
            and str(images[idx].get("mouthOpenPath") or "").strip()
        ]
        sprite_layout_keys = set()
        acting_pose_keys = set()
        shot_size_keys = set()
        foreground_keys = set()
        def _rounded_motion_float(motion: Dict[str, Any], key: str) -> float:
            try:
                return round(float(motion.get(key, 0) or 0), 2)
            except Exception:
                return 0.0

        for idx in simple_sprite_indices:
            image = images[idx]
            motion = dict(image.get("motion", {}) or {})
            foreground = str(image.get("foregroundPath") or "").strip()
            if foreground:
                foreground_keys.add(foreground)
            layout_key = (
                _rounded_motion_float(motion, "sprite_center_x"),
                _rounded_motion_float(motion, "sprite_center_y"),
                _rounded_motion_float(motion, "sprite_width_ratio"),
                _rounded_motion_float(motion, "sprite_height_ratio"),
            )
            if any(layout_key):
                sprite_layout_keys.add(layout_key)
            acting_pose = str(motion.get("acting_pose") or "").strip().lower()
            if acting_pose:
                acting_pose_keys.add(acting_pose)
            shot_size = str(motion.get("shot_size") or "").strip().lower()
            if shot_size:
                shot_size_keys.add(shot_size)
        if synthetic_face_overlays:
            add_issue(
                "synthetic_face_overlay",
                "error",
                "Code-generated sticker face overlays are not allowed for production VideoToon renders.",
                synthetic_face_overlays,
            )
        if len(simple_sprite_indices) >= 6 and len(sprite_layout_keys) < 3:
            add_issue(
                "sprite_blocking_low_variety",
                "warn",
                f"Character blocking variety is low: {len(sprite_layout_keys)} layouts for {len(simple_sprite_indices)} simple-sprite scenes.",
            )
        if len(simple_sprite_indices) >= 6 and len(acting_pose_keys) < 3:
            add_issue(
                "acting_pose_low_variety",
                "warn",
                f"Acting pose variety is low: {len(acting_pose_keys)} poses for {len(simple_sprite_indices)} simple-sprite scenes.",
            )
        if len(simple_sprite_indices) >= 6 and len(foreground_keys) < 2:
            add_issue(
                "character_sprite_low_variety",
                "warn",
                "All simple-sprite scenes appear to reuse one foreground sprite; use expression/shot variants.",
            )

        bg_hashes: List[str] = []
        for image in images:
            bg_path = str(image.get("backgroundPath") or image.get("path") or "")
            digest = self._average_image_hash(self._resolve_public_asset(bg_path))
            if digest:
                bg_hashes.append(digest)
        bg_counts = Counter(bg_hashes)
        top_reuse_count = max(bg_counts.values()) if bg_counts else 0
        unique_backgrounds = len(bg_counts)
        unique_ratio = unique_backgrounds / max(1, len(bg_hashes))
        if len(bg_hashes) >= 8 and unique_ratio < 0.35:
            add_issue(
                "background_repetition_high",
                "warn",
                f"Background visual variety is low: {unique_backgrounds}/{len(bg_hashes)} unique hashes.",
            )
        if top_reuse_count >= max(6, int(len(bg_hashes) * 0.45)):
            add_issue(
                "background_top_reuse_high",
                "warn",
                f"One background appears reused {top_reuse_count} times.",
            )

        if not props.get("bgmPath"):
            add_issue("bgm_missing", "warn", "No BGM was attached to render props.")
        if not sfx_cues:
            add_issue("sfx_missing", "warn", "No SFX cues were attached to render props.")

        error_count = sum(1 for issue in issues if issue["severity"] == "error")
        warn_count = sum(1 for issue in issues if issue["severity"] == "warn")
        score = 100
        score -= error_count * 18
        score -= warn_count * 6
        score -= min(20, len(long_subtitles) * 2)
        score = max(0, min(100, score))

        return {
            "status": "fail" if error_count else ("warn" if warn_count else "pass"),
            "score": score,
            "sceneCount": len(images),
            "subtitleCount": len(subtitles),
            "simpleSpriteSceneCount": len(simple_sprite_indices),
            "nativeFaceRigCount": len(native_face_rigs),
            "syntheticFaceOverlayCount": len(synthetic_face_overlays),
            "spriteLayoutVarietyCount": len(sprite_layout_keys),
            "actingPoseVarietyCount": len(acting_pose_keys),
            "shotSizeVarietyCount": len(shot_size_keys),
            "foregroundSpriteVarietyCount": len(foreground_keys),
            "hiddenSubtitleCount": len(hidden_subtitles),
            "ribbonSubtitleCount": len(ribbon_subtitles),
            "longSubtitleCount": len(long_subtitles),
            "backgroundHashCount": len(bg_hashes),
            "uniqueBackgroundCount": unique_backgrounds,
            "backgroundUniqueRatio": round(unique_ratio, 3),
            "topBackgroundReuseCount": top_reuse_count,
            "bgmAttached": bool(props.get("bgmPath")),
            "sfxCueCount": len(sfx_cues),
            "issues": issues,
        }

    def _write_render_qc_report(self, report: Dict[str, Any]) -> None:
        try:
            qc_file = REMOTION_PROJECT_PATH / "render_qc_report.json"
            with open(qc_file, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            if report.get("status") == "fail":
                logger.error(f"[RenderQC] FAIL score={report.get('score')} issues={len(report.get('issues') or [])} ({qc_file})")
            elif report.get("status") == "warn":
                logger.warning(f"[RenderQC] WARN score={report.get('score')} issues={len(report.get('issues') or [])} ({qc_file})")
            else:
                logger.info(f"[RenderQC] PASS score={report.get('score')} ({qc_file})")
        except Exception as exc:
            logger.warning(f"[RenderQC] 리포트 저장 실패: {exc}")

    @staticmethod
    def _collect_existing_scene_layered_assets(scene: SceneData) -> Dict[str, str]:
        assets: Dict[str, str] = {}
        for key in (
            "background_path",
            "foreground_path",
            "head_path",
            "body_path",
            "left_arm_path",
            "right_arm_path",
            "eyes_open_path",
            "eyes_closed_path",
            "mouth_closed_path",
            "mouth_open_path",
        ):
            value = str(getattr(scene, key, "") or "")
            if value and Path(value).exists():
                assets[key] = value
        return assets

    @staticmethod
    def _load_prebuilt_simple_sprite_assets(scene: SceneData, src_img: Path) -> Dict[str, str]:
        assets = RemotionAssembler._collect_existing_scene_layered_assets(scene)
        bundle_dir = src_img.parent / "_motiontoon"
        stem = src_img.stem
        for key, suffix in (
            ("background_path", "__bg.png"),
            ("foreground_path", "__fg.png"),
            ("head_path", "__head.png"),
            ("body_path", "__body.png"),
            ("left_arm_path", "__left_arm.png"),
            ("right_arm_path", "__right_arm.png"),
            ("eyes_open_path", "__eyes_open.png"),
            ("eyes_closed_path", "__eyes_closed.png"),
            ("mouth_closed_path", "__mouth_closed.png"),
            ("mouth_open_path", "__mouth_open.png"),
        ):
            bundle_path = bundle_dir / f"{stem}{suffix}"
            if bundle_path.exists():
                assets[key] = str(bundle_path)
        if assets.get("background_path"):
            allowed_face_sources = {"native_golden_cast", "native_expression_sprite", "provided_face_parts", "native_face_parts"}
            motion = dict(getattr(scene, "motion_data", {}) or {})
            face_part_source = str(motion.get("face_part_source", "") or "").strip().lower()
            try:
                meta = load_layered_cutout_metadata(str(src_img), min_strength=0.65)
                rig = dict(meta.get("rig", {}) or {}) if isinstance(meta, dict) else {}
                face_part_source = face_part_source or str(rig.get("face_part_source", "") or "").strip().lower()
            except Exception:
                face_part_source = face_part_source or ""
            if face_part_source not in allowed_face_sources:
                for key in ("eyes_open_path", "eyes_closed_path", "mouth_closed_path", "mouth_open_path"):
                    assets[key] = ""
            return assets
        return {}

    def _copy_assets_to_public(
        self,
    ) -> Tuple[
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        List[str],
        Optional[str],
    ]:
        """
        에셋을 Remotion public 폴더로 복사
        Returns: (image_paths, audio_paths, background_paths, foreground_paths, head_paths, body_paths, left_arm_paths, right_arm_paths, eyes_open_paths, eyes_closed_paths, mouth_closed_paths, mouth_open_paths, bgm_path)
        """
        public_dir = REMOTION_PROJECT_PATH / "public"
        images_dir = public_dir / "render_images"
        layered_bg_dir = public_dir / "render_layered_bg"
        layered_fg_dir = public_dir / "render_layered_fg"
        layered_head_dir = public_dir / "render_layered_head"
        layered_body_dir = public_dir / "render_layered_body"
        layered_left_arm_dir = public_dir / "render_layered_left_arm"
        layered_right_arm_dir = public_dir / "render_layered_right_arm"
        layered_eyes_open_dir = public_dir / "render_layered_eyes_open"
        layered_eyes_closed_dir = public_dir / "render_layered_eyes_closed"
        layered_mouth_closed_dir = public_dir / "render_layered_mouth_closed"
        layered_mouth_open_dir = public_dir / "render_layered_mouth_open"
        audio_dir = public_dir / "render_audio"

        # 기존 렌더링 폴더 정리
        if images_dir.exists():
            shutil.rmtree(images_dir, ignore_errors=True)
        if layered_bg_dir.exists():
            shutil.rmtree(layered_bg_dir, ignore_errors=True)
        if layered_fg_dir.exists():
            shutil.rmtree(layered_fg_dir, ignore_errors=True)
        if layered_head_dir.exists():
            shutil.rmtree(layered_head_dir, ignore_errors=True)
        if layered_body_dir.exists():
            shutil.rmtree(layered_body_dir, ignore_errors=True)
        if layered_left_arm_dir.exists():
            shutil.rmtree(layered_left_arm_dir, ignore_errors=True)
        if layered_right_arm_dir.exists():
            shutil.rmtree(layered_right_arm_dir, ignore_errors=True)
        if layered_eyes_open_dir.exists():
            shutil.rmtree(layered_eyes_open_dir, ignore_errors=True)
        if layered_eyes_closed_dir.exists():
            shutil.rmtree(layered_eyes_closed_dir, ignore_errors=True)
        if layered_mouth_closed_dir.exists():
            shutil.rmtree(layered_mouth_closed_dir, ignore_errors=True)
        if layered_mouth_open_dir.exists():
            shutil.rmtree(layered_mouth_open_dir, ignore_errors=True)
        if audio_dir.exists():
            shutil.rmtree(audio_dir, ignore_errors=True)

        images_dir.mkdir(parents=True, exist_ok=True)
        layered_bg_dir.mkdir(parents=True, exist_ok=True)
        layered_fg_dir.mkdir(parents=True, exist_ok=True)
        layered_head_dir.mkdir(parents=True, exist_ok=True)
        layered_body_dir.mkdir(parents=True, exist_ok=True)
        layered_left_arm_dir.mkdir(parents=True, exist_ok=True)
        layered_right_arm_dir.mkdir(parents=True, exist_ok=True)
        layered_eyes_open_dir.mkdir(parents=True, exist_ok=True)
        layered_eyes_closed_dir.mkdir(parents=True, exist_ok=True)
        layered_mouth_closed_dir.mkdir(parents=True, exist_ok=True)
        layered_mouth_open_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        image_paths = []
        audio_paths = []
        background_paths = []
        foreground_paths = []
        head_paths = []
        body_paths = []
        left_arm_paths = []
        right_arm_paths = []
        eyes_open_paths = []
        eyes_closed_paths = []
        mouth_closed_paths = []
        mouth_open_paths = []

        for i, scene in enumerate(self.scenes):
            duration_frames = self._ms_to_frames(scene.duration_ms)
            motion = dict(scene.motion_data or {})
            if not motion:
                motion = build_scene_motion_directive(
                    text=scene.text,
                    speaker=scene.speaker,
                    duration_frames=duration_frames,
                    config=self.motiontoon_config,
                )

            # 이미지 복사
            src_img = Path(scene.image_path)
            if src_img.exists():
                motion = self._augment_motion_from_asset_path(motion, str(src_img))
                cutout_meta = {}
                simple_sprite_mode = (
                    str(motion.get("character_layer_mode") or "").strip().lower() == "simple_sprite"
                )
                simple_sprite_assets = {}
                if motion.get("use_layered_cutout"):
                    if simple_sprite_mode:
                        simple_sprite_assets = self._load_prebuilt_simple_sprite_assets(scene, src_img)
                    cutout_meta = load_layered_cutout_metadata(
                        str(src_img),
                        min_strength=float(motion.get("layered_cutout_strength") or 0.65),
                    )
                    if (
                        simple_sprite_mode
                        and not simple_sprite_assets
                        and (
                            not isinstance(cutout_meta, dict)
                            or not all(
                                key in dict(cutout_meta.get("rig", {}) or {})
                                for key in ("sprite_center_x", "sprite_center_y", "sprite_width_ratio", "sprite_height_ratio")
                            )
                            or float(dict(cutout_meta.get("rig", {}) or {}).get("sprite_width_ratio", 1.0) or 1.0) >= 0.88
                            or float(dict(cutout_meta.get("rig", {}) or {}).get("sprite_height_ratio", 1.0) or 1.0) >= 0.96
                        )
                    ):
                        cutout_assets = build_layered_cutout_assets(
                            str(src_img),
                            overlay_kind=str(motion.get("overlay_kind") or ""),
                            strength=float(motion.get("layered_cutout_strength") or 0.65),
                            force=True,
                            rig_overrides={
                                "character_layer_mode": motion.get("character_layer_mode"),
                                "cast_slot": motion.get("cast_slot"),
                                "character_id_hint": motion.get("character_id_hint"),
                                "overlay_theme": motion.get("overlay_theme"),
                                "emotion_hint": motion.get("dominant_emotion"),
                            },
                        )
                        if cutout_assets:
                            cutout_meta = load_layered_cutout_metadata(
                                str(src_img),
                                overlay_kind=str(motion.get("overlay_kind") or ""),
                                min_strength=float(motion.get("layered_cutout_strength") or 0.65),
                            )
                    rig = cutout_meta.get("rig", {}) if isinstance(cutout_meta, dict) else {}
                    if isinstance(rig, dict):
                        for key in (
                            "face_anchor_x",
                            "face_anchor_y",
                            "face_scale",
                            "bob_strength",
                            "cast_slot",
                            "character_id_hint",
                            "sprite_center_x",
                            "sprite_center_y",
                            "sprite_width_ratio",
                            "sprite_height_ratio",
                            "sprite_kind",
                            "shot_size",
                            "acting_pose",
                            "sprite_enter_px",
                            "sprite_parallax_px",
                            "sprite_lean_deg",
                            "sprite_breathe_px",
                            "sprite_focus_scale",
                            "face_part_source",
                            "allow_synthetic_face_parts",
                        ):
                            if key in rig and rig.get(key) is not None:
                                motion[key] = rig.get(key)
                dst_img = images_dir / f"{i:04d}{src_img.suffix}"
                shutil.copy2(src_img, dst_img)
                image_paths.append(f"render_images/{dst_img.name}")

                if motion.get("use_layered_cutout"):
                    layered_assets = dict(simple_sprite_assets or {})
                    if not layered_assets:
                        layered_assets = load_layered_cutout_assets(
                            str(src_img),
                            overlay_kind=str(motion.get("overlay_kind") or ""),
                            min_strength=float(motion.get("layered_cutout_strength") or 0.65),
                        )
                    if not layered_assets:
                        layered_assets = build_layered_cutout_assets(
                            str(src_img),
                            overlay_kind=str(motion.get("overlay_kind") or ""),
                            strength=float(motion.get("layered_cutout_strength") or 0.65),
                        )
                    if str(motion.get("character_layer_mode") or "").strip().lower() == "simple_sprite":
                        face_source = str(motion.get("face_part_source") or "").strip().lower()
                        if face_source not in {"native_golden_cast", "native_expression_sprite", "provided_face_parts", "native_face_parts"}:
                            for key in ("eyes_open_path", "eyes_closed_path", "mouth_closed_path", "mouth_open_path"):
                                layered_assets[key] = ""
                    scene.background_path = layered_assets.get("background_path", "")
                    scene.foreground_path = layered_assets.get("foreground_path", "")
                    scene.head_path = layered_assets.get("head_path", "")
                    scene.body_path = layered_assets.get("body_path", "")
                    scene.left_arm_path = layered_assets.get("left_arm_path", "")
                    scene.right_arm_path = layered_assets.get("right_arm_path", "")
                    scene.eyes_open_path = layered_assets.get("eyes_open_path", "")
                    scene.eyes_closed_path = layered_assets.get("eyes_closed_path", "")
                    scene.mouth_closed_path = layered_assets.get("mouth_closed_path", "")
                    scene.mouth_open_path = layered_assets.get("mouth_open_path", "")
                    if str(motion.get("character_layer_mode") or "").strip().lower() == "simple_sprite":
                        scene.head_path = ""
                        scene.body_path = ""
                        scene.left_arm_path = ""
                        scene.right_arm_path = ""
                else:
                    scene.background_path = ""
                    scene.foreground_path = ""
                    scene.head_path = ""
                    scene.body_path = ""
                    scene.left_arm_path = ""
                    scene.right_arm_path = ""
                    scene.eyes_open_path = ""
                    scene.eyes_closed_path = ""
                    scene.mouth_closed_path = ""
                    scene.mouth_open_path = ""
                scene.motion_data = dict(motion)
            else:
                logger.warning(f"[RemotionAssembler] 이미지 없음: {src_img}")
                image_paths.append("")
                scene.background_path = ""
                scene.foreground_path = ""
                scene.head_path = ""
                scene.body_path = ""
                scene.left_arm_path = ""
                scene.right_arm_path = ""
                scene.eyes_open_path = ""
                scene.eyes_closed_path = ""
                scene.mouth_closed_path = ""
                scene.mouth_open_path = ""
                scene.motion_data = dict(motion)

            if scene.background_path and Path(scene.background_path).exists():
                src_bg = Path(scene.background_path)
                dst_bg = layered_bg_dir / f"{i:04d}{src_bg.suffix}"
                self._copy_background_plate_with_variant(src_bg, dst_bg, i)
                background_paths.append(f"render_layered_bg/{dst_bg.name}")
            else:
                background_paths.append("")

            if scene.foreground_path and Path(scene.foreground_path).exists():
                src_fg = Path(scene.foreground_path)
                dst_fg = layered_fg_dir / f"{i:04d}{src_fg.suffix}"
                shutil.copy2(src_fg, dst_fg)
                foreground_paths.append(f"render_layered_fg/{dst_fg.name}")
            else:
                foreground_paths.append("")

            if scene.head_path and Path(scene.head_path).exists():
                src_head = Path(scene.head_path)
                dst_head = layered_head_dir / f"{i:04d}{src_head.suffix}"
                shutil.copy2(src_head, dst_head)
                head_paths.append(f"render_layered_head/{dst_head.name}")
            else:
                head_paths.append("")

            if scene.body_path and Path(scene.body_path).exists():
                src_body = Path(scene.body_path)
                dst_body = layered_body_dir / f"{i:04d}{src_body.suffix}"
                shutil.copy2(src_body, dst_body)
                body_paths.append(f"render_layered_body/{dst_body.name}")
            else:
                body_paths.append("")

            if scene.left_arm_path and Path(scene.left_arm_path).exists():
                src_left_arm = Path(scene.left_arm_path)
                dst_left_arm = layered_left_arm_dir / f"{i:04d}{src_left_arm.suffix}"
                shutil.copy2(src_left_arm, dst_left_arm)
                left_arm_paths.append(f"render_layered_left_arm/{dst_left_arm.name}")
            else:
                left_arm_paths.append("")

            if scene.right_arm_path and Path(scene.right_arm_path).exists():
                src_right_arm = Path(scene.right_arm_path)
                dst_right_arm = layered_right_arm_dir / f"{i:04d}{src_right_arm.suffix}"
                shutil.copy2(src_right_arm, dst_right_arm)
                right_arm_paths.append(f"render_layered_right_arm/{dst_right_arm.name}")
            else:
                right_arm_paths.append("")

            if scene.eyes_open_path and Path(scene.eyes_open_path).exists():
                src_eyes_open = Path(scene.eyes_open_path)
                dst_eyes_open = layered_eyes_open_dir / f"{i:04d}{src_eyes_open.suffix}"
                shutil.copy2(src_eyes_open, dst_eyes_open)
                eyes_open_paths.append(f"render_layered_eyes_open/{dst_eyes_open.name}")
            else:
                eyes_open_paths.append("")

            if scene.eyes_closed_path and Path(scene.eyes_closed_path).exists():
                src_eyes_closed = Path(scene.eyes_closed_path)
                dst_eyes_closed = layered_eyes_closed_dir / f"{i:04d}{src_eyes_closed.suffix}"
                shutil.copy2(src_eyes_closed, dst_eyes_closed)
                eyes_closed_paths.append(f"render_layered_eyes_closed/{dst_eyes_closed.name}")
            else:
                eyes_closed_paths.append("")

            if scene.mouth_closed_path and Path(scene.mouth_closed_path).exists():
                src_mouth_closed = Path(scene.mouth_closed_path)
                dst_mouth_closed = layered_mouth_closed_dir / f"{i:04d}{src_mouth_closed.suffix}"
                shutil.copy2(src_mouth_closed, dst_mouth_closed)
                mouth_closed_paths.append(f"render_layered_mouth_closed/{dst_mouth_closed.name}")
            else:
                mouth_closed_paths.append("")

            if scene.mouth_open_path and Path(scene.mouth_open_path).exists():
                src_mouth_open = Path(scene.mouth_open_path)
                dst_mouth_open = layered_mouth_open_dir / f"{i:04d}{src_mouth_open.suffix}"
                shutil.copy2(src_mouth_open, dst_mouth_open)
                mouth_open_paths.append(f"render_layered_mouth_open/{dst_mouth_open.name}")
            else:
                mouth_open_paths.append("")

            # 오디오 복사
            if scene.audio_path and scene.audio_path.strip():
                src_audio = Path(scene.audio_path)
                if src_audio.exists() and src_audio.is_file():
                    dst_audio = audio_dir / f"{i:04d}{src_audio.suffix}"
                    shutil.copy2(src_audio, dst_audio)
                    audio_paths.append(f"render_audio/{dst_audio.name}")
                else:
                    logger.warning(f"[RemotionAssembler] 오디오 없음: {src_audio}")
                    audio_paths.append("")
            else:
                audio_paths.append("")

        # BGM 복사
        bgm_public_path = None
        if self.bgm_path and Path(self.bgm_path).exists():
            src_bgm = Path(self.bgm_path)
            dst_bgm = public_dir / f"bgm{src_bgm.suffix}"
            shutil.copy2(src_bgm, dst_bgm)
            bgm_public_path = f"bgm{src_bgm.suffix}"

        # v59.3.5: SFX 파일 복사
        sfx_dir = public_dir / "render_sfx"
        if self.sfx_cues:
            if sfx_dir.exists():
                shutil.rmtree(sfx_dir)
            sfx_dir.mkdir(parents=True, exist_ok=True)

            for i, cue in enumerate(self.sfx_cues):
                src_sfx = Path(cue.get('sfx_path', ''))
                if src_sfx.exists():
                    dst_sfx = sfx_dir / f"sfx_{i:04d}{src_sfx.suffix}"
                    shutil.copy2(src_sfx, dst_sfx)
                    cue['_public_path'] = f"render_sfx/{dst_sfx.name}"
                else:
                    logger.warning(f"[v59.3.5] SFX 파일 없음: {src_sfx}")
                    cue['_public_path'] = None

        return (
            image_paths,
            audio_paths,
            background_paths,
            foreground_paths,
            head_paths,
            body_paths,
            left_arm_paths,
            right_arm_paths,
            eyes_open_paths,
            eyes_closed_paths,
            mouth_closed_paths,
            mouth_open_paths,
            bgm_public_path,
        )

    @staticmethod
    def _format_subtitle_display_text(text: str, max_line_chars: int = 34, max_lines: int = 3) -> str:
        """Soft-wrap long subtitles without changing the spoken TTS text."""
        normalized = " ".join(str(text or "").replace("\n", " ").split()).strip()
        if len(normalized) <= max_line_chars:
            return normalized

        lines: List[str] = []
        remaining = normalized
        separators = ("。", ".", "?", "!", ",", "，", " ", "·")
        while len(remaining) > max_line_chars and len(lines) < max_lines - 1:
            window = remaining[: max_line_chars + 1]
            cut = -1
            for sep in separators:
                pos = window.rfind(sep)
                if pos >= int(max_line_chars * 0.45):
                    cut = max(cut, pos + (0 if sep == " " else 1))
            if cut < int(max_line_chars * 0.45):
                cut = max_line_chars
            line = remaining[:cut].strip()
            if line:
                lines.append(line)
            remaining = remaining[cut:].strip(" ,，")

        if remaining:
            lines.append(remaining)
        return "\n".join(lines[:max_lines])

    def _build_props(
        self,
        image_paths: List[str],
        audio_paths: List[str],
        background_paths: List[str],
        foreground_paths: List[str],
        head_paths: List[str],
        body_paths: List[str],
        left_arm_paths: List[str],
        right_arm_paths: List[str],
        eyes_open_paths: List[str],
        eyes_closed_paths: List[str],
        mouth_closed_paths: List[str],
        mouth_open_paths: List[str],
        bgm_path: Optional[str],
    ) -> Dict[str, Any]:
        """Remotion props 생성"""
        images = []
        audio_segments = []
        subtitles = []

        # v58.3.13: 이미지/자막 모두 current_frame 누적 (동기화 핵심!)
        current_frame = 0
        total_frames = 0

        # v59.4: 호흡 간격은 media_factory.py의 full.wav 조립 시점에서 처리
        # (remotion_assembler에서 추가하면 오디오와 이미지/자막 싱크가 깨짐)
        # scene.duration_ms에 이미 pause 포함 (scene_end - start 기반)

        for i, scene in enumerate(self.scenes):
            duration_frames = self._ms_to_frames(scene.duration_ms)
            motion = dict(scene.motion_data or {})
            if not motion:
                motion = build_scene_motion_directive(
                    text=scene.text,
                    speaker=scene.speaker,
                    duration_frames=duration_frames,
                    config=self.motiontoon_config,
                )
            motion = self._augment_motion_from_asset_path(motion, scene.image_path)

            # v58.3.13: 자막도 이미지와 동일하게 current_frame 누적 사용!
            # 이유: start_ms → frame 변환 시 int() 반올림 오차가 누적됨
            # 해결: 이미지/자막 모두 동일한 current_frame 사용 (프레임 기반 동기화)

            mouth_cues = self._load_mouth_cues(scene.mouth_cues_path)
            if (
                not mouth_cues
                and scene.audio_path
                and i < len(mouth_closed_paths)
                and i < len(mouth_open_paths)
                and mouth_closed_paths[i]
                and mouth_open_paths[i]
            ):
                mouth_cues = self._build_mouth_cues_from_audio(scene.audio_path, duration_frames, self.fps)
            if (
                not mouth_cues
                and i < len(mouth_closed_paths)
                and i < len(mouth_open_paths)
                and mouth_closed_paths[i]
                and mouth_open_paths[i]
            ):
                mouth_cues = self._build_mouth_cues_from_text(scene.text, duration_frames)

            # 이미지 (순차 배치)
            if image_paths[i]:
                images.append({
                    "path": image_paths[i],
                    "backgroundPath": background_paths[i] if i < len(background_paths) else "",
                    "foregroundPath": foreground_paths[i] if i < len(foreground_paths) else "",
                    "headPath": head_paths[i] if i < len(head_paths) else "",
                    "bodyPath": body_paths[i] if i < len(body_paths) else "",
                    "leftArmPath": left_arm_paths[i] if i < len(left_arm_paths) else "",
                    "rightArmPath": right_arm_paths[i] if i < len(right_arm_paths) else "",
                    "eyesOpenPath": eyes_open_paths[i] if i < len(eyes_open_paths) else "",
                    "eyesClosedPath": eyes_closed_paths[i] if i < len(eyes_closed_paths) else "",
                    "mouthClosedPath": mouth_closed_paths[i] if i < len(mouth_closed_paths) else "",
                    "mouthOpenPath": mouth_open_paths[i] if i < len(mouth_open_paths) else "",
                    "mouthCues": mouth_cues,
                    "startFrame": current_frame,
                    "durationFrames": duration_frames,
                    "motion": motion,
                })

            # 오디오 (개별 세그먼트 - 잘 안쓰임)
            if audio_paths[i]:
                audio_segments.append({
                    "path": audio_paths[i],
                    "startFrame": current_frame,
                })

            # 자막 - duration_ms에 pause 포함되어 있으므로 그대로 사용
            # (호흡 간격 동안 이미지는 유지, 자막은 text가 있으면 표시)
            if scene.text:
                subtitles.append({
                    "text": self._format_subtitle_display_text(scene.text),
                    "speaker": scene.speaker,
                    "speakerColor": scene.speaker_color,  # v57.4: 화자 색상
                    "startFrame": current_frame,  # v58.3.13: 이미지와 동일!
                    "durationFrames": duration_frames,
                    "motion": motion,
                })

            current_frame += duration_frames
            total_frames = current_frame  # v58.3.13: 단순화

        # v58.3.12: 디버그 로그 - 자막 동기화 확인용
        # v58.3.13: 동기화 확인 로그
        if subtitles and images:
            logger.info(f"[v58.3.14] 이미지/자막 동기화 완료: {len(images)}개 씬, 누적 {total_frames}프레임 ({total_frames/self.fps:.1f}초)")

        # v58.3.3: fullAudioPath 처리 (public 폴더에 복사)
        # v58.3.14: 오디오 길이 기준으로 totalFrames 계산 (핵심!)
        full_audio_relative = None
        audio_duration_frames = total_frames  # 기본값: 누적 프레임

        if self.full_audio_path and os.path.exists(self.full_audio_path):
            public_path = REMOTION_PROJECT_PATH / "public"
            full_audio_dest = public_path / "full_audio.wav"
            import shutil
            shutil.copy2(self.full_audio_path, full_audio_dest)
            full_audio_relative = "full_audio.wav"

            # v58.3.14: 오디오 실제 길이로 totalFrames 계산 (동기화 핵심!)
            try:
                audio_duration_sec = get_audio_duration_ms(self.full_audio_path) / 1000.0
                audio_duration_frames = round(audio_duration_sec * self.fps)
                logger.info(f"[v58.3.14] 오디오 길이: {audio_duration_sec:.3f}초 = {audio_duration_frames}프레임")
                logger.info(f"[v58.3.14] 누적 프레임과 차이: {audio_duration_frames - total_frames}프레임 ({(audio_duration_frames - total_frames)/self.fps:.3f}초)")
            except Exception as e:
                logger.warning(f"[v58.3.14] 오디오 길이 측정 실패, 누적 프레임 사용: {e}")
                audio_duration_frames = total_frames

            logger.info(f"[RemotionAssembler] 전체 오디오 복사: {full_audio_dest}")

        # v58.3.14: totalFrames = 오디오 길이 기준 (자막보다 오디오가 정확함!)
        final_total_frames = audio_duration_frames

        # v58.3.14 + v61.1 (#42): 마지막 이미지/자막의 duration 보정
        # 반올림 누적 오차를 마지막 프레임에서 흡수하되, 최대 30프레임(1초) 캡
        if images and final_total_frames > total_frames:
            frame_diff = final_total_frames - total_frames
            capped_diff = min(frame_diff, 30)  # v61.1: 최대 1초 캡 (기존: 무제한 → 2~3초 정지)
            images[-1]["durationFrames"] += capped_diff
            if frame_diff > 30:
                logger.warning(f"[v61.1] 마지막 이미지 보정 캡 적용: {frame_diff}→{capped_diff}프레임")
            else:
                logger.info(f"[v58.3.14] 마지막 이미지 duration 보정: +{capped_diff}프레임")

        if subtitles and final_total_frames > total_frames:
            frame_diff = final_total_frames - total_frames
            capped_diff = min(frame_diff, 30)  # v61.1: 최대 1초 캡
            subtitles[-1]["durationFrames"] += capped_diff
            if frame_diff > 30:
                logger.warning(f"[v61.1] 마지막 자막 보정 캡 적용: {frame_diff}→{capped_diff}프레임")
            else:
                logger.info(f"[v58.3.14] 마지막 자막 duration 보정: +{capped_diff}프레임")

        # v58.4.0: hook이 있으면 totalFrames에 hook 길이 추가
        hook_frames = self.hook_data["durationFrames"] if self.hook_data else 0
        total_with_hook = final_total_frames + hook_frames

        props = {
            "images": images,
            "audioSegments": audio_segments,
            "subtitles": subtitles,
            "bgmPath": bgm_path,
            "bgmVolume": self.bgm_volume,
            "totalFrames": total_with_hook,  # v58.4.0: hook 포함 총 프레임
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            # v57.4: 채널별 자막 스타일
            "subtitleSize": self.subtitle_size,
            "speakerSize": self.speaker_size,
            "channel": self.channel,
            # v58.1: AI 제작 표기 (AI법 준수) + TTS 볼륨
            "showAiDisclosure": self.show_ai_disclosure,
            "aiDisclosureDuration": self.ai_disclosure_duration,
            "ttsVolume": self.tts_volume,
            # v58.3.3: 전체 TTS 오디오 (MoviePy 제거)
            "fullAudioPath": full_audio_relative,
            # v58.4.0: Hook 데이터 (재조립 제거)
            "hook": self.hook_data,
        }

        # v59.3.5: SFX 효과음 큐 (Remotion 통합)
        if self.sfx_cues:
            sfx_props = []
            for cue in self.sfx_cues:
                public_path = cue.get('_public_path')
                if not public_path:
                    continue
                sfx_props.append({
                    "path": public_path,
                    "startFrame": self._ms_to_frames(cue.get('timestamp_ms', 0)),
                    "volume": cue.get('volume', 0.3),
                    "durationFrames": self._ms_to_frames(cue.get('duration_ms', 0)) if cue.get('duration_ms') else None,
                    "fadeInFrames": self._ms_to_frames(cue.get('fade_in_ms', 0)) if cue.get('fade_in_ms') else None,
                    "fadeOutFrames": self._ms_to_frames(cue.get('fade_out_ms', 0)) if cue.get('fade_out_ms') else None,
                })
            if sfx_props:
                props["sfxCues"] = sfx_props
                logger.info(f"[v59.3.5] SFX props 추가: {len(sfx_props)}개 효과음")

        # v59: 비주얼 이펙트 설정 (있을 경우에만 추가)
        if self.visual_effects:
            # v59: dict 구조 → RadioDrama.tsx 호환 형식으로 변환
            ve_props = self._convert_visual_effects_to_props(self.visual_effects)
            if ve_props:
                props["visualEffects"] = ve_props
                logger.info(f"[v59] 비주얼 이펙트 props 추가: {ve_props}")

        # v59: 자막 스타일 설정 (있을 경우에만 추가)
        if self.subtitle_style:
            # v59: dict 구조 → RadioDrama.tsx 호환 형식으로 변환
            ss_props = self._convert_subtitle_style_to_props(self.subtitle_style)
            if ss_props:
                props["subtitleStyle"] = ss_props
                logger.info(f"[v59] 자막 스타일 props 추가: style={ss_props.get('style')}")

        if self.motiontoon_config.get("enabled"):
            props["motiontoon"] = self.motiontoon_config

        qc_report = self._build_render_qc_report(props)
        props["qcReport"] = qc_report
        self._write_render_qc_report(qc_report)
        if qc_report.get("status") == "fail" and os.getenv("REVERIE_STRICT_RENDER_QC", "").strip() == "1":
            raise RuntimeError(f"Render QC failed: {qc_report.get('issues')}")

        return props

    def render(
        self,
        output_path: str,
        codec: str = "h264",
        crf: int = 18,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        영상 렌더링

        Args:
            output_path: 출력 파일 경로
            codec: 코덱 (h264 권장)
            crf: 품질 (0-51, 낮을수록 고품질, 18 권장)
            progress_callback: 진행률 콜백 (0.0 ~ 1.0)

        Returns:
            렌더링 결과 정보
        """
        if not self.scenes:
            raise ValueError("렌더링할 씬이 없습니다")

        logger.info(f"[RemotionAssembler] 렌더링 시작: {len(self.scenes)}개 씬")

        # 에셋 복사
        if progress_callback:
            progress_callback(0.1)
        image_paths, audio_paths, background_paths, foreground_paths, head_paths, body_paths, left_arm_paths, right_arm_paths, eyes_open_paths, eyes_closed_paths, mouth_closed_paths, mouth_open_paths, bgm_path = self._copy_assets_to_public()

        # Props 생성
        props = self._build_props(
            image_paths,
            audio_paths,
            background_paths,
            foreground_paths,
            head_paths,
            body_paths,
            left_arm_paths,
            right_arm_paths,
            eyes_open_paths,
            eyes_closed_paths,
            mouth_closed_paths,
            mouth_open_paths,
            bgm_path,
        )
        props_file = REMOTION_PROJECT_PATH / "render_props.json"
        with open(props_file, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False, indent=2)

        logger.info(f"[RemotionAssembler] 총 프레임: {props['totalFrames']}, 예상 길이: {props['totalFrames']/self.fps:.1f}초")

        if progress_callback:
            progress_callback(0.2)

        # v60.1.0: Node.js/npx 설치 검증
        npx_cmd = "npx"
        if os.name == "nt":
            # Windows: npx.cmd 검색
            import shutil as _shutil
            npx_found = _shutil.which("npx") or _shutil.which("npx.cmd")
            if not npx_found:
                raise RuntimeError(
                    "Node.js/npx가 설치되지 않았습니다.\n"
                    "1) https://nodejs.org 에서 Node.js LTS를 설치하세요.\n"
                    "2) 설치 후 터미널에서 'npx --version'이 동작하는지 확인하세요.\n"
                    "3) remotion-poc/ 폴더에서 'npm install'을 실행하세요."
                )
            npx_cmd = npx_found

        # node_modules 존재 확인
        node_modules = REMOTION_PROJECT_PATH / "node_modules"
        if not node_modules.exists():
            raise RuntimeError(
                f"Remotion 의존성이 설치되지 않았습니다.\n"
                f"'{REMOTION_PROJECT_PATH}' 폴더에서 'npm install'을 실행하세요."
            )

        # Remotion CLI 실행
        # v57.6.1: --pixel-format=yuv420p 추가 (재생 호환성)
        # NOTE: NVENC 미적용. 현재 소프트웨어 인코딩(--crf) 사용 중
        cmd = [
            npx_cmd, "remotion", "render",
            "RadioDrama",
            str(output_path),
            f"--props={props_file}",
            f"--concurrency={self.concurrency}",
            f"--codec={codec}",
            f"--crf={crf}",
            "--pixel-format=yuv420p",  # v57.6.1: 표준 픽셀 포맷 (필수!)
        ]

        start_time = time.time()
        total_frames = props["totalFrames"]
        # v60.1.0: 렌더 timeout (30분 기본, 10분 영상 기준 충분)
        render_timeout = max(1800, total_frames * 2)  # 최소 30분, 또는 프레임당 2초

        try:
            # v57.5: 실시간 진행률 출력
            # v61.1 (#47): shell=False — npx_cmd는 전체 경로 (shutil.which)
            process = subprocess.Popen(
                cmd,
                cwd=str(REMOTION_PROJECT_PATH),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
                bufsize=1,
                creationflags=_NO_WINDOW,
                startupinfo=_hidden_startupinfo(),
            )

            # v62.21 C-1: 비동기 stdout 읽기 + 데드라인 기반 timeout
            # 기존 문제: for line in process.stdout: 블로킹 → process.wait(timeout) 도달 불가
            last_progress = 0.2
            deadline = time.time() + render_timeout
            stdout_q: _queue.Queue = _queue.Queue()

            def _read_stdout():
                try:
                    for ln in process.stdout:
                        stdout_q.put(ln)
                except Exception:
                    pass
                finally:
                    stdout_q.put(None)  # sentinel

            reader_thread = threading.Thread(target=_read_stdout, daemon=True)
            reader_thread.start()

            while True:
                # 데드라인 초과 → 강제 종료
                if time.time() > deadline:
                    process.kill()
                    process.wait(timeout=10)
                    raise RuntimeError(
                        f"Remotion 렌더링 timeout ({render_timeout}초 초과). "
                        f"프레임: {total_frames}, 경과: {time.time() - start_time:.0f}초"
                    )
                try:
                    line = stdout_q.get(timeout=2.0)
                    if line is None:
                        break  # stdout 종료 (프로세스 종료됨)
                except _queue.Empty:
                    # 2초간 출력 없음 — 프로세스 종료 체크
                    if process.poll() is not None:
                        break
                    continue

                line = line.strip()
                if not line:
                    continue

                # Remotion 진행률 파싱: "Rendered 150/600 frames (25%)"
                if "Rendered" in line and "frames" in line:
                    try:
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if "/" in p and i > 0 and parts[i-1] == "Rendered":  # v62.10: i>0 가드
                                current, total = p.split("/")
                                current = int(current)
                                total = int(total)
                                pct = current / total
                                mapped_progress = 0.2 + (pct * 0.7)
                                if progress_callback and mapped_progress > last_progress:
                                    progress_callback(mapped_progress)
                                    last_progress = mapped_progress
                                print(f"\r   [Remotion] {current}/{total} frames ({pct*100:.0f}%)", end="", flush=True)
                                break
                    except (ValueError, IndexError):
                        pass

                # 기타 중요 메시지 출력
                elif any(kw in line.lower() for kw in ["error", "warning", "stitching", "encoding"]):
                    print(f"\n   [Remotion] {line}")

            # 프로세스 완전 종료 대기
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            print()  # 줄바꿈

            elapsed = time.time() - start_time

            if progress_callback:
                progress_callback(0.9)

            if process.returncode != 0:
                logger.error(f"[RemotionAssembler] 렌더링 실패 (exit code {process.returncode})")
                raise RuntimeError(f"Remotion render failed with exit code {process.returncode}")

            # 결과 확인
            output_file = Path(output_path)
            if not output_file.exists():
                raise FileNotFoundError(f"출력 파일 생성 실패: {output_path}")

            file_size = output_file.stat().st_size / (1024 * 1024)
            duration = props["totalFrames"] / self.fps

            if progress_callback:
                progress_callback(1.0)

            logger.info(f"[RemotionAssembler] 렌더링 완료: {elapsed:.1f}초, {file_size:.1f}MB")

            return {
                "success": True,
                "output_path": str(output_path),
                "elapsed_seconds": elapsed,
                "file_size_mb": file_size,
                "total_frames": props["totalFrames"],
                "duration_seconds": duration,
                "fps": self.fps,
                "scene_count": len(self.scenes),
            }

        finally:
            # v58.3.12: props 파일 보존 (디버깅용)
            # 동기화 문제 해결 후 삭제 로직 복원
            logger.info(f"[v58.3.12 DEBUG] props 파일 보존: {props_file}")
            pass

    def get_estimated_duration(self) -> float:
        """예상 영상 길이 (초)"""
        total_ms = sum(scene.duration_ms for scene in self.scenes)
        return total_ms / 1000


# 테스트
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    assembler = RemotionAssembler()

    # 테스트 데이터 (public 폴더의 기존 파일 사용)
    public_path = REMOTION_PROJECT_PATH / "public"

    for i in range(1, 11):
        img = public_path / "images" / f"{i:03d}.png"
        audio = public_path / "audio" / f"{i:03d}_narrator_calm.wav"

        if img.exists():
            assembler.add_scene(
                image_path=str(img),
                audio_path=str(audio) if audio.exists() else "",
                text=f"테스트 자막 {i}",
                speaker="나레이터" if i % 3 == 1 else ("여자" if i % 3 == 2 else "남자"),
                duration_ms=3000,  # 3초
            )

    result = assembler.render(
        output_path=str(REMOTION_PROJECT_PATH / "out" / "assembler_test.mp4"),
    )

    print(f"\n렌더링 결과:")
    for k, v in result.items():
        print(f"  {k}: {v}")
