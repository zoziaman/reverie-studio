# src/utils/gpu_checker.py
"""
GPU VRAM 사양 자동 체크 모듈

비개발자 친화적 경고 메시지 제공.
setup_wizard와 main_window에서 사용.

최소 사양: NVIDIA GPU 6GB VRAM
권장 사양: NVIDIA RTX 3060 12GB 이상
"""
import logging
import subprocess
from typing import Dict, Any

logger = logging.getLogger(__name__)

MIN_VRAM_GB = 6.0
RECOMMENDED_VRAM_GB = 8.0


def check_gpu_vram() -> Dict[str, Any]:
    """
    GPU VRAM 자동 체크

    PyTorch → nvidia-smi 순서로 시도.

    Returns:
        dict: {
            available: bool,        # 최소 사양 충족 여부
            gpu_name: str,          # GPU 이름
            vram_total_gb: float,   # 전체 VRAM (GB)
            vram_free_gb: float,    # 여유 VRAM (GB)
            warning: str,           # 경고 메시지 (빈 문자열이면 정상)
            recommended: bool,      # 권장 사양 충족 여부
            method: str,            # 감지 방법 (torch / nvidia-smi / none)
        }
    """
    result = {
        "available": False,
        "gpu_name": "",
        "vram_total_gb": 0.0,
        "vram_free_gb": 0.0,
        "warning": "",
        "recommended": False,
        "method": "none",
    }

    # 1차: PyTorch (이미 설치되어 있으면 가장 정확)
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            result["gpu_name"] = torch.cuda.get_device_name(0)
            result["vram_total_gb"] = round(props.total_mem / (1024 ** 3), 1)
            result["vram_free_gb"] = round(
                (props.total_mem - torch.cuda.memory_allocated(0)) / (1024 ** 3), 1
            )
            result["method"] = "torch"
            return _evaluate(result)
    except (ImportError, Exception) as e:
        logger.debug(f"PyTorch GPU 감지 실패 (nvidia-smi 시도): {e}")

    # 2차: nvidia-smi (PyTorch 없어도 동작)
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            timeout=10, stderr=subprocess.STDOUT
        ).decode("utf-8").strip()

        lines = output.split("\n")
        if lines:
            parts = lines[0].split(", ")
            if len(parts) >= 3:
                result["gpu_name"] = parts[0].strip()
                result["vram_total_gb"] = round(float(parts[1].strip()) / 1024, 1)
                result["vram_free_gb"] = round(float(parts[2].strip()) / 1024, 1)
                result["method"] = "nvidia-smi"
                return _evaluate(result)
    except FileNotFoundError:
        logger.debug("nvidia-smi 미설치")
    except Exception as e:
        logger.debug(f"nvidia-smi 실행 실패: {e}")

    # 감지 실패
    result["warning"] = (
        "NVIDIA GPU를 감지할 수 없습니다.\n\n"
        "Reverie Studio는 NVIDIA GPU(CUDA 지원, 6GB VRAM 이상)가 필수입니다.\n"
        "- NVIDIA 드라이버가 최신인지 확인하세요\n"
        "- AMD GPU, Intel 내장 그래픽은 지원하지 않습니다\n"
        "- 노트북의 경우 전용 GPU가 활성화되어 있는지 확인하세요"
    )
    return result


def _evaluate(result: Dict[str, Any]) -> Dict[str, Any]:
    """사양 평가 후 경고 메시지 설정"""
    vram = result["vram_total_gb"]
    gpu = result["gpu_name"]

    result["available"] = vram >= MIN_VRAM_GB
    result["recommended"] = vram >= RECOMMENDED_VRAM_GB

    if vram < MIN_VRAM_GB:
        result["warning"] = (
            f"GPU VRAM 부족: {gpu} ({vram}GB)\n\n"
            f"최소 {MIN_VRAM_GB}GB 이상의 NVIDIA GPU가 필요합니다.\n"
            f"이미지 생성(Stable Diffusion)이 실행되지 않거나 매우 느릴 수 있습니다.\n\n"
            f"권장: RTX 3060 12GB 이상"
        )
    elif vram < RECOMMENDED_VRAM_GB:
        result["warning"] = (
            f"GPU: {gpu} ({vram}GB) - 최소 사양 충족\n\n"
            f"동작은 가능하지만 {RECOMMENDED_VRAM_GB}GB 이상을 권장합니다.\n"
            f"이미지 해상도가 768x432로 제한됩니다.\n"
            f"TTS와 이미지 생성을 동시에 사용하면 VRAM 부족이 발생할 수 있습니다."
        )
    # else: 충분하면 warning 비움

    return result


def get_gpu_summary_text() -> str:
    """GUI 표시용 한 줄 요약"""
    info = check_gpu_vram()

    if info["method"] == "none":
        return "GPU: 감지 불가 (NVIDIA GPU 필요)"

    vram = info["vram_total_gb"]
    gpu = info["gpu_name"]

    if not info["available"]:
        return f"GPU: {gpu} ({vram}GB) - VRAM 부족"
    elif not info["recommended"]:
        return f"GPU: {gpu} ({vram}GB) - 최소 사양"
    else:
        return f"GPU: {gpu} ({vram}GB) - OK"
