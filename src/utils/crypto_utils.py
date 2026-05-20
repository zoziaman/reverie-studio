# src/utils/crypto_utils.py
"""
암호화 유틸리티 모듈 (v62.22 보안 강화)

- Fernet 기반 대칭키 암호화 (AES-128-CBC + HMAC-SHA256)
- PBKDF2 기반 키 파생 (하드웨어 ID → Fernet 키)
- Atomic JSON write (temp + rename)
- 암호화된 JSON 읽기/쓰기

크몽 배포 전 보안 필수 모듈.
"""
import os
import json
import base64
import hashlib
import tempfile
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Fernet 사용 가능 여부 (cryptography 미설치 환경 대비)
try:
    from cryptography.fernet import Fernet, InvalidToken
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False
    Fernet = None
    InvalidToken = Exception
    logger.warning("[CryptoUtils] cryptography 라이브러리 미설치 — 암호화 비활성")


# ============================================================
# 키 파생
# ============================================================

def derive_fernet_key(password: str, salt: str = "reverie_studio_2025") -> bytes:
    """
    PBKDF2 기반 Fernet 키 파생

    Args:
        password: 비밀번호 (하드웨어 ID 등)
        salt: 솔트 (고정값, 앱 단위)

    Returns:
        bytes: 32바이트 base64url 인코딩된 Fernet 키
    """
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100_000,
        dklen=32
    )
    return base64.urlsafe_b64encode(key)


# ============================================================
# Fernet 암호화/복호화
# ============================================================

def fernet_encrypt(plaintext: str, key: bytes) -> str:
    """
    Fernet 암호화

    Args:
        plaintext: 평문 문자열
        key: derive_fernet_key()로 생성한 키

    Returns:
        str: 암호화된 토큰 (gAAAAA... 형태)
    """
    if not FERNET_AVAILABLE:
        raise RuntimeError("cryptography 라이브러리가 설치되지 않았습니다.")
    f = Fernet(key)
    return f.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def fernet_decrypt(encrypted: str, key: bytes) -> str:
    """
    Fernet 복호화

    Args:
        encrypted: 암호화된 토큰
        key: derive_fernet_key()로 생성한 키

    Returns:
        str: 복호화된 평문

    Raises:
        InvalidToken: 키 불일치 또는 변조
    """
    if not FERNET_AVAILABLE:
        raise RuntimeError("cryptography 라이브러리가 설치되지 않았습니다.")
    f = Fernet(key)
    return f.decrypt(encrypted.encode('utf-8')).decode('utf-8')


def fernet_encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """
    바이트 데이터 Fernet 암호화

    Args:
        data: 바이트 데이터 (pickle 등)
        key: derive_fernet_key()로 생성한 키

    Returns:
        bytes: 암호화된 토큰
    """
    if not FERNET_AVAILABLE:
        raise RuntimeError("cryptography 라이브러리가 설치되지 않았습니다.")
    f = Fernet(key)
    return f.encrypt(data)


def fernet_decrypt_bytes(encrypted: bytes, key: bytes) -> bytes:
    """
    바이트 데이터 Fernet 복호화

    Args:
        encrypted: 암호화된 토큰
        key: derive_fernet_key()로 생성한 키

    Returns:
        bytes: 복호화된 바이트 데이터

    Raises:
        InvalidToken: 키 불일치 또는 변조
    """
    if not FERNET_AVAILABLE:
        raise RuntimeError("cryptography 라이브러리가 설치되지 않았습니다.")
    f = Fernet(key)
    return f.decrypt(encrypted)


# ============================================================
# Atomic JSON 읽기/쓰기
# ============================================================

def atomic_json_write(path: str, data: Any):
    """
    Atomic JSON 쓰기 (temp → rename 패턴)

    프로세스 중단 시에도 원본 파일 손상 방지.
    Windows에서 os.replace()는 atomic 보장.

    Args:
        path: 저장할 파일 경로
        data: JSON 직렬화 가능한 데이터
    """
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)  # Atomic on Windows
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_json_read(path: str) -> Optional[Any]:
    """
    JSON 파일 안전 읽기

    Args:
        path: 파일 경로

    Returns:
        파싱된 데이터 또는 None
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
        logger.debug(f"[CryptoUtils] JSON 로드 실패 ({path}): {e}")
        return None


# ============================================================
# 암호화된 JSON 읽기/쓰기
# ============================================================

def encrypted_json_write(path: str, data: Any, key: bytes):
    """
    Fernet 암호화 + Atomic JSON 쓰기

    파일 내용: Fernet 토큰 (텍스트, gAAAAA... 형태)

    Args:
        path: 저장할 파일 경로
        data: JSON 직렬화 가능한 데이터
        key: derive_fernet_key()로 생성한 키
    """
    plaintext = json.dumps(data, ensure_ascii=False, indent=2)
    encrypted = fernet_encrypt(plaintext, key)

    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(encrypted)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def encrypted_json_read(path: str, key: bytes) -> Optional[Any]:
    """
    Fernet 암호화된 JSON 읽기 (평문 JSON 자동 마이그레이션 포함)

    동작:
    1. 파일 내용이 gAAAAA로 시작 → Fernet 복호화 후 JSON 파싱
    2. 파일 내용이 { 또는 [ 로 시작 → 평문 JSON → 자동 암호화 마이그레이션

    Args:
        path: 파일 경로
        key: derive_fernet_key()로 생성한 키

    Returns:
        파싱된 데이터 또는 None
    """
    if not os.path.exists(path):
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except (FileNotFoundError, OSError) as e:
        logger.debug(f"[CryptoUtils] 파일 읽기 실패 ({path}): {e}")
        return None

    if not content:
        return None

    # Case 1: Fernet 암호화된 파일
    if content.startswith('gAAAAA'):
        try:
            decrypted = fernet_decrypt(content, key)
            return json.loads(decrypted)
        except InvalidToken as e:
            logger.debug(f"[CryptoUtils] Fernet 복호화 실패 ({path}): {e}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"[CryptoUtils] 복호화 후 JSON 파싱 실패 ({path}): {e}")
            return None

    # Case 2: 평문 JSON → 자동 마이그레이션
    if content.startswith('{') or content.startswith('['):
        try:
            data = json.loads(content)
            # 자동 암호화 마이그레이션
            try:
                encrypted_json_write(path, data, key)
                logger.info(f"[CryptoUtils] 평문 → 암호화 마이그레이션 완료: {path}")
            except Exception as e:
                logger.warning(f"[CryptoUtils] 마이그레이션 쓰기 실패 ({path}): {e}")
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"[CryptoUtils] JSON 파싱 실패 ({path}): {e}")
            return None

    # Case 3: 알 수 없는 형식
    logger.debug(f"[CryptoUtils] 알 수 없는 파일 형식 ({path})")
    return None
