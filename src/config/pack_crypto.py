# src/config/pack_crypto.py
# ============================================================
# ReveriePack 암호화 / 서명 / 접근 제어
# v62.42b: pack_config.py에서 분리
# ============================================================
"""
팩 보안 계층 — Fernet 암호화, HMAC-SHA256 서명, 라이선스 접근 제어, Firebase Phase B 서버 키.

이 모듈은 cryptography 라이브러리에 의존하며, 미설치 시 graceful fallback.
"""

import os
import json
import zipfile
import logging
import base64
import hashlib
import hmac as _hmac_mod
from pathlib import Path
from typing import Optional, Tuple

from config.path_utils import is_dev_mode_enabled

logger = logging.getLogger(__name__)


# ============================================================
# cryptography 라이브러리 가용성
# ============================================================

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("[PackCrypto] cryptography 미설치, 암호화된 팩 로드 불가")


# ============================================================
# DEV 모드 판정
# ============================================================

def _is_dev_pack_mode() -> bool:
    """Return True when local dev pack fallbacks are allowed."""
    if os.environ.get("REVERIE_DEV_MODE", "0") == "1":
        return True

    if is_dev_mode_enabled():
        return True

    try:
        from config.settings import config as app_config
        cwd = Path.cwd().resolve()
        base_dir = Path(app_config.BASE_DIR).resolve()
        if cwd == base_dir or base_dir in cwd.parents:
            return is_dev_mode_enabled(base_dir=app_config.BASE_DIR, data_dir=app_config.DATA_DIR)
    except Exception:
        return False

    return False


# ============================================================
# 암호화 설정 (pack_creator_full.py와 동일)
# ============================================================

# v62.23: 암호화 키 — 환경변수/런타임 키 우선
# v63: 레거시 하드코딩 키는 기본 비활성화, 명시적 migration opt-in에서만 허용
_DEFAULT_PACK_ENCRYPTION_SALT = b'ReveriePack2024Salt!'
_LEGACY_PACK_ENCRYPTION_PASSWORD_ENV = "REVERIE_PACK_LEGACY_PASSWORD"
_legacy_pack_key_warning_emitted = False
_runtime_pack_password: Optional[str] = None  # 라이선스 기반 런타임 키 (메모리 전용)


def _is_encrypted_pack_required() -> bool:
    """
    암호화된 .revpack 강제 여부

    환경변수:
    - REVERIE_PACK_REQUIRE_ENCRYPTED=1  -> 평문 ZIP .revpack 거부
    """
    return os.environ.get("REVERIE_PACK_REQUIRE_ENCRYPTED", "0") == "1"


def _allow_legacy_pack_key() -> bool:
    """
    하드코딩 레거시 키 허용 여부

    환경변수:
    - REVERIE_PACK_ALLOW_LEGACY_KEY=0 -> 레거시 키 완전 차단 (권장)
    """
    if _is_dev_pack_mode():
        return True
    return os.environ.get("REVERIE_PACK_ALLOW_LEGACY_KEY", "0") == "1"


def _get_legacy_pack_password_bytes() -> Optional[bytes]:
    """Return the external legacy migration password when explicitly supplied."""
    legacy_password = os.environ.get(_LEGACY_PACK_ENCRYPTION_PASSWORD_ENV, "")
    if not legacy_password:
        return None
    return legacy_password.encode("utf-8")


def configure_pack_crypto(license_key: str = "", hardware_id: str = "") -> bool:
    """
    라이선스 + 하드웨어 기반 런타임 팩 복호화 키 설정.

    보안 의도:
    - 팩 키를 고정 하드코딩 대신 실행 시점 동적으로 결정
    - 메인 윈도우에서는 정상 로드 가능, 외부 단독 복호화 난이도 상승

    Args:
        license_key: 사용자 라이선스 키
        hardware_id: 현재 하드웨어 ID

    Returns:
        설정 성공 여부
    """
    global _runtime_pack_password

    lk = (license_key or "").strip().upper()
    hw = (hardware_id or "").strip().upper()

    # 최소 한쪽은 있어야 동적 키를 만들 수 있음
    if not lk and not hw:
        return False

    # 라이선스 시크릿은 환경변수로만 주입한다.
    secret = os.environ.get("REVERIE_SECRET_KEY", "")
    if not secret:
        logger.warning("[PackCrypto] REVERIE_SECRET_KEY 미설정 — 런타임 팩 키 생성 불가")
        return False

    material = f"{lk}|{hw}|{secret}|REVERIE_PACK_V1"
    _runtime_pack_password = hashlib.sha256(material.encode("utf-8")).hexdigest()
    logger.info("[PackCrypto] 런타임 팩 키 설정 완료 (license/hwid 기반)")
    return True


def _resolve_pack_crypto_params() -> Tuple[bytes, Optional[bytes]]:
    """
    현재 실행 컨텍스트에서 팩 복호화용 (salt, password_bytes) 반환.
    password_bytes가 None이면 복호화 키 생성 불가.
    """
    salt_env = os.environ.get("REVERIE_PACK_SALT", "")
    salt = salt_env.encode("utf-8") if salt_env else _DEFAULT_PACK_ENCRYPTION_SALT

    # 1) 환경변수 우선
    pw_env = os.environ.get("REVERIE_PACK_PASSWORD", "")
    if pw_env:
        return salt, pw_env.encode("utf-8")

    # 2) Phase B: license/HWID-derived runtime password
    if _runtime_pack_password:
        return salt, _runtime_pack_password.encode("utf-8")

    # 3) Legacy migration is opt-in and requires an external password.
    if _allow_legacy_pack_key():
        legacy_password = _get_legacy_pack_password_bytes()
        if not legacy_password:
            logger.warning(
                "[PackCrypto] Legacy migration requested but REVERIE_PACK_LEGACY_PASSWORD is not set."
            )
            return salt, None
        global _legacy_pack_key_warning_emitted
        if not _legacy_pack_key_warning_emitted:
            logger.warning("[PackCrypto] 레거시 팩 키 허용 모드 활성화")
            _legacy_pack_key_warning_emitted = True
        return salt, legacy_password

    return salt, None


# ============================================================
# v62.25: 팩 무결성 서명 (HMAC-SHA256)
# ============================================================
# 서명 키: 암호화 패스워드 + 고정 suffix (암호화 키와 분리)
_PACK_SIGN_SUFFIX = b"_signature_v1"


def _get_pack_sign_key() -> bytes:
    """팩 서명용 HMAC 키 반환."""
    _, pw = _resolve_pack_crypto_params()
    if pw:
        return pw + _PACK_SIGN_SUFFIX

    secret = os.environ.get("REVERIE_SECRET_KEY", "")
    if secret:
        return secret.encode("utf-8") + _PACK_SIGN_SUFFIX

    raise RuntimeError("팩 서명 키를 생성할 수 없습니다. REVERIE_PACK_PASSWORD 또는 REVERIE_SECRET_KEY 필요")


def calc_pack_signature(zf: zipfile.ZipFile, sign_key: bytes) -> str:
    """
    ZIP 내 모든 파일의 HMAC-SHA256 계산.
    manifest.json의 'signature' 필드는 제외하고 계산.
    """
    h = _hmac_mod.new(sign_key, digestmod=hashlib.sha256)
    for name in sorted(zf.namelist()):
        content = zf.read(name)
        if name == "manifest.json":
            try:
                data = json.loads(content)
                data.pop("signature", None)
                content = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
            except Exception:
                pass
        h.update(name.encode("utf-8") + b"\x00" + content)
    return h.hexdigest()


def _verify_pack_signature(zf: zipfile.ZipFile, manifest: dict) -> bool:
    """
    팩 서명 검증.
    - signature 필드 없음: 경고만 (구버전 팩 허용)
    - signature 불일치: REVERIE_PACK_REQUIRE_SIGNATURE=1이면 거부, 아니면 경고
    - .dev 파일 존재 시 검사 생략
    """
    # DEV_MODE: 검사 생략
    if _is_dev_pack_mode():
        return True

    stored_sig = manifest.get("signature")
    if not stored_sig:
        logger.debug("[PackCrypto] signature 필드 없음 (구버전 팩 — 검증 생략)")
        return True

    try:
        sign_key = _get_pack_sign_key()
    except RuntimeError as e:
        strict = os.environ.get("REVERIE_PACK_REQUIRE_SIGNATURE", "0") == "1"
        if strict:
            logger.error(f"[PackCrypto] ❌ 서명 키 없음 — 엄격 모드에서 거부: {e}")
            return False
        logger.warning(f"[PackCrypto] 서명 키 없음 — 검증 생략: {e}")
        return True
    expected = calc_pack_signature(zf, sign_key)

    if stored_sig != expected:
        strict = os.environ.get("REVERIE_PACK_REQUIRE_SIGNATURE", "0") == "1"
        if strict:
            logger.error(
                "[PackCrypto] ❌ 팩 서명 불일치 — 변조 감지! "
                "(REVERIE_PACK_REQUIRE_SIGNATURE=1)"
            )
            return False
        else:
            logger.warning("[PackCrypto] ⚠️ 팩 서명 불일치 — 경고 (엄격 모드 비활성)")
    else:
        logger.info("[PackCrypto] ✅ 팩 서명 검증 OK")
    return True


# ============================================================
# v62.26: 라이선스 접근 제어 (load_pack 레벨)
# ============================================================

def _is_pack_strict_access() -> bool:
    """
    팩 접근 제어 엄격 모드 여부.
    REVERIE_PACK_STRICT_ACCESS=1 → owned_packs 없음/에러 시 deny (배포 환경 권장)
    기본값 0 → fail-open (UX 우선, 오프라인 허용)
    """
    return os.environ.get("REVERIE_PACK_STRICT_ACCESS", "0") == "1"


def _check_pack_access(plan_required: str) -> bool:
    """
    팩의 plan_required 값과 사용자 라이선스 owned_packs를 비교하여 접근 허용 여부 반환.

    매칭 방식: plan_required prefix가 owned_packs 항목에 포함되면 허용
      예) plan_required="horror" → "horror_pack" in owned → 허용
          plan_required="senior" → "senior_touching" in owned → 허용

    모드:
    - 기본(fail-open): 오프라인/에러/owned_packs 없음 → 허용 (UX 우선)
    - 엄격(fail-closed, REVERIE_PACK_STRICT_ACCESS=1): 에러/없음 → 거부
    """
    # DEV_MODE 우회
    if _is_dev_pack_mode():
        return True

    strict = _is_pack_strict_access()

    try:
        from utils.firebase_license import HybridLicenseValidator
        from config.settings_v2 import config as _app_config
        validator = HybridLicenseValidator(_app_config.DATA_DIR)
        owned = validator.get_owned_packs()

        if not owned:
            if strict:
                logger.warning("[PackCrypto] owned_packs 없음 — 엄격 모드: 거부")
                return False
            logger.debug("[PackCrypto] owned_packs 없음 — fail-open")
            return True

        if "*" in owned:
            return True

        # plan_required prefix 매칭 (대소문자 무시)
        req = plan_required.lower()
        for p in owned:
            if req in p.lower():
                return True

        logger.warning(
            f"[PackCrypto] ⚠️ 팩 접근 거부: plan_required={plan_required!r}, "
            f"owned_packs={owned}"
        )
        return False

    except Exception as e:
        if strict:
            logger.warning(f"[PackCrypto] 라이선스 접근 제어 실패 — 엄격 모드: 거부 ({e})")
            return False
        logger.debug(f"[PackCrypto] 라이선스 접근 제어 실패 (fail-open): {e}")
        return True


# ============================================================
# v62.27: Firebase Phase B — 서버 팩 키 발급
# ============================================================

# 팩 ID별 서버 발급 키 캐시 (pack_id → password_string)
_server_pack_keys: dict = {}


def fetch_pack_key_from_server(pack_id: str) -> Optional[str]:
    """
    Firebase getPackKey API를 통해 팩 복호화 키를 서버에서 발급받음.

    Phase B MVP:
    - 서버에 pack_keys/{pack_id} 미등록 시 null 반환 → Phase A 레거시 키로 폴백
    - pack_keys 등록 후: 서버 키로 재암호화된 팩만 이 경로로 복호화 가능

    결과는 _server_pack_keys[pack_id]에 캐시됨 (세션 내 재사용).

    Args:
        pack_id: 팩 ID (예: "horror_v59")

    Returns:
        팩 키 문자열 또는 None
    """
    # 이미 캐시된 경우
    if pack_id in _server_pack_keys:
        return _server_pack_keys[pack_id]

    try:
        from utils.firebase_license import HybridLicenseValidator
        from config.settings_v2 import config as _app_config
        validator = HybridLicenseValidator(_app_config.DATA_DIR)
        server_key = validator.get_pack_key(pack_id)
        if server_key:
            _server_pack_keys[pack_id] = server_key
            logger.info(f"[PackCrypto] 서버 팩 키 수신: {pack_id}")
        else:
            logger.debug(f"[PackCrypto] 서버 팩 키 없음 (레거시 폴백): {pack_id}")
        return server_key
    except Exception as e:
        logger.debug(f"[PackCrypto] 서버 팩 키 조회 실패 (폴백): {e}")
        return None


def _decrypt_content_with_password(encrypted: bytes, password: bytes) -> Optional[bytes]:
    """
    명시적 패스워드로 Fernet 복호화 (서버 키 전용).
    전역 상태를 수정하지 않음 — 서버 키 시도용.
    v62.28: salt를 _resolve_pack_crypto_params()에서 가져와 환경변수 일관성 보장.
    """
    if not CRYPTO_AVAILABLE:
        return None
    try:
        # salt는 _resolve_pack_crypto_params()와 동일 경로 사용 (env var 우선)
        salt, _ = _resolve_pack_crypto_params()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        fernet = Fernet(key)
        return fernet.decrypt(encrypted)
    except Exception:
        return None


def _get_decryption_key() -> Optional[bytes]:
    """복호화 키 생성"""
    if not CRYPTO_AVAILABLE:
        return None

    salt, pack_password = _resolve_pack_crypto_params()
    if not pack_password:
        logger.error(
            "[PackCrypto] 복호화 키 없음: "
            "REVERIE_PACK_PASSWORD 또는 configure_pack_crypto() 필요 "
            "(REVERIE_PACK_ALLOW_LEGACY_KEY=0 상태)"
        )
        return None

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pack_password))
    return key


def _decrypt_content(encrypted: bytes) -> Optional[bytes]:
    """암호화된 콘텐츠 복호화"""
    if not CRYPTO_AVAILABLE:
        logger.error("[PackCrypto] 암호화 라이브러리 없음 - pip install cryptography 실행 필요")
        return None

    salt, pack_password = _resolve_pack_crypto_params()
    try:
        if not pack_password:
            return None
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(pack_password))
        fernet = Fernet(key)
        return fernet.decrypt(encrypted)
    except Exception as e:
        legacy_password = _get_legacy_pack_password_bytes() if _allow_legacy_pack_key() else None
        if legacy_password and pack_password != legacy_password:
            legacy_decrypted = _decrypt_content_with_password(encrypted, legacy_password)
            if legacy_decrypted is not None:
                logger.info("[PackCrypto] 레거시 팩 키로 복호화 폴백 성공")
                return legacy_decrypted

        # v57.7.4: 암호화 키 불일치 시 상세 에러 메시지
        error_msg = str(e)
        if "InvalidToken" in error_msg or "Invalid" in error_msg:
            logger.error(
                "[PackCrypto] ⚠️ 복호화 실패: 암호화 키 불일치!\n"
                "  - 이 팩은 다른 버전의 Reverie Studio에서 생성되었거나\n"
                "  - pack_creator_full.py와 pack_config.py의 암호화 키가 일치하지 않습니다.\n"
                "  - 해결방법: 팩을 다시 생성하거나 암호화 없이 저장하세요."
            )
        else:
            logger.error(f"[PackCrypto] 복호화 실패: {e}")
        return None
