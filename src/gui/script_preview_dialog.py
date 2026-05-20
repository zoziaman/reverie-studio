# src/gui/script_preview_dialog.py
"""
v38 - 대본 미리보기 다이얼로그

기능:
1. 대본 생성 전 미리보기
2. 대본 내용 확인/수정
3. 승인 후 영상 제작 진행
4. 재생성 옵션
5. 통계 분석 표시
6. v38: ScenarioEditor 고급 편집 연동
"""

import customtkinter as ctk
from tkinter import messagebox
import threading
import json
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime

# 폰트 설정
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    """통일된 폰트 반환"""
    sizes = {"small": 12, "normal": 13, "medium": 14, "large": 16, "title": 20, "header": 24}
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


class ScriptPreviewDialog(ctk.CTkToplevel):
    """대본 미리보기 다이얼로그"""

    # 감정별 색상
    EMOTION_COLORS = {
        "calm": "#64B5F6",      # 파랑
        "sad": "#7986CB",       # 보라
        "angry": "#E57373",     # 빨강
        "happy": "#81C784",     # 초록
        "fear": "#FFB74D",      # 주황
    }

    # 역할별 아이콘
    ROLE_ICONS = {
        "narrator": "📖",
        "grandma": "👵",
        "grandpa": "👴",
        "man": "👨",
        "woman": "👩",
    }

    def __init__(
        self,
        parent,
        plan_data: Dict[str, Any],
        on_approve: Callable[[Dict[str, Any]], None] = None,
        on_regenerate: Callable[[], None] = None,
        on_cancel: Callable[[], None] = None,
    ):
        super().__init__(parent)

        self.plan_data = plan_data
        self.on_approve = on_approve
        self.on_regenerate = on_regenerate
        self.on_cancel = on_cancel

        # 윈도우 설정
        self.title("📝 대본 미리보기")
        self.geometry("1100x800")
        self.resizable(True, True)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 대본 데이터
        self.script_list = plan_data.get("script_list", [])
        self.edited_script = list(self.script_list)  # 편집용 복사본

        # UI 생성
        self._create_ui()

        # 닫기 이벤트
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _create_ui(self):
        """UI 생성"""
        # 메인 컨테이너
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # === 상단: 헤더 ===
        self._create_header(main_frame)

        # === 중앙: 2단 레이아웃 (대본 | 정보) ===
        content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, pady=10)

        # 좌측: 대본 뷰어 (70%)
        script_panel = ctk.CTkFrame(content_frame, fg_color="#1a1a2e")
        script_panel.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self._create_script_viewer(script_panel)

        # 우측: 정보 패널 (30%)
        info_panel = ctk.CTkFrame(content_frame, width=320, fg_color="#1a1a2e")
        info_panel.pack(side="right", fill="y", padx=(5, 0))
        info_panel.pack_propagate(False)

        self._create_info_panel(info_panel)

        # === 하단: 버튼 ===
        self._create_buttons(main_frame)

    def _create_header(self, parent):
        """헤더 생성"""
        header = ctk.CTkFrame(parent, fg_color="#252542", corner_radius=10)
        header.pack(fill="x", pady=(0, 10))

        # 제목
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(
            title_frame,
            text="📝 대본 미리보기",
            font=get_font("title", bold=True)
        ).pack(side="left")

        # 프롬프트 모드 표시
        mode_label = "Enhanced" if self.plan_data.get("prompt_mode") == "enhanced" else "Classic"
        ctk.CTkLabel(
            title_frame,
            text=f"AI: {mode_label}",
            font=get_font("small"),
            text_color="#888888"
        ).pack(side="right")

        # 주제
        topic = self.plan_data.get("topic", "주제 없음")
        ctk.CTkLabel(
            header,
            text=f"📌 {topic}",
            font=get_font("medium"),
            text_color="#AAAAAA"
        ).pack(anchor="w", padx=15, pady=(0, 10))

    def _create_script_viewer(self, parent):
        """대본 뷰어 생성"""
        # 헤더
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(
            header_frame,
            text=f"📜 대본 ({len(self.script_list)}턴)",
            font=get_font("medium", bold=True)
        ).pack(side="left")

        # 필터 드롭다운
        self.filter_var = ctk.StringVar(value="전체")
        filter_combo = ctk.CTkComboBox(
            header_frame,
            values=["전체", "narrator", "grandma", "grandpa", "man", "woman"],
            variable=self.filter_var,
            width=120,
            font=get_font("small"),
            command=self._apply_filter
        )
        filter_combo.pack(side="right", padx=5)

        ctk.CTkLabel(
            header_frame, text="필터:", font=get_font("small")
        ).pack(side="right")

        # 스크롤 영역
        self.script_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.script_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 대본 표시
        self._populate_script()

    def _populate_script(self, filter_role: str = None):
        """대본 내용 표시"""
        # 기존 위젯 제거
        for widget in self.script_scroll.winfo_children():
            widget.destroy()

        if not self.script_list:
            ctk.CTkLabel(
                self.script_scroll,
                text="대본이 없습니다.",
                font=get_font("medium"),
                text_color="#888888"
            ).pack(pady=50)
            return

        for idx, line in enumerate(self.script_list):
            role = line.get("role", "narrator")
            text = line.get("text", "")
            emotion = line.get("emotion", "calm")

            # 필터 적용
            if filter_role and filter_role != "전체" and role != filter_role:
                continue

            # 라인 컨테이너
            line_frame = ctk.CTkFrame(
                self.script_scroll,
                fg_color="#2a2a4a",
                corner_radius=8
            )
            line_frame.pack(fill="x", pady=2, padx=5)

            # 라인 번호
            ctk.CTkLabel(
                line_frame,
                text=f"{idx+1:03d}",
                width=40,
                font=get_font("small"),
                text_color="#666666"
            ).pack(side="left", padx=5)

            # 역할 아이콘
            icon = self.ROLE_ICONS.get(role, "👤")
            ctk.CTkLabel(
                line_frame,
                text=icon,
                width=25,
                font=get_font("medium")
            ).pack(side="left")

            # 역할명
            ctk.CTkLabel(
                line_frame,
                text=role,
                width=70,
                font=get_font("small"),
                text_color="#AAAAAA"
            ).pack(side="left", padx=5)

            # 감정 태그
            emotion_color = self.EMOTION_COLORS.get(emotion, "#888888")
            emotion_label = ctk.CTkLabel(
                line_frame,
                text=emotion,
                width=50,
                font=get_font("small"),
                fg_color=emotion_color,
                corner_radius=4,
                text_color="white"
            )
            emotion_label.pack(side="left", padx=5)

            # 대사 텍스트
            text_label = ctk.CTkLabel(
                line_frame,
                text=text[:100] + ("..." if len(text) > 100 else ""),
                font=get_font("normal"),
                anchor="w",
                wraplength=500
            )
            text_label.pack(side="left", fill="x", expand=True, padx=10, pady=8)

            # 편집 버튼
            edit_btn = ctk.CTkButton(
                line_frame,
                text="✏️",
                width=30,
                height=28,
                font=get_font("small"),
                fg_color="#555555",
                hover_color="#666666",
                command=lambda i=idx: self._edit_line(i)
            )
            edit_btn.pack(side="right", padx=5, pady=5)

    def _apply_filter(self, value: str):
        """필터 적용"""
        self._populate_script(value if value != "전체" else None)

    def _edit_line(self, index: int):
        """대사 편집"""
        if index >= len(self.script_list):
            return

        line = self.script_list[index]

        # 편집 다이얼로그
        dialog = ScriptLineEditDialog(
            self,
            line,
            on_save=lambda edited: self._save_edited_line(index, edited)
        )

    def _save_edited_line(self, index: int, edited: Dict[str, Any]):
        """편집된 라인 저장"""
        self.script_list[index] = edited
        self.edited_script[index] = edited
        self._populate_script(self.filter_var.get() if self.filter_var.get() != "전체" else None)
        self._update_stats()

    def _create_info_panel(self, parent):
        """정보 패널 생성"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # === 메타데이터 ===
        meta_frame = ctk.CTkFrame(scroll, fg_color="#252542", corner_radius=8)
        meta_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            meta_frame,
            text="📋 메타데이터",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        # 제목
        title = self.plan_data.get("title", "")
        self._add_info_row(meta_frame, "제목", title[:40] + ("..." if len(title) > 40 else ""))

        # 썸네일 텍스트
        thumb_title = self.plan_data.get("thumbnail_title", "")
        self._add_info_row(meta_frame, "썸네일", thumb_title)

        # 태그
        tags = self.plan_data.get("tags", "")
        tag_preview = tags[:50] + ("..." if len(tags) > 50 else "")
        self._add_info_row(meta_frame, "태그", tag_preview)

        # === 통계 ===
        stats_frame = ctk.CTkFrame(scroll, fg_color="#252542", corner_radius=8)
        stats_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            stats_frame,
            text="📊 통계",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.stats_container = ctk.CTkFrame(stats_frame, fg_color="transparent")
        self.stats_container.pack(fill="x", padx=10, pady=(0, 10))

        self._update_stats()

        # === 스토리 바이블 ===
        bible_frame = ctk.CTkFrame(scroll, fg_color="#252542", corner_radius=8)
        bible_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            bible_frame,
            text="📖 스토리 바이블",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        bible_text = self.plan_data.get("story_bible", "없음")
        bible_textbox = ctk.CTkTextbox(
            bible_frame,
            height=150,
            font=get_font("small"),
            fg_color="#1a1a2e"
        )
        bible_textbox.pack(fill="x", padx=10, pady=(0, 10))
        bible_textbox.insert("1.0", bible_text)
        bible_textbox.configure(state="disabled")

        # === 후킹 멘트 ===
        hook_frame = ctk.CTkFrame(scroll, fg_color="#252542", corner_radius=8)
        hook_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            hook_frame,
            text="🪝 오프닝 훅",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        hook = self.plan_data.get("hook", "")
        ctk.CTkLabel(
            hook_frame,
            text=f'"{hook}"',
            font=get_font("normal"),
            text_color="#4CAF50",
            wraplength=280
        ).pack(anchor="w", padx=10, pady=(0, 10))

    def _add_info_row(self, parent, label: str, value: str):
        """정보 행 추가"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(
            row, text=f"{label}:", width=60, anchor="w",
            font=get_font("small"), text_color="#888888"
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=value, anchor="w",
            font=get_font("small"), wraplength=200
        ).pack(side="left", fill="x", expand=True)

    def _update_stats(self):
        """통계 업데이트"""
        # 기존 위젯 제거
        for widget in self.stats_container.winfo_children():
            widget.destroy()

        if not self.script_list:
            return

        # 기본 통계
        total_turns = len(self.script_list)
        total_chars = sum(len(s.get("text", "")) for s in self.script_list)
        est_duration = total_chars / 4 / 60  # 초당 4글자 기준

        self._add_stat_row(self.stats_container, "총 턴 수", f"{total_turns}턴")
        self._add_stat_row(self.stats_container, "총 글자 수", f"{total_chars:,}자")
        self._add_stat_row(self.stats_container, "예상 시간", f"{est_duration:.1f}분")

        # 역할 분포
        role_counts = {}
        for s in self.script_list:
            role = s.get("role", "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1

        role_text = ", ".join([f"{k}:{v}" for k, v in role_counts.items()])
        self._add_stat_row(self.stats_container, "역할 분포", role_text)

        # 감정 분포
        emotion_counts = {}
        for s in self.script_list:
            emo = s.get("emotion", "calm")
            emotion_counts[emo] = emotion_counts.get(emo, 0) + 1

        emotion_text = ", ".join([f"{k}:{v}" for k, v in emotion_counts.items()])
        self._add_stat_row(self.stats_container, "감정 분포", emotion_text)

    def _add_stat_row(self, parent, label: str, value: str):
        """통계 행 추가"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=1)

        ctk.CTkLabel(
            row, text=label, width=70, anchor="w",
            font=get_font("small"), text_color="#888888"
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=value, anchor="w",
            font=get_font("small")
        ).pack(side="left", fill="x", expand=True)

    def _create_buttons(self, parent):
        """하단 버튼 생성"""
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))

        # 취소 버튼
        ctk.CTkButton(
            btn_frame,
            text="❌ 취소",
            width=100,
            height=40,
            font=get_font("medium"),
            fg_color="#757575",
            hover_color="#616161",
            command=self._on_cancel
        ).pack(side="left", padx=5)

        # 재생성 버튼
        ctk.CTkButton(
            btn_frame,
            text="🔄 재생성",
            width=100,
            height=40,
            font=get_font("medium"),
            fg_color="#FF9800",
            hover_color="#F57C00",
            command=self._on_regenerate_click
        ).pack(side="left", padx=5)

        # v38: 고급 편집 버튼 (ScenarioEditor 연동)
        ctk.CTkButton(
            btn_frame,
            text="✏️ 고급 편집",
            width=110,
            height=40,
            font=get_font("medium"),
            fg_color="#9C27B0",
            hover_color="#7B1FA2",
            command=self._open_scenario_editor
        ).pack(side="left", padx=5)

        # JSON 저장 버튼
        ctk.CTkButton(
            btn_frame,
            text="💾 저장",
            width=80,
            height=40,
            font=get_font("medium"),
            fg_color="#2196F3",
            hover_color="#1976D2",
            command=self._save_json
        ).pack(side="left", padx=5)

        # 승인 버튼
        ctk.CTkButton(
            btn_frame,
            text="✅ 승인 및 제작 진행",
            width=180,
            height=40,
            font=get_font("medium", bold=True),
            fg_color="#4CAF50",
            hover_color="#388E3C",
            command=self._on_approve_click
        ).pack(side="right", padx=5)

    def _on_cancel(self):
        """취소"""
        if self.on_cancel:
            self.on_cancel()
        self.destroy()

    def _on_regenerate_click(self):
        """재생성"""
        if messagebox.askyesno("확인", "대본을 새로 생성하시겠습니까?\n현재 편집 내용은 사라집니다."):
            if self.on_regenerate:
                self.on_regenerate()
            self.destroy()

    def _on_approve_click(self):
        """승인"""
        # 편집된 내용 반영
        self.plan_data["script_list"] = self.edited_script

        if self.on_approve:
            self.on_approve(self.plan_data)
        self.destroy()

    def _open_scenario_editor(self):
        """v38: ScenarioEditor로 고급 편집 열기"""
        try:
            from gui.scenario_editor import ScenarioEditorWindow

            # 편집된 내용 반영
            edit_plan = dict(self.plan_data)
            edit_plan["script_list"] = self.edited_script

            def on_editor_approve(approved_plan):
                """ScenarioEditor에서 승인됨"""
                # 편집된 내용으로 업데이트
                self.plan_data = approved_plan
                self.script_list = approved_plan.get("script_list", [])
                self.edited_script = list(self.script_list)

                # UI 갱신
                self._populate_script()
                self._update_stats()

                # 바로 제작 진행
                if self.on_approve:
                    self.on_approve(approved_plan)
                self.destroy()

            def on_editor_save(saved_plan):
                """ScenarioEditor에서 저장만 함 (제작 진행 X)"""
                # 편집된 내용으로 업데이트
                self.plan_data = saved_plan
                self.script_list = saved_plan.get("script_list", [])
                self.edited_script = list(self.script_list)

                # UI 갱신
                self._populate_script()
                self._update_stats()

            # ScenarioEditor 열기
            editor = ScenarioEditorWindow(
                self,
                plan_data=edit_plan,
                on_save=on_editor_save,
                on_approve=on_editor_approve,
            )

        except ImportError as e:
            messagebox.showerror(
                "모듈 오류",
                f"ScenarioEditor를 로드할 수 없습니다.\n\n{e}"
            )
        except Exception as e:
            messagebox.showerror(
                "오류",
                f"고급 편집기를 열 수 없습니다.\n\n{e}"
            )

    def _save_json(self):
        """JSON 저장"""
        from tkinter import filedialog
        import os

        # 기본 파일명
        project_name = self.plan_data.get("project_name", "script")
        default_name = f"{project_name}_preview.json"

        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile=default_name
        )

        if filepath:
            # 편집된 내용 반영
            save_data = dict(self.plan_data)
            save_data["script_list"] = self.edited_script

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("저장 완료", f"저장됨: {filepath}")


class ScriptLineEditDialog(ctk.CTkToplevel):
    """대사 편집 다이얼로그"""

    ROLES = ["narrator", "grandma", "grandpa", "man", "woman"]
    EMOTIONS = ["calm", "sad", "angry", "happy", "fear"]

    def __init__(self, parent, line_data: Dict[str, Any], on_save: Callable[[Dict], None] = None):
        super().__init__(parent)

        self.line_data = dict(line_data)  # 복사본
        self.on_save = on_save

        self.title("✏️ 대사 편집")
        self.geometry("500x350")
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self._create_ui()

    def _create_ui(self):
        """UI 생성"""
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 역할 선택
        role_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        role_row.pack(fill="x", pady=5)

        ctk.CTkLabel(
            role_row, text="역할:", width=60, anchor="w", font=get_font("normal")
        ).pack(side="left")

        self.role_var = ctk.StringVar(value=self.line_data.get("role", "narrator"))
        ctk.CTkComboBox(
            role_row,
            values=self.ROLES,
            variable=self.role_var,
            width=200,
            font=get_font("normal")
        ).pack(side="left", padx=10)

        # 감정 선택
        emotion_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        emotion_row.pack(fill="x", pady=5)

        ctk.CTkLabel(
            emotion_row, text="감정:", width=60, anchor="w", font=get_font("normal")
        ).pack(side="left")

        self.emotion_var = ctk.StringVar(value=self.line_data.get("emotion", "calm"))
        ctk.CTkComboBox(
            emotion_row,
            values=self.EMOTIONS,
            variable=self.emotion_var,
            width=200,
            font=get_font("normal")
        ).pack(side="left", padx=10)

        # 대사 텍스트
        ctk.CTkLabel(
            main_frame, text="대사:", anchor="w", font=get_font("normal")
        ).pack(anchor="w", pady=(10, 5))

        self.text_box = ctk.CTkTextbox(main_frame, height=120, font=get_font("normal"))
        self.text_box.pack(fill="x", pady=5)
        self.text_box.insert("1.0", self.line_data.get("text", ""))

        # 버튼
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            font=get_font("normal"),
            fg_color="#757575",
            command=self.destroy
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="저장",
            width=100,
            font=get_font("normal"),
            fg_color="#4CAF50",
            command=self._save
        ).pack(side="right", padx=5)

    def _save(self):
        """저장"""
        self.line_data["role"] = self.role_var.get()
        self.line_data["emotion"] = self.emotion_var.get()
        self.line_data["text"] = self.text_box.get("1.0", "end-1c").strip()

        if self.on_save:
            self.on_save(self.line_data)

        self.destroy()
