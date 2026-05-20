# src/utils/hardware_id.py
"""
하드웨어 ID 수집 모듈
시스템 고유 ID를 생성하여 라이센스와 바인딩
"""
import logging
import platform
import uuid
import hashlib
import subprocess
import socket
import os

logger = logging.getLogger(__name__)


def get_hardware_id() -> str:
    """
    시스템 고유 ID 생성
    
    수집 정보:
    - CPU 정보
    - 메인보드 시리얼
    - MAC 주소
    
    Returns:
        str: 16자 해시 (예: A1B2C3D4E5F6G7H8)
    """
    components = []
    
    # 1. CPU 정보
    try:
        cpu_id = platform.processor()
        if cpu_id:
            components.append(cpu_id)
    except Exception as e:
        logger.debug(f"CPU 정보 조회 실패: {e}")

    # 2. 메인보드 시리얼 (Windows)
    try:
        if platform.system() == "Windows":
            cmd = "wmic baseboard get serialnumber"
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()
            lines = output.strip().split('\n')
            if len(lines) > 1:
                board_serial = lines[1].strip()
                if board_serial and board_serial != "To Be Filled By O.E.M.":
                    components.append(board_serial)
    except Exception as e:
        logger.debug(f"메인보드 시리얼 조회 실패: {e}")

    # 3. MAC 주소
    try:
        mac = uuid.getnode()
        mac_str = ':'.join(['{:02x}'.format((mac >> elements) & 0xff) 
                           for elements in range(0, 2*6, 2)][::-1])
        components.append(mac_str)
    except Exception as e:
        logger.debug(f"MAC 주소 조회 실패: {e}")

    # 4. 최소 1개 이상의 정보가 있어야 함
    if not components:
        # ✅ 수정: 랜덤 UUID 대신 '컴퓨터명+사용자명' 조합으로 고정 ID 생성
        try:
            hostname = socket.gethostname()
            username = os.getenv('USERNAME') or os.getenv('USER') or "UnknownUser"
            static_fallback = f"{hostname}-{username}"
            components.append(static_fallback)
        except Exception:
            # 최후의 수단 (정말 아무것도 안 될 때만 고정 문자열)
            components.append("REVERIE_FALLBACK_ID_V1")
    
    # 조합 후 해시
    combined = "|".join(components)
    hash_value = hashlib.sha256(combined.encode()).hexdigest()
    
    # 16자로 자르기
    return hash_value[:16].upper()


def get_system_info() -> dict:
    """
    시스템 정보 수집 (디버깅용)
    
    Returns:
        dict: 시스템 정보
    """
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }


if __name__ == "__main__":
    # 테스트 실행
    print("=" * 60)
    print("하드웨어 ID 확인")
    print("=" * 60)
    
    hw_id = get_hardware_id()
    print(f"\n하드웨어 ID: {hw_id}")
    print("\n※ 이 ID를 개발자에게 전달하여 라이센스를 발급받으세요.")
    
    print("\n" + "=" * 60)
    print("시스템 정보")
    print("=" * 60)
    
    info = get_system_info()
    for key, value in info.items():
        print(f"{key:20s}: {value}")
    
    print("\n" + "=" * 60)