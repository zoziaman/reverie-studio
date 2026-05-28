# src/gui/mixins/auth_mixin.py
"""
v60.1.0: 인증 Mixin — YouTube OAuth
v63: 라이선스 관련 기능 제거 (개인용). YouTube 인증만 유지.

ReverieGUI에서 추출된 메서드:
- _upload_youtube_credentials: credentials.json 업로드
- _authenticate_youtube: YouTube OAuth 인증
- _reset_youtube_auth: YouTube 인증 초기화
- _apply_license_restrictions: 채널 목록 새로고침 (이름 유지, 라이선스 제한 없음)

의존하는 self 변수:
- self.youtube_cred_path, self.youtube_token_path
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
    """인증 횡단 관심사 (YouTube OAuth)"""

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
        v63: 라이선스 제한 없음 (개인용). 채널 목록만 새로고침.
        (메서드명은 호출부 호환을 위해 유지)
        """
        # 채널 목록 새로고침 (전체 채널 표시)
        self.channel_options = self._load_channel_options()
        display_names = [opt[1] for opt in self.channel_options]
        self.channel_dropdown.configure(values=display_names)

        # 첫 번째 채널 자동 선택
        if display_names:
            self.channel_dropdown.set(display_names[0])
            self._on_channel_selected(display_names[0])
