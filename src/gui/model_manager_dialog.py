# src/gui/model_manager_dialog.py
"""
v33: TTS 모델 관리 다이얼로그

기능:
- 모델 목록 조회 (기본 제공 + 커스텀)
- 커스텀 모델 추가/편집/삭제
- 채널별 캐릭터-모델 매핑
- 감정 관리 (추가/삭제/테스트)
"""
import os
import customtkinter as ctk
from tkinter import messagebox, filedialog
from typing import Dict, Any, Callable, Optional, List
import threading

from utils.model_manager import get_model_manager, ModelInfo


class ModelManagerDialog(ctk.CTkToplevel):
    """TTS 모델 관리 다이얼로그"""

    def __init__(self, parent, on_change_callback: Callable = None):
        super().__init__(parent)

        self.model_manager = get_model_manager()
        self.on_change_callback = on_change_callback
        self.parent_window = parent
        self.selected_model_id = None

        self.title("🎤 TTS 모델 관리")
        self.geometry("900x650")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 900) // 2
        y = (self.winfo_screenheight() - 650) // 2
        self.geometry(f"900x650+{x}+{y}")

        self._create_ui()
        self._refresh_models()

    def _create_ui(self):
        """UI 구성"""
        # 제목
        ctk.CTkLabel(
            self,
            text="🎤 TTS 모델 관리",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=15)

        # 메인 컨테이너
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=20, pady=10)

        # 좌측: 모델 목록
        left_frame = ctk.CTkFrame(main_container)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ctk.CTkLabel(
            left_frame,
            text="모델 목록",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        # 모델 목록 스크롤
        self.model_scroll = ctk.CTkScrollableFrame(left_frame, width=350)
        self.model_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        # 모델 추가 버튼
        btn_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(
            btn_frame,
            text="➕ 새 모델 등록",
            command=self._show_add_model_wizard,
            width=150,
            fg_color="#2E7D32",
            hover_color="#1B5E20"
        ).pack(side="left", padx=5)

        # 우측: 모델 상세 정보
        right_frame = ctk.CTkFrame(main_container)
        right_frame.pack(side="right", fill="both", expand=True)

        self.detail_frame = right_frame
        self._show_no_selection()

        # 하단 버튼
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkButton(
            bottom_frame,
            text="캐릭터 슬롯 설정",
            command=self._show_character_mapping,
            width=140
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            bottom_frame,
            text="닫기",
            command=self.destroy,
            width=80
        ).pack(side="right", padx=5)

    def _refresh_models(self):
        """모델 목록 새로고침"""
        for widget in self.model_scroll.winfo_children():
            widget.destroy()

        models = self.model_manager.get_all_models()

        # 카테고리별 그룹화
        categories = {
            "builtin": [],
            "custom": []
        }

        for m in models:
            cat = "custom" if m["type"] == "custom" else "builtin"
            categories[cat].append(m)

        # 기본 제공 모델
        if categories["builtin"]:
            ctk.CTkLabel(
                self.model_scroll,
                text="📦 기본 제공 모델",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#90CAF9"
            ).pack(anchor="w", pady=(10, 5))

            for m in categories["builtin"]:
                self._create_model_row(m)

        # 커스텀 모델
        ctk.CTkLabel(
            self.model_scroll,
            text="🎨 커스텀 모델",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#A5D6A7"
        ).pack(anchor="w", pady=(15, 5))

        if categories["custom"]:
            for m in categories["custom"]:
                self._create_model_row(m)
        else:
            ctk.CTkLabel(
                self.model_scroll,
                text="커스텀 모델이 없습니다.\n새 모델을 등록해보세요!",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            ).pack(pady=10)

    def _create_model_row(self, model: Dict):
        """모델 행 생성"""
        row = ctk.CTkFrame(self.model_scroll)
        row.pack(fill="x", pady=2)

        # 선택 상태 표시
        is_selected = self.selected_model_id == model["id"]
        row.configure(fg_color="#1E3A5F" if is_selected else "transparent")

        # 모델 타입 아이콘
        type_icon = "📦" if model["type"] == "builtin" else "🎨"

        # 모델 정보
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=5, pady=5)

        ctk.CTkLabel(
            info_frame,
            text=f"{type_icon} {model['name']}",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(anchor="w")

        # 감정 목록 (최대 5개)
        emotions = model.get("emotions", [])[:5]
        emo_text = ", ".join(emotions)
        if len(model.get("emotions", [])) > 5:
            emo_text += "..."

        ctk.CTkLabel(
            info_frame,
            text=f"감정: {emo_text}" if emotions else "감정 없음",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w"
        ).pack(anchor="w")

        # 선택 버튼
        ctk.CTkButton(
            row,
            text="상세",
            width=50,
            height=28,
            command=lambda m=model: self._select_model(m)
        ).pack(side="right", padx=5, pady=5)

    def _select_model(self, model: Dict):
        """모델 선택"""
        self.selected_model_id = model["id"]
        self._refresh_models()
        self._show_model_detail(model)

    def _show_no_selection(self):
        """선택된 모델 없음 표시"""
        for widget in self.detail_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self.detail_frame,
            text="🎤",
            font=ctk.CTkFont(size=48)
        ).pack(pady=(80, 10))

        ctk.CTkLabel(
            self.detail_frame,
            text="모델을 선택하세요",
            font=ctk.CTkFont(size=16),
            text_color="gray"
        ).pack()

        ctk.CTkLabel(
            self.detail_frame,
            text="왼쪽 목록에서 모델을 선택하면\n상세 정보를 확인할 수 있습니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(pady=10)

    def _show_model_detail(self, model: Dict):
        """모델 상세 정보 표시"""
        for widget in self.detail_frame.winfo_children():
            widget.destroy()

        # 헤더
        header_frame = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=15)

        type_icon = "📦" if model["type"] == "builtin" else "🎨"
        ctk.CTkLabel(
            header_frame,
            text=f"{type_icon} {model['name']}",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            header_frame,
            text=f"ID: {model['id']}",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w")

        if model.get("description"):
            ctk.CTkLabel(
                header_frame,
                text=model["description"],
                font=ctk.CTkFont(size=12),
                wraplength=350
            ).pack(anchor="w", pady=(5, 0))

        # 구분선
        ctk.CTkFrame(self.detail_frame, height=2, fg_color="gray").pack(fill="x", padx=15, pady=10)

        # 감정 목록
        emotion_frame = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        emotion_frame.pack(fill="both", expand=True, padx=15)

        ctk.CTkLabel(
            emotion_frame,
            text="📋 감정 목록",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", pady=(0, 10))

        # 감정 스크롤
        emotion_scroll = ctk.CTkScrollableFrame(emotion_frame, height=200)
        emotion_scroll.pack(fill="both", expand=True)

        model_info = self.model_manager.get_model_info(model["id"])
        emotions = model_info.emotions if model_info else {}

        if emotions:
            for emo_name, emo_info in emotions.items():
                self._create_emotion_row(emotion_scroll, model, emo_name, emo_info)
        else:
            ctk.CTkLabel(
                emotion_scroll,
                text="감정이 등록되지 않았습니다.",
                text_color="gray"
            ).pack(pady=20)

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)

        if model["type"] == "custom":
            ctk.CTkButton(
                btn_frame,
                text="➕ 감정 추가",
                command=lambda: self._show_add_emotion_dialog(model),
                width=100
            ).pack(side="left", padx=5)

            ctk.CTkButton(
                btn_frame,
                text="✏️ 편집",
                command=lambda: self._show_edit_model_dialog(model),
                width=80
            ).pack(side="left", padx=5)

            ctk.CTkButton(
                btn_frame,
                text="🗑️ 삭제",
                command=lambda: self._delete_model(model),
                width=80,
                fg_color="#C62828",
                hover_color="#B71C1C"
            ).pack(side="left", padx=5)
        else:
            ctk.CTkLabel(
                btn_frame,
                text="ℹ️ 기본 제공 모델은 수정할 수 없습니다",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            ).pack(side="left")

    def _create_emotion_row(self, parent, model: Dict, emo_name: str, emo_info):
        """감정 행 생성"""
        row = ctk.CTkFrame(parent)
        row.pack(fill="x", pady=2)

        # 감정 정보
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=5, pady=3)

        ctk.CTkLabel(
            info_frame,
            text=f"🎭 {emo_name}",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(anchor="w")

        ref_text = emo_info.reference_text if hasattr(emo_info, 'reference_text') else str(emo_info)
        if len(ref_text) > 40:
            ref_text = ref_text[:40] + "..."

        ctk.CTkLabel(
            info_frame,
            text=f'"{ref_text}"',
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w"
        ).pack(anchor="w")

        # v58: TTS 테스트 미구현 - 버튼 숨김
        # ctk.CTkButton(
        #     row,
        #     text="▶",
        #     width=30,
        #     height=25,
        #     command=lambda: self._test_emotion(model, emo_name)
        # ).pack(side="right", padx=2, pady=3)

        # 커스텀 모델인 경우 삭제 버튼
        if model["type"] == "custom":
            ctk.CTkButton(
                row,
                text="🗑",
                width=30,
                height=25,
                fg_color="#C62828",
                hover_color="#B71C1C",
                command=lambda: self._remove_emotion(model, emo_name)
            ).pack(side="right", padx=2, pady=3)

    def _test_emotion(self, model: Dict, emotion: str):
        """감정 테스트 (TTS 미리 듣기)"""
        messagebox.showinfo(
            "테스트",
            f"'{model['name']}' 모델의 '{emotion}' 감정 테스트\n\n"
            "(TTS 서버가 실행 중이어야 합니다)"
        )

    def _remove_emotion(self, model: Dict, emotion: str):
        """감정 제거"""
        if messagebox.askyesno("확인", f"'{emotion}' 감정을 제거하시겠습니까?"):
            success, msg = self.model_manager.remove_emotion_from_model(model["id"], emotion)
            if success:
                messagebox.showinfo("완료", msg)
                self._refresh_models()
                self._show_model_detail(self.model_manager.get_model_by_id(model["id"]))
            else:
                messagebox.showerror("오류", msg)

    def _delete_model(self, model: Dict):
        """모델 삭제"""
        if messagebox.askyesno(
            "확인",
            f"'{model['name']}' 모델을 삭제하시겠습니까?\n\n"
            "이 작업은 되돌릴 수 없습니다."
        ):
            success, msg = self.model_manager.delete_custom_model(model["id"])
            if success:
                messagebox.showinfo("완료", msg)
                self.selected_model_id = None
                self._refresh_models()
                self._show_no_selection()
                if self.on_change_callback:
                    self.on_change_callback()
            else:
                messagebox.showerror("오류", msg)

    # ============================================================
    # 모델 추가 마법사
    # ============================================================
    def _show_add_model_wizard(self):
        """새 모델 등록 마법사"""
        wizard = AddModelWizard(self, self._on_model_added)
        wizard.grab_set()

    def _on_model_added(self):
        """모델 추가 완료 콜백"""
        self._refresh_models()
        if self.on_change_callback:
            self.on_change_callback()

    # ============================================================
    # 모델 편집
    # ============================================================
    def _show_edit_model_dialog(self, model: Dict):
        """모델 편집 다이얼로그"""
        dialog = EditModelDialog(self, model, self._on_model_edited)
        dialog.grab_set()

    def _on_model_edited(self):
        """모델 편집 완료 콜백"""
        self._refresh_models()
        if self.selected_model_id:
            model = self.model_manager.get_model_by_id(self.selected_model_id)
            if model:
                self._show_model_detail(model)

    # ============================================================
    # 감정 추가
    # ============================================================
    def _show_add_emotion_dialog(self, model: Dict):
        """감정 추가 다이얼로그"""
        dialog = AddEmotionDialog(self, model, self._on_emotion_added)
        dialog.grab_set()

    def _on_emotion_added(self):
        """감정 추가 완료 콜백"""
        if self.selected_model_id:
            model = self.model_manager.get_model_by_id(self.selected_model_id)
            if model:
                self._show_model_detail(model)

    # ============================================================
    # 캐릭터 슬롯 매핑
    # ============================================================
    def _show_character_mapping(self):
        """캐릭터 슬롯 설정 다이얼로그"""
        dialog = CharacterMappingDialog(self, self.on_change_callback)
        dialog.grab_set()


# ============================================================
# 새 모델 등록 마법사
# ============================================================
class AddModelWizard(ctk.CTkToplevel):
    """새 모델 등록 마법사"""

    def __init__(self, parent, on_complete: Callable = None):
        super().__init__(parent)

        self.model_manager = get_model_manager()
        self.on_complete = on_complete

        self.title("➕ 새 모델 등록")
        self.geometry("550x500")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 550) // 2
        y = (self.winfo_screenheight() - 500) // 2
        self.geometry(f"550x500+{x}+{y}")

        # 입력 변수
        self.model_name = ctk.StringVar()
        self.model_desc = ctk.StringVar()
        self.gpt_path = ctk.StringVar()
        self.sovits_path = ctk.StringVar()
        self.ref_audio_path = ctk.StringVar()
        self.ref_text = ctk.StringVar(value="안녕하세요.")

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        # 제목
        ctk.CTkLabel(
            self,
            text="➕ 새 TTS 모델 등록",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=15)

        # 폼
        form_frame = ctk.CTkScrollableFrame(self)
        form_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 모델 이름
        ctk.CTkLabel(form_frame, text="모델 이름 *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(10, 5))
        ctk.CTkEntry(form_frame, textvariable=self.model_name, width=400, placeholder_text="예: 우리할배").pack(anchor="w")

        # 설명
        ctk.CTkLabel(form_frame, text="설명", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        ctk.CTkEntry(form_frame, textvariable=self.model_desc, width=400, placeholder_text="예: 친근한 할아버지 목소리").pack(anchor="w")

        # GPT 가중치
        ctk.CTkLabel(form_frame, text="GPT 가중치 파일 (.ckpt) *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        gpt_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        gpt_frame.pack(fill="x")
        ctk.CTkEntry(gpt_frame, textvariable=self.gpt_path, width=320).pack(side="left")
        ctk.CTkButton(gpt_frame, text="찾기", width=70, command=self._browse_gpt).pack(side="left", padx=5)

        # SoVITS 가중치
        ctk.CTkLabel(form_frame, text="SoVITS 가중치 파일 (.pth) *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        sov_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        sov_frame.pack(fill="x")
        ctk.CTkEntry(sov_frame, textvariable=self.sovits_path, width=320).pack(side="left")
        ctk.CTkButton(sov_frame, text="찾기", width=70, command=self._browse_sovits).pack(side="left", padx=5)

        # 구분선
        ctk.CTkFrame(form_frame, height=2, fg_color="gray").pack(fill="x", pady=20)

        # 기본 감정 (calm)
        ctk.CTkLabel(form_frame, text="기본 감정 (calm) 설정", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(form_frame, text="참조 음성 파일 (.wav) *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(5, 5))
        ref_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        ref_frame.pack(fill="x")
        ctk.CTkEntry(ref_frame, textvariable=self.ref_audio_path, width=320).pack(side="left")
        ctk.CTkButton(ref_frame, text="찾기", width=70, command=self._browse_ref_audio).pack(side="left", padx=5)

        ctk.CTkLabel(form_frame, text="참조 텍스트 (음성 파일의 대사) *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        ctk.CTkEntry(form_frame, textvariable=self.ref_text, width=400, placeholder_text="참조 음성의 대사를 입력하세요").pack(anchor="w")

        # 버튼
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkButton(
            btn_frame,
            text="등록",
            command=self._submit,
            width=100,
            fg_color="#2E7D32",
            hover_color="#1B5E20"
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            command=self.destroy,
            width=80
        ).pack(side="right", padx=5)

    def _browse_gpt(self):
        path = filedialog.askopenfilename(
            title="GPT 가중치 파일 선택",
            filetypes=[("Checkpoint", "*.ckpt"), ("All", "*.*")]
        )
        if path:
            self.gpt_path.set(path)

    def _browse_sovits(self):
        path = filedialog.askopenfilename(
            title="SoVITS 가중치 파일 선택",
            filetypes=[("PyTorch", "*.pth"), ("All", "*.*")]
        )
        if path:
            self.sovits_path.set(path)

    def _browse_ref_audio(self):
        path = filedialog.askopenfilename(
            title="참조 음성 파일 선택",
            filetypes=[("Audio", "*.wav *.mp3"), ("All", "*.*")]
        )
        if path:
            self.ref_audio_path.set(path)

    def _submit(self):
        """등록 제출"""
        name = self.model_name.get().strip()
        desc = self.model_desc.get().strip()
        gpt = self.gpt_path.get().strip()
        sov = self.sovits_path.get().strip()
        ref_audio = self.ref_audio_path.get().strip()
        ref_text = self.ref_text.get().strip()

        # 검증
        if not name:
            messagebox.showerror("오류", "모델 이름을 입력하세요.")
            return
        if not gpt or not os.path.exists(gpt):
            messagebox.showerror("오류", "GPT 가중치 파일을 선택하세요.")
            return
        if not sov or not os.path.exists(sov):
            messagebox.showerror("오류", "SoVITS 가중치 파일을 선택하세요.")
            return
        if not ref_audio or not os.path.exists(ref_audio):
            messagebox.showerror("오류", "참조 음성 파일을 선택하세요.")
            return
        if not ref_text:
            messagebox.showerror("오류", "참조 텍스트를 입력하세요.")
            return

        # 감정 데이터
        emotions = {
            "calm": {
                "reference_audio": ref_audio,
                "reference_text": ref_text,
                "description": "기본 감정"
            }
        }

        # 생성
        success, msg = self.model_manager.create_custom_model(
            name=name,
            gpt_weights_src=gpt,
            sovits_weights_src=sov,
            description=desc,
            emotions=emotions
        )

        if success:
            messagebox.showinfo("완료", msg)
            if self.on_complete:
                self.on_complete()
            self.destroy()
        else:
            messagebox.showerror("오류", msg)


# ============================================================
# 모델 편집 다이얼로그
# ============================================================
class EditModelDialog(ctk.CTkToplevel):
    """모델 편집 다이얼로그"""

    def __init__(self, parent, model: Dict, on_complete: Callable = None):
        super().__init__(parent)

        self.model_manager = get_model_manager()
        self.model = model
        self.on_complete = on_complete

        self.title("✏️ 모델 편집")
        self.geometry("450x300")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 450) // 2
        y = (self.winfo_screenheight() - 300) // 2
        self.geometry(f"450x300+{x}+{y}")

        # 입력 변수
        model_info = self.model_manager.get_model_info(model["id"])
        self.model_name = ctk.StringVar(value=model_info.name if model_info else model["name"])
        self.model_desc = ctk.StringVar(value=model_info.description if model_info else "")

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        ctk.CTkLabel(
            self,
            text="✏️ 모델 정보 편집",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)

        form_frame = ctk.CTkFrame(self, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=30)

        ctk.CTkLabel(form_frame, text="모델 이름", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(10, 5))
        ctk.CTkEntry(form_frame, textvariable=self.model_name, width=350).pack(anchor="w")

        ctk.CTkLabel(form_frame, text="설명", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        ctk.CTkEntry(form_frame, textvariable=self.model_desc, width=350).pack(anchor="w")

        # 버튼
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=20)

        ctk.CTkButton(
            btn_frame,
            text="저장",
            command=self._save,
            width=80
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            command=self.destroy,
            width=80
        ).pack(side="right", padx=5)

    def _save(self):
        name = self.model_name.get().strip()
        desc = self.model_desc.get().strip()

        if not name:
            messagebox.showerror("오류", "모델 이름을 입력하세요.")
            return

        success, msg = self.model_manager.update_custom_model(
            self.model["id"],
            name=name,
            description=desc
        )

        if success:
            messagebox.showinfo("완료", msg)
            if self.on_complete:
                self.on_complete()
            self.destroy()
        else:
            messagebox.showerror("오류", msg)


# ============================================================
# 감정 추가 다이얼로그
# ============================================================
class AddEmotionDialog(ctk.CTkToplevel):
    """감정 추가 다이얼로그"""

    def __init__(self, parent, model: Dict, on_complete: Callable = None):
        super().__init__(parent)

        self.model_manager = get_model_manager()
        self.model = model
        self.on_complete = on_complete

        self.title("➕ 감정 추가")
        self.geometry("500x400")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 500) // 2
        y = (self.winfo_screenheight() - 400) // 2
        self.geometry(f"500x400+{x}+{y}")

        # 입력 변수
        self.emo_name = ctk.StringVar()
        self.ref_audio = ctk.StringVar()
        self.ref_text = ctk.StringVar()
        self.emo_desc = ctk.StringVar()

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        ctk.CTkLabel(
            self,
            text=f"➕ '{self.model['name']}'에 감정 추가",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)

        form_frame = ctk.CTkFrame(self, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=30)

        # 감정 이름
        ctk.CTkLabel(form_frame, text="감정 이름 *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(10, 5))
        ctk.CTkEntry(form_frame, textvariable=self.emo_name, width=400, placeholder_text="예: 소노, 중노, 대노, 서운함").pack(anchor="w")

        # 참조 음성
        ctk.CTkLabel(form_frame, text="참조 음성 파일 *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        ref_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        ref_frame.pack(fill="x")
        ctk.CTkEntry(ref_frame, textvariable=self.ref_audio, width=320).pack(side="left")
        ctk.CTkButton(ref_frame, text="찾기", width=70, command=self._browse_audio).pack(side="left", padx=5)

        # 참조 텍스트
        ctk.CTkLabel(form_frame, text="참조 텍스트 *", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        ctk.CTkEntry(form_frame, textvariable=self.ref_text, width=400, placeholder_text="참조 음성의 대사").pack(anchor="w")

        # 설명
        ctk.CTkLabel(form_frame, text="감정 설명 (Gemini 힌트용)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        ctk.CTkEntry(form_frame, textvariable=self.emo_desc, width=400, placeholder_text="예: 약간 화난 상태").pack(anchor="w")

        # 버튼
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=20)

        ctk.CTkButton(
            btn_frame,
            text="추가",
            command=self._add,
            width=80,
            fg_color="#2E7D32",
            hover_color="#1B5E20"
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            command=self.destroy,
            width=80
        ).pack(side="right", padx=5)

    def _browse_audio(self):
        path = filedialog.askopenfilename(
            title="참조 음성 파일 선택",
            filetypes=[("Audio", "*.wav *.mp3"), ("All", "*.*")]
        )
        if path:
            self.ref_audio.set(path)

    def _add(self):
        name = self.emo_name.get().strip()
        audio = self.ref_audio.get().strip()
        text = self.ref_text.get().strip()
        desc = self.emo_desc.get().strip()

        if not name:
            messagebox.showerror("오류", "감정 이름을 입력하세요.")
            return
        if not audio or not os.path.exists(audio):
            messagebox.showerror("오류", "참조 음성 파일을 선택하세요.")
            return
        if not text:
            messagebox.showerror("오류", "참조 텍스트를 입력하세요.")
            return

        success, msg = self.model_manager.add_emotion_to_model(
            self.model["id"],
            emotion_name=name,
            reference_audio=audio,
            reference_text=text,
            description=desc
        )

        if success:
            messagebox.showinfo("완료", msg)
            if self.on_complete:
                self.on_complete()
            self.destroy()
        else:
            messagebox.showerror("오류", msg)


# ============================================================
# 캐릭터 슬롯 매핑 다이얼로그
# ============================================================
class CharacterMappingDialog(ctk.CTkToplevel):
    """채널별 캐릭터-모델 매핑 설정"""

    def __init__(self, parent, on_change: Callable = None):
        super().__init__(parent)

        self.model_manager = get_model_manager()
        self.on_change = on_change

        self.title("🎭 캐릭터 슬롯 설정")
        self.geometry("700x550")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 700) // 2
        y = (self.winfo_screenheight() - 550) // 2
        self.geometry(f"700x550+{x}+{y}")

        # 현재 채널
        self.current_channel = ctk.StringVar(value="daily_life_toon")
        self.mapping_widgets = {}

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        ctk.CTkLabel(
            self,
            text="🎭 캐릭터 슬롯 설정",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=15)

        ctk.CTkLabel(
            self,
            text="각 캐릭터에 사용할 TTS 모델을 지정합니다.\n지정하지 않으면 기본 모델이 사용됩니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack()

        # 채널 선택
        channel_frame = ctk.CTkFrame(self, fg_color="transparent")
        channel_frame.pack(fill="x", padx=30, pady=15)

        ctk.CTkLabel(channel_frame, text="채널:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        channels = [
            ("일상 영상툰", "daily_life_toon"),
            ("미스터리 영상툰", "mystery_toon"),
        ]

        for label, value in channels:
            ctk.CTkRadioButton(
                channel_frame,
                text=label,
                variable=self.current_channel,
                value=value,
                command=self._on_channel_change
            ).pack(side="left", padx=10)

        # 매핑 테이블
        self.mapping_frame = ctk.CTkScrollableFrame(self)
        self.mapping_frame.pack(fill="both", expand=True, padx=30, pady=10)

        self._refresh_mapping()

        # 버튼
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=15)

        ctk.CTkButton(
            btn_frame,
            text="기본값 복원",
            command=self._reset_mapping,
            width=100
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="닫기",
            command=self.destroy,
            width=80
        ).pack(side="right", padx=5)

    def _on_channel_change(self):
        """채널 변경"""
        self._refresh_mapping()

    def _refresh_mapping(self):
        """매핑 테이블 새로고침"""
        for widget in self.mapping_frame.winfo_children():
            widget.destroy()

        self.mapping_widgets = {}
        channel_id = self.current_channel.get()

        # 채널별 기본 캐릭터
        characters = self.model_manager.DEFAULT_CHARACTERS.get(channel_id, [])

        # 모든 모델 목록
        models = self.model_manager.get_all_models()
        model_choices = ["(기본값)"] + [f"{m['name']} ({m['id']})" for m in models]
        model_ids = [""] + [m["id"] for m in models]

        # 헤더
        header = ctk.CTkFrame(self.mapping_frame)
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(header, text="캐릭터", width=120, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header, text="사용 모델", width=300, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header, text="동작", width=100, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)

        # 캐릭터별 행
        char_names = {
            "narrator": "내레이터",
            "grandma": "할머니",
            "grandpa": "할아버지",
            "man": "남자",
            "woman": "여자",
        }

        for char in characters:
            row = ctk.CTkFrame(self.mapping_frame)
            row.pack(fill="x", pady=3)

            char_display = char_names.get(char, char)
            ctk.CTkLabel(row, text=char_display, width=120).pack(side="left", padx=10)

            # 현재 매핑된 모델
            current_model_id = self.model_manager.get_character_model(channel_id, char) or ""
            current_idx = 0
            if current_model_id in model_ids:
                current_idx = model_ids.index(current_model_id)

            # 드롭다운
            combo = ctk.CTkComboBox(
                row,
                values=model_choices,
                width=300
            )
            combo.set(model_choices[current_idx])
            combo.pack(side="left", padx=10)

            self.mapping_widgets[char] = (combo, model_ids)

            # 적용 버튼
            ctk.CTkButton(
                row,
                text="적용",
                width=60,
                command=lambda c=char: self._apply_mapping(c)
            ).pack(side="left", padx=5)

            # 테스트 버튼
            ctk.CTkButton(
                row,
                text="▶",
                width=30,
                command=lambda c=char: self._test_character(c)
            ).pack(side="left", padx=2)

    def _apply_mapping(self, character: str):
        """매핑 적용"""
        combo, model_ids = self.mapping_widgets[character]
        selected = combo.get()
        channel_id = self.current_channel.get()

        # 선택된 모델 ID 찾기
        model_id = ""
        for mid, choice in zip(model_ids, combo.cget("values")):
            if choice == selected:
                model_id = mid
                break

        if model_id:
            success, msg = self.model_manager.set_character_model(channel_id, character, model_id)
        else:
            # 기본값으로 복원
            mapping = self.model_manager.get_channel_mapping(channel_id)
            if character in mapping.character_models:
                del mapping.character_models[character]
            self.model_manager._save_mappings()
            success, msg = True, "기본 모델로 설정되었습니다."

        if success:
            messagebox.showinfo("완료", msg)
            if self.on_change:
                self.on_change()
        else:
            messagebox.showerror("오류", msg)

    def _test_character(self, character: str):
        """캐릭터 테스트"""
        channel_id = self.current_channel.get()
        model_info = self.model_manager.resolve_model_for_character(channel_id, character)

        if model_info:
            messagebox.showinfo(
                "모델 정보",
                f"캐릭터: {character}\n"
                f"모델: {model_info['name']} ({model_info['model_id']})\n"
                f"경로: {model_info['path']}"
            )
        else:
            messagebox.showwarning("경고", "모델을 찾을 수 없습니다.")

    def _reset_mapping(self):
        """매핑 초기화"""
        if messagebox.askyesno("확인", "이 채널의 모든 매핑을 초기화하시겠습니까?"):
            channel_id = self.current_channel.get()
            self.model_manager.reset_channel_mapping(channel_id)
            self._refresh_mapping()
            messagebox.showinfo("완료", "매핑이 초기화되었습니다.")
            if self.on_change:
                self.on_change()


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()

    dialog = ModelManagerDialog(root)
    dialog.mainloop()
