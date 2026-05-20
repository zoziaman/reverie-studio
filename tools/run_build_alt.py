#!/usr/bin/env python3
"""
Run Nuitka build using an alternate release directory to bypass file-lock conflicts.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_nuitka as b


def main() -> int:
    start = time.time()
    b.RELEASE_DIR = os.path.join(b.PROJECT_ROOT, "release_codex")
    os.makedirs(b.RELEASE_DIR, exist_ok=True)

    print("=" * 60)
    print("Codex alternate build start")
    print(f"release dir: {b.RELEASE_DIR}")
    print("=" * 60)

    if not b.check_nuitka_installed():
        return 1
    b.check_c_compiler()

    build_src = b.prepare_build_dir()
    deleted = b.delete_sensitive_files(build_src)
    print(f"removed sensitive items: {deleted}")

    sanitized = b.sanitize_secrets(build_src)
    path_cleaned = b.sanitize_developer_paths(build_src)
    b.create_api_settings_template(build_src)
    print(f"sanitized: {sanitized}, path_cleaned: {path_cleaned}")

    cmd = b.build_nuitka_command(build_src, "standalone")
    ok = b.run_nuitka_build(cmd, dry_run=False)
    if not ok:
        b.cleanup_build(build_src)
        return 2

    b.create_release_structure()
    b.cleanup_build(build_src)

    elapsed = time.time() - start
    print(f"build done in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
