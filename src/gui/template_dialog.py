# src/gui/template_dialog.py
"""
템플릿 관리 다이얼로그
"""
import customtkinter as ctk
from tkinter import messagebox, simpledialog
from typing import Dict, Any, Callable, Optional


class TemplateDialog(ctk.CTkToplevel):
    """템플릿 저장/불러오기 다이얼로그"""

    def __init__(self, parent, template_manager, on_load_callback: Callable = None):
        super().__init__(parent)

        self.template_manager = template_manager
        self.on_load_callback = on_load_callback
        self.parent_window = parent

        self.title("📁 템플릿 관리")
        self.geometry("600x500")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 600) // 2
        y = (self.winfo_screenheight() - 500) // 2
        self.geometry(f"600x500+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        # 제목
        ctk.CTkLabel(
            self,
            text="📁 템플릿 관리",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=15)

        # 템플릿 목록
        list_frame = ctk.CTkFrame(self)
        list_frame.pack(fill="both", expand=True, padx=20, pady=10)

        ctk.CTkLabel(
            list_frame,
            text="저장된 템플릿",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.template_scroll = ctk.CTkScrollableFrame(list_frame)
        self.template_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        self._refresh_templates()

        # 버튼 프레임
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkButton(
            button_frame,
            text="➕ 현재 설정 저장",
            command=self._save_current,
            width=140
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            button_frame,
            text="닫기",
            command=self.destroy,
            width=80
        ).pack(side="right", padx=5)

    def _refresh_templates(self):
        """템플릿 목록 새로고침"""
        for widget in self.template_scroll.winfo_children():
            widget.destroy()

        templates = self.template_manager.get_all_templates()

        if not templates:
            ctk.CTkLabel(
                self.template_scroll,
                text="저장된 템플릿이 없습니다.",
                font=ctk.CTkFont(size=12),
                text_color="gray"
            ).pack(pady=30)
            return

        default_name = self.template_manager.templates.get("default_template")

        for template in templates:
            self._create_template_row(template, template["name"] == default_name)

    def _create_template_row(self, template: Dict[str, Any], is_default: bool):
        """템플릿 행 생성"""
        row = ctk.CTkFrame(self.template_scroll)
        row.pack(fill="x", pady=3)

        # 기본 템플릿 표시
        prefix = "⭐ " if is_default else "   "

        # 템플릿 정보
        name = template["name"]
        channel = template.get("channel", "")
        mode = template.get("mode", "")
        description = template.get("description", "")[:30]

        info_text = f"{prefix}{name} [{channel}/{mode}]"
        if description:
            info_text += f" - {description}..."

        ctk.CTkLabel(
            row,
            text=info_text,
            font=ctk.CTkFont(size=12),
            anchor="w"
        ).pack(side="left", padx=10, fill="x", expand=True)

        # 버튼들
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=5)

        # 불러오기
        ctk.CTkButton(
            btn_frame,
            text="불러오기",
            width=70,
            command=lambda n=name: self._load_template(n)
        ).pack(side="left", padx=2)

        # 기본 설정
        ctk.CTkButton(
            btn_frame,
            text="⭐",
            width=30,
            fg_color="orange" if is_default else "gray",
            command=lambda n=name: self._set_default(n)
        ).pack(side="left", padx=2)

        # 복제
        ctk.CTkButton(
            btn_frame,
            text="📋",
            width=30,
            command=lambda n=name: self._duplicate_template(n)
        ).pack(side="left", padx=2)

        # 삭제
        ctk.CTkButton(
            btn_frame,
            text="🗑️",
            width=30,
            fg_color="red",
            hover_color="darkred",
            command=lambda n=name: self._delete_template(n)
        ).pack(side="left", padx=2)

    def _load_template(self, name: str):
        """템플릿 불러오기"""
        template = self.template_manager.get_template(name)
        if template and self.on_load_callback:
            self.on_load_callback(template)
            self.destroy()
            messagebox.showinfo("불러오기", f"'{name}' 템플릿이 적용되었습니다.")

    def _set_default(self, name: str):
        """기본 템플릿 설정"""
        self.template_manager.set_default_template(name)
        self._refresh_templates()
        messagebox.showinfo("기본 템플릿", f"'{name}'이(가) 기본 템플릿으로 설정되었습니다.")

    def _duplicate_template(self, name: str):
        """템플릿 복제"""
        new_name = self.template_manager.duplicate_template(name)
        if new_name:
            self._refresh_templates()
            messagebox.showinfo("복제 완료", f"'{new_name}' 템플릿이 생성되었습니다.")

    def _delete_template(self, name: str):
        """템플릿 삭제"""
        if messagebox.askyesno("삭제 확인", f"'{name}' 템플릿을 삭제하시겠습니까?"):
            self.template_manager.delete_template(name)
            self._refresh_templates()

    def _save_current(self):
        """현재 설정을 템플릿으로 저장"""
        name = simpledialog.askstring("템플릿 저장", "템플릿 이름을 입력하세요:", parent=self)

        if not name:
            return

        # 부모 창에서 현재 설정 가져오기
        try:
            channel_mode = self.parent_window.channel_var.get()
            if channel_mode == "mystery_toon":
                channel = "mystery_toon"
                mode = "mystery_toon"
            else:
                channel = "daily_life_toon"
                mode = "daily_life_toon"

            quantity = self.parent_window.quantity_var.get()
            topic_mode = self.parent_window.topic_mode_var.get()
            manual_topic = self.parent_window.manual_topic_entry.get()
            auto_upload = self.parent_window.auto_upload_var.get()

            # 음성 감정 설정
            voice_emotions = {}
            if hasattr(self.parent_window, 'voice_emotion_vars'):
                for role, var in self.parent_window.voice_emotion_vars.items():
                    voice_emotions[role] = var.get()

            description = simpledialog.askstring(
                "설명 추가",
                "템플릿 설명 (선택사항):",
                parent=self
            ) or ""

            self.template_manager.save_template(
                name=name,
                channel=channel,
                mode=mode,
                quantity=quantity,
                topic_mode=topic_mode,
                manual_topic=manual_topic,
                auto_upload=auto_upload,
                voice_emotions=voice_emotions,
                description=description
            )

            self._refresh_templates()
            messagebox.showinfo("저장 완료", f"'{name}' 템플릿이 저장되었습니다.")

        except Exception as e:
            messagebox.showerror("오류", f"템플릿 저장 실패:\n{e}")
