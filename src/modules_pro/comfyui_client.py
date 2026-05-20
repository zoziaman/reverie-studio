# src/modules_pro/comfyui_client.py
# ============================================================
# [v50] ComfyUI API Client
#
# ComfyUI 서버와 통신하여 AnimateDiff 영상을 생성하는 클라이언트
# - 워크플로우 실행
# - 이미지/영상 생성 요청
# - 결과 다운로드
# ============================================================
import os
import json
import time
import uuid
import logging

# HTTP 요청
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# WebSocket (선택적)
try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass
from enum import Enum
from utils.runtime_utils import parse_url_host_port

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("comfyui_client")
except ImportError:
    logger = logging.getLogger("comfyui_client")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


class ComfyUIError(Exception):
    """ComfyUI 관련 예외"""
    pass


class GenerationMode(Enum):
    """v50 생성 모드"""
    QUALITY = "quality"      # 고품질 (Flux + SVD) - 공포 채널용
    SPEED = "speed"          # 속도 우선 (SD 1.5 + AnimateDiff) - 시니어 채널용


@dataclass
class ComfyUIConfig:
    """ComfyUI 설정 — v60.1.0: config.COMFYUI_URL에서 기본값 유도"""
    host: str = None
    port: int = None
    timeout: int = 300  # 5분

    def __post_init__(self):
        if self.host is None or self.port is None:
            try:
                from config.settings import config as _cfg
                _h, _p = parse_url_host_port(
                    getattr(_cfg, 'COMFYUI_URL', 'http://127.0.0.1:8188'),
                    "127.0.0.1", 8188
                )
                if self.host is None:
                    self.host = _h
                if self.port is None:
                    self.port = _p
            except ImportError:
                if self.host is None:
                    self.host = "127.0.0.1"
                if self.port is None:
                    self.port = 8188

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"


class ComfyUIClient:
    """
    ComfyUI API 클라이언트

    사용법:
        client = ComfyUIClient()
        if client.check_connection():
            result = client.generate_animated_image(
                prompt="dark haunted house, horror atmosphere",
                negative_prompt="bright, happy",
                checkpoint="dreamshaper_8.safetensors"
            )
    """

    def __init__(self, config: Optional[ComfyUIConfig] = None):
        self.config = config or ComfyUIConfig()
        self.client_id = str(uuid.uuid4())
        self._ws = None

        # 의존성 확인
        if not REQUESTS_AVAILABLE:
            logger.warning("[ComfyUI] requests 패키지 없음. pip install requests")
        if not WEBSOCKET_AVAILABLE:
            logger.warning("[ComfyUI] websocket-client 패키지 없음. pip install websocket-client")

    def check_connection(self) -> bool:
        """ComfyUI 서버 연결 확인"""
        if not REQUESTS_AVAILABLE:
            logger.error("[ComfyUI] requests 패키지가 필요합니다.")
            return False

        try:
            response = requests.get(
                f"{self.config.base_url}/system_stats",
                timeout=5
            )
            if response.status_code == 200:
                logger.info(f"[ComfyUI] 서버 연결 성공: {self.config.base_url}")
                return True
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ComfyUI] 서버 연결 실패: {e}")
        return False

    def get_available_models(self) -> Dict[str, List[str]]:
        """사용 가능한 모델 목록 조회"""
        try:
            response = requests.get(
                f"{self.config.base_url}/object_info",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()

                models = {
                    "checkpoints": [],
                    "animatediff": [],
                    "loras": [],
                    "vaes": []
                }

                # CheckpointLoaderSimple에서 체크포인트 목록 추출
                if "CheckpointLoaderSimple" in data:
                    ckpt_info = data["CheckpointLoaderSimple"]
                    if "input" in ckpt_info and "required" in ckpt_info["input"]:
                        if "ckpt_name" in ckpt_info["input"]["required"]:
                            models["checkpoints"] = ckpt_info["input"]["required"]["ckpt_name"][0]

                # AnimateDiff 모델 목록
                if "ADE_LoadAnimateDiffModel" in data:
                    ad_info = data["ADE_LoadAnimateDiffModel"]
                    if "input" in ad_info and "required" in ad_info["input"]:
                        if "model_name" in ad_info["input"]["required"]:
                            models["animatediff"] = ad_info["input"]["required"]["model_name"][0]

                logger.info(f"[ComfyUI] 모델 목록 조회 완료: "
                           f"체크포인트 {len(models['checkpoints'])}개, "
                           f"AnimateDiff {len(models['animatediff'])}개")
                return models

        except Exception as e:
            logger.error(f"[ComfyUI] 모델 목록 조회 실패: {e}")

        return {"checkpoints": [], "animatediff": [], "loras": [], "vaes": []}

    def queue_prompt(self, workflow: Dict) -> str:
        """워크플로우 실행 큐에 추가"""
        payload = {
            "prompt": workflow,
            "client_id": self.client_id
        }

        try:
            response = requests.post(
                f"{self.config.base_url}/prompt",
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                prompt_id = result.get("prompt_id")
                logger.info(f"[ComfyUI] 작업 큐 추가: {prompt_id}")
                return prompt_id
            else:
                error_msg = response.text
                logger.error(f"[ComfyUI] 큐 추가 실패: {error_msg}")
                raise ComfyUIError(f"큐 추가 실패: {error_msg}")

        except requests.exceptions.RequestException as e:
            logger.error(f"[ComfyUI] 요청 실패: {e}")
            raise ComfyUIError(f"요청 실패: {e}")

    def wait_for_completion(
        self,
        prompt_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        작업 완료 대기

        Args:
            prompt_id: 프롬프트 ID
            progress_callback: 진행률 콜백 (percent, message)
            timeout: 타임아웃 (초)

        Returns:
            출력 결과 딕셔너리
        """
        if not WEBSOCKET_AVAILABLE:
            # WebSocket 없으면 폴링으로 대체
            return self._wait_for_completion_polling(prompt_id, progress_callback, timeout)

        timeout = timeout or self.config.timeout
        start_time = time.time()

        try:
            # WebSocket 연결
            ws = websocket.create_connection(
                f"{self.config.ws_url}?clientId={self.client_id}",
                timeout=10
            )

            while True:
                # 타임아웃 체크
                if time.time() - start_time > timeout:
                    ws.close()
                    raise ComfyUIError(f"작업 타임아웃: {timeout}초 초과")

                # 메시지 수신
                try:
                    ws.settimeout(1.0)
                    message = ws.recv()
                    data = json.loads(message)

                    msg_type = data.get("type")
                    msg_data = data.get("data", {})

                    if msg_type == "progress":
                        # 진행률 업데이트
                        value = msg_data.get("value", 0)
                        max_val = msg_data.get("max", 100)
                        percent = int((value / max_val) * 100) if max_val > 0 else 0

                        if progress_callback:
                            progress_callback(percent, f"생성 중... {percent}%")

                    elif msg_type == "executing":
                        node = msg_data.get("node")
                        if node is None:
                            # 실행 완료
                            logger.info(f"[ComfyUI] 작업 완료: {prompt_id}")
                            ws.close()
                            return self._get_history(prompt_id)

                    elif msg_type == "execution_error":
                        error = msg_data.get("exception_message", "알 수 없는 오류")
                        ws.close()
                        raise ComfyUIError(f"실행 오류: {error}")

                except websocket.WebSocketTimeoutException:
                    continue

        except websocket.WebSocketException as e:
            logger.error(f"[ComfyUI] WebSocket 오류: {e}")
            raise ComfyUIError(f"WebSocket 오류: {e}")

    def _wait_for_completion_polling(
        self,
        prompt_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        WebSocket 없이 폴링으로 작업 완료 대기 (폴백)
        """
        timeout = timeout or self.config.timeout
        start_time = time.time()
        poll_interval = 2.0  # 2초마다 확인

        logger.info(f"[ComfyUI] 폴링 모드로 대기 중: {prompt_id}")

        while True:
            elapsed = time.time() - start_time

            if elapsed > timeout:
                raise ComfyUIError(f"작업 타임아웃: {timeout}초 초과")

            # 히스토리에서 완료 여부 확인
            try:
                response = requests.get(
                    f"{self.config.base_url}/history/{prompt_id}",
                    timeout=10
                )

                if response.status_code == 200:
                    history = response.json()
                    if prompt_id in history:
                        result = history[prompt_id]
                        # outputs가 있으면 완료된 것
                        if result.get("outputs"):
                            logger.info(f"[ComfyUI] 작업 완료: {prompt_id}")
                            if progress_callback:
                                progress_callback(100, "완료")
                            return result

            except Exception as e:
                logger.warning(f"[ComfyUI] 폴링 중 오류: {e}")

            # 진행률 표시 (추정)
            if progress_callback:
                estimated_percent = min(int((elapsed / timeout) * 100), 95)
                progress_callback(estimated_percent, f"생성 중... {int(elapsed)}초 경과")

            time.sleep(poll_interval)

    def _get_history(self, prompt_id: str) -> Dict[str, Any]:
        """실행 히스토리에서 결과 조회"""
        try:
            response = requests.get(
                f"{self.config.base_url}/history/{prompt_id}",
                timeout=10
            )

            if response.status_code == 200:
                history = response.json()
                if prompt_id in history:
                    return history[prompt_id]

        except Exception as e:
            logger.error(f"[ComfyUI] 히스토리 조회 실패: {e}")

        return {}

    def download_output(
        self,
        filename: str,
        subfolder: str = "",
        output_type: str = "output"
    ) -> bytes:
        """
        생성된 파일 다운로드

        Args:
            filename: 파일명
            subfolder: 서브폴더
            output_type: 출력 타입 (output, temp)

        Returns:
            파일 바이트 데이터
        """
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": output_type
        }

        try:
            response = requests.get(
                f"{self.config.base_url}/view",
                params=params,
                timeout=60
            )

            if response.status_code == 200:
                return response.content
            else:
                raise ComfyUIError(f"다운로드 실패: {response.status_code}")

        except requests.exceptions.RequestException as e:
            raise ComfyUIError(f"다운로드 요청 실패: {e}")

    def save_output(
        self,
        filename: str,
        save_path: str,
        subfolder: str = "",
        output_type: str = "output"
    ) -> str:
        """
        생성된 파일을 로컬에 저장

        Args:
            filename: 원본 파일명
            save_path: 저장 경로
            subfolder: 서브폴더
            output_type: 출력 타입

        Returns:
            저장된 파일 경로
        """
        data = self.download_output(filename, subfolder, output_type)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        with open(save_path, "wb") as f:
            f.write(data)

        logger.info(f"[ComfyUI] 파일 저장: {save_path}")
        return save_path

    def build_animatediff_workflow(
        self,
        prompt: str,
        negative_prompt: str = "",
        checkpoint: str = "dreamshaper_8.safetensors",
        motion_model: str = "animatediff_lightning_8step_diffusers.safetensors",
        width: int = 512,
        height: int = 512,
        frames: int = 16,
        fps: int = 8,
        steps: int = 8,
        cfg: float = 1.5,
        seed: int = -1
    ) -> Dict:
        """
        AnimateDiff Lightning 워크플로우 생성

        Args:
            prompt: 프롬프트
            negative_prompt: 네거티브 프롬프트
            checkpoint: SD 체크포인트 파일명
            motion_model: AnimateDiff 모델 파일명
            width: 너비
            height: 높이
            frames: 프레임 수 (8~32)
            fps: FPS
            steps: 샘플링 스텝 (Lightning은 4~8 권장)
            cfg: CFG 스케일 (Lightning은 1.0~2.0 권장)
            seed: 시드 (-1이면 랜덤)

        Returns:
            ComfyUI 워크플로우 딕셔너리
        """
        import random

        if seed == -1:
            seed = random.randint(0, 2**32 - 1)

        # 기본 네거티브 확장 (v50 프리미엄 스타일)
        default_negative = "blurry, low quality, distorted, deformed, disfigured, bad anatomy, bad hands, missing fingers, extra fingers"
        full_negative = f"{negative_prompt}, {default_negative}" if negative_prompt else default_negative

        workflow = {
            # 체크포인트 로더
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": checkpoint
                }
            },

            # AnimateDiff 모션 모델 로더
            "2": {
                "class_type": "ADE_LoadAnimateDiffModel",
                "inputs": {
                    "model_name": motion_model
                }
            },

            # AnimateDiff 적용 - motion_model만 받음 (model 파라미터 제거)
            # [v50 패치] 최신 AnimateDiff-Evolved API 호환
            "3": {
                "class_type": "ADE_ApplyAnimateDiffModelSimple",
                "inputs": {
                    "motion_model": ["2", 0]
                }
            },

            # Evolved Sampling 사용 (MODEL + M_MODELS 연결)
            "10": {
                "class_type": "ADE_UseEvolvedSampling",
                "inputs": {
                    "model": ["1", 0],
                    "m_models": ["3", 0],
                    "beta_schedule": "sqrt_linear (AnimateDiff)"
                }
            },

            # 빈 Latent 이미지 (배치)
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": frames
                }
            },

            # 프롬프트 인코딩
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["1", 1]
                }
            },

            # 네거티브 프롬프트 인코딩
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": full_negative,
                    "clip": ["1", 1]
                }
            },

            # KSampler (Evolved Sampling 모델 사용)
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["10", 0],
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": ["4", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler",
                    "scheduler": "sgm_uniform",
                    "denoise": 1.0
                }
            },

            # VAE 디코드
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["7", 0],
                    "vae": ["1", 2]
                }
            },

            # 비디오 저장 (VideoHelperSuite)
            "9": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["8", 0],
                    "frame_rate": fps,
                    "loop_count": 0,
                    "filename_prefix": "animatediff",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True
                }
            }
        }

        return workflow

    def generate_animated_clip(
        self,
        prompt: str,
        negative_prompt: str = "",
        checkpoint: str = "dreamshaper_8.safetensors",
        output_dir: str = "./output",
        output_filename: str = "clip",
        width: int = 512,
        height: int = 512,
        frames: int = 16,
        fps: int = 8,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Optional[str]:
        """
        AnimateDiff 영상 클립 생성

        Args:
            prompt: 이미지 프롬프트
            negative_prompt: 네거티브 프롬프트
            checkpoint: 체크포인트 파일명
            output_dir: 출력 디렉토리
            output_filename: 출력 파일명 (확장자 제외)
            width: 너비
            height: 높이
            frames: 프레임 수
            fps: FPS
            progress_callback: 진행률 콜백

        Returns:
            생성된 비디오 파일 경로 (실패 시 None)
        """
        try:
            # 워크플로우 생성
            workflow = self.build_animatediff_workflow(
                prompt=prompt,
                negative_prompt=negative_prompt,
                checkpoint=checkpoint,
                width=width,
                height=height,
                frames=frames,
                fps=fps
            )

            # 큐에 추가
            if progress_callback:
                progress_callback(0, "작업 큐 추가 중...")

            prompt_id = self.queue_prompt(workflow)

            # 완료 대기
            if progress_callback:
                progress_callback(10, "영상 생성 중...")

            result = self.wait_for_completion(prompt_id, progress_callback)

            # 결과에서 출력 파일 찾기
            outputs = result.get("outputs", {})

            for node_id, node_output in outputs.items():
                if "gifs" in node_output:
                    # VHS_VideoCombine 출력
                    for gif_info in node_output["gifs"]:
                        filename = gif_info.get("filename")
                        subfolder = gif_info.get("subfolder", "")

                        if filename:
                            # 파일 다운로드 및 저장
                            save_path = os.path.join(
                                output_dir,
                                f"{output_filename}.mp4"
                            )

                            self.save_output(
                                filename=filename,
                                save_path=save_path,
                                subfolder=subfolder
                            )

                            if progress_callback:
                                progress_callback(100, "완료!")

                            return save_path

            logger.warning("[ComfyUI] 출력 파일을 찾을 수 없음")
            return None

        except ComfyUIError as e:
            logger.error(f"[ComfyUI] 생성 실패: {e}")
            return None
        except Exception as e:
            logger.error(f"[ComfyUI] 예외 발생: {e}")
            return None


# ============================================================
# 편의 함수
# ============================================================
def get_comfyui_client(
    host: str = None,
    port: int = None
) -> ComfyUIClient:
    """ComfyUI 클라이언트 인스턴스 생성 — v60.1.0: config에서 기본값 유도"""
    comfy_config = ComfyUIConfig(host=host, port=port)
    return ComfyUIClient(comfy_config)


def test_comfyui_connection(host: str = None, port: int = None) -> bool:
    """ComfyUI 연결 테스트 — v60.1.0: config에서 기본값 유도"""
    client = get_comfyui_client(host, port)
    return client.check_connection()


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("ComfyUI Client Test")
    print("=" * 60)

    client = get_comfyui_client()

    # 연결 테스트
    if client.check_connection():
        print("[OK] ComfyUI 서버 연결 성공")

        # 모델 목록 조회
        models = client.get_available_models()
        print(f"\n[모델 목록]")
        print(f"  체크포인트: {models['checkpoints']}")
        print(f"  AnimateDiff: {models['animatediff']}")
    else:
        print("[FAIL] ComfyUI 서버에 연결할 수 없습니다.")
        print("ComfyUI가 실행 중인지 확인하세요:")
        print("  cd C:\\AI\\ComfyUI\\ComfyUI")
        print("  python main.py")
