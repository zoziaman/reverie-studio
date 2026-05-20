#!/usr/bin/env python3
# tools/build_nuitka.py
"""
Nuitka 鍮뚮뱶 ?ㅽ겕由쏀듃 ??Python ???ㅼ씠?곕툕 諛붿씠?덈━

Cython蹂대떎 10諛??댁긽 媛뺣젰??蹂댄샇:
- Python 諛붿씠?몄퐫??0% (?쒖닔 C 蹂??
- IDA Pro 湲??꾧뎄 ?놁씠 由щ쾭???붿??덉뼱留?遺덇?
- 蹂?섎챸, ?⑥닔紐?紐⑤몢 ?뚮㈇

?ъ슜踰?
    python tools/build_nuitka.py                    # ?꾩껜 鍮뚮뱶 (standalone)
    python tools/build_nuitka.py --mode=onefile      # ?⑥씪 EXE
    python tools/build_nuitka.py --mode=standalone    # ?대뜑 紐⑤뱶 (異붿쿇, ?쒖옉 鍮좊쫫)
    python tools/build_nuitka.py --dry-run            # 鍮뚮뱶 ?놁씠 紐낅졊?대쭔 ?뺤씤

寃곌낵:
    release/ReverieStudio.dist/  (standalone 紐⑤뱶)
    release/ReverieStudio.exe    (onefile 紐⑤뱶)
"""
import os
import sys
import shutil
import subprocess
import time
import argparse
import json

# Avoid Windows cp949 console encode crashes when source text contains mixed Unicode.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ============================================================
# ?ㅼ젙
# ============================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
RELEASE_DIR = os.path.join(PROJECT_ROOT, "release")
ENTRY_POINT = os.path.join(SRC_DIR, "main_gui.py")
DIST_DIR_NAME = "main_gui.dist"
EXE_NAME = "ReverieStudio.exe"

# Nuitka???ы븿???⑦궎吏
INCLUDE_PACKAGES = [
    "pipeline",
    "modules_pro",
    "config",
    "utils",
    "core",
    "facades",
    "gui",
    "gui.mixins",
]

# Nuitka???ы븿???곗씠???붾젆?좊━ (?뚯뒪 ??諛붿씠?덈━ ?대?)
INCLUDE_DATA_DIRS = [
    # (?뚯뒪 寃쎈줈, ???寃쎈줈)
    # ?? BGM, SFX, 紐⑤뜽? ?몃????먮뒗 寃??섏쓬 (?⑸웾 ??
]

# Nuitka???ы븿???곗씠???뚯씪
INCLUDE_DATA_FILES = [
    # gui ?꾩씠肄????꾩닔 由ъ냼?ㅻ쭔
]

# ============================================================
# 鍮뚮뱶 ?꾨왂: ?곕━ 肄붾뱶留?C 而댄뙆?? ?쒕뱶?뚰떚??Python 洹몃?濡?
# ============================================================
# --nofollow-imports: 湲곕낯?곸쑝濡?紐⑤뱺 import 異붿쟻 以묐떒
# --follow-import-to=?⑦궎吏: ?곕━ 肄붾뱶 ?⑦궎吏留?C 而댄뙆?????
#
# ?④낵:
#   - ?곕━ 肄붾뱶 8媛??⑦궎吏 ??C ???ㅼ씠?곕툕 諛붿씠?덈━ (??났??諛⑹?)
#   - ?쒕뱶?뚰떚 (google, numpy, PIL ?? ??Python .py 洹몃?濡??ы븿 (蹂댄샇 遺덊븘??
#   - 鍮뚮뱶 ?쒓컙: ?섏떆媛???~10遺?
#   - 寃곌낵臾??ш린: ???媛먯냼
#
# ?쒕뱶?뚰떚??pip install濡??꾧뎄??諛쏆쓣 ???덉쑝誘濡??뷀샇?뷀븷 ?댁쑀 ?놁쓬

# ============================================================
# 媛쒖씤?뺣낫/?쒗겕由??쒓굅 ???(鍮뚮뱶 ???뺣━)
# ============================================================

# 鍮뚮뱶 ????젣???뚯씪 (媛쒖씤?뺣낫 ?ы븿)
FILES_TO_DELETE_BEFORE_BUILD = [
    "src/nuitka-crash-report.xml",     # 鍮뚮뱶 癒몄떊 ?꾩껜 寃쎈줈 ?몄텧
    "src/data/api_settings.json",      # ?ㅼ젣 API ???ы븿
    "src/data/.dev",                   # 媛쒕컻??諛붿씠?⑥뒪 ?뚯씪
    "src/data/license.dat",            # 濡쒖뺄 ?쇱씠?좎뒪 ?뚯씪
    "src/data/license_cache.json",     # 濡쒖뺄 罹먯떆
    "src/data/license_history.json",   # ?쇱씠?좎뒪 諛쒓툒 ?대젰 (?ъ슜?륤D/HWID/???ы븿)  ??v62.35 異붽?
    "src/data/gui_settings.json",      # 濡쒖뺄 GUI ?ㅼ젙
    "src/data/production_stats.json",  # 濡쒖뺄 ?듦퀎
    "src/data/batch_queue.json",       # 濡쒖뺄 ??
]

# 鍮뚮뱶 ????젣???뚯씪 glob ?⑦꽩 (?⑦꽩 留ㅼ묶 ?꾩슂???뚯씪)
FILES_TO_DELETE_PATTERNS = [
    "config/token_*.pickle",           # YouTube OAuth ?좏겙 (梨꾨꼸蹂?pickle)  ??v62.35 異붽?
    "config/youtube_token*.pickle",    # YouTube OAuth ?좏겙 ?泥?寃쎈줈
    "data/*.mp4",                      # ?곗텧臾??곸긽 (鍮뚮뱶??遺덊븘??
    "data/*.wav",                      # ?곗텧臾??ㅻ뵒??
    "data/*.log",                      # 濡쒓렇 ?뚯씪
]

# 鍮뚮뱶 ????젣???붾젆?좊━ (?ъ슜???곗텧臾?濡쒓렇 ??諛고룷???ы븿?섎㈃ 媛쒖씤?뺣낫쨌IP ?좎텧)
DIRS_TO_DELETE_BEFORE_BUILD = [
    "src/data/outputs",       # ?앹꽦???곸긽/?대?吏/?ㅻ뵒??(?ъ슜??肄섑뀗痢?  ??v62.35 異붽?
    "src/data/temp_images",   # ?꾩떆 ?대?吏 罹먯떆
    "src/data/temp_audio",    # ?꾩떆 ?ㅻ뵒??罹먯떆
    "src/data/logs",          # ?고???濡쒓렇 (?ъ슜???댁쁺 ?댁뿭)
    "src/data/scripts",       # ?앹꽦???蹂??뚯씪 (?ъ슜??肄섑뀗痢?  ??v62.35 異붽?
    "src/data/thumbnails",    # ?앹꽦???몃꽕???대?吏 (?ъ슜??肄섑뀗痢?  ??v62.35 異붽?
    "src/data/open_nexus",    # OpenNexus ?몄뀡 ?곗씠??
]

# 鍮뚮뱶?먯꽌 ?꾩쟾 ?쒖쇅???뚯씪 (愿由ъ옄 ?꾩슜)
FILES_TO_EXCLUDE_FROM_BUILD = [
    # ?? ?쇱씠?좎뒪 愿由??꾧뎄 (愿由ъ옄留??ъ슜, 諛고룷 湲덉?) ??
    "src/utils/license_generator.py",       # ?쇱씠?좎뒪 ???앹꽦湲?(SECRET_KEY ?ы븿)
    "src/utils/license_manager_gui.py",     # ?쇱씠?좎뒪 愿由ъ옄 GUI (諛쒓툒?대젰, ?ъ슜??寃??  ??v62.35 異붽?
    "src/gui/license_generator_gui.py",     # ?쇱씠?좎뒪 ?앹꽦湲?GUI (愿由ъ옄 ?꾩슜)
    # ?? 愿由ъ옄 ??쒕낫??(B2B/?먯씠?꾩떆 ?꾩슜, ?쇰컲 援щℓ??諛고룷 湲덉?) ??
    "src/gui/admin_dashboard.py",           # B2B 愿由ъ옄 ??쒕낫??(?먭꺽 ?쇱씠?좎뒪 ?쒖뼱 ??  ??v62.35 異붽?
    # ?? ?쒗겕由??뚯씪 ??
    "src/config/client_secrets.json",       # Google OAuth ?대씪?댁뼵???쒗겕由?
]

# ?뚯뒪?먯꽌 ?섎뱶肄붾뵫 ?쒗겕由??쒓굅 (鍮뚮뱶 ??sanitize)
SECRETS_TO_SANITIZE = {
    "src/config/pack_config.py": [
        # (李얠쓣 臾몄옄?? ?泥?臾몄옄??
        (
            "b'ReverieStudio_PackEncryption_v57'",
            "b''  # REVERIE_PACK_PASSWORD ?섍꼍蹂???꾩닔"
        ),
        (
            "b'ReveriePack2024Salt!'",
            "b''  # REVERIE_PACK_SALT ?섍꼍蹂???꾩닔"
        ),
        # v62.33: DEV_MODE ?뚯씪 湲곕컲 ?고쉶 李⑤떒 (諛고룷 鍮뚮뱶 ?먮룞 援먯껜)
        # 媛쒕컻: data/.dev ?뚯씪濡?DEV_MODE ?쒖꽦??媛??
        # 諛고룷: Nuitka媛 False濡?而댄뙆?????고??꾩뿉 ?뚯씪??留뚮뱾?대룄 ?고쉶 遺덇?
        (
            'os.path.exists("data/.dev") or os.path.exists(".dev")',
            'False',  # PROD: 諛고룷 鍮뚮뱶 ?먮룞 援먯껜 ??二쇱꽍??new_str???ｌ쑝硫?if臾?':' ?욎뿉 ?쇱뼱 SyntaxError
        ),
    ],
    "src/utils/license_validator.py": [
        # SECRET_KEY 諛붿씠??諛곗뿴 ?대갚 ?쒓굅
        (
            "_k = [82, 69, 86, 69, 82, 73, 69, 95, 80, 82, 79, 68, 95, 50, 48, 50, 53, 95,\n"
            "          83, 69, 67, 85, 82, 69, 95, 75, 69, 89, 95, 70, 73, 78, 65, 76]",
            "_k = []  # REVERIE_SECRET_KEY ?섍꼍蹂???꾩닔"
        ),
    ],
    "src/modules_pro/comfyui_client.py": [
        # ?섎뱶肄붾뵫 寃쎈줈 ?쒓굅
        (
            'print("  cd C:\\\\AI\\\\ComfyUI\\\\ComfyUI")',
            'print("  cd <ComfyUI ?ㅼ튂 寃쎈줈>")'
        ),
    ],
    "src/config/settings_v2.py": [
        # v62.35: dev_mode.txt ?뚯씪 湲곕컲 DEV_MODE ?고쉶 李⑤떒
        # 媛쒕컻: dev_mode.txt 議댁옱?섎㈃ DEV_MODE=True濡??고쉶 媛??
        # 諛고룷: False ?섎뱶肄붾뵫 ???뚯씪 ?앹꽦?대룄 ?고쉶 遺덇?
        (
            "            self.DEV_MODE = os.path.exists(dev_mode_file)",
            "            self.DEV_MODE = False  # PROD: dev_mode.txt ?고쉶 鍮꾪솢?깊솕 (諛고룷 鍮뚮뱶 ?먮룞 援먯껜)",
        ),
    ],
}

# 二쇱꽍 ??媛쒕컻??寃쎈줈 ?쒓굅 ?⑦꽩
COMMENT_PATH_PATTERNS = [
    "C:\\\\ffmpeg8\\\\",
    "C:\\\\AI\\\\",
    "C:\\\\ReverieStudio",
    "C:\\\\Users\\\\<username>",
]


# ============================================================
# 鍮뚮뱶 ?⑥닔
# ============================================================

def check_nuitka_installed():
    """Nuitka check - import fallback (subprocess timeout bypass)"""
    try:
        import nuitka
        version = getattr(nuitka, "__version__", "unknown")
        print(f"  Nuitka: {version}")
        return True
    except ImportError:
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            print(f"  Nuitka: {version}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    print("  [ERROR] Nuitka not installed.")
    print("  Install: pip install nuitka ordered-set")
    return False

def check_c_compiler():
    """C compiler check."""
    # Nuitka媛 ?먯껜?곸쑝濡?MSVC/MinGW瑜??먯깋?섎?濡?
    # PATH??cl.exe媛 ?놁뼱??VS ?ㅼ튂 寃쎈줈?먯꽌 ?먮룞 諛쒓껄??
    # ?ш린?쒕뒗 ?덈궡 硫붿떆吏留?異쒕젰
    print("  C 而댄뙆?쇰윭: Nuitka媛 ?먮룞 媛먯? (MSVC ?먮뒗 MinGW64)")
    return True


def guard_locked_output_dist():
    """
    Prevent link-stage failures caused by a locked existing exe.
    Move existing main_gui.dist aside before compiling.
    """
    dist_dir = os.path.join(RELEASE_DIR, DIST_DIR_NAME)
    if not os.path.exists(dist_dir):
        return None

    stamp = time.strftime("%Y%m%d_%H%M%S")

    # Antivirus/Explorer can hold transient file locks; retry briefly.
    for attempt in range(1, 11):
        backup_dir = os.path.join(
            RELEASE_DIR,
            f"_backup_{DIST_DIR_NAME}_{stamp}_{attempt}"
        )
        try:
            shutil.move(dist_dir, backup_dir)
            print(f"  lock-guard: moved {DIST_DIR_NAME} -> {os.path.basename(backup_dir)}")
            return backup_dir
        except Exception as e:
            if attempt < 10:
                print(f"  lock-guard: move retry {attempt}/10 ({e})")
                time.sleep(1.5)
                continue

            exe_path = os.path.join(dist_dir, EXE_NAME)
            print("  [ERROR] existing dist is locked and cannot be moved")
            print(f"  target: {exe_path}")
            print(f"  detail: {e}")
            print("  action: close running ReverieStudio.exe and retry")
            return False


def prepare_build_dir():
    """鍮뚮뱶???꾩떆 ?붾젆?좊━ 以鍮?(?먮낯 蹂댄샇)"""
    build_src = os.path.join(RELEASE_DIR, "_build_src")

    if os.path.exists(build_src):
        shutil.rmtree(build_src)

    # src/ ?꾩껜瑜?鍮뚮뱶???붾젆?좊━濡?蹂듭궗
    # Windows ?덉빟??nul, con, aux ????蹂듭궗 遺덇? ???먮윭 臾댁떆
    def _ignore_patterns(directory, filenames):
        # Windows ?덉빟 ?μ튂紐?(??뚮Ц??臾닿?)
        reserved = {'nul', 'con', 'aux', 'prn',
                     'com1', 'com2', 'com3', 'com4',
                     'lpt1', 'lpt2', 'lpt3'}
        ignored = set()
        for fn in filenames:
            name_lower = fn.lower().split('.')[0]  # nul.txt ??nul
            if name_lower in reserved:
                ignored.add(fn)
            elif fn in ('__pycache__',):
                ignored.add(fn)
            elif fn.endswith(('.pyc', '.pyo', '.c', '.pyd', '.so')):
                ignored.add(fn)
            elif fn.endswith('.egg-info'):
                ignored.add(fn)
            elif fn == 'nuitka-crash-report.xml':
                ignored.add(fn)
        return ignored

    shutil.copytree(SRC_DIR, build_src, ignore=_ignore_patterns)
    print(f"  ?뚯뒪 蹂듭궗: {SRC_DIR} -> {build_src}")

    # v62.36: main_gui.py 蹂듭궗 ?뺤씤 (MultiprocessingPlugin??吏곸젒 ?쎌쓬)
    entry_in_build = os.path.join(build_src, "main_gui.py")
    if not os.path.exists(entry_in_build):
        raise FileNotFoundError(f"[FATAL] main_gui.py 蹂듭궗 ?ㅽ뙣: {entry_in_build}")
    print(f"  main_gui.py ?뺤씤: OK")

    return build_src


def delete_sensitive_files(build_src):
    """媛쒖씤?뺣낫/?쒗겕由??뚯씪 ??젣"""
    import glob as _glob
    deleted = 0

    # 1. ?붾젆?좊━吏???젣 (?ъ슜???곗텧臾?濡쒓렇)
    for rel_path in DIRS_TO_DELETE_BEFORE_BUILD:
        clean_path = rel_path.replace("src/", "", 1)
        full_path = os.path.join(build_src, clean_path)
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            # ??젣 ??鍮??붾젆?좊━ ?ъ깮??(???쒖옉 ??寃쎈줈 ?놁쑝硫??щ옒??諛⑹?)
            os.makedirs(full_path, exist_ok=True)
            deleted += 1
            print(f"    ??젣(?붾젆?좊━): {rel_path}/")

    # 2. ?뺥솗??寃쎈줈 ?뚯씪 ??젣
    for rel_path in FILES_TO_DELETE_BEFORE_BUILD:
        clean_path = rel_path.replace("src/", "", 1)
        full_path = os.path.join(build_src, clean_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            deleted += 1
            print(f"    ??젣: {rel_path}")

    # 3. glob ?⑦꽩 ?뚯씪 ??젣 (token_*.pickle ??
    for pattern in FILES_TO_DELETE_PATTERNS:
        full_pattern = os.path.join(build_src, pattern)
        matched = _glob.glob(full_pattern)
        for full_path in matched:
            os.remove(full_path)
            deleted += 1
            rel = os.path.relpath(full_path, build_src)
            print(f"    ??젣(?⑦꽩): {rel}")

    # 4. 愿由ъ옄 ?꾩슜 ?뚯씪 ?쒖쇅
    for rel_path in FILES_TO_EXCLUDE_FROM_BUILD:
        clean_path = rel_path.replace("src/", "", 1)
        full_path = os.path.join(build_src, clean_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            deleted += 1
            print(f"    ?쒖쇅: {rel_path}")

    return deleted


def sanitize_secrets(build_src):
    """?뚯뒪肄붾뱶 ???섎뱶肄붾뵫 ?쒗겕由??쒓굅"""
    sanitized = 0
    for rel_path, replacements in SECRETS_TO_SANITIZE.items():
        clean_path = rel_path.replace("src/", "", 1)
        full_path = os.path.join(build_src, clean_path)
        if not os.path.exists(full_path):
            continue

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        modified = False
        for old_str, new_str in replacements:
            if old_str in content:
                content = content.replace(old_str, new_str)
                modified = True
                sanitized += 1
                print(f"    ?뺣━: {rel_path} ({old_str[:40]}...)")

        if modified:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

    return sanitized


def sanitize_developer_paths(build_src):
    """二쇱꽍/臾몄옄????媛쒕컻??寃쎈줈 ?쒓굅"""
    cleaned = 0
    for root, dirs, files in os.walk(build_src):
        # __pycache__ ?ㅽ궢
        dirs[:] = [d for d in dirs if d != '__pycache__']

        for fname in files:
            if not fname.endswith('.py'):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except (UnicodeDecodeError, PermissionError):
                continue

            modified = False
            for pattern in COMMENT_PATH_PATTERNS:
                if pattern in content:
                    # 二쇱꽍 ??寃쎈줈留??쒓굅 (# 濡??쒖옉?섎뒗 以??먮뒗 臾몄옄????
                    content = content.replace(pattern, "<...>")
                    modified = True
                    cleaned += 1

            if modified:
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(content)

    return cleaned


def create_api_settings_template(build_src):
    """api_settings.json 鍮??쒗뵆由??앹꽦"""
    template = {
        "sd_url": "http://127.0.0.1:7860",
        "sovits_url": "http://127.0.0.1:9880",
        "gemini_api_key": "",
        "youtube_api_key": ""
    }
    data_dir = os.path.join(build_src, "data")
    os.makedirs(data_dir, exist_ok=True)

    template_path = os.path.join(data_dir, "api_settings.template.json")
    with open(template_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    print(f"    ?앹꽦: api_settings.template.json")


def build_nuitka_command(build_src, mode="standalone"):
    """Nuitka 鍮뚮뱶 紐낅졊???앹꽦"""
    entry = os.path.join(build_src, "main_gui.py")
    output_dir = RELEASE_DIR

    cmd = [
        sys.executable, "-m", "nuitka",

        # 湲곕낯 ?ㅼ젙
        f"--output-dir={output_dir}",
        "--output-filename=ReverieStudio",

        # Windows ?ㅼ젙
        "--windows-console-mode=attach",  # 肄섏넄 李??좎? (濡쒓렇 ?뺤씤??
        "--assume-yes-for-downloads",      # MinGW64 ?먮룞 ?ㅼ슫濡쒕뱶

        # 理쒖쟻??
        "--remove-output",                 # ?댁쟾 鍮뚮뱶 ?먮룞 ??젣

        # GUI ?뚮윭洹몄씤 (CustomTkinter = tkinter 湲곕컲)
        "--enable-plugin=tk-inter",

        # Memory optimization (v62.36+ OOM fix)
        "--low-memory",
        "--jobs=2",        # TCL/Tk ?ы븿 ?꾩닔 (?놁쑝硫?李????대┝)

        # ?ы븿???⑦궎吏
    ]

    # 紐⑤뱶 ?ㅼ젙
    if mode == "onefile":
        cmd.append("--onefile")
    else:
        cmd.append("--standalone")

    # ???듭떖 ?꾨왂: ?곕━ 肄붾뱶留?C 而댄뙆??
    # --nofollow-imports: 湲곕낯?쇰줈 紐⑤뱺 import 異붿쟻 以묐떒
    # --follow-import-to: ?곕━ ?⑦궎吏留?C 而댄뙆????곸쑝濡?異붿쟻
    cmd.append("--nofollow-imports")

    # ?곕━ 肄붾뱶 ?⑦궎吏留?C 而댄뙆??(include + follow)
    for pkg in INCLUDE_PACKAGES:
        cmd.append(f"--include-package={pkg}")
        cmd.append(f"--follow-import-to={pkg}")

    # ?곗씠???붾젆?좊━ (?덉쑝硫??ы븿)
    for src_path, dst_path in INCLUDE_DATA_DIRS:
        full_src = os.path.join(build_src, src_path)
        if os.path.exists(full_src):
            cmd.append(f"--include-data-dir={full_src}={dst_path}")

    # Nuitka ?뚮윭洹몄씤
    # tk-inter ?뚮윭洹몄씤 ?쒓굅 ???섏〈??泥댁씤?쇰줈 scipy/sympy/torch ???섎갚 紐⑤뱢 ?좎엯
    # customtkinter??standalone 紐⑤뱶?먯꽌 ?먮룞 蹂듭궗??(Python ?뚯씪 洹몃?濡?

    # 踰⑦듃+硫쒕뭇: --nofollow-imports?먮룄 遺덇뎄?섍퀬 鍮좎졇?섏삤??嫄곕? ?⑦궎吏 紐낆떆 李⑤떒
    # (Nuitka 2.8.x?먯꽌 standalone 紐⑤뱶 ??--nofollow-imports媛 ?쇰? ?⑦궎吏??誘몄쟻?⑸릺???꾩긽)
    HARD_BLOCK = [
        "torch", "torchaudio", "torchvision", "transformers", "tensorflow", "keras",
        "scipy", "sympy", "sklearn", "pandas", "numba", "llvmlite", "joblib",
        "matplotlib", "plotly", "seaborn",
        "aiohttp", "uvicorn", "starlette", "websockets", "mcp",
        "rich", "pygments",
        "Cython", "cython", "setuptools", "distutils", "pip",
        "pytest", "test",  # unittest???쒓굅 ???고???IMPORT_HARD ?먮윭 諛쒖깮 (v62.35 ?섏젙)
        "cv2", "IPython", "jupyter", "notebook",
        "soundfile", "_soundfile", "_soundfile_data",
        "numpy.testing", "numpy.f2py", "numpy.distutils",
        "scipy.integrate", "scipy.optimize", "scipy.linalg", "scipy.sparse",
        "scipy.interpolate", "scipy.signal", "scipy.stats", "scipy.special",
        # v62.40: google.genai/generativeai ?섏젙 寃쎈줈 - 吏곸젒 吏숈이??(google.genai.types) Nuitka 誘몄?? 臾몄?
        # --nofollow-import-to 濡???Python bytecode濡??ы뵒?섌뿬 ?곕줂 ?⑦궎吏 理?섏쟻??
        "google.genai", "google.generativeai",
        "google.api_core", "google.api", "google.auth", "google.oauth2",
        "google.protobuf", "google.cloud",
        "googleapis_common_protos", "proto",
        "grpc", "grpcio",
        "cryptography",  # Fernet 肄붾뱶 - bytecode濡???ы뵒?섌뿬 ?곕줂 ?⑦궎吏 理?섏쟻??
        "blinker",
    ]
    for pkg in HARD_BLOCK:
        cmd.append(f"--nofollow-import-to={pkg}")

    # 吏꾪뻾瑜??쒖떆 (肄섏넄?먯꽌 吏곸젒 ?ㅽ뻾 ???좎슜)
    cmd.extend([
        "--show-progress",
        "--show-memory",
    ])

    # ?뷀듃由??ъ씤??
    cmd.append(entry)

    return cmd


def run_nuitka_build(cmd, dry_run=False):
    """Nuitka 鍮뚮뱶 ?ㅽ뻾"""
    print("\n  紐낅졊??")
    # 湲?紐낅졊??以꾨컮轅?
    for i, arg in enumerate(cmd):
        if i == 0:
            print(f"    {arg}", end="")
        else:
            print(f" \\\n      {arg}", end="")
    print("\n")

    if dry_run:
        print("  [DRY RUN] ?ㅼ젣 鍮뚮뱶瑜??ㅽ뻾?섏? ?딆뒿?덈떎.")
        return True

    # 濡쒓렇 ?뚯씪 寃쎈줈
    log_path = os.path.join(RELEASE_DIR, "nuitka_build.log")

    try:
        # stdout ??肄섏넄 + 濡쒓렇 ?뚯씪 ?숈떆 異쒕젰
        log_file = open(log_path, 'w', encoding='utf-8')

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )

        # ?ㅼ떆媛?異쒕젰 (?꾪꽣留?+ FATAL 利됱떆 媛먯?)
        for line in process.stdout:
            line = line.rstrip()
            if not line:
                continue

            # 濡쒓렇 ?뚯씪?먮뒗 ?꾨? 湲곕줉
            log_file.write(line + '\n')
            log_file.flush()

            line_lower = line.lower()

            # 肄섏넄 異쒕젰 (cp949 ?덉쟾?섍쾶)
            try:
                # FATAL/ERROR ??利됱떆 異쒕젰 + 鍮뚮뱶 以묐떒
                if 'fatal' in line_lower or ('error' in line_lower and 'not finished' not in line_lower):
                    print(f"  [ERROR] {line}")

                # 以묒슂 吏꾪뻾 ?ы빆 異쒕젰
                elif any(k in line_lower for k in [
                    'pass ', 'compil', 'link', 'creating', 'copying',
                    'generating', 'scons',
                ]):
                    print(f"  {line}")

                # Finished 移댁슫??(吏꾪뻾瑜?異붿쟻)
                elif 'modules to go' in line_lower:
                    print(f"  {line}")
            except (UnicodeEncodeError, UnicodeDecodeError):
                # cp949?먯꽌 異쒕젰 遺덇???臾몄옄 ??臾댁떆
                pass

        process.wait()
        log_file.close()

        if process.returncode != 0:
            print(f"\n  [ERROR] Nuitka 鍮뚮뱶 ?ㅽ뙣 (exit code: {process.returncode})")
            print(f"  濡쒓렇: {log_path}")
            return False

        print(f"  濡쒓렇 ??? {log_path}")
        return True

    except Exception as e:
        print(f"  [ERROR] Nuitka 鍮뚮뱶 ?덉쇅: {e}")
        return False



def copy_assets_to_dist():
    """Copy assets/ into dist/assets/ so the exe can resolve runtime resources."""
    dist_dir = os.path.join(RELEASE_DIR, DIST_DIR_NAME)
    if not os.path.isdir(dist_dir):
        print("  [SKIP] dist/ 폴더 없음 (dry-run일 수 있음)")
        return

    assets_src = os.path.join(PROJECT_ROOT, "assets")
    assets_dst = os.path.join(dist_dir, "assets")

    if not os.path.isdir(assets_src):
        print("  [WARN] assets/ 폴더가 프로젝트 루트에 없음")
        return

    # 복사할 서브폴더 목록
    ASSET_SUBDIRS = ["packs", "fonts", "bgm", "sfx", "models"]

    # v62.38: Windows 예약 파일명 필터 (nul, con, prn, aux, com1-9, lpt1-9)
    # shutil.copytree가 이 이름의 파일/폴더에서 [WinError 87] 발생
    _WIN_RESERVED = {
        'nul', 'con', 'prn', 'aux',
        'com1', 'com2', 'com3', 'com4', 'com5', 'com6', 'com7', 'com8', 'com9',
        'lpt1', 'lpt2', 'lpt3', 'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9',
    }

    def _ignore_reserved(directory, contents):
        """Windows 예약 파일명을 복사 대상에서 제외"""
        ignored = []
        for name in contents:
            stem = os.path.splitext(name)[0].lower()
            if stem in _WIN_RESERVED:
                print(f"  [SKIP] Windows 예약 파일명 제외: {os.path.join(directory, name)}")
                ignored.append(name)
        return ignored

    copied_count = 0
    skipped_count = 0

    for subdir in ASSET_SUBDIRS:
        src = os.path.join(assets_src, subdir)
        dst = os.path.join(assets_dst, subdir)

        if not os.path.isdir(src):
            print(f"  [SKIP] assets/{subdir}/ 없음")
            skipped_count += 1
            continue

        if os.path.exists(dst):
            shutil.rmtree(dst)

        try:
            shutil.copytree(src, dst, ignore=_ignore_reserved)
            n_files = sum(len(files) for _, _, files in os.walk(dst))
            src_mb = sum(
                os.path.getsize(os.path.join(dp, fname))
                for dp, dn, filenames in os.walk(src)
                for fname in filenames
            ) / (1024 * 1024)
            print(f"  복사: assets/{subdir}/ -> dist/assets/{subdir}/ ({n_files}개, {src_mb:.1f}MB)")
            copied_count += 1
        except Exception as e:
            print(f"  [ERROR] assets/{subdir}/ 복사 실패: {e}")

    print(f"  -> assets 복사 완료: {copied_count}개 폴더 ({skipped_count}개 스킵)")

    # data/ 초기 구조 생성
    data_dst = os.path.join(dist_dir, "data")
    os.makedirs(os.path.join(data_dst, "logs"), exist_ok=True)
    os.makedirs(os.path.join(data_dst, "crash_logs"), exist_ok=True)
    print("  생성: dist/data/logs/, dist/data/crash_logs/")

    # .env 템플릿 생성 (dist/ 내부)
    env_template = os.path.join(dist_dir, ".env.template")
    with open(env_template, 'w', encoding='utf-8') as f:
        f.write(
            "# Reverie Studio - 환경변수 설정 (필수)\n"
            "# .env.template을 .env로 복사하고 값을 채우세요\n"
            "\n"
            "GEMINI_API_KEY=여기에_Gemini_API_키_입력\n"
            "GS_ROOT=C:\\\\GPT-SoVITS\n"
            "SD_WEBUI_ROOT=C:\\\\stable-diffusion-webui\n"
            "FFMPEG_PATH=C:\\\\ffmpeg\\\\bin\\\\ffmpeg.exe\n"
            "SD_URL=http://127.0.0.1:7860\n"
            "SOVITS_URL=http://127.0.0.1:9880\n"
            "REVERIE_PACK_PASSWORD=\n"
            "REVERIE_PACK_SALT=\n"
            "REVERIE_SECRET_KEY=\n"
        )
    print("  생성: dist/.env.template")

    # 실행 배치파일 생성 (dist/ 내부, .env 자동 로딩)
    bat_path = os.path.join(dist_dir, "레베리스튜디오_실행.bat")
    bat_content = (
        "@echo off\n"
        "chcp 65001 >nul\n"
        "\n"
        ":: .env 파일에서 환경변수 자동 로딩\n"
        "if not exist \"%~dp0.env\" (\n"
        "    echo [오류] .env 파일이 없습니다. .env.template을 .env로 복사하고 설정하세요.\n"
        "    pause\n"
        "    exit /b 1\n"
        ")\n"
        "for /f \"usebackq tokens=1,* delims==\" %%%%A in (\"%~dp0.env\") do (\n"
        "    if not \"%%%%A\"==\"\" if not \"%%%%A:~0,1%%\"==\"#\" set \"%%%%A=%%%%B\"\n"
        ")\n"
        "\n"
        "\"%~dp0ReverieStudio.exe\"\n"
    )
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    print("  생성: dist/레베리스튜디오_실행.bat (.env 자동 로딩)")


def create_release_structure():
    """諛고룷 ?⑦궎吏 援ъ“ ?앹꽦 (鍮뚮뱶 寃곌낵臾?二쇰? ?뚯씪 諛곗튂)"""

    # .env.example
    env_example = os.path.join(RELEASE_DIR, ".env.example")
    with open(env_example, 'w', encoding='utf-8') as f:
        f.write("""# ============================================================
# Reverie Studio - ?섍꼍 ?ㅼ젙
# ???뚯씪??.env 濡?蹂듭궗????媛믪쓣 ?낅젰?섏꽭??
# ============================================================

# [?꾩닔] Gemini API ??(https://aistudio.google.com/apikey ?먯꽌 諛쒓툒)
GEMINI_API_KEY=?ш린??Gemini_API_???낅젰

# [?꾩닔] YouTube API ??(Google Cloud Console?먯꽌 諛쒓툒)
YOUTUBE_API_KEY=?ш린??YouTube_API_???낅젰

# [?꾩닔] ?쒕쾭 URL (湲곕낯媛?洹몃?濡??ъ슜 媛??
SD_URL=http://127.0.0.1:7860
SOVITS_URL=http://127.0.0.1:9880

# [?꾩닔] ?몃? ?꾧뎄 寃쎈줈
GS_ROOT=C:\\GPT-SoVITS
SD_WEBUI_ROOT=C:\\stable-diffusion-webui
FFMPEG_PATH=C:\\ffmpeg\\bin\\ffmpeg.exe

# [?꾩닔] ???뷀샇????(援щℓ ???쒓났)
REVERIE_PACK_PASSWORD=援щℓ???쒓났?섎뒗_??
REVERIE_PACK_SALT=援щℓ???쒓났?섎뒗_?뷀듃

# [?꾩닔] ?쇱씠?좎뒪 ??(援щℓ ???쒓났)
REVERIE_SECRET_KEY=援щℓ???쒓났?섎뒗_?쒗겕由?

# [?좏깮] ?쒕쾭 ?쒖옉 ?ㅼ젙
SD_WEBUI_SCRIPT=webui-user.bat
SOVITS_SCRIPT=start_api_with_ffmpeg.bat
AUTO_START_SERVERS=true
""")
    print(f"  ?앹꽦: .env.example")

    # main.bat
    main_bat = os.path.join(RELEASE_DIR, "main.bat")
    with open(main_bat, 'w', encoding='utf-8') as f:
        f.write("""@echo off
chcp 65001 >nul 2>&1
title Reverie Studio

echo ============================================
echo   Reverie Studio
echo ============================================

:: .env ?뚯씪 ?뺤씤
if not exist ".env" (
    echo.
    echo [ERROR] .env ?뚯씪???놁뒿?덈떎!
    echo .env.example ??.env 濡?蹂듭궗?????ㅼ젙媛믪쓣 ?낅젰?섏꽭??
    echo.
    pause
    exit /b 1
)

:: ?ㅽ뻾
cd /d "%~dp0"
main_gui.dist\\ReverieStudio.exe
pause
""")
    print(f"  ?앹꽦: main.bat")

    # VERSION
    version_file = os.path.join(RELEASE_DIR, "VERSION")
    with open(version_file, 'w') as f:
        f.write(f"v63.0\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    print(f"  ?앹꽦: VERSION")

    # assets/ ?붾젆?좊━ 蹂듭궗 ?덈궡
    print(f"\n  [INFO] ?ㅼ쓬 ?붾젆?좊━瑜??섎룞?쇰줈 release/ ??蹂듭궗?섏꽭??")
    print(f"    - assets/packs/    (???뚯씪)")
    print(f"    - assets/bgm/      (諛곌꼍?뚯븙)")
    print(f"    - assets/sfx/      (?④낵??")
    print(f"    - assets/models/   (TTS 紐⑤뜽)")
    print(f"    - remotion-poc/    (Remotion ?꾨줈?앺듃)")


def cleanup_build(build_src):
    """鍮뚮뱶 ?꾩떆 ?뚯씪 ?뺣━"""
    if os.path.exists(build_src):
        shutil.rmtree(build_src)
        print(f"  ?뺣━: {build_src}")

    # Nuitka 罹먯떆 ?뺣━
    nuitka_cache = os.path.join(RELEASE_DIR, "main_gui.build")
    if os.path.exists(nuitka_cache):
        shutil.rmtree(nuitka_cache)
        print(f"  ?뺣━: {nuitka_cache}")


# ============================================================
# 硫붿씤
# ============================================================

def cleanup_backup_dist(backup_dir):
    """Remove backup dist directory created by lock guard."""
    if backup_dir and os.path.exists(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)
        print(f"  cleanup: {backup_dir}")


def main():
    parser = argparse.ArgumentParser(description="Reverie Studio Nuitka 鍮뚮뱶")
    parser.add_argument("--mode", default="standalone",
                        choices=["standalone", "onefile"],
                        help="鍮뚮뱶 紐⑤뱶 (standalone=?대뜑, onefile=?⑥씪EXE)")
    parser.add_argument("--dry-run", action="store_true",
                        help="鍮뚮뱶 紐낅졊?대쭔 ?뺤씤 (?ㅽ뻾 ????")
    parser.add_argument("--skip-sanitize", action="store_true",
                        help="?쒗겕由??뺣━ 嫄대꼫?곌린 (?뚯뒪?몄슜)")
    parser.add_argument("--keep-build", action="store_true",
                        help="鍮뚮뱶 ?꾩떆 ?뚯씪 ?좎? (?붾쾭洹몄슜)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Reverie Studio - Nuitka 諛고룷 鍮뚮뱶")
    print("=" * 60)
    start_time = time.time()

    # Step 0: ?섍꼍 ?뺤씤
    print("\n[0/7] ?섍꼍 ?뺤씤")
    if not check_nuitka_installed():
        sys.exit(1)
    check_c_compiler()

    # Step 1: release/ ?뺣━
    print("\n[1/7] 鍮뚮뱶 ?붾젆?좊━ ?뺣━")
    os.makedirs(RELEASE_DIR, exist_ok=True)
    backup_dist = guard_locked_output_dist()
    if backup_dist is False:
        sys.exit(1)

    # Step 2: ?뚯뒪 蹂듭궗 (?먮낯 蹂댄샇)
    print("\n[2/7] ?뚯뒪 蹂듭궗 (?먮낯 蹂댄샇)")
    build_src = prepare_build_dir()

    # Step 3: 媛쒖씤?뺣낫 ?뚯씪 ??젣
    print("\n[3/7] 媛쒖씤?뺣낫/?쒗겕由??뚯씪 ?쒓굅")
    deleted = delete_sensitive_files(build_src)
    print(f"  -> {deleted}媛??뚯씪 ?쒓굅")

    # Step 4: ?뚯뒪肄붾뱶 ???쒗겕由??뺣━
    if not args.skip_sanitize:
        print("\n[4/7] ?뚯뒪肄붾뱶 ?쒗겕由?sanitize")
        sanitized = sanitize_secrets(build_src)
        path_cleaned = sanitize_developer_paths(build_src)
        create_api_settings_template(build_src)
        print(f"  -> ?쒗겕由?{sanitized}媛?援먯껜, 媛쒕컻寃쎈줈 {path_cleaned}媛??뺣━")
    else:
        print("\n[4/7] ?쒗겕由?sanitize ?ㅽ궢 (--skip-sanitize)")

    # Step 5: Nuitka 鍮뚮뱶
    print(f"\n[5/7] Nuitka 鍮뚮뱶 (mode={args.mode})")
    cmd = build_nuitka_command(build_src, args.mode)
    success = run_nuitka_build(cmd, args.dry_run)

    if not success and not args.dry_run:
        print("\n[ERROR] 鍮뚮뱶 ?ㅽ뙣!")
        if not args.keep_build:
            cleanup_build(build_src)
            cleanup_backup_dist(backup_dist)
        sys.exit(1)

    # Step 6: 배포 파일 생성 + assets 복사 (v62.37)
    print("\n[6/7] 배포 파일 생성 + assets 복사")
    create_release_structure()
    if not args.dry_run:
        print("  [6-2] assets/ -> dist/assets/ 복사 중...")
        copy_assets_to_dist()

    # Step 7: ?뺣━
    if not args.keep_build:
        print(f"\n[7/7] ?꾩떆 ?뚯씪 ?뺣━")
        cleanup_build(build_src)
        cleanup_backup_dist(backup_dist)
    else:
        print(f"\n[7/7] ?꾩떆 ?뚯씪 ?좎? (--keep-build)")

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    if not args.dry_run:
        # 寃곌낵臾??ш린 怨꾩궛
        dist_dir = os.path.join(RELEASE_DIR, DIST_DIR_NAME)
        if os.path.exists(dist_dir):
            size = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, dn, filenames in os.walk(dist_dir)
                for f in filenames
            ) / (1024 * 1024)
            print(f"  鍮뚮뱶 ?꾨즺! ({elapsed:.0f}珥? {size:.0f}MB)")
        else:
            print(f"  鍮뚮뱶 ?꾨즺! ({elapsed:.0f}珥?")
    else:
        print(f"  DRY RUN ?꾨즺! ({elapsed:.0f}珥?")
    print(f"  異쒕젰: {RELEASE_DIR}")
    print("=" * 60)

    # 理쒖쥌 ?먭?
    print("\n[諛고룷 ??泥댄겕由ъ뒪??")
    print(f"  [ ] .env.example -> .env 蹂듭궗 ?????낅젰")
    print(f"  [ ] assets/ (packs, bgm, sfx, models) 蹂듭궗")
    print(f"  [ ] remotion-poc/ 蹂듭궗 + npm install")
    print(f"  [ ] client_secrets.json 諛고룷??OAuth ?ㅻ줈 援먯껜 ??蹂듭궗")
    print("  [ ] main.bat run test")


if __name__ == "__main__":
    main()
