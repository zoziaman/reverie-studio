"""
Remotion Bridge for Reverie Studio
Python에서 Remotion CLI를 호출하여 영상 렌더링
v1.0.0
"""

import json
import subprocess
import os
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImageSegment:
    """이미지 세그먼트 정보"""
    path: str
    start_frame: int
    duration_frames: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "startFrame": self.start_frame,
            "durationFrames": self.duration_frames,
        }


@dataclass
class AudioSegment:
    """오디오 세그먼트 정보"""
    path: str
    start_frame: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "startFrame": self.start_frame,
        }


@dataclass
class SubtitleSegment:
    """자막 세그먼트 정보"""
    text: str
    speaker: str
    start_frame: int
    duration_frames: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "speaker": self.speaker,
            "startFrame": self.start_frame,
            "durationFrames": self.duration_frames,
        }


class RemotionBridge:
    """
    Remotion CLI를 Python에서 호출하는 브릿지

    사용법:
        bridge = RemotionBridge("C:/ReverieStudio/remotion-poc")
        bridge.add_image("image.png", start_frame=0, duration_frames=90)
        bridge.add_audio("audio.wav", start_frame=0)
        bridge.add_subtitle("안녕하세요", "나레이터", start_frame=0, duration_frames=90)
        bridge.render("output.mp4")
    """

    def __init__(
        self,
        remotion_project_path: str,
        fps: int = 30,
        width: int = 1920,
        height: int = 1080,
        concurrency: int = 6,
    ):
        self.project_path = Path(remotion_project_path)
        self.fps = fps
        self.width = width
        self.height = height
        self.concurrency = concurrency

        self.images: List[ImageSegment] = []
        self.audio_segments: List[AudioSegment] = []
        self.subtitles: List[SubtitleSegment] = []
        self.bgm_path: Optional[str] = None
        self.bgm_volume: float = 0.15

        # Remotion 프로젝트 존재 확인
        if not (self.project_path / "package.json").exists():
            raise FileNotFoundError(f"Remotion project not found at {self.project_path}")

    def clear(self):
        """모든 세그먼트 초기화"""
        self.images.clear()
        self.audio_segments.clear()
        self.subtitles.clear()
        self.bgm_path = None

    def add_image(self, path: str, start_frame: int, duration_frames: int):
        """이미지 추가"""
        self.images.append(ImageSegment(
            path=str(Path(path).as_posix()),  # URL 형식으로 변환
            start_frame=start_frame,
            duration_frames=duration_frames,
        ))

    def add_audio(self, path: str, start_frame: int):
        """오디오 세그먼트 추가"""
        self.audio_segments.append(AudioSegment(
            path=str(Path(path).as_posix()),
            start_frame=start_frame,
        ))

    def add_subtitle(self, text: str, speaker: str, start_frame: int, duration_frames: int):
        """자막 추가"""
        self.subtitles.append(SubtitleSegment(
            text=text,
            speaker=speaker,
            start_frame=start_frame,
            duration_frames=duration_frames,
        ))

    def set_bgm(self, path: str, volume: float = 0.15):
        """BGM 설정"""
        self.bgm_path = str(Path(path).as_posix())
        self.bgm_volume = volume

    def get_total_frames(self) -> int:
        """총 프레임 수 계산"""
        if not self.images:
            return 0
        last_image = max(self.images, key=lambda x: x.start_frame + x.duration_frames)
        return last_image.start_frame + last_image.duration_frames

    def _build_props(self) -> Dict[str, Any]:
        """Remotion에 전달할 props 생성"""
        return {
            "images": [img.to_dict() for img in self.images],
            "audioSegments": [audio.to_dict() for audio in self.audio_segments],
            "subtitles": [sub.to_dict() for sub in self.subtitles],
            "bgmPath": self.bgm_path,
            "bgmVolume": self.bgm_volume,
            "totalFrames": self.get_total_frames(),
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
        }

    def render(
        self,
        output_path: str,
        codec: str = "h264",
        crf: int = 18,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """
        Remotion으로 영상 렌더링

        Args:
            output_path: 출력 파일 경로
            codec: 코덱 (h264, h265, vp8, vp9, prores)
            crf: 품질 (0-51, 낮을수록 고품질)
            verbose: 상세 로그 출력

        Returns:
            렌더링 결과 정보 (시간, 파일 크기 등)
        """
        props = self._build_props()
        props_json = json.dumps(props, ensure_ascii=False)

        # props를 임시 파일로 저장 (긴 JSON은 CLI 인자로 전달이 어려움)
        props_file = self.project_path / "temp_props.json"
        with open(props_file, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False, indent=2)

        # Remotion CLI 명령어 구성
        cmd = [
            "npx", "remotion", "render",
            "RadioDrama",
            str(output_path),
            f"--props={props_file}",
            f"--concurrency={self.concurrency}",
            f"--codec={codec}",
            f"--crf={crf}",
        ]

        if verbose:
            cmd.append("--log=verbose")

        logger.info(f"[RemotionBridge] 렌더링 시작: {output_path}")
        logger.info(f"[RemotionBridge] 총 프레임: {props['totalFrames']}, FPS: {self.fps}")
        logger.info(f"[RemotionBridge] 이미지: {len(self.images)}개, 오디오: {len(self.audio_segments)}개")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                shell=True,  # Windows에서 npx 실행을 위해
            )

            elapsed = time.time() - start_time

            if result.returncode != 0:
                logger.error(f"[RemotionBridge] 렌더링 실패: {result.stderr}")
                raise RuntimeError(f"Remotion render failed: {result.stderr}")

            # 결과 파일 확인
            output_file = Path(output_path)
            if not output_file.exists():
                raise FileNotFoundError(f"Output file not created: {output_path}")

            file_size = output_file.stat().st_size / (1024 * 1024)  # MB

            logger.info(f"[RemotionBridge] 렌더링 완료: {elapsed:.1f}초, {file_size:.1f}MB")

            return {
                "success": True,
                "output_path": str(output_path),
                "elapsed_seconds": elapsed,
                "file_size_mb": file_size,
                "total_frames": props["totalFrames"],
                "fps": self.fps,
                "duration_seconds": props["totalFrames"] / self.fps,
            }

        finally:
            # 임시 파일 정리
            if props_file.exists():
                props_file.unlink()


def test_bridge():
    """브릿지 테스트"""
    project_path = Path(__file__).resolve().parent
    bridge = RemotionBridge(
        remotion_project_path=str(project_path),
        fps=30,
        concurrency=6,
    )

    # public 폴더의 이미지/오디오 사용
    public_path = project_path / "public"

    # 10개 이미지 추가 (각 3초)
    for i in range(1, 11):
        img_path = public_path / "images" / f"{i:03d}.png"
        if img_path.exists():
            bridge.add_image(
                path=f"images/{i:03d}.png",  # staticFile 경로
                start_frame=(i - 1) * 90,
                duration_frames=90,
            )

    # 자막 추가
    speakers = ["나레이터", "여자", "나레이터", "남자", "나레이터",
                "여자", "남자", "나레이터", "남자", "남자"]
    for i, speaker in enumerate(speakers):
        bridge.add_subtitle(
            text=f"테스트 자막 {i + 1}",
            speaker=speaker,
            start_frame=i * 90,
            duration_frames=90,
        )

    # 렌더링
    result = bridge.render(
        output_path=str(project_path / "out" / "bridge_test.mp4"),
        verbose=True,
    )

    print(f"\n렌더링 결과:")
    print(f"  - 소요 시간: {result['elapsed_seconds']:.1f}초")
    print(f"  - 파일 크기: {result['file_size_mb']:.1f}MB")
    print(f"  - 영상 길이: {result['duration_seconds']:.1f}초")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_bridge()
