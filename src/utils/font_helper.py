# src/utils/font_helper.py
# ============================================================
# 크로스 플랫폼 폰트 헬퍼
#
# 절대경로 없이 시스템 폰트를 찾아서 반환
# ============================================================
import os
import sys
import platform
from typing import Optional, List


def get_system_font_dirs() -> List[str]:
    """
    OS별 시스템 폰트 디렉토리 반환
    """
    system = platform.system()

    if system == "Windows":
        # Windows 폰트 디렉토리
        windir = os.environ.get("WINDIR", "C:\\Windows")
        return [
            os.path.join(windir, "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
        ]
    elif system == "Darwin":
        # macOS 폰트 디렉토리
        return [
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ]
    else:
        # Linux 폰트 디렉토리
        return [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
            os.path.expanduser("~/.local/share/fonts"),
        ]


def find_font(font_names: List[str], fallback: Optional[str] = None) -> Optional[str]:
    """
    시스템에서 폰트 파일 찾기

    Args:
        font_names: 찾을 폰트 파일명 리스트 (우선순위 순)
        fallback: 못 찾으면 반환할 기본값

    Returns:
        폰트 파일 경로 또는 fallback
    """
    font_dirs = get_system_font_dirs()

    for font_name in font_names:
        for font_dir in font_dirs:
            if not os.path.exists(font_dir):
                continue

            # 직접 경로 확인
            font_path = os.path.join(font_dir, font_name)
            if os.path.exists(font_path):
                return font_path

            # 하위 디렉토리 검색 (Linux/macOS)
            for root, dirs, files in os.walk(font_dir):
                if font_name in files:
                    return os.path.join(root, font_name)

    return fallback


def get_korean_font() -> str:
    """
    한글 폰트 경로 반환 (크로스 플랫폼)

    우선순위:
    1. 맑은 고딕 Bold (Windows)
    2. 맑은 고딕 (Windows)
    3. Apple SD Gothic Neo (macOS)
    4. Noto Sans CJK (Linux)
    5. 기본 폰트
    """
    # Windows 폰트
    windows_fonts = [
        "malgunbd.ttf",     # 맑은 고딕 Bold
        "malgun.ttf",       # 맑은 고딕
        "NanumGothicBold.ttf",
        "NanumGothic.ttf",
    ]

    # macOS 폰트
    mac_fonts = [
        "AppleSDGothicNeo-Bold.otf",
        "AppleSDGothicNeo-Regular.otf",
    ]

    # Linux 폰트
    linux_fonts = [
        "NotoSansCJK-Bold.ttc",
        "NotoSansCJK-Regular.ttc",
        "NotoSansKR-Bold.otf",
        "NotoSansKR-Regular.otf",
    ]

    system = platform.system()

    if system == "Windows":
        search_order = windows_fonts + linux_fonts
    elif system == "Darwin":
        search_order = mac_fonts + linux_fonts
    else:
        search_order = linux_fonts + windows_fonts

    font = find_font(search_order)

    if font:
        return font

    # 최후의 폴백: 프로젝트 내 폰트
    project_font = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "assets", "fonts", "NanumGothic.ttf"
    )
    if os.path.exists(project_font):
        return project_font

    # 정말 없으면 None (PIL이 기본 폰트 사용)
    return None


def get_korean_font_bold() -> str:
    """
    한글 Bold 폰트 경로 반환
    """
    bold_fonts = [
        "malgunbd.ttf",
        "NanumGothicBold.ttf",
        "AppleSDGothicNeo-Bold.otf",
        "NotoSansCJK-Bold.ttc",
    ]

    font = find_font(bold_fonts)
    return font or get_korean_font()


# 편의 상수 (자주 사용되는 폰트)
KOREAN_FONT = get_korean_font()
KOREAN_FONT_BOLD = get_korean_font_bold()


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("Font Helper Test")
    print("=" * 50)
    print(f"Platform: {platform.system()}")
    print(f"Font dirs: {get_system_font_dirs()}")
    print()
    print(f"Korean Font: {KOREAN_FONT}")
    print(f"Korean Font Bold: {KOREAN_FONT_BOLD}")
