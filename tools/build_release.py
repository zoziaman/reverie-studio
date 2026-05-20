#!/usr/bin/env python3
# tools/build_release.py
"""
레베리 스튜디오 배포 빌드 스크립트

개발 환경(src/*.py) → 배포 패키지(release/*.pyd + 필수 리소스)

사용법:
    python tools/build_release.py              # 전체 빌드
    python tools/build_release.py --skip-cython # Cython 없이 (테스트용)
    python tools/build_release.py --tier=1      # Tier 1만 컴파일

결과:
    release/
    ├── src/          ← .pyd(컴파일) + .py(GUI/비핵심)
    ├── remotion-poc/ ← Remotion 프로젝트
    ├── assets/       ← BGM, SFX, 팩
    ├── data/         ← 빈 디렉토리 (런타임 데이터)
    ├── .env.example  ← 환경변수 템플릿
    ├── main.bat      ← 실행 스크립트
    └── README.txt    ← 설치 가이드
"""
import os
import sys
import shutil
import subprocess
import glob
import time

# ============================================================
# 설정
# ============================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
RELEASE_DIR = os.path.join(PROJECT_ROOT, "release")
RELEASE_SRC = os.path.join(RELEASE_DIR, "src")

# 배포에서 제거할 파일/패턴
REMOVE_PATTERNS = [
    # 보안: 시크릿/키 파일
    "src/data/api_settings.json",
    "src/data/.dev",
    "src/data/license.dat",
    "src/data/license_cache.json",
    "src/data/youtube_token*.pickle",
    # 개발 전용
    "src/data/gui_settings.json",
    "src/data/backups/",
    "src/data/production_stats.json",
    "src/data/batch_queue.json",
    # 테스트/도구
    "tests/",
    "tools/",
    "docs/",
    # Git
    ".git/",
    ".gitignore",
    # 빌드 잔여물
    "**/*.c",           # Cython 생성 C 파일
    "**/__pycache__/",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.egg-info/",
    "build/",
]

# 배포에서 제거할 소스 파일 (.pyd가 있으면 .py 제거)
# .pyd 컴파일 성공한 모듈의 .py는 삭제하여 소스코드 보호
REMOVE_PY_IF_PYD_EXISTS = True

# 배포 패키지에 포함할 디렉토리
INCLUDE_DIRS = [
    "src",
    "remotion-poc",
    "assets/packs",
    "assets/bgm",
    "assets/sfx",
]

# 배포에 포함할 루트 파일
INCLUDE_ROOT_FILES = [
    "requirements.txt",
]


# ============================================================
# 빌드 함수
# ============================================================

def clean_release():
    """이전 빌드 정리"""
    if os.path.exists(RELEASE_DIR):
        print(f"[1/6] 이전 빌드 정리: {RELEASE_DIR}")
        shutil.rmtree(RELEASE_DIR)
    os.makedirs(RELEASE_DIR)


def copy_source():
    """소스 및 리소스 복사"""
    print(f"[2/6] 소스 복사 중...")

    for dir_name in INCLUDE_DIRS:
        src_path = os.path.join(PROJECT_ROOT, dir_name)
        dst_path = os.path.join(RELEASE_DIR, dir_name)

        if not os.path.exists(src_path):
            print(f"  [WARN] 디렉토리 없음: {dir_name}")
            continue

        # remotion-poc은 node_modules 제외
        if dir_name == "remotion-poc":
            shutil.copytree(
                src_path, dst_path,
                ignore=shutil.ignore_patterns(
                    "node_modules", ".cache", "out", "render_*",
                    "*.wav", "*.mp4", "images", "audio"
                )
            )
        else:
            shutil.copytree(
                src_path, dst_path,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.pyo", "*.c",
                    "*.egg-info", ".git"
                )
            )
        print(f"  OK: {dir_name}")

    # 루트 파일 복사
    for fname in INCLUDE_ROOT_FILES:
        src_path = os.path.join(PROJECT_ROOT, fname)
        if os.path.exists(src_path):
            shutil.copy2(src_path, os.path.join(RELEASE_DIR, fname))
            print(f"  OK: {fname}")

    # data/ 빈 디렉토리 생성 (런타임용)
    data_dir = os.path.join(RELEASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    # .gitkeep 생성
    with open(os.path.join(data_dir, ".gitkeep"), "w") as f:
        f.write("")
    print(f"  OK: data/ (빈 디렉토리)")


def run_cython_build(tier="all"):
    """Cython 컴파일 실행"""
    print(f"[3/6] Cython 컴파일 중 (tier={tier})...")

    setup_script = os.path.join(PROJECT_ROOT, "tools", "setup_build.py")

    cmd = [
        sys.executable, setup_script,
        "build_ext", "--inplace",
        f"--tier={tier}"
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600  # 10분 타임아웃
        )

        if result.returncode != 0:
            print(f"  [ERROR] Cython 빌드 실패:")
            print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
            return False

        print(f"  OK: Cython 컴파일 완료")
        return True

    except subprocess.TimeoutExpired:
        print(f"  [ERROR] Cython 빌드 타임아웃 (10분)")
        return False
    except Exception as e:
        print(f"  [ERROR] Cython 빌드 예외: {e}")
        return False


def copy_pyd_files():
    """컴파일된 .pyd 파일을 release/src/ 로 복사"""
    print(f"[4/6] .pyd 파일 복사 중...")

    pyd_count = 0
    py_removed = 0

    for root, dirs, files in os.walk(SRC_DIR):
        for fname in files:
            if fname.endswith('.pyd') or fname.endswith('.so'):
                src_pyd = os.path.join(root, fname)
                # 상대 경로 계산
                rel_path = os.path.relpath(src_pyd, SRC_DIR)
                dst_pyd = os.path.join(RELEASE_SRC, rel_path)

                os.makedirs(os.path.dirname(dst_pyd), exist_ok=True)
                shutil.copy2(src_pyd, dst_pyd)
                pyd_count += 1

                # .pyd가 있으면 해당 .py 제거 (소스코드 보호)
                if REMOVE_PY_IF_PYD_EXISTS:
                    # 모듈명 추출 (예: orchestrator.cpython-311-x86_64-linux-gnu.so → orchestrator)
                    module_name = fname.split('.')[0]
                    py_file = os.path.join(
                        RELEASE_SRC,
                        os.path.dirname(rel_path),
                        module_name + ".py"
                    )
                    if os.path.exists(py_file):
                        os.remove(py_file)
                        py_removed += 1

    print(f"  OK: .pyd {pyd_count}개 복사, .py {py_removed}개 제거")
    return pyd_count


def remove_sensitive_files():
    """보안 파일 및 불필요 파일 제거"""
    print(f"[5/6] 민감 파일 제거 중...")

    removed = 0
    for pattern in REMOVE_PATTERNS:
        full_pattern = os.path.join(RELEASE_DIR, pattern)

        # glob 패턴 처리
        matches = glob.glob(full_pattern, recursive=True)
        for match in matches:
            if os.path.isfile(match):
                os.remove(match)
                removed += 1
            elif os.path.isdir(match):
                shutil.rmtree(match)
                removed += 1

    # 추가: .py 파일 내 하드코딩 시크릿 정리 (컴파일 안 된 파일들)
    _sanitize_remaining_py_files()

    print(f"  OK: {removed}개 파일/폴더 제거")


def _sanitize_remaining_py_files():
    """
    컴파일되지 않은 .py 파일에서 하드코딩 시크릿 제거

    .pyd로 대체된 파일은 이미 삭제됨.
    남은 .py (GUI 등)에서 시크릿이 있는 경우 처리.
    """
    # pack_config.py가 .pyd로 컴파일 안 됐을 경우 폴백 값 제거
    pack_config_py = os.path.join(RELEASE_SRC, "config", "pack_config.py")
    if os.path.exists(pack_config_py):
        with open(pack_config_py, 'r', encoding='utf-8') as f:
            content = f.read()

        # 하드코딩 폴백 제거 — 환경변수 필수로 전환
        content = content.replace(
            "b'ReverieStudio_PackEncryption_v57'",
            "b''  # 배포: REVERIE_PACK_PASSWORD 환경변수 필수"
        )
        content = content.replace(
            "b'ReveriePack2024Salt!'",
            "b''  # 배포: REVERIE_PACK_SALT 환경변수 필수"
        )

        with open(pack_config_py, 'w', encoding='utf-8') as f:
            f.write(content)

    # license_validator.py — SECRET_KEY 하드코딩 폴백 제거
    license_py = os.path.join(RELEASE_SRC, "utils", "license_validator.py")
    if os.path.exists(license_py):
        with open(license_py, 'r', encoding='utf-8') as f:
            content = f.read()

        # .dev 바이패스 블록 전체 제거
        import re
        content = re.sub(
            r'# 개발자 모드 바이패스.*?return True.*?\n',
            '# [배포] 개발자 바이패스 제거됨\n',
            content,
            flags=re.DOTALL
        )

        # SECRET_KEY 바이트 배열 폴백 제거
        content = content.replace(
            '_k = [82, 69, 86, 69, 82, 73, 69, 95, 80, 82, 79, 68, 95, 50, 48, 50, 53, 95,\n'
            '          83, 69, 67, 85, 82, 69, 95, 75, 69, 89, 95, 70, 73, 78, 65, 76]',
            '_k = []  # 배포: REVERIE_SECRET_KEY 환경변수 필수'
        )

        with open(license_py, 'w', encoding='utf-8') as f:
            f.write(content)


def create_release_files():
    """배포 전용 파일 생성"""
    print(f"[6/6] 배포 파일 생성 중...")

    # .env.example
    env_example = os.path.join(RELEASE_DIR, ".env.example")
    with open(env_example, 'w', encoding='utf-8') as f:
        f.write("""# ============================================================
# Reverie Studio - 환경 설정
# 이 파일을 .env 로 복사한 후 값을 입력하세요
# ============================================================

# [필수] API 키
GEMINI_API_KEY=여기에_Gemini_API_키_입력
YOUTUBE_API_KEY=여기에_YouTube_API_키_입력

# [필수] 서버 경로
SD_URL=http://127.0.0.1:7860
SOVITS_URL=http://127.0.0.1:9880
GS_ROOT=C:\\GPT-SoVITS\\GPT-SoVITS-v3lora-20250228
SD_WEBUI_ROOT=C:\\AI\\webui

# [필수] FFmpeg 경로 (8.0+ 필요)
FFMPEG_PATH=C:\\ffmpeg8\\ffmpeg-8.0.1-full_build\\bin\\ffmpeg.exe

# [필수] 팩 암호화 키 (구매 시 제공됨)
REVERIE_PACK_PASSWORD=구매시_제공되는_키
REVERIE_PACK_SALT=구매시_제공되는_솔트

# [필수] 라이선스 검증 키 (구매 시 제공됨)
REVERIE_SECRET_KEY=구매시_제공되는_시크릿

# [자동] 서버 시작 설정
SD_WEBUI_SCRIPT=webui-user.bat
SOVITS_SCRIPT=start_api_with_ffmpeg.bat
AUTO_START_SERVERS=true
AUTO_START_LIST=SD WebUI,GPT-SoVITS

# [자동] TTS 설정
TTS_ENGINE=sovits
TTS_HYBRID_ENABLED=false
TTS_SOVITS_ROLES=narrator,grandpa,grandma,man,woman,young_man,young_woman,middle_man,middle_woman,narrator_male,narrator_female

# [자동] 렌더링 설정
RENDER_ENGINE=auto
""")
    print(f"  OK: .env.example")

    # main.bat (Windows 실행 스크립트)
    main_bat = os.path.join(RELEASE_DIR, "main.bat")
    with open(main_bat, 'w', encoding='utf-8') as f:
        f.write("""@echo off
chcp 65001 >nul 2>&1
title Reverie Studio

echo ============================================
echo   Reverie Studio 시작
echo ============================================

:: .env 파일 확인
if not exist ".env" (
    echo [ERROR] .env 파일이 없습니다!
    echo .env.example 을 .env 로 복사한 후 설정값을 입력하세요.
    pause
    exit /b 1
)

:: Python 실행
cd /d "%~dp0"
python src\\main_gui.py
pause
""")
    print(f"  OK: main.bat")

    # VERSION 파일
    version_file = os.path.join(RELEASE_DIR, "VERSION")
    with open(version_file, 'w') as f:
        f.write(f"v63.0\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    print(f"  OK: VERSION")


# ============================================================
# 메인
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Reverie Studio 배포 빌드")
    parser.add_argument("--mode", default="nuitka",
                        choices=["nuitka", "cython", "source"],
                        help="빌드 모드: nuitka(추천), cython, source(소스 그대로)")
    parser.add_argument("--tier", default="all", choices=["1", "2", "all"],
                        help="Cython Tier (cython 모드 전용)")
    parser.add_argument("--dry-run", action="store_true",
                        help="빌드 없이 명령어만 확인")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  Reverie Studio 배포 빌드 (mode={args.mode})")
    print("=" * 60)

    if args.mode == "nuitka":
        # Nuitka 빌드는 전용 스크립트로 위임
        print("\n  -> build_nuitka.py 로 위임합니다.\n")
        nuitka_cmd = [sys.executable, os.path.join(PROJECT_ROOT, "tools", "build_nuitka.py")]
        if args.dry_run:
            nuitka_cmd.append("--dry-run")
        os.execv(sys.executable, nuitka_cmd)
        return

    # Cython 또는 Source 모드 (레거시)
    start = time.time()

    # Step 1: 정리
    clean_release()

    # Step 2: 소스 복사
    copy_source()

    # Step 3: Cython 컴파일
    if args.mode == "cython":
        success = run_cython_build(args.tier)
        if not success:
            print("\n[WARN] Cython 빌드 실패 -- .py 소스 그대로 배포됩니다")
        else:
            # Step 4: .pyd 복사 + .py 제거
            copy_pyd_files()
    else:
        print(f"[3/6] 컴파일 스킵 (mode=source)")
        print(f"[4/6] .pyd 복사 스킵")

    # Step 5: 민감 파일 제거
    remove_sensitive_files()

    # Step 6: 배포 파일 생성
    create_release_files()

    elapsed = time.time() - start
    print()
    print("=" * 60)
    release_size = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, dn, filenames in os.walk(RELEASE_DIR)
        for f in filenames
    ) / (1024 * 1024)
    print(f"  빌드 완료! ({elapsed:.1f}초, {release_size:.1f}MB)")
    print(f"  출력: {RELEASE_DIR}")
    print("=" * 60)

    # 최종 점검 요약
    print("\n[배포 전 체크리스트]")
    print(f"  [ ] .env.example -> .env 복사 후 키 입력")
    print(f"  [ ] 팩 파일 (.revpack) 포함 확인")
    print(f"  [ ] Python 3.11 + CUDA + Node.js 설치 확인")
    print(f"  [ ] SD WebUI + GPT-SoVITS 설치 확인")
    print(f"  [ ] remotion-poc/ 에서 npm install 실행")
    print(f"  [ ] main.bat 으로 실행 테스트")


if __name__ == "__main__":
    main()
