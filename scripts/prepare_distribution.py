# scripts/prepare_distribution.py
"""
배포용 패키지 준비 스크립트
- 개발자 설정을 제외한 배포용 파일 생성
- 실행: python scripts/prepare_distribution.py
"""
import os
import sys
import shutil
import json
from datetime import datetime

# 프로젝트 루트 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# 배포 폴더
DIST_DIR = os.path.join(PROJECT_ROOT, "dist_package")


def clean_dist():
    """기존 배포 폴더 정리"""
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR)
    print(f"✓ 배포 폴더 생성: {DIST_DIR}")


def copy_source_files():
    """소스 파일 복사 (개발자 전용 파일 제외)"""
    # 복사할 폴더들
    folders_to_copy = ["src", "assets"]

    for folder in folders_to_copy:
        src = os.path.join(PROJECT_ROOT, folder)
        dst = os.path.join(DIST_DIR, folder)
        if os.path.exists(src):
            shutil.copytree(src, dst)
            print(f"✓ 폴더 복사: {folder}")

    # 루트 파일들 복사
    root_files = ["requirements.txt", "README.md", "LICENSE"]
    for f in root_files:
        src = os.path.join(PROJECT_ROOT, f)
        if os.path.exists(src):
            shutil.copy2(src, DIST_DIR)
            print(f"✓ 파일 복사: {f}")


def setup_branding_template():
    """배포용 branding.json 설정 (빈 템플릿)"""
    template_src = os.path.join(PROJECT_ROOT, "src", "data", "branding_template.json")
    branding_dst = os.path.join(DIST_DIR, "src", "data", "branding.json")

    if os.path.exists(template_src):
        shutil.copy2(template_src, branding_dst)
        print("✓ branding.json을 빈 템플릿으로 교체")
    else:
        # 템플릿이 없으면 빈 기본값 생성
        default_branding = {
            "horror": {
                "channel_name": "",
                "intro_file": "",
                "openings": ["안녕하세요, {채널명}입니다."]
            },
            "senior_touching": {
                "channel_name": "",
                "intro_file": "",
                "openings": ["안녕하십니까. {채널명}입니다."]
            },
            "senior_makjang": {
                "channel_name": "",
                "intro_file": "",
                "openings": ["{채널명}입니다."]
            }
        }
        with open(branding_dst, "w", encoding="utf-8") as f:
            json.dump(default_branding, f, ensure_ascii=False, indent=2)
        print("✓ 빈 branding.json 생성")


def create_env_example():
    """.env.example 파일 생성"""
    env_example = """# Anti Reverie 환경 설정
# 이 파일을 .env로 복사한 후 값을 입력하세요

# Gemini API 키 (필수)
GEMINI_API_KEY=your_gemini_api_key_here

# Stable Diffusion WebUI URL (기본값: http://127.0.0.1:7860)
SD_URL=http://127.0.0.1:7860

# GPT-SoVITS URL (기본값: http://127.0.0.1:9880)
SOVITS_URL=http://127.0.0.1:9880

# GPT-SoVITS 설치 경로
GS_ROOT=C:\\GPT-SoVITS\\GPT-SoVITS-v3lora-20250228
"""

    env_path = os.path.join(DIST_DIR, ".env.example")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_example)
    print("✓ .env.example 생성")


def remove_dev_files():
    """개발자 전용 파일 제거"""
    dev_files = [
        os.path.join(DIST_DIR, "src", "data", "branding_template.json"),
        os.path.join(DIST_DIR, "src", "data", "gui_settings.json"),
    ]

    dev_folders = [
        os.path.join(DIST_DIR, "src", "data", "backups"),
        os.path.join(DIST_DIR, "__pycache__"),
    ]

    for f in dev_files:
        if os.path.exists(f):
            os.remove(f)
            print(f"✓ 개발 파일 제거: {os.path.basename(f)}")

    for folder in dev_folders:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"✓ 개발 폴더 제거: {os.path.basename(folder)}")

    # __pycache__ 폴더들 재귀적 제거
    for root, dirs, files in os.walk(DIST_DIR):
        for d in dirs:
            if d == "__pycache__":
                pycache_path = os.path.join(root, d)
                shutil.rmtree(pycache_path)


def create_version_info():
    """버전 정보 파일 생성"""
    version_info = {
        "version": "1.0.0",
        "build_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "distribution": True
    }

    version_path = os.path.join(DIST_DIR, "version.json")
    with open(version_path, "w", encoding="utf-8") as f:
        json.dump(version_info, f, ensure_ascii=False, indent=2)
    print("✓ version.json 생성")


def main():
    print("=" * 50)
    print("Anti Reverie 배포 패키지 준비")
    print("=" * 50)
    print()

    # 1. 배포 폴더 정리
    clean_dist()

    # 2. 소스 파일 복사
    copy_source_files()

    # 3. branding.json 템플릿으로 교체
    setup_branding_template()

    # 4. .env.example 생성
    create_env_example()

    # 5. 개발자 전용 파일 제거
    remove_dev_files()

    # 6. 버전 정보 생성
    create_version_info()

    print()
    print("=" * 50)
    print(f"✓ 배포 패키지 준비 완료!")
    print(f"  위치: {DIST_DIR}")
    print("=" * 50)
    print()
    print("다음 단계:")
    print("1. dist_package 폴더 내용 확인")
    print("2. Nuitka 또는 PyInstaller로 EXE 빌드")
    print("3. Inno Setup으로 설치 프로그램 생성")


if __name__ == "__main__":
    main()
