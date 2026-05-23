# Reverie Insight - 스타일 분석기
# Version: 1.2.0

"""
딥 분석 모듈
- 영상 다운로드 (yt-dlp)
- 프레임 캡처 (FFmpeg)
- 색상 분석 (OpenCV)
- 스타일 정밀 분석 (Gemini Vision)
- 클론 레시피 + TTS 가이드 생성
"""

import os
import sys
import json
import subprocess
import sys
# v62.17: Windows 콘솔 창 깜빡임 방지
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
def _hidden_startupinfo():
    if sys.platform == 'win32':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None
import tempfile
import shutil
import base64
import requests
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Tuple, Callable
from datetime import datetime
from enum import Enum
from utils.secret_redaction import redact_sensitive_text

# OpenCV (선택적)
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class ColorPalette:
    """색상 팔레트"""
    dominant_colors: List[Tuple[int, int, int]]  # RGB
    color_names: List[str]  # 색상 이름
    brightness: str  # dark, medium, bright
    saturation: str  # desaturated, normal, vibrant
    mood: str  # 분위기 (gloomy, neutral, cheerful, etc)


@dataclass
class EditingStyle:
    """편집 스타일"""
    avg_scene_duration: float  # 평균 장면 길이 (초)
    pacing: str  # slow, medium, fast
    transition_style: str  # cut, fade, dissolve, etc
    text_overlay: bool  # 자막/텍스트 오버레이 사용 여부
    effects_level: str  # minimal, moderate, heavy


@dataclass
class SDModelRecommendation:
    """SD 모델 추천"""
    model_name: str
    model_type: str  # checkpoint, LoRA
    civitai_url: Optional[str]
    match_reason: str
    prompt_style: str  # 추천 프롬프트 스타일


@dataclass
class TTSGuide:
    """TTS 가이드 (비밀 문서용)"""
    voice_gender: str  # male, female
    voice_age: str  # child, young, adult, elderly
    voice_tone: str  # calm, energetic, mysterious, scary, etc
    required_emotions: List[str]  # 필요한 감정 목록
    sample_scripts: Dict[str, str]  # 감정별 샘플 대사
    recording_tips: List[str]  # 녹음 팁
    elevenlabs_hints: str  # ElevenLabs v3용 힌트


@dataclass
class CloneRecipe:
    """클론 레시피 (종합)"""
    video_id: str
    video_title: str
    channel_title: str

    # 분석 결과
    content_type: str  # REAL, FACELESS
    style_type: str
    feasibility_score: int
    clone_difficulty: str

    # 비주얼 분석
    color_palette: Optional[ColorPalette]
    editing_style: Optional[EditingStyle]

    # 추천
    sd_models: List[SDModelRecommendation]
    lora_recommendations: List[str]
    prompt_template: str
    negative_prompt: str

    # TTS 가이드
    tts_guide: TTSGuide

    # 메타
    analyzed_at: str = ""
    analysis_version: str = "1.2.0"


# ============================================================
# SD 모델 매핑 테이블
# ============================================================

SD_MODEL_MAPPING = {
    # 스타일 → 추천 모델
    "silhouette": {
        "models": [
            {"name": "Anything V5", "type": "checkpoint", "url": "https://civitai.com/models/9409"},
            {"name": "Dark Sushi Mix", "type": "checkpoint", "url": "https://civitai.com/models/24779"},
        ],
        "loras": ["silhouette style", "shadow art"],
        "prompt_style": "silhouette, shadow, dark background, minimal details, high contrast"
    },
    "2d_anime": {
        "models": [
            {"name": "Anything V5", "type": "checkpoint", "url": "https://civitai.com/models/9409"},
            {"name": "Counterfeit V3", "type": "checkpoint", "url": "https://civitai.com/models/4468"},
            {"name": "MeinaMix", "type": "checkpoint", "url": "https://civitai.com/models/7240"},
        ],
        "loras": ["anime style", "flat color"],
        "prompt_style": "anime style, 2d illustration, flat colors, clean lines"
    },
    "slideshow": {
        "models": [
            {"name": "Realistic Vision V5", "type": "checkpoint", "url": "https://civitai.com/models/4201"},
            {"name": "DreamShaper", "type": "checkpoint", "url": "https://civitai.com/models/4384"},
        ],
        "loras": [],
        "prompt_style": "high quality photo, detailed, sharp focus"
    },
    "ai_generated": {
        "models": [
            {"name": "DreamShaper", "type": "checkpoint", "url": "https://civitai.com/models/4384"},
            {"name": "Deliberate V3", "type": "checkpoint", "url": "https://civitai.com/models/4823"},
        ],
        "loras": ["midjourney style", "ai art style"],
        "prompt_style": "digital art, detailed, vibrant colors, dramatic lighting"
    },
    "pixel_art": {
        "models": [
            {"name": "Pixel Art Diffusion", "type": "checkpoint", "url": "https://civitai.com/models/7820"},
        ],
        "loras": ["pixel art", "8bit style", "16bit style"],
        "prompt_style": "pixel art, 8bit, retro game style, limited palette"
    },
    "lo-fi": {
        "models": [
            {"name": "Anything V5", "type": "checkpoint", "url": "https://civitai.com/models/9409"},
            {"name": "Pastel Mix", "type": "checkpoint", "url": "https://civitai.com/models/5414"},
        ],
        "loras": ["lo-fi aesthetic", "soft colors", "cozy"],
        "prompt_style": "lo-fi aesthetic, soft lighting, warm colors, cozy atmosphere"
    },
    "text_based": {
        "models": [
            {"name": "Realistic Vision V5", "type": "checkpoint", "url": "https://civitai.com/models/4201"},
        ],
        "loras": [],
        "prompt_style": "simple background, clean, minimal"
    },
    "stock_footage": {
        "models": [
            {"name": "Realistic Vision V5", "type": "checkpoint", "url": "https://civitai.com/models/4201"},
            {"name": "epiCRealism", "type": "checkpoint", "url": "https://civitai.com/models/25694"},
        ],
        "loras": [],
        "prompt_style": "photorealistic, stock photo style, professional, high quality"
    }
}

# 채널 장르별 TTS 프리셋
TTS_PRESETS = {
    "horror": {
        "voice_gender": "female",
        "voice_age": "young",
        "voice_tone": "mysterious, whispering",
        "required_emotions": ["calm", "whisper", "fear", "shock", "crying"],
        "sample_scripts": {
            "calm": "그날 밤, 모든 것이 시작되었습니다.",
            "whisper": "조용히... 뒤를 돌아보지 마세요...",
            "fear": "무언가가... 다가오고 있어요!",
            "shock": "안돼! 그럴 리가 없어!",
            "crying": "제발... 살려주세요..."
        },
        "recording_tips": [
            "속삭이는 톤 연습 필수",
            "공포 분위기를 위해 약간의 떨림 추가",
            "ASMR 마이크 사용 권장"
        ]
    },
    "mystery": {
        "voice_gender": "male",
        "voice_age": "adult",
        "voice_tone": "calm, authoritative, narrator",
        "required_emotions": ["calm", "serious", "curious", "dramatic"],
        "sample_scripts": {
            "calm": "이 사건의 진실을 파헤쳐 보겠습니다.",
            "serious": "하지만 여기서 의문이 생깁니다.",
            "curious": "과연 그것이 사실일까요?",
            "dramatic": "그리고 마침내, 진실이 밝혀졌습니다."
        },
        "recording_tips": [
            "다큐멘터리 내레이터 톤",
            "적절한 포즈(멈춤) 활용",
            "신뢰감 있는 목소리"
        ]
    },
    "entertainment": {
        "voice_gender": "any",
        "voice_age": "young",
        "voice_tone": "energetic, friendly, casual",
        "required_emotions": ["happy", "excited", "surprised", "casual"],
        "sample_scripts": {
            "happy": "안녕하세요! 오늘도 재미있는 이야기 가져왔어요!",
            "excited": "대박! 이거 진짜 미쳤어요!",
            "surprised": "헉! 이게 진짜라고요?",
            "casual": "그래서 말인데요..."
        },
        "recording_tips": [
            "밝고 활기찬 톤 유지",
            "리액션 과장 OK",
            "친근한 말투"
        ]
    },
    "education": {
        "voice_gender": "any",
        "voice_age": "adult",
        "voice_tone": "clear, professional, warm",
        "required_emotions": ["calm", "explain", "emphasis", "friendly"],
        "sample_scripts": {
            "calm": "오늘은 이 주제에 대해 알아보겠습니다.",
            "explain": "쉽게 말해서, 이것은 이런 의미입니다.",
            "emphasis": "여기서 중요한 포인트는 바로 이것입니다.",
            "friendly": "어렵지 않죠? 천천히 따라와 주세요."
        },
        "recording_tips": [
            "명확한 발음",
            "적절한 속도 조절",
            "친근하지만 신뢰감 있는 톤"
        ]
    },
    "news": {
        "voice_gender": "any",
        "voice_age": "adult",
        "voice_tone": "professional, neutral, clear",
        "required_emotions": ["neutral", "serious", "urgent", "closing"],
        "sample_scripts": {
            "neutral": "오늘의 주요 뉴스입니다.",
            "serious": "심각한 상황이 발생했습니다.",
            "urgent": "긴급 속보입니다.",
            "closing": "이상으로 뉴스를 마치겠습니다."
        },
        "recording_tips": [
            "뉴스 앵커 톤",
            "감정 절제",
            "정확한 전달"
        ]
    }
}


# ============================================================
# 스타일 분석기 클래스
# ============================================================

class StyleAnalyzer:
    """스타일 심층 분석기"""

    def __init__(self, gemini_api_key: str, work_dir: Optional[Path] = None):
        self.api_key = gemini_api_key
        self.work_dir = work_dir or Path(tempfile.gettempdir()) / "reverie_insight"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # yt-dlp / FFmpeg 경로 확인
        self.ytdlp_path = self._find_executable("yt-dlp")
        self.ffmpeg_path = self._find_executable("ffmpeg")

    def _find_executable(self, name: str) -> Optional[str]:
        """실행파일 경로 찾기"""
        # Windows
        if sys.platform == "win32":
            result = shutil.which(name) or shutil.which(f"{name}.exe")
        else:
            result = shutil.which(name)
        return result

    # ============================================================
    # 영상 다운로드
    # ============================================================

    def download_video(
        self,
        video_id: str,
        max_duration: int = 120,
        progress_callback: Optional[Callable] = None
    ) -> Optional[Path]:
        """
        YouTube 영상 다운로드 (분석용 저화질)

        Args:
            video_id: YouTube 영상 ID
            max_duration: 최대 다운로드 길이 (초)
            progress_callback: 진행 콜백

        Returns:
            다운로드된 파일 경로 (실패시 None)
        """
        if not self.ytdlp_path:
            print("[ERROR] yt-dlp를 찾을 수 없습니다.")
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"
        output_path = self.work_dir / f"{video_id}.mp4"

        # 이미 있으면 스킵
        if output_path.exists():
            return output_path

        try:
            if progress_callback:
                progress_callback("downloading", video_id)

            # yt-dlp 명령어 (저화질, 짧은 길이만)
            cmd = [
                self.ytdlp_path,
                "-f", "worst[ext=mp4]/worst",  # 최저 화질
                "--download-sections", f"*0-{max_duration}",  # 처음 N초만
                "-o", str(output_path),
                "--no-playlist",
                "--quiet",
                url
            ]

            result = subprocess.run(cmd, capture_output=True, timeout=120, creationflags=_NO_WINDOW, startupinfo=_hidden_startupinfo())

            if output_path.exists():
                return output_path
            else:
                print(f"[ERROR] 다운로드 실패: {video_id}")
                return None

        except subprocess.TimeoutExpired:
            print(f"[ERROR] 다운로드 타임아웃: {video_id}")
            return None
        except Exception as e:
            print(f"[ERROR] 다운로드 오류: {e}")
            return None

    # ============================================================
    # 프레임 캡처
    # ============================================================

    def capture_frames(
        self,
        video_path: Path,
        num_frames: int = 9,
        progress_callback: Optional[Callable] = None
    ) -> List[Path]:
        """
        영상에서 프레임 캡처

        Args:
            video_path: 영상 파일 경로
            num_frames: 캡처할 프레임 수
            progress_callback: 진행 콜백

        Returns:
            캡처된 이미지 파일 경로 리스트
        """
        if not self.ffmpeg_path:
            print("[ERROR] FFmpeg를 찾을 수 없습니다.")
            return []

        if not video_path.exists():
            return []

        video_id = video_path.stem
        frames_dir = self.work_dir / f"{video_id}_frames"
        frames_dir.mkdir(exist_ok=True)

        if progress_callback:
            progress_callback("capturing", video_id)

        try:
            # 영상 길이 확인
            probe_cmd = [
                self.ffmpeg_path, "-i", str(video_path),
                "-hide_banner"
            ]
            probe_result = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=30,
                creationflags=_NO_WINDOW,
                startupinfo=_hidden_startupinfo(),
            )

            # Duration 파싱 (예: Duration: 00:01:30.50)
            duration = 60  # 기본값
            for line in probe_result.stderr.split('\n'):
                if 'Duration:' in line:
                    try:
                        time_str = line.split('Duration:')[1].split(',')[0].strip()
                        parts = time_str.split(':')
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    except (ValueError, IndexError):
                        pass
                    break

            # 균등 간격으로 프레임 캡처
            interval = duration / (num_frames + 1)
            frame_paths = []

            for i in range(num_frames):
                timestamp = interval * (i + 1)
                output_file = frames_dir / f"frame_{i+1:02d}.jpg"

                cmd = [
                    self.ffmpeg_path,
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    "-y",
                    str(output_file)
                ]

                subprocess.run(cmd, capture_output=True, timeout=30, creationflags=_NO_WINDOW, startupinfo=_hidden_startupinfo())

                if output_file.exists():
                    frame_paths.append(output_file)

            return frame_paths

        except Exception as e:
            print(f"[ERROR] 프레임 캡처 오류: {e}")
            return []

    def create_grid_image(
        self,
        frame_paths: List[Path],
        grid_size: Tuple[int, int] = (3, 3)
    ) -> Optional[Path]:
        """
        프레임들을 그리드 이미지로 합치기

        Args:
            frame_paths: 프레임 이미지 경로 리스트
            grid_size: 그리드 크기 (행, 열)

        Returns:
            그리드 이미지 경로
        """
        if not CV2_AVAILABLE:
            print("[WARNING] OpenCV 없음 - 그리드 생성 스킵")
            return None

        if not frame_paths:
            return None

        rows, cols = grid_size
        target_count = rows * cols

        # 프레임 수 맞추기
        while len(frame_paths) < target_count:
            frame_paths.append(frame_paths[-1])
        frame_paths = frame_paths[:target_count]

        # 이미지 로드
        images = []
        for path in frame_paths:
            img = cv2.imread(str(path))
            if img is not None:
                images.append(img)

        if not images:
            return None

        # 크기 통일 (첫 이미지 기준)
        h, w = images[0].shape[:2]
        cell_size = (w // cols, h // rows)

        resized = []
        for img in images:
            resized.append(cv2.resize(img, cell_size))

        # 그리드 생성
        grid_rows = []
        for i in range(rows):
            row_images = resized[i * cols:(i + 1) * cols]
            grid_rows.append(np.hstack(row_images))

        grid_image = np.vstack(grid_rows)

        # 저장
        video_id = frame_paths[0].parent.stem.replace("_frames", "")
        grid_path = self.work_dir / f"{video_id}_grid.jpg"
        cv2.imwrite(str(grid_path), grid_image)

        return grid_path

    # ============================================================
    # 색상 분석
    # ============================================================

    def analyze_colors(self, frame_paths: List[Path], num_colors: int = 5) -> Optional[ColorPalette]:
        """
        프레임들에서 색상 팔레트 추출

        Args:
            frame_paths: 프레임 이미지 경로 리스트
            num_colors: 추출할 주요 색상 수

        Returns:
            ColorPalette 객체
        """
        if not CV2_AVAILABLE:
            return None

        if not frame_paths:
            return None

        # 모든 프레임의 픽셀 수집
        all_pixels = []
        brightness_values = []
        saturation_values = []

        for path in frame_paths:
            img = cv2.imread(str(path))
            if img is None:
                continue

            # RGB로 변환
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # HSV로 변환 (밝기/채도 분석용)
            img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

            # 픽셀 수집 (샘플링)
            h, w = img_rgb.shape[:2]
            pixels = img_rgb.reshape(-1, 3)[::100]  # 100픽셀당 1개 샘플링
            all_pixels.extend(pixels)

            # 밝기/채도 평균
            brightness_values.append(np.mean(img_hsv[:, :, 2]))
            saturation_values.append(np.mean(img_hsv[:, :, 1]))

        if not all_pixels:
            return None

        # K-means 클러스터링으로 주요 색상 추출
        try:
            from sklearn.cluster import KMeans
        except ImportError:
            logger.warning("[StyleAnalyzer] scikit-learn 미설치 — 색상 분석 건너뜀")
            return None
        pixels_array = np.array(all_pixels)

        kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=10)
        kmeans.fit(pixels_array)

        colors = kmeans.cluster_centers_.astype(int)

        # 색상 이름 매핑 (간단 버전)
        color_names = [self._get_color_name(tuple(c)) for c in colors]

        # 밝기/채도 판정
        avg_brightness = np.mean(brightness_values)
        avg_saturation = np.mean(saturation_values)

        if avg_brightness < 85:
            brightness = "dark"
        elif avg_brightness < 170:
            brightness = "medium"
        else:
            brightness = "bright"

        if avg_saturation < 85:
            saturation = "desaturated"
        elif avg_saturation < 170:
            saturation = "normal"
        else:
            saturation = "vibrant"

        # 분위기 판정
        if brightness == "dark" and saturation == "desaturated":
            mood = "gloomy"
        elif brightness == "dark" and saturation == "normal":
            mood = "mysterious"
        elif brightness == "bright" and saturation == "vibrant":
            mood = "cheerful"
        elif brightness == "medium" and saturation == "normal":
            mood = "neutral"
        else:
            mood = "mixed"

        return ColorPalette(
            dominant_colors=[tuple(c) for c in colors],
            color_names=color_names,
            brightness=brightness,
            saturation=saturation,
            mood=mood
        )

    def _get_color_name(self, rgb: Tuple[int, int, int]) -> str:
        """RGB를 색상 이름으로 변환 (간단 버전)"""
        r, g, b = rgb

        # 무채색 판정
        if max(r, g, b) - min(r, g, b) < 30:
            if r < 50:
                return "black"
            elif r < 128:
                return "dark gray"
            elif r < 200:
                return "light gray"
            else:
                return "white"

        # 유채색 판정
        if r > g and r > b:
            if g > b:
                return "orange" if g > r * 0.5 else "red"
            else:
                return "pink" if b > r * 0.3 else "red"
        elif g > r and g > b:
            if r > b:
                return "yellow-green" if r > g * 0.5 else "green"
            else:
                return "cyan" if b > g * 0.5 else "green"
        else:
            if r > g:
                return "purple" if r > b * 0.5 else "blue"
            else:
                return "teal" if g > b * 0.3 else "blue"

    # ============================================================
    # Gemini Vision 정밀 분석
    # ============================================================

    def analyze_style_with_gemini(
        self,
        video_info: Dict,
        grid_image_path: Optional[Path] = None,
        thumbnail_url: Optional[str] = None
    ) -> Dict:
        """
        Gemini Vision으로 스타일 정밀 분석

        Args:
            video_info: 영상 정보 (title, description, category 등)
            grid_image_path: 그리드 이미지 경로
            thumbnail_url: 썸네일 URL (그리드 없을 때 fallback)

        Returns:
            분석 결과 딕셔너리
        """
        # 이미지 준비
        image_data = None

        if grid_image_path and grid_image_path.exists():
            with open(grid_image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
        elif thumbnail_url:
            try:
                response = requests.get(thumbnail_url, timeout=10)
                if response.status_code == 200:
                    image_data = base64.b64encode(response.content).decode('utf-8')
            except (requests.RequestException, OSError):
                pass

        if not image_data:
            return {"error": "이미지를 로드할 수 없습니다."}

        # 프롬프트 생성
        prompt = self._build_style_analysis_prompt(video_info)

        # Gemini API 호출
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"

            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_data
                            }
                        }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 2000
                }
            }

            response = requests.post(url, json=payload, timeout=60)

            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']

                # JSON 파싱
                import re
                json_match = re.search(r'\{[\s\S]*\}', text)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    return {"error": "JSON 파싱 실패", "raw": text}
            else:
                return {"error": f"API 오류: {response.status_code}"}

        except Exception as e:
            return {"error": redact_sensitive_text(e)}

    def _build_style_analysis_prompt(self, video_info: Dict) -> str:
        """스타일 분석 프롬프트 생성"""
        title = video_info.get('title', '')
        channel = video_info.get('channel_title', '')
        category = video_info.get('category_name', '')
        description = video_info.get('description', '')[:500]

        prompt = f"""이 YouTube 영상의 프레임들을 분석하여 Stable Diffusion으로 복제하기 위한 상세 스타일 가이드를 작성해주세요.

## 영상 정보
- 제목: {title}
- 채널: {channel}
- 카테고리: {category}
- 설명: {description}...

## 분석 항목

### 1. 비주얼 스타일 분석
- 전체적인 아트 스타일 (사실적, 애니메이션, 일러스트, 실루엣 등)
- 색감 (어둡고 칙칙한지, 밝고 화사한지, 파스텔톤인지 등)
- 조명 스타일 (자연광, 드라마틱 조명, 네온, 암울한 분위기 등)
- 배경 스타일 (단색, 그라데이션, 상세한 배경, 미니멀 등)

### 2. SD 모델 추천
- 이 스타일에 맞는 Stable Diffusion 체크포인트 추천 (1-3개)
- 추천 LoRA (있다면)
- Civitai에서 검색할 키워드

### 3. 프롬프트 템플릿
- 이 스타일을 재현하기 위한 SD 프롬프트 템플릿
- 네거티브 프롬프트 추천

### 4. 채널 장르 판단
- horror (공포/괴담)
- mystery (미스터리/사건)
- entertainment (예능/재미)
- education (교육/정보)
- news (뉴스/시사)
- other

## 응답 형식 (JSON)
```json
{{
  "visual_style": {{
    "art_style": "스타일 설명",
    "color_scheme": "색감 설명",
    "lighting": "조명 설명",
    "background": "배경 설명"
  }},
  "sd_recommendation": {{
    "checkpoints": [
      {{"name": "모델명", "reason": "추천 이유"}}
    ],
    "loras": ["LoRA1", "LoRA2"],
    "civitai_keywords": ["키워드1", "키워드2"]
  }},
  "prompt_template": {{
    "positive": "추천 프롬프트",
    "negative": "네거티브 프롬프트",
    "style_tags": ["태그1", "태그2"]
  }},
  "channel_genre": "horror/mystery/entertainment/education/news/other",
  "additional_notes": "기타 복제 팁"
}}
```

JSON만 응답해주세요."""

        return prompt

    # ============================================================
    # TTS 가이드 생성
    # ============================================================

    def generate_tts_guide(
        self,
        video_info: Dict,
        channel_genre: str,
        style_analysis: Dict
    ) -> TTSGuide:
        """
        TTS 가이드 자동 생성

        Args:
            video_info: 영상 정보
            channel_genre: 채널 장르
            style_analysis: 스타일 분석 결과

        Returns:
            TTSGuide 객체
        """
        # 프리셋 가져오기
        preset = TTS_PRESETS.get(channel_genre, TTS_PRESETS["entertainment"])

        # Gemini로 커스터마이징 요청
        custom_guide = self._customize_tts_guide_with_gemini(video_info, preset)

        if custom_guide and not custom_guide.get("error"):
            # Gemini 결과로 가이드 생성
            return TTSGuide(
                voice_gender=custom_guide.get("voice_gender", preset["voice_gender"]),
                voice_age=custom_guide.get("voice_age", preset["voice_age"]),
                voice_tone=custom_guide.get("voice_tone", preset["voice_tone"]),
                required_emotions=custom_guide.get("required_emotions", preset["required_emotions"]),
                sample_scripts=custom_guide.get("sample_scripts", preset["sample_scripts"]),
                recording_tips=custom_guide.get("recording_tips", preset["recording_tips"]),
                elevenlabs_hints=custom_guide.get("elevenlabs_hints", f"Use {preset['voice_tone']} tone for {channel_genre} content")
            )
        else:
            # 프리셋 그대로 사용
            return TTSGuide(
                voice_gender=preset["voice_gender"],
                voice_age=preset["voice_age"],
                voice_tone=preset["voice_tone"],
                required_emotions=preset["required_emotions"],
                sample_scripts=preset["sample_scripts"],
                recording_tips=preset["recording_tips"],
                elevenlabs_hints=f"Use {preset['voice_tone']} tone for {channel_genre} content"
            )

    def _customize_tts_guide_with_gemini(self, video_info: Dict, preset: Dict) -> Dict:
        """Gemini로 TTS 가이드 커스터마이징"""
        title = video_info.get('title', '')
        description = video_info.get('description', '')[:300]

        prompt = f"""이 영상 스타일에 맞는 TTS(Text-to-Speech) 녹음 가이드를 작성해주세요.

## 영상 정보
- 제목: {title}
- 설명: {description}...

## 기본 프리셋
- 목소리 성별: {preset['voice_gender']}
- 목소리 연령대: {preset['voice_age']}
- 목소리 톤: {preset['voice_tone']}

## 요청사항
이 영상 스타일에 맞게 다음을 작성해주세요:

1. 필요한 감정 목록 (4-6개)
2. 각 감정별 샘플 대사 (한국어, 자연스러운 문장)
3. 녹음 팁 (3-5개)
4. ElevenLabs v3 목소리 생성을 위한 힌트 (영어로)

## 응답 형식 (JSON)
```json
{{
  "voice_gender": "male/female",
  "voice_age": "child/young/adult/elderly",
  "voice_tone": "톤 설명 (영어 키워드)",
  "required_emotions": ["emotion1", "emotion2", ...],
  "sample_scripts": {{
    "emotion1": "샘플 대사 한국어",
    "emotion2": "샘플 대사 한국어"
  }},
  "recording_tips": ["팁1", "팁2", ...],
  "elevenlabs_hints": "English description for ElevenLabs v3 voice cloning"
}}
```

JSON만 응답해주세요."""

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1500
                }
            }

            response = requests.post(url, json=payload, timeout=30)

            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']

                import re
                json_match = re.search(r'\{[\s\S]*\}', text)
                if json_match:
                    return json.loads(json_match.group())

            return {"error": "API 실패"}

        except Exception as e:
            return {"error": redact_sensitive_text(e)}

    # ============================================================
    # 클론 레시피 생성 (종합)
    # ============================================================

    def generate_clone_recipe(
        self,
        video_info: Dict,
        gatekeeper_result: Dict,
        deep_analysis: bool = True,
        progress_callback: Optional[Callable] = None
    ) -> CloneRecipe:
        """
        종합 클론 레시피 생성

        Args:
            video_info: 영상 정보
            gatekeeper_result: AI 문지기 분석 결과
            deep_analysis: 딥 분석 수행 여부 (영상 다운로드 포함)
            progress_callback: 진행 콜백

        Returns:
            CloneRecipe 객체
        """
        video_id = video_info.get('video_id', '')

        color_palette = None
        editing_style = None
        grid_path = None

        # 딥 분석 (영상 다운로드 + 프레임 캡처)
        if deep_analysis:
            if progress_callback:
                progress_callback("download", video_id)

            video_path = self.download_video(video_id)

            if video_path:
                if progress_callback:
                    progress_callback("capture", video_id)

                frames = self.capture_frames(video_path)

                if frames:
                    # 그리드 생성
                    grid_path = self.create_grid_image(frames)

                    # 색상 분석
                    if progress_callback:
                        progress_callback("color", video_id)
                    color_palette = self.analyze_colors(frames)

        # Gemini Vision 스타일 분석
        if progress_callback:
            progress_callback("style", video_id)

        style_result = self.analyze_style_with_gemini(
            video_info,
            grid_path,
            video_info.get('thumbnail_high_url') or video_info.get('thumbnail_url')
        )

        # 채널 장르 추출
        channel_genre = style_result.get('channel_genre', 'entertainment')

        # TTS 가이드 생성
        if progress_callback:
            progress_callback("tts", video_id)

        tts_guide = self.generate_tts_guide(video_info, channel_genre, style_result)

        # SD 모델 추천 조합
        style_type = gatekeeper_result.get('style_type', 'slideshow')
        base_models = SD_MODEL_MAPPING.get(style_type, SD_MODEL_MAPPING['slideshow'])
        gemini_models = style_result.get('sd_recommendation', {})

        sd_recommendations = []

        # Gemini 추천 모델
        for model in gemini_models.get('checkpoints', []):
            sd_recommendations.append(SDModelRecommendation(
                model_name=model.get('name', ''),
                model_type='checkpoint',
                civitai_url=None,
                match_reason=model.get('reason', ''),
                prompt_style=style_result.get('prompt_template', {}).get('positive', '')
            ))

        # 기본 매핑 모델 추가
        for model in base_models.get('models', [])[:2]:
            if not any(m.model_name == model['name'] for m in sd_recommendations):
                sd_recommendations.append(SDModelRecommendation(
                    model_name=model['name'],
                    model_type=model['type'],
                    civitai_url=model.get('url'),
                    match_reason=f"스타일 '{style_type}'에 추천",
                    prompt_style=base_models.get('prompt_style', '')
                ))

        # 프롬프트 템플릿
        prompt_template = style_result.get('prompt_template', {})
        positive_prompt = prompt_template.get('positive', base_models.get('prompt_style', ''))
        negative_prompt = prompt_template.get('negative', 'low quality, blurry, watermark')

        # LoRA 추천
        lora_list = gemini_models.get('loras', []) + base_models.get('loras', [])
        lora_list = list(set(lora_list))[:5]  # 중복 제거, 최대 5개

        return CloneRecipe(
            video_id=video_id,
            video_title=video_info.get('title', ''),
            channel_title=video_info.get('channel_title', ''),
            content_type=gatekeeper_result.get('content_type', 'FACELESS'),
            style_type=style_type,
            feasibility_score=gatekeeper_result.get('feasibility_score', 0),
            clone_difficulty=gatekeeper_result.get('clone_difficulty', 'MEDIUM'),
            color_palette=color_palette,
            editing_style=editing_style,
            sd_models=sd_recommendations,
            lora_recommendations=lora_list,
            prompt_template=positive_prompt,
            negative_prompt=negative_prompt,
            tts_guide=tts_guide,
            analyzed_at=datetime.now().isoformat(),
            analysis_version="1.2.0"
        )

    # ============================================================
    # 결과 저장/내보내기
    # ============================================================

    def export_recipe_json(self, recipe: CloneRecipe, output_path: Path) -> Path:
        """클론 레시피를 JSON으로 저장"""
        data = {
            "video_id": recipe.video_id,
            "video_title": recipe.video_title,
            "channel_title": recipe.channel_title,
            "content_type": recipe.content_type,
            "style_type": recipe.style_type,
            "feasibility_score": recipe.feasibility_score,
            "clone_difficulty": recipe.clone_difficulty,
            "color_palette": asdict(recipe.color_palette) if recipe.color_palette else None,
            "editing_style": asdict(recipe.editing_style) if recipe.editing_style else None,
            "sd_models": [asdict(m) for m in recipe.sd_models],
            "lora_recommendations": recipe.lora_recommendations,
            "prompt_template": recipe.prompt_template,
            "negative_prompt": recipe.negative_prompt,
            "tts_guide": asdict(recipe.tts_guide),
            "analyzed_at": recipe.analyzed_at,
            "analysis_version": recipe.analysis_version
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return output_path

    def export_tts_guide_markdown(self, recipe: CloneRecipe, output_path: Path) -> Path:
        """TTS 가이드를 마크다운으로 저장 (비밀 문서)"""
        tts = recipe.tts_guide

        content = f"""# TTS 녹음 가이드 (비밀)

> 이 문서는 ElevenLabs v3로 목소리를 클론한 후 GPT-SoVITS로 재학습하기 위한 가이드입니다.
> 생성일: {recipe.analyzed_at}

## 1. 타겟 영상 정보

- **영상**: {recipe.video_title}
- **채널**: {recipe.channel_title}
- **스타일**: {recipe.style_type}
- **난이도**: {recipe.clone_difficulty}

---

## 2. 목소리 스펙

| 항목 | 값 |
|------|-----|
| 성별 | {tts.voice_gender} |
| 연령대 | {tts.voice_age} |
| 톤 | {tts.voice_tone} |

---

## 3. 필요한 감정 목록

{chr(10).join(f'- **{e}**' for e in tts.required_emotions)}

---

## 4. 샘플 대사 스크립트

각 감정당 3~5초 분량으로 녹음하세요.

"""

        for emotion, script in tts.sample_scripts.items():
            content += f"""### {emotion.upper()}

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

---

## 7. 재학습 순서

1. ElevenLabs에서 위 스펙에 맞는 목소리 검색 또는 생성
2. 샘플 대사 녹음 (감정당 3개 이상)
3. GPT-SoVITS 학습 마법사에서 학습
4. .revpack에 모델 번들링

---

*이 문서는 자동 생성되었습니다. Reverie Insight v1.2.0*
"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return output_path

    # ============================================================
    # 정리
    # ============================================================

    def cleanup(self, video_id: Optional[str] = None):
        """임시 파일 정리"""
        if video_id:
            # 특정 영상만 정리
            patterns = [
                f"{video_id}.mp4",
                f"{video_id}_frames",
                f"{video_id}_grid.jpg"
            ]
            for pattern in patterns:
                path = self.work_dir / pattern
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
        else:
            # 전체 정리
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)
                self.work_dir.mkdir(parents=True, exist_ok=True)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print("StyleAnalyzer 모듈 로드 완료")
    print(f"OpenCV: {'사용 가능' if CV2_AVAILABLE else '사용 불가'}")
