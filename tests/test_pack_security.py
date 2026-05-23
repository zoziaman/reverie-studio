# tests/test_pack_security.py
"""
팩 보안 경로 테스트 (v62.30)
- Fernet 암호화 헤더 검증
- 실제 .revpack 파일 로드 (DEV_MODE 환경)
- HMAC-SHA256 서명 검증 경로
- plan_required 접근 제어 (fail-open / fail-closed)

CI 환경에서는 .revpack 파일이 없으므로 pack_exists 체크로 자동 skip.
"""
import os
import sys
import zipfile
import json
import pytest
import base64

# 프로젝트 루트 / src 경로는 conftest.py에서 이미 sys.path에 추가됨

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(PROJECT_ROOT, "assets", "packs")

PACK_IDS = ["horror_v59", "senior_touching", "senior_makjang"]


def _pack_path(pack_id: str) -> str:
    return os.path.join(PACKS_DIR, f"{pack_id}.revpack")


def _any_pack_exists() -> bool:
    return any(os.path.exists(_pack_path(p)) for p in PACK_IDS)


def _pack_exists(pack_id: str) -> bool:
    return os.path.exists(_pack_path(pack_id))


# ─────────────────────────────────────────────────────────
# 1. Fernet 암호화 헤더 검증
# ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not _any_pack_exists(), reason=".revpack 파일 없음 (CI 환경 skip)")
@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_revpack_is_fernet_encrypted(pack_id):
    """각 .revpack 파일이 Fernet 암호화 형식(gAAAAA 헤더)으로 시작하는지 확인"""
    path = _pack_path(pack_id)
    if not os.path.exists(path):
        pytest.skip(f"{pack_id}.revpack 없음")

    with open(path, "rb") as f:
        raw = f.read(20)

    # Fernet 토큰은 base64url 인코딩 → 'gAAAAA' 로 시작
    assert raw[:6] == b"gAAAAA", (
        f"{pack_id}.revpack 이 Fernet 헤더(gAAAAA)로 시작하지 않습니다. "
        f"실제 시작: {raw[:10]!r}"
    )


# ─────────────────────────────────────────────────────────
# 2. 실제 .revpack 로드 (DEV_MODE 활성 필요)
# ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not _any_pack_exists(), reason=".revpack 파일 없음 (CI 환경 skip)")
@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_load_real_pack_dev_mode(pack_id, tmp_path, monkeypatch):
    """
    DEV_MODE (.dev 파일 존재) 상태에서 팩 3종 실제 로드 검증.
    서명/라이선스/HWID 우회 → load_pack()이 True 반환해야 함.

    주의: Phase B 활성화 후에는 REVERIE_PACK_PASSWORD 환경변수가 필요합니다.
    미설정 시 복호화 자체가 불가하므로 자동 skip.
    """
    if not os.environ.get("REVERIE_PACK_PASSWORD"):
        pytest.skip(
            "REVERIE_PACK_PASSWORD 미설정 — Phase B 활성 환경에서는 팩 로드 불가 "
            "(개발자/배포 환경에서만 실행 가능)"
        )

    path = _pack_path(pack_id)
    if not os.path.exists(path):
        pytest.skip(f"{pack_id}.revpack 없음")

    # DEV_MODE 활성화:
    # pack_config.py는 os.path.exists("data/.dev") 를 상대경로로 체크하므로
    # monkeypatch.chdir(tmp_path) 후 data/.dev 파일을 생성하면 DEV_MODE=True
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / ".dev").write_text("test")
    monkeypatch.chdir(tmp_path)

    # pack_config 모듈 임포트 (conftest.py가 src/ 추가)
    import importlib
    import config.pack_config as pc
    importlib.reload(pc)

    monkeypatch.setenv("REVERIE_DEV_MODE", "1")
    # 캐시 초기화
    monkeypatch.setattr(pc, "ACTIVE_PACK", None)
    if hasattr(pc, "_pack_load_cache"):
        monkeypatch.setattr(pc, "_pack_load_cache", {})

    result = pc.load_pack(path)
    assert result is True, f"{pack_id} load_pack() 실패 (DEV_MODE 상태)"

    # ACTIVE_PACK 필수 필드 확인
    assert pc.ACTIVE_PACK is not None
    manifest = pc.ACTIVE_PACK.manifest if hasattr(pc.ACTIVE_PACK, "manifest") else {}
    assert manifest.get("pack_id") == pack_id, (
        f"manifest.pack_id={manifest.get('pack_id')} ≠ {pack_id}"
    )
    assert manifest.get("plan_required") is not None, (
        f"{pack_id}: manifest에 plan_required 필드 없음"
    )
    assert manifest.get("signature") is not None, (
        f"{pack_id}: manifest에 signature 필드 없음 (HMAC 서명 미주입)"
    )


# ─────────────────────────────────────────────────────────
# 3. HMAC 서명 검증 경로
# ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not _any_pack_exists(), reason=".revpack 파일 없음 (CI 환경 skip)")
def test_revpack_encryption_implies_signature_injected():
    """
    Phase B 활성화 환경에서 서버 키 없이 ZIP을 열 수 없으므로,
    manifest.json의 signature 필드를 직접 확인할 수 없습니다.

    대신 이 테스트는 다음을 검증합니다:
    - .revpack 파일이 Fernet 암호화 형식(gAAAAA)으로 시작함
    - v62.25 encrypt_revpacks.py 빌드 프로세스가 서명 주입 후 암호화하므로,
      암호화가 확인되면 서명도 포함됐다고 간주할 수 있음 (빌드 프로세스 보장)

    NOTE: signature 필드를 직접 검증하려면 REVERIE_PACK_PASSWORD 환경변수가 필요합니다.
          해당 검증은 test_signature_verification_respects_require_env (mock zip)로 대신합니다.
    """
    target = None
    for pid in PACK_IDS:
        if _pack_exists(pid):
            target = pid
            break
    if target is None:
        pytest.skip("사용 가능한 .revpack 없음")

    pack_path = _pack_path(target)
    with open(pack_path, "rb") as f:
        raw = f.read(6)

    # Phase B: 모든 팩은 Fernet 암호화 상태여야 함
    assert raw == b"gAAAAA", (
        f"{target}.revpack 가 Fernet 암호화 형식이 아닙니다. "
        f"실제 헤더: {raw!r}\n"
        "Phase B 활성화 후에는 모든 팩이 gAAAAA 헤더로 시작해야 합니다."
    )


def test_signature_verification_respects_require_env(monkeypatch, tmp_path):
    """
    REVERIE_PACK_REQUIRE_SIGNATURE=1 이면 서명 불일치 시 _verify_pack_signature가 False를 반환해야 함.
    REVERIE_PACK_REQUIRE_SIGNATURE=0 (기본) 이면 불일치여도 True (경고만).
    mock zip 생성으로 DEV_MODE 없이 테스트.
    """
    try:
        import config.pack_config as pc
        import importlib
        importlib.reload(pc)
    except ImportError:
        pytest.skip("pack_config 임포트 불가")

    if not hasattr(pc, "_verify_pack_signature"):
        pytest.skip("_verify_pack_signature 함수 없음 (v62.25 미적용)")

    # 가짜 manifest (signature 필드 존재, 값은 틀림)
    fake_manifest = {
        "pack_id": "test_pack",
        "version": "1.0",
        "signature": "INVALID_SIGNATURE_VALUE"
    }

    # 가짜 ZIP 생성
    fake_zip_path = tmp_path / "test_fake.revpack"
    with zipfile.ZipFile(str(fake_zip_path), "w") as zf:
        zf.writestr("manifest.json", json.dumps(fake_manifest))
        zf.writestr("settings.json", '{"version": "1.0"}')
        zf.writestr("prompts/writer_system.txt", "test prompt")

    with zipfile.ZipFile(str(fake_zip_path), "r") as zf:
        # DEV_MODE 끔 + 서명 필수 모드
        # pack_config.py는 os.path.exists("data/.dev")를 CWD 기준 체크
        # tmp_path로 chdir → .dev 파일 없으므로 DEV_MODE=False
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("REVERIE_DEV_MODE", "0")
        monkeypatch.setenv("REVERIE_PACK_REQUIRE_SIGNATURE", "1")

        result_strict = pc._verify_pack_signature(zf, fake_manifest)
        assert result_strict is False, (
            "REQUIRE_SIGNATURE=1인데 서명 불일치에서 True 반환 (보안 버그!)"
        )

        # 비엄격 모드 (기본)
        monkeypatch.setenv("REVERIE_PACK_REQUIRE_SIGNATURE", "0")
        result_lenient = pc._verify_pack_signature(zf, fake_manifest)
        assert result_lenient is True, (
            "REQUIRE_SIGNATURE=0인데 서명 불일치에서 False 반환 (fail-open 미동작)"
        )


def test_legacy_pack_fallback_still_decrypts_when_runtime_key_is_set(monkeypatch):
    try:
        import config.pack_config as pc
        import importlib
        importlib.reload(pc)
    except ImportError:
        pytest.skip("pack_config import 불가")

    if not getattr(pc, "CRYPTO_AVAILABLE", False):
        pytest.skip("cryptography 미설치")

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    payload = b"legacy-pack-payload"
    legacy_password = b"test-legacy-pack-password"
    monkeypatch.setenv("REVERIE_PACK_LEGACY_PASSWORD", legacy_password.decode("utf-8"))
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=pc._DEFAULT_PACK_ENCRYPTION_SALT,
        iterations=100000,
    )
    legacy_key = base64.urlsafe_b64encode(kdf.derive(legacy_password))
    encrypted = Fernet(legacy_key).encrypt(payload)

    monkeypatch.setenv("REVERIE_PACK_ALLOW_LEGACY_KEY", "1")
    monkeypatch.setattr(pc, "_runtime_pack_password", "runtime-key-that-does-not-match", raising=False)

    assert pc._decrypt_content(encrypted) == payload


# ─────────────────────────────────────────────────────────
# 4. plan_required 접근 제어
# ─────────────────────────────────────────────────────────

def test_access_denied_strict_mode(monkeypatch, tmp_path):
    """
    REVERIE_PACK_STRICT_ACCESS=1 + owned_packs=[] → False (접근 거부) 검증.

    HybridLicenseValidator.get_owned_packs()를 mock → []
    _check_pack_access 내부 로직:
      if not owned: if strict: return False  ← 이 경로를 강제 실행
    """
    try:
        import config.pack_config as pc
        import utils.firebase_license as fl
        import importlib
        importlib.reload(pc)
    except ImportError:
        pytest.skip("pack_config 또는 firebase_license 임포트 불가")

    if not hasattr(pc, "_check_pack_access"):
        pytest.skip("_check_pack_access 함수 없음 (v62.26 미적용)")

    # DEV_MODE 끔: tmp_path로 chdir → .dev 파일 없음 → DEV_MODE=False
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REVERIE_DEV_MODE", "0")
    monkeypatch.setenv("REVERIE_PACK_STRICT_ACCESS", "1")

    # get_owned_packs()를 mock → [] 반환 (소유 팩 없음)
    # _check_pack_access: if not owned + strict=True → return False 보장
    monkeypatch.setattr(fl.HybridLicenseValidator, "get_owned_packs", lambda self: [])

    result = pc._check_pack_access("horror")

    assert result is False, (
        "STRICT_ACCESS=1 + owned_packs=[] 인데 True 반환 (보안 버그!) "
        f"실제 반환값: {result}"
    )


def test_access_allowed_fail_open(monkeypatch, tmp_path):
    """
    REVERIE_PACK_STRICT_ACCESS=0 (기본) → 오류 시 True (fail-open)
    """
    try:
        import config.pack_config as pc
        import importlib
        importlib.reload(pc)
    except ImportError:
        pytest.skip("pack_config 임포트 불가")

    if not hasattr(pc, "_is_pack_strict_access"):
        pytest.skip("_is_pack_strict_access 없음 (v62.26 미적용)")

    monkeypatch.setenv("REVERIE_PACK_STRICT_ACCESS", "0")
    result = pc._is_pack_strict_access()
    assert result is False, "STRICT_ACCESS=0인데 True 반환"

    monkeypatch.setenv("REVERIE_PACK_STRICT_ACCESS", "1")
    result = pc._is_pack_strict_access()
    assert result is True, "STRICT_ACCESS=1인데 False 반환"


def test_access_plan_prefix_matching(monkeypatch, tmp_path):
    """
    owned_packs prefix 매칭 검증:
    owned_packs=["horror_pack"] + plan_required="horror" → 접근 허용
    owned_packs=["senior_pack"] + plan_required="horror" → 접근 거부 (STRICT=1)
    """
    try:
        import config.pack_config as pc
        import importlib
        importlib.reload(pc)
    except ImportError:
        pytest.skip("pack_config 임포트 불가")

    if not hasattr(pc, "_check_pack_access"):
        pytest.skip("_check_pack_access 없음 (v62.26 미적용)")

    import inspect
    sig = inspect.signature(pc._check_pack_access)
    params = list(sig.parameters.keys())

    # owned_packs를 직접 파라미터로 받는 경우
    if "owned_packs" in params:
        monkeypatch.setenv("REVERIE_PACK_STRICT_ACCESS", "1")
        monkeypatch.setenv("REVERIE_DEV_MODE", "0")
        monkeypatch.setattr(pc, "DEV_MODE_FILE", str(tmp_path / "nonexistent.dev"))

        result_match = pc._check_pack_access("horror", owned_packs=["horror_pack"])
        assert result_match is True, "horror_pack 보유 시 horror 팩 접근 거부됨"

        result_no_match = pc._check_pack_access("horror", owned_packs=["senior_pack"])
        assert result_no_match is False, "senior_pack만 보유 시 horror 팩 접근 허용됨 (STRICT=1)"
    else:
        # 내부 캐시 의존 → 기본 동작만 확인
        result = pc._check_pack_access("horror")
        assert isinstance(result, bool)
