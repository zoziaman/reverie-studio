# -*- coding: utf-8 -*-
"""
Reverie Studio - 개발 환경 설치 마법사
v1.0.0 - 2026-02-08

VM 테스트에서 검증된 설치 과정을 자동화합니다.
"""

import subprocess
import sys
import os
import threading
import time
from pathlib import Path

# CustomTkinter 없을 때를 대비한 기본 tkinter fallback
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    USE_CTK = True
except ImportError:
    import tkinter as tk
    from tkinter import ttk
    USE_CTK = False


class InstallerApp:
    """Reverie Studio 개발 환경 설치 마법사"""

    # =========================================================================
    # VM 테스트에서 검증된 설치 목록 (2026-02-08)
    # =========================================================================

    CHOCO_PACKAGES = [
        ("python311", "Python 3.11"),
        ("nodejs-lts", "Node.js LTS"),
        ("ffmpeg", "FFmpeg"),
        ("git", "Git"),
    ]

    # 누락됐던 것들까지 모두 포함!
    PIP_PACKAGES = [
        "python-dotenv",
        "requests",
        "numpy",
        "pyperclip",
        "customtkinter",
        "google-generativeai",
        "pillow",
        "moviepy==1.0.3",      # 버전 명시 중요!
        "pydantic-settings",    # VM에서 누락됐던 것
        "firebase-admin",       # VM에서 누락됐던 것
        "openai-whisper",
        "google-auth-oauthlib",
        "google-api-python-client",
        "websocket-client",
        "torch",
    ]

    FOLDERS_TO_CREATE = [
        "data",
        "data/temp",
        "data/outputs",
        "data/scripts",
        "data/temp_audio",
        "data/temp_images",
        "data/thumbnails",
        "assets",
        "config",
        "logs",
    ]

    def __init__(self):
        self.current_step = 0
        self.install_path = None
        self.log_messages = []
        self.is_installing = False
        self.install_thread = None

        self._create_window()
        self._create_pages()
        self._show_page(0)

    def _create_window(self):
        """메인 윈도우 생성"""
        if USE_CTK:
            self.root = ctk.CTk()
            self.root.title("🎬 Reverie Studio 설치 마법사")
            self.root.geometry("700x650")
            self.root.resizable(False, False)
        else:
            self.root = tk.Tk()
            self.root.title("Reverie Studio 설치 마법사")
            self.root.geometry("700x650")
            self.root.resizable(False, False)

        # 중앙 정렬
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (700 // 2)
        y = (self.root.winfo_screenheight() // 2) - (650 // 2)
        self.root.geometry(f"700x650+{x}+{y}")

        # 메인 컨테이너
        if USE_CTK:
            self.main_frame = ctk.CTkFrame(self.root)
            self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        else:
            self.main_frame = tk.Frame(self.root, bg="#1a1a2e")
            self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def _create_pages(self):
        """설치 마법사 페이지들 생성"""
        self.pages = []

        # 페이지 1: 환영
        self.pages.append(self._create_welcome_page())

        # 페이지 2: 설치 경로
        self.pages.append(self._create_path_page())

        # 페이지 3: 설치 진행
        self.pages.append(self._create_install_page())

        # 페이지 4: 완료
        self.pages.append(self._create_complete_page())

    def _create_welcome_page(self):
        """환영 페이지"""
        if USE_CTK:
            frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

            # 제목
            title = ctk.CTkLabel(
                frame,
                text="🎬 Reverie Studio",
                font=ctk.CTkFont(size=32, weight="bold")
            )
            title.pack(pady=(40, 10))

            subtitle = ctk.CTkLabel(
                frame,
                text="개발 환경 설치 마법사",
                font=ctk.CTkFont(size=18)
            )
            subtitle.pack(pady=(0, 30))

            # 설명
            desc_text = """이 마법사는 Reverie Studio 실행에 필요한
개발 환경을 자동으로 설치합니다.

설치될 항목:
  ✓ Python 3.11
  ✓ Node.js LTS
  ✓ FFmpeg (영상 처리)
  ✓ Git
  ✓ Python 패키지들
  ✓ Remotion (영상 렌더링)

설치 시간: 약 10~20분 (인터넷 속도에 따라 다름)
필요 용량: 약 5GB"""

            desc = ctk.CTkLabel(
                frame,
                text=desc_text,
                font=ctk.CTkFont(size=14),
                justify="left"
            )
            desc.pack(pady=20)

            # 주의사항
            warning = ctk.CTkLabel(
                frame,
                text="⚠️ 관리자 권한이 필요합니다. 설치 중 다른 프로그램을 사용하지 마세요.",
                font=ctk.CTkFont(size=12),
                text_color="#ffcc00"
            )
            warning.pack(pady=(30, 0))

            # 버튼
            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.pack(side="bottom", fill="x", pady=20)

            next_btn = ctk.CTkButton(
                btn_frame,
                text="다음 ▶",
                font=ctk.CTkFont(size=16, weight="bold"),
                width=150,
                height=45,
                command=lambda: self._next_page()
            )
            next_btn.pack(side="right", padx=10)

            cancel_btn = ctk.CTkButton(
                btn_frame,
                text="취소",
                font=ctk.CTkFont(size=14),
                width=100,
                height=40,
                fg_color="#555555",
                command=self._cancel
            )
            cancel_btn.pack(side="right", padx=10)
        else:
            frame = tk.Frame(self.main_frame, bg="#1a1a2e")
            tk.Label(frame, text="Reverie Studio 설치 마법사",
                    font=("Arial", 24, "bold"), bg="#1a1a2e", fg="white").pack(pady=40)

        return frame

    def _create_path_page(self):
        """설치 경로 선택 페이지"""
        if USE_CTK:
            frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

            title = ctk.CTkLabel(
                frame,
                text="📁 설치 위치 선택",
                font=ctk.CTkFont(size=24, weight="bold")
            )
            title.pack(pady=(40, 30))

            # 경로 입력
            path_label = ctk.CTkLabel(
                frame,
                text="Reverie Studio를 설치할 폴더를 선택하세요:",
                font=ctk.CTkFont(size=14)
            )
            path_label.pack(pady=(0, 10))

            path_frame = ctk.CTkFrame(frame, fg_color="transparent")
            path_frame.pack(fill="x", padx=50, pady=10)

            # 기본 경로
            default_path = str(Path.home() / "ReverieStudio")

            self.path_entry = ctk.CTkEntry(
                path_frame,
                font=ctk.CTkFont(size=14),
                height=40,
                width=400
            )
            self.path_entry.insert(0, default_path)
            self.path_entry.pack(side="left", padx=(0, 10))

            browse_btn = ctk.CTkButton(
                path_frame,
                text="찾아보기",
                font=ctk.CTkFont(size=12),
                width=100,
                height=40,
                command=self._browse_folder
            )
            browse_btn.pack(side="left")

            # 설명
            info = ctk.CTkLabel(
                frame,
                text="""
💡 참고사항:
  • 경로에 한글이나 공백이 없는 것을 권장합니다
  • 약 5GB의 여유 공간이 필요합니다
  • 기존 Reverie 프로젝트 폴더와 다른 위치를 선택하세요
                """,
                font=ctk.CTkFont(size=12),
                justify="left",
                text_color="#aaaaaa"
            )
            info.pack(pady=30)

            # 버튼
            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.pack(side="bottom", fill="x", pady=20)

            next_btn = ctk.CTkButton(
                btn_frame,
                text="설치 시작 ▶",
                font=ctk.CTkFont(size=16, weight="bold"),
                width=150,
                height=45,
                fg_color="#28a745",
                hover_color="#218838",
                command=lambda: self._start_installation()
            )
            next_btn.pack(side="right", padx=10)

            back_btn = ctk.CTkButton(
                btn_frame,
                text="◀ 이전",
                font=ctk.CTkFont(size=14),
                width=100,
                height=40,
                fg_color="#555555",
                command=lambda: self._prev_page()
            )
            back_btn.pack(side="right", padx=10)
        else:
            frame = tk.Frame(self.main_frame, bg="#1a1a2e")
            tk.Label(frame, text="설치 경로 선택",
                    font=("Arial", 18), bg="#1a1a2e", fg="white").pack(pady=40)

        return frame

    def _create_install_page(self):
        """설치 진행 페이지"""
        if USE_CTK:
            frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

            title = ctk.CTkLabel(
                frame,
                text="⏳ 설치 진행 중...",
                font=ctk.CTkFont(size=24, weight="bold")
            )
            title.pack(pady=(30, 20))

            # 현재 작업 표시
            self.current_task_label = ctk.CTkLabel(
                frame,
                text="준비 중...",
                font=ctk.CTkFont(size=14)
            )
            self.current_task_label.pack(pady=10)

            # 전체 진행률
            self.progress_bar = ctk.CTkProgressBar(frame, width=500, height=25)
            self.progress_bar.pack(pady=10)
            self.progress_bar.set(0)

            self.progress_label = ctk.CTkLabel(
                frame,
                text="0%",
                font=ctk.CTkFont(size=14, weight="bold")
            )
            self.progress_label.pack(pady=5)

            # 로그 영역
            log_label = ctk.CTkLabel(
                frame,
                text="📋 설치 로그:",
                font=ctk.CTkFont(size=12),
                anchor="w"
            )
            log_label.pack(fill="x", padx=50, pady=(20, 5))

            self.log_textbox = ctk.CTkTextbox(
                frame,
                font=ctk.CTkFont(size=11),
                height=180,
                width=580
            )
            self.log_textbox.pack(pady=5)

            # 버튼 (설치 중에는 비활성화)
            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.pack(side="bottom", fill="x", pady=20)

            self.install_next_btn = ctk.CTkButton(
                btn_frame,
                text="완료",
                font=ctk.CTkFont(size=16, weight="bold"),
                width=150,
                height=45,
                state="disabled",
                command=lambda: self._next_page()
            )
            self.install_next_btn.pack(side="right", padx=10)
        else:
            frame = tk.Frame(self.main_frame, bg="#1a1a2e")
            tk.Label(frame, text="설치 중...",
                    font=("Arial", 18), bg="#1a1a2e", fg="white").pack(pady=40)

        return frame

    def _create_complete_page(self):
        """설치 완료 페이지"""
        if USE_CTK:
            frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

            # 성공 아이콘
            success_icon = ctk.CTkLabel(
                frame,
                text="✅",
                font=ctk.CTkFont(size=72)
            )
            success_icon.pack(pady=(50, 20))

            title = ctk.CTkLabel(
                frame,
                text="설치 완료!",
                font=ctk.CTkFont(size=28, weight="bold")
            )
            title.pack(pady=10)

            desc = ctk.CTkLabel(
                frame,
                text="""Reverie Studio 개발 환경이 성공적으로 설치되었습니다!

다음 단계:
  1. ComfyUI 설치 (이미지 생성용) - 별도 가이드 참조
  2. GPT-SoVITS 설치 (음성 합성용) - 별도 가이드 참조
  3. API 키 설정 (Gemini API 등)

설치 폴더에서 main_gui.py를 실행하여 시작하세요!""",
                font=ctk.CTkFont(size=14),
                justify="left"
            )
            desc.pack(pady=30)

            # 버튼
            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.pack(side="bottom", fill="x", pady=20)

            open_folder_btn = ctk.CTkButton(
                btn_frame,
                text="📂 설치 폴더 열기",
                font=ctk.CTkFont(size=14),
                width=150,
                height=40,
                command=self._open_install_folder
            )
            open_folder_btn.pack(side="left", padx=10)

            finish_btn = ctk.CTkButton(
                btn_frame,
                text="마침",
                font=ctk.CTkFont(size=16, weight="bold"),
                width=150,
                height=45,
                fg_color="#28a745",
                hover_color="#218838",
                command=self._finish
            )
            finish_btn.pack(side="right", padx=10)
        else:
            frame = tk.Frame(self.main_frame, bg="#1a1a2e")
            tk.Label(frame, text="설치 완료!",
                    font=("Arial", 24, "bold"), bg="#1a1a2e", fg="white").pack(pady=40)

        return frame

    # =========================================================================
    # 네비게이션
    # =========================================================================

    def _show_page(self, index):
        """페이지 표시"""
        for page in self.pages:
            page.pack_forget()
        self.pages[index].pack(fill="both", expand=True)
        self.current_step = index

    def _next_page(self):
        """다음 페이지"""
        if self.current_step < len(self.pages) - 1:
            self._show_page(self.current_step + 1)

    def _prev_page(self):
        """이전 페이지"""
        if self.current_step > 0:
            self._show_page(self.current_step - 1)

    def _cancel(self):
        """설치 취소"""
        if USE_CTK:
            dialog = ctk.CTkInputDialog(text="정말 취소하시겠습니까?", title="확인")
        self.root.destroy()

    def _finish(self):
        """설치 마법사 종료"""
        self.root.destroy()

    # =========================================================================
    # 폴더 선택
    # =========================================================================

    def _browse_folder(self):
        """폴더 선택 다이얼로그"""
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="설치 폴더 선택")
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _open_install_folder(self):
        """설치 폴더 열기"""
        if self.install_path and os.path.exists(self.install_path):
            os.startfile(self.install_path)

    # =========================================================================
    # 설치 프로세스
    # =========================================================================

    def _start_installation(self):
        """설치 시작"""
        self.install_path = self.path_entry.get()

        # 폴더 생성
        os.makedirs(self.install_path, exist_ok=True)

        # 설치 페이지로 이동
        self._show_page(2)

        # 백그라운드에서 설치 실행
        self.is_installing = True
        self.install_thread = threading.Thread(target=self._run_installation, daemon=True)
        self.install_thread.start()

    def _run_installation(self):
        """실제 설치 프로세스 (백그라운드 스레드)"""
        total_steps = 6
        current = 0

        try:
            # Step 1: Chocolatey 확인/설치
            current += 1
            self._update_progress(current, total_steps, "Chocolatey 확인 중...")
            self._ensure_chocolatey()

            # Step 2: 기본 패키지 설치 (Python, Node.js, FFmpeg, Git)
            current += 1
            self._update_progress(current, total_steps, "Python, Node.js, FFmpeg, Git 설치 중...")
            self._install_choco_packages()

            # Step 3: Python 패키지 설치
            current += 1
            self._update_progress(current, total_steps, "Python 패키지 설치 중... (시간이 걸립니다)")
            self._install_pip_packages()

            # Step 4: 프로젝트 파일 복사 (현재 폴더에서)
            current += 1
            self._update_progress(current, total_steps, "프로젝트 파일 복사 중...")
            self._copy_project_files()

            # Step 5: Remotion 설치
            current += 1
            self._update_progress(current, total_steps, "Remotion 설치 중...")
            self._install_remotion()

            # Step 6: 폴더 구조 생성
            current += 1
            self._update_progress(current, total_steps, "폴더 구조 생성 중...")
            self._create_folders()

            # 완료
            self._update_progress(total_steps, total_steps, "✅ 설치 완료!")
            self._log("=" * 50)
            self._log("🎉 모든 설치가 완료되었습니다!")
            self._log(f"📁 설치 경로: {self.install_path}")

            # 완료 버튼 활성화
            self.root.after(0, lambda: self.install_next_btn.configure(state="normal"))

        except Exception as e:
            self._log(f"❌ 오류 발생: {str(e)}")
            self._update_progress(current, total_steps, f"❌ 오류: {str(e)}")

    def _update_progress(self, current, total, message):
        """진행률 업데이트 (메인 스레드에서)"""
        progress = current / total
        percent = int(progress * 100)

        def update():
            if USE_CTK:
                self.progress_bar.set(progress)
                self.progress_label.configure(text=f"{percent}%")
                self.current_task_label.configure(text=message)

        self.root.after(0, update)
        self._log(f"[{percent}%] {message}")

    def _log(self, message):
        """로그 메시지 추가"""
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        self.log_messages.append(log_line)

        def update():
            if USE_CTK and hasattr(self, 'log_textbox'):
                self.log_textbox.insert("end", log_line + "\n")
                self.log_textbox.see("end")

        self.root.after(0, update)
        print(log_line)  # 콘솔에도 출력

    def _run_command(self, cmd, shell=True):
        """명령어 실행"""
        self._log(f"실행: {cmd}")
        try:
            result = subprocess.run(
                cmd,
                shell=shell,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            if result.returncode != 0:
                self._log(f"경고: {result.stderr[:200] if result.stderr else 'Unknown error'}")
            return result.returncode == 0
        except Exception as e:
            self._log(f"명령 실행 실패: {e}")
            return False

    # =========================================================================
    # 설치 단계별 함수들
    # =========================================================================

    def _ensure_chocolatey(self):
        """Chocolatey 설치 확인/설치"""
        # choco 명령어 확인
        result = subprocess.run("choco --version", shell=True, capture_output=True)
        if result.returncode == 0:
            self._log("✓ Chocolatey 이미 설치됨")
            return

        self._log("Chocolatey 설치 중...")
        # PowerShell로 Chocolatey 설치
        choco_install = '''Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))'''
        self._run_command(f'powershell -Command "{choco_install}"')

        # 환경변수 새로고침
        os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\ProgramData\chocolatey\bin"

    def _install_choco_packages(self):
        """Chocolatey로 기본 패키지 설치"""
        packages = " ".join([pkg[0] for pkg in self.CHOCO_PACKAGES])
        self._run_command(f"choco install {packages} -y --no-progress")

        # PATH 업데이트
        python_paths = [
            r"C:\Python311",
            r"C:\Python311\Scripts",
            r"C:\Program Files\nodejs",
            r"C:\ProgramData\chocolatey\bin",
        ]
        current_path = os.environ.get("PATH", "")
        for p in python_paths:
            if p not in current_path:
                os.environ["PATH"] = p + ";" + current_path
                current_path = os.environ["PATH"]

    def _install_pip_packages(self):
        """pip로 Python 패키지 설치"""
        # pip 업그레이드
        self._run_command("python -m pip install --upgrade pip")

        # 패키지 설치 (한번에)
        packages = " ".join(self.PIP_PACKAGES)
        self._run_command(f"pip install {packages}")

    def _copy_project_files(self):
        """프로젝트 파일 복사"""
        import shutil

        # 현재 스크립트 위치에서 프로젝트 루트 찾기
        script_dir = Path(__file__).parent.parent  # installer 폴더의 상위

        # 복사할 폴더들
        folders_to_copy = ["src", "config", "remotion-poc", "docs"]
        files_to_copy = ["requirements.txt", "CLAUDE.md", "USER_MANUAL.txt"]

        for folder in folders_to_copy:
            src = script_dir / folder
            dst = Path(self.install_path) / folder
            if src.exists():
                self._log(f"복사 중: {folder}/")
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                    'node_modules', '__pycache__', '*.pyc', '.git'
                ))

        for file in files_to_copy:
            src = script_dir / file
            dst = Path(self.install_path) / file
            if src.exists():
                self._log(f"복사 중: {file}")
                shutil.copy2(src, dst)

    def _install_remotion(self):
        """Remotion 설치 (npm install)"""
        remotion_path = Path(self.install_path) / "remotion-poc"
        if remotion_path.exists():
            self._run_command(f'cd "{remotion_path}" && npm install')
        else:
            self._log("⚠️ remotion-poc 폴더가 없습니다")

    def _create_folders(self):
        """필요한 폴더 구조 생성"""
        for folder in self.FOLDERS_TO_CREATE:
            folder_path = Path(self.install_path) / folder
            folder_path.mkdir(parents=True, exist_ok=True)
            self._log(f"폴더 생성: {folder}")

    # =========================================================================
    # 실행
    # =========================================================================

    def run(self):
        """마법사 실행"""
        self.root.mainloop()


def main():
    """메인 함수"""
    # 관리자 권한 확인
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("[!] 관리자 권한이 필요합니다!")
        print("이 프로그램을 마우스 오른쪽 클릭 -> '관리자 권한으로 실행'으로 다시 실행해주세요.")

        # 관리자 권한으로 재실행 시도
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        return

    app = InstallerApp()
    app.run()


if __name__ == "__main__":
    main()
