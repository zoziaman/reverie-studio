"""시니어 2팩 .revpack 재빌드 스크립트"""
import zipfile
import shutil
from pathlib import Path

def repack(pack_dir_str):
    pack_dir = Path(pack_dir_str)
    revpack_path = pack_dir.parent / f"{pack_dir.name}.revpack"

    # 백업
    if revpack_path.exists():
        shutil.copy2(revpack_path, str(revpack_path) + ".bak")

    count = 0
    with zipfile.ZipFile(revpack_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pack_dir.rglob("*")):
            if f.is_file():
                arc_name = f.relative_to(pack_dir).as_posix()
                zf.write(f, arc_name)
                count += 1

    size = revpack_path.stat().st_size
    print(f"  {revpack_path.name}: {count} files, {size:,} bytes")
    return count


if __name__ == "__main__":
    print("=== .revpack rebuild ===")
    repack("assets/packs/senior_touching")
    repack("assets/packs/senior_makjang")
    print("Done!")
