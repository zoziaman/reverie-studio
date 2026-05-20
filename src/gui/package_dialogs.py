# src/gui/package_dialogs.py
"""
v37 - 패키지 관리 다이얼로그

1. PackageImportDialog: 패키지 가져오기 (사용자용)
2. PackageExportDialog: 패키지 내보내기 (Admin용)
3. MissingModelsDialog: 모델 누락 안내 다이얼로그
4. LicenseKeyInputDialog: 라이선스 키 입력 (레거시)
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import logging
import webbrowser
from typing import Optional, Callable, List
from pathlib import Path

logger = logging.getLogger(__name__)


class LicenseKeyInputDialog(ctk.CTkToplevel):
    """
    라이선스 키 입력 다이얼로그 (레거시 지원용)

    Firebase 구독 시스템이 아닌 구버전 패키지용
    """

    def __init__(self, parent, on_submit: Callable[[str], None] = None):
        super().__init__(parent)

        self.on_submit = on_submit

        self.title("라이선스 키 입력")
        self.geometry("400x200")
        self.resizable(False, False)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 중앙 배치
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 100
        self.geometry(f"+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 생성"""
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 안내 메시지
        ctk.CTkLabel(
            main_frame,
            text="이 패키지는 라이선스 키가 필요합니다.",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            main_frame,
            text="패키지 구매 시 받은 라이선스 키를 입력해주세요.",
            font=ctk.CTkFont(size=12),
            text_color="#888888"
        ).pack(anchor="w", pady=(5, 15))

        # 입력 필드
        self.key_entry = ctk.CTkEntry(
            main_frame,
            width=360,
            height=40,
            placeholder_text="XXXX-XXXX-XXXX-XXXX",
            font=ctk.CTkFont(size=14)
        )
        self.key_entry.pack(fill="x", pady=10)
        self.key_entry.bind("<Return>", lambda e: self._on_confirm())

        # 버튼 영역
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(15, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="#555555",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="확인",
            width=100,
            fg_color="#4CAF50",
            command=self._on_confirm
        ).pack(side="right")

        # 포커스
        self.key_entry.focus_set()

    def _on_confirm(self):
        """확인 버튼"""
        key = self.key_entry.get().strip()

        if not key:
            messagebox.showwarning("경고", "라이선스 키를 입력해주세요.")
            return

        if self.on_submit:
            self.on_submit(key)

        self.destroy()


class MissingModelsDialog(ctk.CTkToplevel):
    """
    모델 누락 안내 다이얼로그

    패키지 Import 시 필요한 모델이 없을 때 표시
    다운로드 링크 또는 안내 메시지 제공
    """

    def __init__(self, parent, missing_models: List, on_continue: Callable = None):
        """
        Args:
            parent: 부모 윈도우
            missing_models: ModelValidationResult 리스트
            on_continue: "계속 진행" 버튼 콜백
        """
        super().__init__(parent)

        self.missing_models = missing_models
        self.on_continue = on_continue

        self.title("필요한 모델 안내")
        self.geometry("550x450")
        self.resizable(False, False)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 중앙 배치
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 275
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 225
        self.geometry(f"+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 생성"""
        # 메인 프레임
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 헤더
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            header_frame,
            text="⚠️ 필요한 모델이 설치되지 않았습니다",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#FFA500"
        ).pack(anchor="w")

        ctk.CTkLabel(
            header_frame,
            text="아래 모델을 설치해야 패키지의 모든 기능을 사용할 수 있습니다.",
            font=ctk.CTkFont(size=12),
            text_color="#888888"
        ).pack(anchor="w", pady=(5, 0))

        # 모델 목록 스크롤 영역
        scroll_frame = ctk.CTkScrollableFrame(main_frame, height=250)
        scroll_frame.pack(fill="both", expand=True, pady=10)

        for result in self.missing_models:
            self._create_model_row(scroll_frame, result)

        # 버튼 영역
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(15, 0))

        # 취소 버튼
        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="#555555",
            command=self._on_cancel
        ).pack(side="left")

        # 계속 진행 버튼
        ctk.CTkButton(
            btn_frame,
            text="일단 계속 진행",
            width=150,
            fg_color="#2196F3",
            command=self._on_continue
        ).pack(side="right")

    def _create_model_row(self, parent, result):
        """모델 행 생성"""
        model_info = result.model_info

        # 딕셔너리인 경우 처리
        if isinstance(model_info, dict):
            name = model_info.get("name", "알 수 없음")
            model_type = model_info.get("type", "unknown")
            required = model_info.get("required", True)
            download_url = model_info.get("download_url", "")
            note = model_info.get("note", "")
        else:
            name = model_info.name
            model_type = model_info.type
            required = model_info.required
            download_url = model_info.download_url
            note = model_info.note

        row = ctk.CTkFrame(parent, fg_color="#2B2B2B", corner_radius=8)
        row.pack(fill="x", pady=5, padx=5)

        # 왼쪽: 모델 정보
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=15, pady=10)

        # 필수 여부 표시
        required_text = "필수" if required else "선택"
        required_color = "#F44336" if required else "#888888"

        header_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        header_row.pack(fill="x")

        ctk.CTkLabel(
            header_row,
            text=name,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(side="left")

        ctk.CTkLabel(
            header_row,
            text=f"[{required_text}]",
            font=ctk.CTkFont(size=11),
            text_color=required_color
        ).pack(side="left", padx=(10, 0))

        # 타입
        ctk.CTkLabel(
            info_frame,
            text=f"타입: {model_type}",
            font=ctk.CTkFont(size=11),
            text_color="#888888",
            anchor="w"
        ).pack(anchor="w")

        # 안내 메시지
        if note:
            ctk.CTkLabel(
                info_frame,
                text=note,
                font=ctk.CTkFont(size=11),
                text_color="#FFA500",
                anchor="w"
            ).pack(anchor="w", pady=(5, 0))

        # 오른쪽: 다운로드 버튼
        if download_url:
            ctk.CTkButton(
                row,
                text="다운로드",
                width=80,
                height=30,
                fg_color="#4CAF50",
                command=lambda url=download_url: self._open_url(url)
            ).pack(side="right", padx=15, pady=10)

    def _open_url(self, url: str):
        """URL 열기"""
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.error(f"[MissingModelsDialog] URL 열기 실패: {e}")

    def _on_cancel(self):
        """취소"""
        self.destroy()

    def _on_continue(self):
        """계속 진행"""
        if self.on_continue:
            self.on_continue()
        self.destroy()


class PackageImportDialog(ctk.CTkToplevel):
    """
    패키지 가져오기 다이얼로그 (사용자용)
    """

    def __init__(self, parent, on_complete: Callable = None, on_import_success: Callable = None):
        """
        Args:
            parent: 부모 윈도우
            on_complete: 완료 콜백 (ImportResult)
            on_import_success: 완료 콜백 별칭 (on_complete와 동일)
        """
        super().__init__(parent)

        self.on_complete = on_complete or on_import_success
        self._package_path: Optional[str] = None
        self._preview_data = None

        self.title("패키지 가져오기")
        self.geometry("600x580")
        self.resizable(False, False)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 중앙 배치
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 300
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 250
        self.geometry(f"+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 생성"""
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 헤더 (v57.7.3: 텍스트 개선)
        ctk.CTkLabel(
            main_frame,
            text="🎬 콘텐츠 팩 가져오기",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            main_frame,
            text=".revpack 파일을 선택하면 새로운 콘텐츠 팩이 등록됩니다.\n등록된 팩은 채널 목록에서 선택하여 바로 영상 생산에 사용할 수 있습니다.",
            font=ctk.CTkFont(size=12),
            text_color="#888888"
        ).pack(anchor="w", pady=(5, 20))

        # 파일 선택 영역
        file_frame = ctk.CTkFrame(main_frame, fg_color="#2B2B2B", corner_radius=8)
        file_frame.pack(fill="x", pady=10)

        file_inner = ctk.CTkFrame(file_frame, fg_color="transparent")
        file_inner.pack(fill="x", padx=15, pady=15)

        self.file_label = ctk.CTkLabel(
            file_inner,
            text="파일을 선택하세요...",
            font=ctk.CTkFont(size=12),
            text_color="#888888",
            anchor="w"
        )
        self.file_label.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            file_inner,
            text="파일 선택",
            width=100,
            command=self._browse_file
        ).pack(side="right")

        # 미리보기 영역 (v57.7.3: 텍스트 개선)
        preview_label = ctk.CTkLabel(
            main_frame,
            text="📋 팩 정보",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        preview_label.pack(anchor="w", pady=(20, 10))

        self.preview_frame = ctk.CTkFrame(main_frame, fg_color="#2B2B2B", corner_radius=8)
        self.preview_frame.pack(fill="both", expand=True)

        self.preview_label = ctk.CTkLabel(
            self.preview_frame,
            text="팩 파일(.revpack)을 선택하면\n여기에 팩 정보가 표시됩니다.\n\n• 팩 이름 및 버전\n• 장르 및 스타일\n• BGM/TTS 설정",
            font=ctk.CTkFont(size=12),
            text_color="#888888"
        )
        self.preview_label.pack(expand=True)

        # 버튼 영역
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="#555555",
            command=self.destroy
        ).pack(side="left")

        self.import_btn = ctk.CTkButton(
            btn_frame,
            text="가져오기",
            width=120,
            fg_color="#4CAF50",
            state="disabled",
            command=self._do_import
        )
        self.import_btn.pack(side="right")

    def _browse_file(self):
        """파일 선택"""
        file_path = filedialog.askopenfilename(
            title="패키지 파일 선택",
            filetypes=[("Reverie Package", "*.revpack"), ("All files", "*.*")]
        )

        if file_path:
            self._package_path = file_path
            self.file_label.configure(
                text=Path(file_path).name,
                text_color="#FFFFFF"
            )
            self._load_preview()

    def _load_preview(self):
        """패키지 미리보기 로드"""
        if not self._package_path:
            return

        try:
            from utils.package_manager import get_package_manager
            manager = get_package_manager()
            package = manager._load_package_file(self._package_path)

            if package:
                self._preview_data = package
                self._show_preview(package)
                self.import_btn.configure(state="normal")
            else:
                self._show_preview_error("패키지 파일을 읽을 수 없습니다.")

        except Exception as e:
            logger.error(f"[PackageImportDialog] 미리보기 실패: {e}")
            self._show_preview_error(str(e))

    def _show_preview(self, package):
        """미리보기 표시"""
        # 기존 위젯 제거
        for widget in self.preview_frame.winfo_children():
            widget.destroy()

        # 스크롤 가능한 프레임
        scroll = ctk.CTkScrollableFrame(self.preview_frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # 패키지 정보 (v57.7.3: 텍스트 개선)
        info_items = [
            ("🎬 팩 이름", package.package_name),
            ("📌 버전", package.version),
            ("👤 제작자", package.author or "미지정"),
            ("🎭 장르", package.channel_type),
            ("📝 설명", package.description or "없음"),
            ("⚙️ 필요 버전", f"v{package.reverie_version_min} 이상"),
        ]

        for label, value in info_items:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row,
                text=f"{label}:",
                font=ctk.CTkFont(size=12, weight="bold"),
                width=120,
                anchor="w"
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=str(value)[:50] + ("..." if len(str(value)) > 50 else ""),
                font=ctk.CTkFont(size=12),
                text_color="#CCCCCC",
                anchor="w"
            ).pack(side="left", fill="x", expand=True)

        # 필수 모델 목록
        if package.required_models:
            ctk.CTkLabel(
                scroll,
                text="필요한 모델:",
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w"
            ).pack(anchor="w", pady=(15, 5))

            for key, model in package.required_models.items():
                if isinstance(model, dict):
                    name = model.get("name", key)
                    required = model.get("required", True)
                else:
                    name = model.name
                    required = model.required

                req_text = " (필수)" if required else " (선택)"
                ctk.CTkLabel(
                    scroll,
                    text=f"  • {name}{req_text}",
                    font=ctk.CTkFont(size=11),
                    text_color="#AAAAAA",
                    anchor="w"
                ).pack(anchor="w")

    def _show_preview_error(self, message: str):
        """미리보기 에러 표시"""
        for widget in self.preview_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self.preview_frame,
            text=f"오류: {message}",
            font=ctk.CTkFont(size=12),
            text_color="#F44336"
        ).pack(expand=True)

        self.import_btn.configure(state="disabled")

    def _do_import(self, license_key: Optional[str] = None):
        """패키지 가져오기 실행"""
        if not self._package_path:
            return

        try:
            from utils.package_manager import get_package_manager
            manager = get_package_manager()
            result = manager.import_package(self._package_path, license_key=license_key)

            if result.success:
                # 누락된 모델이 있으면 안내
                if result.missing_models:
                    critical = [m for m in result.missing_models if m.is_critical]
                    if critical:
                        MissingModelsDialog(
                            self,
                            result.missing_models,
                            on_continue=lambda: self._finish_import(result)
                        )
                        return

                self._finish_import(result)
            elif result.error == "LICENSE_REQUIRED":
                # 라이선스 키 필요 -> 입력 다이얼로그 표시 (레거시)
                self._show_license_input_dialog()
            elif "구매하지 않은 패키지" in result.error:
                # 패키지 미소유 - 구매 안내
                self._show_purchase_required_dialog(result.error)
            elif "라이센스가 등록되지 않았습니다" in result.error:
                # 구독 미등록 - 구독 안내
                self._show_subscription_required_dialog()
            else:
                messagebox.showerror("오류", f"가져오기 실패:\n{result.error}")

        except Exception as e:
            logger.error(f"[PackageImportDialog] Import 실패: {e}")
            messagebox.showerror("오류", f"가져오기 실패: {str(e)}")

    def _show_license_input_dialog(self):
        """라이선스 키 입력 다이얼로그 (레거시)"""
        dialog = LicenseKeyInputDialog(
            self,
            on_submit=self._on_license_key_submitted
        )

    def _on_license_key_submitted(self, license_key: str):
        """라이선스 키 입력 후 재시도"""
        if license_key:
            self._do_import(license_key=license_key)

    def _show_purchase_required_dialog(self, message: str):
        """패키지 구매 필요 안내"""
        result = messagebox.askquestion(
            "패키지 구매 필요",
            f"{message}\n\n웹사이트에서 구매 페이지를 여시겠습니까?",
            icon='warning'
        )
        if result == 'yes':
            import webbrowser
            # v60.1.0: 상용화 시 실제 상점 URL로 교체 필요
            # TODO(deploy): Shopify/Firebase Dynamic Links 연동 후 교체
            store_url = "https://reverie-studio.com/store"
            webbrowser.open(store_url)

    def _show_subscription_required_dialog(self):
        """구독 등록 필요 안내"""
        messagebox.showwarning(
            "구독 필요",
            "패키지를 사용하려면 먼저 구독을 등록해야 합니다.\n\n"
            "[시스템] 탭에서 라이센스 키를 입력해주세요."
        )

    def _finish_import(self, result):
        """가져오기 완료"""
        messagebox.showinfo("완료", "패키지를 성공적으로 가져왔습니다!")

        if self.on_complete:
            self.on_complete(result)

        self.destroy()


class PackageExportDialog(ctk.CTkToplevel):
    """
    패키지 내보내기 다이얼로그 (Admin용)
    """

    def __init__(self, parent, channel_type: str = "daily_life_toon", on_complete: Callable = None, on_export_success: Callable = None):
        """
        Args:
            parent: 부모 윈도우
            channel_type: 내보낼 채널 타입
            on_complete: 완료 콜백 (file_path)
            on_export_success: 완료 콜백 별칭 (on_complete와 동일)
        """
        super().__init__(parent)

        self.channel_type = channel_type
        self.on_complete = on_complete or on_export_success

        self.title("패키지 내보내기")
        self.geometry("500x550")
        self.resizable(False, False)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 중앙 배치
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 250
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 275
        self.geometry(f"+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 생성"""
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 헤더
        ctk.CTkLabel(
            main_frame,
            text="채널 패키지 내보내기",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            main_frame,
            text="현재 설정을 .revpack 파일로 저장합니다.",
            font=ctk.CTkFont(size=12),
            text_color="#888888"
        ).pack(anchor="w", pady=(5, 20))

        # 입력 폼
        form_frame = ctk.CTkFrame(main_frame, fg_color="#2B2B2B", corner_radius=8)
        form_frame.pack(fill="x", pady=10)

        form_inner = ctk.CTkFrame(form_frame, fg_color="transparent")
        form_inner.pack(fill="x", padx=20, pady=20)

        # 패키지 이름
        ctk.CTkLabel(
            form_inner,
            text="패키지 이름 *",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w")

        self.name_entry = ctk.CTkEntry(form_inner, width=400, height=35)
        self.name_entry.pack(anchor="w", pady=(5, 15))
        self.name_entry.insert(0, f"{self.channel_type.title()} 채널 팩")

        # 제작자
        ctk.CTkLabel(
            form_inner,
            text="제작자",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w")

        self.author_entry = ctk.CTkEntry(form_inner, width=400, height=35)
        self.author_entry.pack(anchor="w", pady=(5, 15))

        # 설명
        ctk.CTkLabel(
            form_inner,
            text="설명",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w")

        self.desc_textbox = ctk.CTkTextbox(form_inner, width=400, height=80)
        self.desc_textbox.pack(anchor="w", pady=(5, 15))

        # 버전
        ctk.CTkLabel(
            form_inner,
            text="버전",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w")

        self.version_entry = ctk.CTkEntry(form_inner, width=100, height=35)
        self.version_entry.pack(anchor="w", pady=(5, 15))
        self.version_entry.insert(0, "1.0.0")

        # 옵션
        options_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        options_frame.pack(fill="x", pady=10)

        self.preview_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_frame,
            text="미리보기 이미지 포함",
            variable=self.preview_var
        ).pack(anchor="w")

        # 버튼 영역
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="#555555",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="내보내기",
            width=120,
            fg_color="#4CAF50",
            command=self._do_export
        ).pack(side="right")

    def _do_export(self):
        """내보내기 실행"""
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("경고", "패키지 이름을 입력하세요.")
            return

        # 저장 경로 선택
        file_path = filedialog.asksaveasfilename(
            title="패키지 저장",
            defaultextension=".revpack",
            filetypes=[("Reverie Package", "*.revpack")],
            initialfile=f"{name.replace(' ', '_')}.revpack"
        )

        if not file_path:
            return

        try:
            from utils.package_manager import get_package_manager
            manager = get_package_manager()

            # 패키지 생성
            package = manager.create_package_from_current_settings(
                package_name=name,
                channel_type=self.channel_type,
                author=self.author_entry.get().strip(),
                description=self.desc_textbox.get("1.0", "end").strip()
            )
            package.version = self.version_entry.get().strip() or "1.0.0"

            # 내보내기
            success, message = manager.export_package(
                package,
                file_path,
                include_preview=self.preview_var.get()
            )

            if success:
                messagebox.showinfo("완료", message)
                if self.on_complete:
                    self.on_complete(file_path)
                self.destroy()
            else:
                messagebox.showerror("오류", message)

        except Exception as e:
            logger.error(f"[PackageExportDialog] Export 실패: {e}")
            messagebox.showerror("오류", f"내보내기 실패: {str(e)}")
