"""
.revpack 파일을 Fernet wrapper 암호화로 변환하는 스크립트
- 평문 ZIP → gAAAAA... Fernet 암호화 blob
- load_pack()이 gAAAAA 헤더를 자동 감지하여 복호화
- v62.24: Phase A 배포 보안 강화용
- v62.25: HMAC-SHA256 서명 주입 지원
"""
import sys
import io
import json
import hmac
import hashlib
import shutil
import base64
import zipfile
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# 암호화 라이브러리
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# 팩 암호화 키 (pack_config.py와 동일)
_DEFAULT_SALT = b'ReveriePack2024Salt!'
_DEFAULT_PASSWORD = b'ReverieStudio_PackEncryption_v57'

# 서명 키 (pack_config.py _PACK_SIGN_SUFFIX와 동일)
_PACK_SIGN_SUFFIX = b"_signature_v1"

PACK_PATHS = [
    "assets/packs/horror_v59.revpack",
    "assets/packs/senior_touching.revpack",
    "assets/packs/senior_makjang.revpack",
]

# v62.26: 팩별 manifest 추가 필드 (plan_required 등)
PACK_MANIFEST_FIELDS: dict = {
    "assets/packs/horror_v59.revpack": {"plan_required": "horror"},
    "assets/packs/senior_touching.revpack": {"plan_required": "senior"},
    "assets/packs/senior_makjang.revpack": {"plan_required": "senior"},
}


def _get_fernet_key(password: bytes = None, salt: bytes = None) -> bytes:
    """
    PBKDF2 + SHA256으로 Fernet 호환 키 생성.
    v62.28: REVERIE_PACK_PASSWORD / REVERIE_PACK_SALT 환경변수 우선 (pack_config.py와 동일)
    """
    import os as _os
    if password is None:
        pw_env = _os.environ.get("REVERIE_PACK_PASSWORD", "")
        password = pw_env.encode("utf-8") if pw_env else _DEFAULT_PASSWORD
    if salt is None:
        salt_env = _os.environ.get("REVERIE_PACK_SALT", "")
        salt = salt_env.encode("utf-8") if salt_env else _DEFAULT_SALT
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password))


def _get_sign_key(base_password: bytes = None) -> bytes:
    """
    팩 서명용 HMAC raw 키 (pack_config._get_pack_sign_key와 동일 로직).
    v62.28: REVERIE_PACK_PASSWORD 환경변수 우선
    """
    import os as _os
    if base_password is not None:
        base = base_password
    else:
        pw_env = _os.environ.get("REVERIE_PACK_PASSWORD", "")
        base = pw_env.encode("utf-8") if pw_env else _DEFAULT_PASSWORD
    return base + _PACK_SIGN_SUFFIX


def calc_pack_signature(zf: zipfile.ZipFile, sign_key: bytes) -> str:
    """
    ZIP 내 모든 파일의 HMAC-SHA256 계산.
    manifest.json의 'signature' 필드는 제외하고 계산.
    pack_config.calc_pack_signature와 동일한 알고리즘.
    """
    h = hmac.new(sign_key, digestmod=hashlib.sha256)
    for name in sorted(zf.namelist()):
        content = zf.read(name)
        if name == "manifest.json":
            try:
                data = json.loads(content.decode("utf-8", errors="replace"))
                data.pop("signature", None)
                content = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
            except Exception:
                pass
        h.update(name.encode("utf-8") + b"\x00" + content)
    return h.hexdigest()


def is_already_encrypted(path: Path) -> bool:
    """gAAAAA Fernet wrapper 헤더 여부 확인"""
    with open(path, 'rb') as f:
        header = f.read(6)
    return header == b'gAAAAA'


def is_valid_zip(path: Path) -> bool:
    """유효한 ZIP 파일인지 확인"""
    try:
        with zipfile.ZipFile(path, 'r'):
            return True
    except Exception:
        return False


def _inject_signature_into_zip(
    plain_zip_bytes: bytes,
    extra_manifest: dict = None,
    sign_key: bytes = None,
) -> bytes:
    """
    ZIP bytes에서 manifest.json에 signature + extra_manifest 필드 주입.
    서명 계산 → manifest.json 업데이트 → 새 ZIP bytes 반환.

    Args:
        plain_zip_bytes: 평문 ZIP 바이트
        extra_manifest: manifest.json에 추가로 넣을 필드 (예: {"plan_required": "horror"})
    """
    sign_key = sign_key or _get_sign_key()

    # 1) 기존 ZIP에서 모든 파일 읽기 + manifest 업데이트
    with zipfile.ZipFile(io.BytesIO(plain_zip_bytes), 'r') as zf:
        all_names = zf.namelist()
        file_contents = {name: zf.read(name) for name in all_names}

    # manifest.json에 extra_manifest 필드 주입 (signature 제외)
    if "manifest.json" in file_contents:
        manifest_data = json.loads(file_contents["manifest.json"].decode("utf-8", errors="replace"))
        manifest_data.pop("signature", None)  # 기존 서명 제거 후 재계산
        if extra_manifest:
            manifest_data.update(extra_manifest)
        file_contents["manifest.json"] = json.dumps(
            manifest_data, ensure_ascii=False, indent=2
        ).encode("utf-8")

    # 2) 중간 ZIP 빌드 (서명 제외 상태)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as tmp_zf:
        for name in all_names:
            tmp_zf.writestr(name, file_contents[name])
    tmp_zip_bytes = buf.getvalue()

    # 3) 서명 계산 (signature 없는 상태에서)
    with zipfile.ZipFile(io.BytesIO(tmp_zip_bytes), 'r') as zf:
        sig = calc_pack_signature(zf, sign_key)

    # 4) manifest.json에 signature 주입
    if "manifest.json" in file_contents:
        manifest_data = json.loads(file_contents["manifest.json"].decode("utf-8", errors="replace"))
        manifest_data["signature"] = sig
        file_contents["manifest.json"] = json.dumps(
            manifest_data, ensure_ascii=False, indent=2
        ).encode("utf-8")

    # 5) 최종 ZIP 빌드
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as out_zf:
        for name in all_names:
            out_zf.writestr(name, file_contents[name])
    new_zip_bytes = buf.getvalue()

    # 6) 검증
    with zipfile.ZipFile(io.BytesIO(new_zip_bytes), 'r') as zf:
        verify_sig = calc_pack_signature(zf, sign_key)
    assert verify_sig == sig, "서명 재검증 실패"

    extra_info = f", extra={list(extra_manifest.keys())}" if extra_manifest else ""
    logger.info(f"  서명 주입 완료: {sig[:16]}...{extra_info} ({len(new_zip_bytes):,} bytes)")
    return new_zip_bytes


def sign_and_reencrypt_revpack(
    pack_path: Path,
    dry_run: bool = False,
    extra_manifest: dict = None,
    source_password: bytes = None,
    target_password: bytes = None,
) -> bool:
    """
    이미 암호화된 .revpack에 HMAC 서명을 주입하고 재암호화.

    처리 흐름:
      1) Fernet 복호화 → 평문 ZIP 획득
      2) manifest.json에 extra_manifest + signature 필드 주입
      3) Fernet 재암호화 → 저장

    Args:
        pack_path: 처리할 .revpack 경로
        dry_run: True면 실제 파일 미수정
        extra_manifest: manifest에 추가로 넣을 필드 (예: {"plan_required": "horror"})
    Returns:
        성공 여부
    """
    if not pack_path.exists():
        logger.error(f"  [SKIP] 파일 없음: {pack_path}")
        return False

    if not is_already_encrypted(pack_path):
        logger.error(f"  [ERROR] Fernet wrapper가 아님: {pack_path.name} (encrypt_revpack() 먼저 실행)")
        return False

    # 서명이 이미 있는지 확인
    try:
        with open(pack_path, 'rb') as f:
            encrypted_data = f.read()
        source_key = _get_fernet_key(password=source_password)
        source_fernet = Fernet(source_key)
        plain_zip = source_fernet.decrypt(encrypted_data)
        with zipfile.ZipFile(io.BytesIO(plain_zip), 'r') as zf:
            if "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json").decode("utf-8", errors="replace"))
                existing_sig = manifest.get("signature")
                if existing_sig:
                    # extra_manifest 필드가 이미 반영됐는지 확인
                    extra_already_set = True
                    if extra_manifest:
                        for k, v in extra_manifest.items():
                            if manifest.get(k) != v:
                                extra_already_set = False
                                break
                    # 서명 재계산하여 일치 여부 확인
                    sign_key = _get_sign_key(base_password=target_password)
                    expected = calc_pack_signature(zf, sign_key)
                    if existing_sig == expected and extra_already_set:
                        logger.info(f"  [SKIP] 서명+필드 이미 유효: {pack_path.name}")
                        return True
                    else:
                        reason = "서명 불일치" if existing_sig != expected else "extra 필드 미반영"
                        logger.info(f"  [UPDATE] {reason} — 재생성: {pack_path.name}")
    except Exception as e:
        logger.warning(f"  [WARN] 서명 확인 실패: {e} — 강제 진행")
        # 다시 읽기
        with open(pack_path, 'rb') as f:
            encrypted_data = f.read()
        source_key = _get_fernet_key(password=source_password)
        source_fernet = Fernet(source_key)
        plain_zip = source_fernet.decrypt(encrypted_data)

    file_size = pack_path.stat().st_size
    logger.info(f"  {pack_path.name}: {file_size:,} bytes → 서명 주입 중")

    if dry_run:
        logger.info(f"  [DRY RUN] 서명 주입 생략")
        return True

    # 서명 주입 (extra_manifest 필드 포함)
    sign_key = _get_sign_key(base_password=target_password)
    signed_zip = _inject_signature_into_zip(
        plain_zip,
        extra_manifest=extra_manifest,
        sign_key=sign_key,
    )

    # 재암호화
    target_key = _get_fernet_key(password=target_password)
    target_fernet = Fernet(target_key)
    new_encrypted = target_fernet.encrypt(signed_zip)

    # 검증
    decrypted_check = target_fernet.decrypt(new_encrypted)
    if decrypted_check != signed_zip:
        logger.error(f"  [ERROR] 재암호화 검증 실패: {pack_path.name}")
        return False

    # 백업 (서명 전 버전 .prebuild_v6225)
    backup_path = pack_path.with_suffix(pack_path.suffix + ".prebuild_v6225")
    if not backup_path.exists():
        shutil.copy2(pack_path, backup_path)
        logger.info(f"  백업: {backup_path.name}")

    # 저장
    with open(pack_path, 'wb') as f:
        f.write(new_encrypted)

    new_size = pack_path.stat().st_size
    logger.info(f"  → 서명+재암호화 완료: {new_size:,} bytes")
    return True


def encrypt_revpack(
    pack_path: Path,
    dry_run: bool = False,
    target_password: bytes = None,
) -> bool:
    """
    단일 .revpack 파일을 Fernet wrapper로 암호화.
    v62.25: 암호화 후 서명 자동 주입.

    Args:
        pack_path: 변환할 .revpack 파일 경로
        dry_run: True면 실제 파일을 수정하지 않음
    Returns:
        성공 여부
    """
    if not pack_path.exists():
        logger.error(f"  [SKIP] 파일 없음: {pack_path}")
        return False

    if is_already_encrypted(pack_path):
        logger.info(f"  [SKIP] 이미 암호화됨: {pack_path.name} (sign_and_reencrypt로 서명 처리)")
        return True

    if not is_valid_zip(pack_path):
        logger.error(f"  [ERROR] 유효한 ZIP 아님: {pack_path.name}")
        return False

    file_size = pack_path.stat().st_size
    logger.info(f"  {pack_path.name}: {file_size:,} bytes (평문 ZIP)")

    if dry_run:
        logger.info(f"  [DRY RUN] 암호화+서명 생략")
        return True

    # 1) 백업 (.prebuild)
    backup_path = pack_path.with_suffix(pack_path.suffix + ".prebuild")
    if not backup_path.exists():
        shutil.copy2(pack_path, backup_path)
        logger.info(f"  백업: {backup_path.name}")
    else:
        logger.info(f"  백업 이미 존재: {backup_path.name} (스킵)")

    # 2) 평문 ZIP 읽기
    with open(pack_path, 'rb') as f:
        plain_zip_bytes = f.read()

    # 3) 서명 주입
    sign_key = _get_sign_key(base_password=target_password)
    signed_zip = _inject_signature_into_zip(plain_zip_bytes, sign_key=sign_key)

    # 4) Fernet 암호화
    key = _get_fernet_key(password=target_password)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(signed_zip)

    # 5) 검증
    decrypted = fernet.decrypt(encrypted)
    if decrypted != signed_zip:
        logger.error(f"  [ERROR] 암호화/복호화 검증 실패: {pack_path.name}")
        return False

    # 6) 저장
    with open(pack_path, 'wb') as f:
        f.write(encrypted)

    new_size = pack_path.stat().st_size
    logger.info(f"  → 암호화+서명 완료: {new_size:,} bytes (gAAAAA wrapper)")
    return True


def verify_revpack(pack_path: Path, verify_password: bytes = None) -> bool:
    """암호화+서명된 .revpack이 실제로 로드 가능한지 검증"""
    if not pack_path.exists():
        return False
    try:
        with open(pack_path, 'rb') as f:
            header = f.read(6)
        if header != b'gAAAAA':
            logger.error(f"  [검증 실패] gAAAAA 헤더 없음: {pack_path.name}")
            return False

        with open(pack_path, 'rb') as f:
            encrypted_data = f.read()

        key = _get_fernet_key(password=verify_password)
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted_data)

        with zipfile.ZipFile(io.BytesIO(decrypted), 'r') as zf:
            files = zf.namelist()
            has_manifest = "manifest.json" in files

            if has_manifest:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8", errors="replace"))
                sig = manifest.get("signature", "")
                if sig:
                    sign_key = _get_sign_key(base_password=verify_password)
                    expected = calc_pack_signature(zf, sign_key)
                    sig_ok = sig == expected
                else:
                    sig_ok = False

        logger.info(
            f"  [검증 {'OK' if has_manifest and sig_ok else 'PARTIAL'}] "
            f"{pack_path.name}: {len(files)}개 파일, "
            f"manifest={has_manifest}, signature={'✅' if sig_ok else '❌'}"
        )
        return has_manifest and sig_ok
    except Exception as e:
        logger.error(f"  [검증 실패] {pack_path.name}: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description=".revpack Fernet 암호화 + HMAC 서명 변환")
    parser.add_argument("--dry-run", action="store_true", help="실제 변환 없이 확인만")
    parser.add_argument("--sign-only", action="store_true", help="이미 암호화된 팩에 서명만 주입")
    parser.add_argument(
        "--server-key",
        help="Phase B 서버 키 (지정 시 해당 키로 재서명 + 재암호화)",
    )
    parser.add_argument(
        "--source-key",
        help="기존 복호화 키 (미지정 시 REVERIE_PACK_PASSWORD 또는 기본 레거시 키 사용)",
    )
    args = parser.parse_args()

    if not CRYPTO_AVAILABLE:
        logger.error("[ERROR] cryptography 라이브러리 미설치: pip install cryptography")
        sys.exit(1)

    # 프로젝트 루트에서 실행 가정
    project_root = Path(__file__).parent.parent

    logger.info("=" * 50)
    if args.sign_only:
        logger.info(".revpack 서명 주입 (기존 암호화 팩)")
    else:
        logger.info(".revpack 암호화+서명 변환 (Fernet wrapper + HMAC)")
    if args.server_key:
        logger.info("서버 키 모드 활성: 대상 팩을 --server-key 값으로 재서명/재암호화")
    logger.info("=" * 50)

    source_password = args.source_key.encode("utf-8") if args.source_key else None
    target_password = args.server_key.encode("utf-8") if args.server_key else None

    success_count = 0
    for pack_rel in PACK_PATHS:
        pack_path = project_root / pack_rel
        extra = PACK_MANIFEST_FIELDS.get(pack_rel, {})
        logger.info(f"\n[{pack_rel}]")
        if args.sign_only:
            ok = sign_and_reencrypt_revpack(
                pack_path,
                dry_run=args.dry_run,
                extra_manifest=extra,
                source_password=source_password,
                target_password=target_password,
            )
        else:
            if is_already_encrypted(pack_path):
                # 이미 암호화된 경우 서명+extra 주입
                ok = sign_and_reencrypt_revpack(
                    pack_path,
                    dry_run=args.dry_run,
                    extra_manifest=extra,
                    source_password=source_password,
                    target_password=target_password,
                )
            else:
                ok = encrypt_revpack(
                    pack_path,
                    dry_run=args.dry_run,
                    target_password=target_password,
                )
        if ok:
            success_count += 1

    if args.dry_run:
        logger.info(f"\n[DRY RUN 완료] 실제 변환하려면 --dry-run 없이 실행")
        return

    # 검증
    logger.info("\n" + "=" * 50)
    logger.info("복호화+서명 검증")
    logger.info("=" * 50)

    verify_count = 0
    for pack_rel in PACK_PATHS:
        pack_path = project_root / pack_rel
        logger.info(f"\n[{pack_rel}]")
        if verify_revpack(pack_path, verify_password=target_password):
            verify_count += 1

    logger.info("\n" + "=" * 50)
    logger.info(f"결과: 처리 {success_count}/3, 검증 {verify_count}/3")
    if verify_count == 3:
        logger.info("✅ 전체 성공")
    else:
        logger.error("❌ 일부 실패 — .prebuild 백업으로 롤백 가능")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
