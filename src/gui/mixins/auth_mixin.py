# src/gui/mixins/auth_mixin.py
"""
v60.1.0: 인증/라이센스 Mixin — YouTube OAuth + 라이센스 관리

ReverieGUI에서 추출된 5개 메서드:
- _show_license_dialog: 라이센스 입력 다이얼로그
- _upload_youtube_credentials: credentials.json 업로드
- _authenticate_youtube: YouTube OAuth 인증
- _reset_youtube_auth: YouTube 인증 초기화
- _apply_license_restrictions: 라이센스 기반 채널 제한

의존하는 self 변수:
- self.license_validator, self.youtube_cred_path, self.youtube_token_path
- self.cred_status_label, self.token_status_label
- self.channel_options, self.channel_dropdown
"""
import json
import os
import threading
from tkinter import messagebox

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger("auth_mixin")


class AuthMixin:
    """인증/라이센스 횡단 관심사"""

    def _show_license_dialog(self, error_msg: str) -> bool:
        """
        라이센스 입력 다이얼로그

        Args:
            error_msg: 에러 메시지

        Returns:
            bool: 라이센스 등록 성공 여부
        """
        from utils.hardware_id import get_hardware_id
        from gui.main_window import get_font

        # 다이얼로그 생성
        dialog = ctk.CTkToplevel(self)
        dialog.title("🔐 라이센스 인증")
        dialog.geometry("600x500")

        # 중앙 배치
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 600) // 2
        y = (dialog.winfo_screenheight() - 500) // 2
        dialog.geometry(f"600x500+{x}+{y}")

        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        # 결과 저장용
        result = [False]

        # 타이틀
        title = ctk.CTkLabel(
            dialog,
            text="🔐 라이센스 인증",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title.pack(pady=20)

        # 에러 메시지
        if error_msg:
            error_label = ctk.CTkLabel(
                dialog,
                text=f"⚠️ {error_msg}",
                font=ctk.CTkFont(size=12),
                text_color="orange"
            )
            error_label.pack(pady=10)

        # 구분선
        separator1 = ctk.CTkFrame(dialog, height=2, fg_color="gray")
        separator1.pack(fill="x", padx=40, pady=20)

        # 하드웨어 ID 섹션
        hw_frame = ctk.CTkFrame(dialog)
        hw_frame.pack(pady=10, padx=40, fill="x")

        ctk.CTkLabel(
            hw_frame,
            text="💻 하드웨어 ID:",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 5))

        # 하드웨어 ID 가져오기
        hw_id = get_hardware_id()

        hw_entry_frame = ctk.CTkFrame(hw_frame, fg_color="transparent")
        hw_entry_frame.pack(fill="x", pady=5)

        hw_entry = ctk.CTkEntry(
            hw_entry_frame,
            width=400,
            font=ctk.CTkFont(size=13, family="Consolas")
        )
        hw_entry.insert(0, hw_id)
        hw_entry.configure(state="readonly")
        hw_entry.pack(side="left", fill="x", expand=True, padx=(10, 5))

        def copy_hw_id():
            try:
                import pyperclip
                pyperclip.copy(hw_id)
                messagebox.showinfo("복사 완료", "하드웨어 ID가 클립보드에 복사되었습니다.")
            except Exception:
                dialog.clipboard_clear()
                dialog.clipboard_append(hw_id)
                messagebox.showinfo("복사 완료", "하드웨어 ID가 클립보드에 복사되었습니다.")

        copy_btn = ctk.CTkButton(
            hw_entry_frame,
            text="📋",
            width=40,
            command=copy_hw_id
        )
        copy_btn.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            hw_frame,
            text="※ 이 ID를 개발자에게 전달하여 라이센스를 받으세요.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", pady=(5, 10), padx=10)

        # 구분선
        separator2 = ctk.CTkFrame(dialog, height=2, fg_color="gray")
        separator2.pack(fill="x", padx=40, pady=20)

        # 라이센스 입력 섹션
        license_frame = ctk.CTkFrame(dialog)
        license_frame.pack(pady=10, padx=40, fill="x")

        ctk.CTkLabel(
            license_frame,
            text="🔑 라이센스 키:",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 5))

        license_entry = ctk.CTkEntry(
            license_frame,
            placeholder_text="XXXXX-XXXXX-XXXXX-XXXXX",
            font=ctk.CTkFont(size=13, family="Consolas")
        )
        license_entry.pack(fill="x", pady=5, padx=10)

        # 상태 메시지
        status_label = ctk.CTkLabel(
            license_frame,
            text="",
            font=ctk.CTkFont(size=10)
        )
        status_label.pack(pady=5)

        # 버튼
        button_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        button_frame.pack(pady=20)

        def on_submit():
            key = license_entry.get().strip().upper()

            if not key:
                status_label.configure(text="❌ 라이센스 키를 입력하세요.", text_color="red")
                return

            # 검증
            success, msg = self.license_validator.set_license(key)

            if success:
                status_label.configure(text=f"✅ {msg}", text_color="green")
                # v62.24: 라이선스 등록 직후 런타임 팩 복호화 키 동기화
                try:
                    from config.pack_config import configure_pack_crypto
                    info = self.license_validator.get_license_info() if hasattr(self, "license_validator") else {}
                    lk = key
                    hw = ""
                    if isinstance(info, dict):
                        lk = info.get("license_key", lk)
                        hw = info.get("hardware_id", "")
                    if not hw:
                        hw = get_hardware_id()
                    configure_pack_crypto(lk, hw)
                except Exception as e:
                    logger.debug(f"[auth_mixin] pack crypto runtime key 동기화 스킵: {e}")
                result[0] = True
                dialog.after(1000, dialog.destroy)
            else:
                status_label.configure(text=f"❌ {msg}", text_color="red")

        def on_cancel():
            dialog.destroy()

        submit_btn = ctk.CTkButton(
            button_frame,
            text="✅ 등록",
            width=150,
            height=40,
            font=get_font("medium", bold=True),
            fg_color="green",
            hover_color="darkgreen",
            command=on_submit
        )
        submit_btn.pack(side="left", padx=10)

        cancel_btn = ctk.CTkButton(
            button_frame,
            text="❌ 취소",
            width=150,
            height=40,
            font=ctk.CTkFont(size=14),
            fg_color="gray",
            hover_color="darkgray",
            command=on_cancel
        )
        cancel_btn.pack(side="left", padx=10)

        # Enter 키 바인딩
        license_entry.bind("<Return>", lambda e: on_submit())
        license_entry.focus()

        # X 버튼 클릭 시
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        # 다이얼로그 대기
        dialog.wait_window()

        return result[0]

    def _upload_youtube_credentials(self):
        """YouTube credentials.json 파일 업로드"""
        from tkinter import filedialog
        import shutil
        from config.settings import config

        # 파일 선택 다이얼로그
        file_path = filedialog.askopenfilename(
            title="credentials.json 파일 선택",
            filetypes=[("JSON 파일", "*.json"), ("모든 파일", "*.*")],
            initialdir=os.path.expanduser("~")
        )

        if not file_path:
            return

        # 파일 검증
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                cred_data = json.load(f)

            # OAuth 클라이언트 ID 형식 확인
            if "installed" not in cred_data and "web" not in cred_data:
                messagebox.showerror(
                    "오류",
                    "유효한 OAuth 클라이언트 자격증명 파일이 아닙니다.\n\n"
                    "Google Cloud Console에서 'OAuth 2.0 클라이언트 ID'를 생성하고\n"
                    "데스크톱 앱용으로 다운로드한 credentials.json 파일을 사용하세요."
                )
                return

            # data 디렉토리 확인
            os.makedirs(config.DATA_DIR, exist_ok=True)

            # 파일 복사
            shutil.copy2(file_path, self.youtube_cred_path)

            # 상태 업데이트
            self.cred_status_label.configure(text="✅ 등록됨", text_color="green")

            messagebox.showinfo(
                "성공",
                "credentials.json이 등록되었습니다.\n\n"
                "'YouTube 인증' 버튼을 눌러 인증을 완료하세요."
            )

        except json.JSONDecodeError:
            messagebox.showerror("오류", "유효한 JSON 파일이 아닙니다.")
        except Exception as e:
            messagebox.showerror("오류", f"파일 복사 실패:\n{e}")

    def _authenticate_youtube(self):
        """YouTube OAuth 인증 실행"""
        if not os.path.exists(self.youtube_cred_path):
            messagebox.showwarning(
                "알림",
                "먼저 credentials.json 파일을 등록해주세요."
            )
            return

        # 백그라운드에서 인증 실행
        def auth_worker():
            try:
                from utils.youtube_uploader import YouTubeUploader

                # 기존 YouTubeUploader의 경로를 덮어씀
                uploader = YouTubeUploader.__new__(YouTubeUploader)
                uploader.credentials_path = self.youtube_cred_path
                uploader.token_path = self.youtube_token_path
                uploader.service = None

                # 인증 실행 (브라우저 열림)
                if uploader.authenticate():
                    # 채널 정보 가져오기
                    channel_info = uploader.get_channel_info()

                    self.after(0, lambda: self.token_status_label.configure(
                        text="✅ 인증됨",
                        text_color="green"
                    ))

                    if channel_info:
                        self.after(0, lambda: messagebox.showinfo(
                            "인증 성공",
                            f"YouTube 인증이 완료되었습니다!\n\n"
                            f"채널: {channel_info['title']}\n"
                            f"구독자: {channel_info['subscribers']}명\n"
                            f"영상 수: {channel_info['videos']}개"
                        ))
                    else:
                        self.after(0, lambda: messagebox.showinfo(
                            "인증 성공",
                            "YouTube 인증이 완료되었습니다!"
                        ))
                else:
                    self.after(0, lambda: messagebox.showerror(
                        "인증 실패",
                        "YouTube 인증에 실패했습니다.\n"
                        "credentials.json 파일을 확인해주세요."
                    ))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "오류",
                    f"인증 중 오류 발생:\n{str(e)}"
                ))

        # 안내 메시지
        messagebox.showinfo(
            "YouTube 인증",
            "브라우저가 열립니다.\n\n"
            "Google 계정으로 로그인하고 권한을 허용해주세요.\n"
            "인증이 완료되면 이 창에서 결과를 확인할 수 있습니다."
        )

        # 백그라운드 스레드에서 실행
        threading.Thread(target=auth_worker, daemon=True).start()

    def _reset_youtube_auth(self):
        """YouTube 인증 초기화"""
        if not messagebox.askyesno(
            "확인",
            "YouTube 인증 정보를 초기화하시겠습니까?\n\n"
            "토큰이 삭제되며, 다시 인증해야 합니다."
        ):
            return

        try:
            # 토큰 파일 삭제
            if os.path.exists(self.youtube_token_path):
                os.remove(self.youtube_token_path)

            # 상태 업데이트
            self.token_status_label.configure(text="⚠️ 미인증", text_color="orange")

            messagebox.showinfo("완료", "YouTube 인증 정보가 초기화되었습니다.")

        except Exception as e:
            messagebox.showerror("오류", f"초기화 실패:\n{e}")

    def _apply_license_restrictions(self):
        """
        v37: 라이센스 기반 채널 제한 적용

        이제 _load_channel_options에서 owned_packs 기반으로 필터링하므로
        이 메서드는 UI 업데이트만 담당
        """
        # 채널 목록 새로고침 (owned_packs 기반 필터링 적용됨)
        self.channel_options = self._load_channel_options()
        display_names = [opt[1] for opt in self.channel_options]
        self.channel_dropdown.configure(values=display_names)

        # 첫 번째 채널 자동 선택
        if display_names:
            self.channel_dropdown.set(display_names[0])
            self._on_channel_selected(display_names[0])
