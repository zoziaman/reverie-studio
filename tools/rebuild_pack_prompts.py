"""
tools/rebuild_pack_prompts.py
특정 팩의 prompts/*.txt 파일만 교체한 후 서버 키로 재암호화 + 재서명.

사용법:
  python tools/rebuild_pack_prompts.py --pack senior_touching --file prompts/writer_system.txt --src tools/tmp_writer_senior_touching.txt
  python tools/rebuild_pack_prompts.py --pack senior_makjang  --file prompts/writer_system.txt --src tools/tmp_writer_senior_makjang.txt
"""
import argparse, io, os, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dotenv import load_dotenv; load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack",  required=True, help="팩 ID (e.g. senior_touching)")
    parser.add_argument("--file",  required=True, help="교체할 ZIP 내부 경로 (e.g. prompts/writer_system.txt)")
    parser.add_argument("--src",   required=True, help="교체할 내용의 로컬 파일 경로")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pack_path = Path("assets/packs") / f"{args.pack}.revpack"
    if not pack_path.exists():
        print(f"[ERROR] 팩 없음: {pack_path}")
        sys.exit(1)

    with open(args.src, "r", encoding="utf-8") as f:
        new_content = f.read().encode("utf-8")

    # 1. 현재 팩 복호화 (서버 키 or 레거시 키)
    import config.pack_config as pc
    from cryptography.fernet import Fernet

    with open(pack_path, "rb") as f:
        encrypted_data = f.read()

    # Phase B: 서버 키로 복호화 시도
    server_key = pc.fetch_pack_key_from_server(args.pack)
    zip_bytes = None
    used_password = None

    if server_key:
        decrypted = pc._decrypt_content_with_password(encrypted_data, server_key.encode("utf-8"))
        if decrypted:
            zip_bytes = decrypted
            used_password = server_key.encode("utf-8")
            print(f"[OK] Phase B 서버 키로 복호화 성공")

    if zip_bytes is None:
        decrypted = pc._decrypt_content(encrypted_data)
        if decrypted:
            zip_bytes = decrypted
            # 레거시 키 재암호화용
            salt, pw = pc._resolve_pack_crypto_params()
            used_password = None  # 레거시 → encrypt_revpacks.py가 처리
            print(f"[OK] Phase A 레거시 키로 복호화 성공")

    if zip_bytes is None:
        print(f"[ERROR] 복호화 실패")
        sys.exit(1)

    # 2. ZIP 내부 파일 교체
    old_zip = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    file_list = old_zip.namelist()
    print(f"[INFO] ZIP 내 파일: {file_list}")

    if args.file not in file_list:
        print(f"[ERROR] '{args.file}' 가 ZIP에 없음. 사용 가능: {file_list}")
        sys.exit(1)

    # 새 ZIP 빌드
    new_zip_buf = io.BytesIO()
    with zipfile.ZipFile(new_zip_buf, "w", zipfile.ZIP_DEFLATED) as new_zf:
        for name in file_list:
            if name == args.file:
                new_zf.writestr(name, new_content)
                print(f"[REPLACED] {name} ({len(new_content)} bytes)")
            else:
                new_zf.writestr(name, old_zip.read(name))
                print(f"[KEEP] {name}")
    old_zip.close()

    plain_zip_bytes = new_zip_buf.getvalue()

    if args.dry_run:
        print("[DRY-RUN] 실제 쓰기 건너뜀")
        return

    # 3. 서명 주입 + 재암호화
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "encrypt_revpacks",
        Path(__file__).parent / "encrypt_revpacks.py"
    )
    _ermod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_ermod)
    _get_fernet_key = _ermod._get_fernet_key
    _get_sign_key = _ermod._get_sign_key
    _inject_signature_into_zip = _ermod._inject_signature_into_zip
    calc_pack_signature = _ermod.calc_pack_signature
    from cryptography.fernet import Fernet as _Fernet

    # 서명 키: pack_config._get_pack_sign_key()와 동일 → 항상 레거시 키 기반
    # (Phase B 암호화와 무관하게 서명 키는 레거시 패스워드 고정)
    sign_key = _get_sign_key()  # env var or _DEFAULT_PASSWORD

    # Fernet 암호화 키: Phase B 서버 키 사용
    if used_password:
        fernet_key = _get_fernet_key(password=used_password)
    else:
        fernet_key = _get_fernet_key()

    # 서명 주입 (레거시 키)
    signed_zip = _inject_signature_into_zip(plain_zip_bytes, sign_key=sign_key)

    # Fernet 암호화 (서버 키)
    fernet = _Fernet(fernet_key)
    final_bytes = fernet.encrypt(signed_zip)

    pack_path.write_bytes(final_bytes)
    print(f"\n[DONE] {pack_path} 재빌드 완료 ({len(final_bytes):,} bytes)")

    # 4. 검증
    print("[검증] 팩 로드 테스트...")
    pc.ACTIVE_PACK = pc.ActivePack()   # None으로 설정하면 load_pack이 .pack_id 접근 시 크래시
    ok = pc.load_pack(str(pack_path))
    if ok and pc.ACTIVE_PACK:
        txt = pc.get_prompt("writer_system")
        lines = len((txt or "").splitlines())
        print(f"[OK] 로드 성공, writer_system.txt = {lines}줄")
    else:
        print("[FAIL] 로드 실패! 원인 확인 필요")
        sys.exit(1)


if __name__ == "__main__":
    main()
