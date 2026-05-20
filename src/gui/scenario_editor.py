# src/gui/scenario_editor.py
# ============================================================
# Reverie Studio 3.1.0 - 시나리오 에디터 GUI
# ============================================================
"""
시나리오 에디터 (카드 기반 대본 편집)

기능:
1. 장면별 카드 뷰 (드래그 & 드롭)
2. 개별 장면 수정/삭제/추가
3. 실시간 미리보기
4. 부분 재생성 ("이 장면만 다시")
5. 타임라인 뷰
6. AI 대사 제안
"""

import os
import json
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path

try:
    import customtkinter as ctk
    from tkinter import messagebox, filedialog
    import tkinter as tk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

# ============================================================
# 폰트 설정
# ============================================================
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False) -> 'ctk.CTkFont':
    """통일된 폰트 반환"""
    if not CTK_AVAILABLE:
        return None
    sizes = {"small": 11, "normal": 13, "medium": 14, "large": 16, "title": 20, "header": 24}
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class SceneLine:
    """대본 한 줄"""
    role: str = "narrator"
    text: str = ""
    emotion: str = "calm"
    duration: float = 0.0  # 예상 시간 (초)

    def estimate_duration(self) -> float:
        """예상 시간 계산 (초당 4글자 기준)"""
        if self.text:
            self.duration = len(self.text) / 4.0
        return self.duration


@dataclass
class Scene:
    """장면 (여러 대사로 구성)"""
    scene_id: str = ""
    scene_number: int = 0
    title: str = ""
    description: str = ""
    lines: List[SceneLine] = field(default_factory=list)
    image_prompt: str = ""
    thumbnail_text: str = ""

    # 상태
    is_generated: bool = False
    is_modified: bool = False

    def get_total_duration(self) -> float:
        """총 시간 계산"""
        return sum(line.estimate_duration() for line in self.lines)

    def get_line_count(self) -> int:
        """대사 수"""
        return len(self.lines)

    def get_char_count(self) -> int:
        """총 글자 수"""
        return sum(len(line.text) for line in self.lines)


@dataclass
class Scenario:
    """전체 시나리오"""
    scenario_id: str = ""
    title: str = ""
    topic: str = ""
    genre: str = ""
    scenes: List[Scene] = field(default_factory=list)

    # 메타데이터
    created_at: str = ""
    modified_at: str = ""
    version: int = 1

    # 스토리 요소
    story_bible: str = ""
    hook: str = ""
    tags: List[str] = field(default_factory=list)

    def get_total_duration(self) -> float:
        """총 시간 계산"""
        return sum(scene.get_total_duration() for scene in self.scenes)

    def get_total_lines(self) -> int:
        """총 대사 수"""
        return sum(scene.get_line_count() for scene in self.scenes)


# ============================================================
# 색상 정의
# ============================================================

COLORS = {
    # 배경
    "bg_dark": "#1a1a2e",
    "bg_card": "#252542",
    "bg_hover": "#2a2a4a",

    # 역할별 색상
    "narrator": "#64B5F6",
    "grandma": "#FFB74D",
    "grandpa": "#81C784",
    "man": "#7986CB",
    "woman": "#F48FB1",

    # 감정별 색상
    "calm": "#64B5F6",
    "sad": "#7986CB",
    "angry": "#E57373",
    "happy": "#81C784",
    "fear": "#FFB74D",
    "whisper": "#9E9E9E",

    # 상태
    "generated": "#4CAF50",
    "modified": "#FF9800",
    "pending": "#757575",

    # 버튼
    "primary": "#6366F1",
    "success": "#10B981",
    "warning": "#F59E0B",
    "danger": "#EF4444",
}

ROLE_ICONS = {
    "narrator": "📖",
    "grandma": "👵",
    "grandpa": "👴",
    "man": "👨",
    "woman": "👩",
    "child": "🧒",
}


# ============================================================
# 시나리오 에디터 메인 윈도우
# ============================================================

class ScenarioEditorWindow(ctk.CTkToplevel):
    """시나리오 에디터 메인 윈도우"""

    def __init__(
        self,
        parent,
        plan_data: Dict[str, Any] = None,
        on_save: Callable[[Dict], None] = None,
        on_approve: Callable[[Dict], None] = None,
        regenerate_callback: Callable[[int, Dict], None] = None,
    ):
        super().__init__(parent)

        self.plan_data = plan_data or {}
        self.on_save = on_save
        self.on_approve = on_approve
        self.regenerate_callback = regenerate_callback

        # 시나리오 데이터
        self.scenario: Optional[Scenario] = None
        self.selected_scene_idx: Optional[int] = None
        self.selected_line_idx: Optional[int] = None

        # 드래그 상태
        self.drag_data = {"scene_idx": None, "line_idx": None, "dragging": False}

        # 히스토리 (Undo/Redo)
        self.history: List[Dict] = []
        self.history_index: int = -1

        # 윈도우 설정
        self.title("Reverie Studio - 시나리오 에디터 v3.1.0")
        self.geometry("1400x900")
        self.minsize(1200, 700)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 시나리오 로드
        self._load_scenario_from_plan()

        # UI 생성
        self._create_ui()

        # 초기 히스토리
        self._save_to_history()

        # 닫기 이벤트
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_scenario_from_plan(self):
        """plan_data에서 시나리오 로드"""
        script_list = self.plan_data.get("script_list", [])

        self.scenario = Scenario(
            scenario_id=self.plan_data.get("project_name", f"scenario_{datetime.now().strftime('%Y%m%d%H%M%S')}"),
            title=self.plan_data.get("title", ""),
            topic=self.plan_data.get("topic", ""),
            genre=self.plan_data.get("genre", "horror"),
            story_bible=self.plan_data.get("story_bible", ""),
            hook=self.plan_data.get("hook", ""),
            tags=self.plan_data.get("tags", "").split(",") if isinstance(self.plan_data.get("tags"), str) else [],
            created_at=datetime.now().isoformat(),
            modified_at=datetime.now().isoformat(),
        )

        # 대사를 장면으로 그룹화 (5-10줄씩)
        if script_list:
            scenes = []
            lines_per_scene = 7  # 장면당 대사 수

            for i in range(0, len(script_list), lines_per_scene):
                chunk = script_list[i:i + lines_per_scene]

                scene_lines = []
                for item in chunk:
                    line = SceneLine(
                        role=item.get("role", "narrator"),
                        text=item.get("text", ""),
                        emotion=item.get("emotion", "calm"),
                    )
                    line.estimate_duration()
                    scene_lines.append(line)

                scene = Scene(
                    scene_id=f"scene_{len(scenes)+1:03d}",
                    scene_number=len(scenes) + 1,
                    title=f"장면 {len(scenes)+1}",
                    description=scene_lines[0].text[:50] + "..." if scene_lines else "",
                    lines=scene_lines,
                    is_generated=True,
                )
                scenes.append(scene)

            self.scenario.scenes = scenes

    def _create_ui(self):
        """UI 생성"""
        # 메인 컨테이너
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 상단 툴바
        self._create_toolbar(main_frame)

        # 중앙 영역 (3단 레이아웃)
        content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, pady=10)

        # 좌측: 장면 목록 (250px)
        self.scene_list_frame = ctk.CTkFrame(content_frame, width=250, fg_color=COLORS["bg_dark"])
        self.scene_list_frame.pack(side="left", fill="y", padx=(0, 5))
        self.scene_list_frame.pack_propagate(False)
        self._create_scene_list(self.scene_list_frame)

        # 중앙: 장면 에디터 (확장)
        self.editor_frame = ctk.CTkFrame(content_frame, fg_color=COLORS["bg_dark"])
        self.editor_frame.pack(side="left", fill="both", expand=True, padx=5)
        self._create_scene_editor(self.editor_frame)

        # 우측: 속성 패널 (300px)
        self.property_frame = ctk.CTkFrame(content_frame, width=300, fg_color=COLORS["bg_dark"])
        self.property_frame.pack(side="right", fill="y", padx=(5, 0))
        self.property_frame.pack_propagate(False)
        self._create_property_panel(self.property_frame)

        # 하단 상태바
        self._create_statusbar(main_frame)

        # 첫 번째 장면 선택
        if self.scenario and self.scenario.scenes:
            self._select_scene(0)

    def _create_toolbar(self, parent):
        """상단 툴바"""
        toolbar = ctk.CTkFrame(parent, height=50, fg_color=COLORS["bg_card"])
        toolbar.pack(fill="x", pady=(0, 10))
        toolbar.pack_propagate(False)

        # 좌측: 파일 작업
        left_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        left_frame.pack(side="left", padx=10, pady=5)

        ctk.CTkButton(
            left_frame, text="💾 저장", width=80, font=get_font("normal"),
            fg_color=COLORS["primary"], command=self._save_scenario
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            left_frame, text="📂 불러오기", width=100, font=get_font("normal"),
            fg_color="#555555", command=self._load_scenario
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            left_frame, text="📤 내보내기", width=100, font=get_font("normal"),
            fg_color="#555555", command=self._export_json
        ).pack(side="left", padx=2)

        # 중앙: 편집 작업
        center_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        center_frame.pack(side="left", padx=20, pady=5)

        ctk.CTkButton(
            center_frame, text="↩️ 실행취소", width=100, font=get_font("normal"),
            fg_color="#555555", command=self._undo
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            center_frame, text="↪️ 다시실행", width=100, font=get_font("normal"),
            fg_color="#555555", command=self._redo
        ).pack(side="left", padx=2)

        # 구분선
        ctk.CTkFrame(center_frame, width=2, height=30, fg_color="#555555").pack(side="left", padx=10)

        ctk.CTkButton(
            center_frame, text="➕ 장면 추가", width=100, font=get_font("normal"),
            fg_color=COLORS["success"], command=self._add_scene
        ).pack(side="left", padx=2)

        # v58: AI 재생성 미구현 - 버튼 숨김
        # ctk.CTkButton(
        #     center_frame, text="🔄 전체 재생성", width=110, font=get_font("normal"),
        #     fg_color=COLORS["warning"], command=self._regenerate_all
        # ).pack(side="left", padx=2)

        # 우측: 승인/취소
        right_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        right_frame.pack(side="right", padx=10, pady=5)

        ctk.CTkButton(
            right_frame, text="❌ 취소", width=80, font=get_font("normal"),
            fg_color=COLORS["danger"], command=self._on_close
        ).pack(side="right", padx=2)

        ctk.CTkButton(
            right_frame, text="✅ 승인 및 제작", width=130, font=get_font("medium", bold=True),
            fg_color=COLORS["success"], command=self._approve_and_produce
        ).pack(side="right", padx=2)

    def _create_scene_list(self, parent):
        """장면 목록 패널"""
        # 헤더
        header = ctk.CTkFrame(parent, height=40, fg_color=COLORS["bg_card"])
        header.pack(fill="x", padx=5, pady=5)
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="📋 장면 목록", font=get_font("medium", bold=True)
        ).pack(side="left", padx=10, pady=5)

        scene_count = len(self.scenario.scenes) if self.scenario else 0
        self.scene_count_label = ctk.CTkLabel(
            header, text=f"({scene_count})", font=get_font("small"), text_color="gray"
        )
        self.scene_count_label.pack(side="left", padx=5, pady=5)

        # 스크롤 영역
        self.scene_list_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.scene_list_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 장면 목록 렌더링
        self._render_scene_list()

    def _render_scene_list(self):
        """장면 목록 렌더링"""
        # 기존 위젯 제거
        for widget in self.scene_list_scroll.winfo_children():
            widget.destroy()

        if not self.scenario or not self.scenario.scenes:
            ctk.CTkLabel(
                self.scene_list_scroll, text="장면 없음", font=get_font("normal"),
                text_color="gray"
            ).pack(pady=20)
            return

        for idx, scene in enumerate(self.scenario.scenes):
            self._create_scene_card(idx, scene)

        # 장면 수 업데이트
        self.scene_count_label.configure(text=f"({len(self.scenario.scenes)})")

    def _create_scene_card(self, idx: int, scene: Scene):
        """장면 카드 생성"""
        is_selected = idx == self.selected_scene_idx

        # 카드 프레임
        card = ctk.CTkFrame(
            self.scene_list_scroll,
            fg_color=COLORS["bg_hover"] if is_selected else COLORS["bg_card"],
            corner_radius=8,
            border_width=2 if is_selected else 0,
            border_color=COLORS["primary"] if is_selected else None
        )
        card.pack(fill="x", pady=2)

        # 클릭 이벤트
        card.bind("<Button-1>", lambda e, i=idx: self._select_scene(i))
        card.bind("<Double-Button-1>", lambda e, i=idx: self._edit_scene_title(i))

        # 드래그 이벤트
        card.bind("<ButtonPress-1>", lambda e, i=idx: self._on_drag_start(i, e))
        card.bind("<B1-Motion>", self._on_drag_motion)
        card.bind("<ButtonRelease-1>", self._on_drag_end)

        # 상단: 번호 + 제목
        top_frame = ctk.CTkFrame(card, fg_color="transparent")
        top_frame.pack(fill="x", padx=8, pady=(8, 2))

        # 상태 표시
        if scene.is_modified:
            status_color = COLORS["modified"]
            status_text = "●"
        elif scene.is_generated:
            status_color = COLORS["generated"]
            status_text = "●"
        else:
            status_color = COLORS["pending"]
            status_text = "○"

        ctk.CTkLabel(
            top_frame, text=status_text, font=get_font("small"),
            text_color=status_color, width=15
        ).pack(side="left")

        ctk.CTkLabel(
            top_frame, text=f"{scene.scene_number}.", font=get_font("normal", bold=True),
            width=25
        ).pack(side="left")

        ctk.CTkLabel(
            top_frame, text=scene.title[:20], font=get_font("normal"), anchor="w"
        ).pack(side="left", fill="x", expand=True)

        # 하단: 통계
        bottom_frame = ctk.CTkFrame(card, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=8, pady=(2, 8))

        duration = scene.get_total_duration()
        line_count = scene.get_line_count()

        ctk.CTkLabel(
            bottom_frame, text=f"🎬 {line_count}줄", font=get_font("small"),
            text_color="#888888"
        ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            bottom_frame, text=f"⏱️ {duration:.0f}초", font=get_font("small"),
            text_color="#888888"
        ).pack(side="left")

        # 삭제 버튼 (호버 시 표시)
        del_btn = ctk.CTkButton(
            bottom_frame, text="🗑️", width=25, height=25,
            fg_color="transparent", hover_color=COLORS["danger"],
            font=get_font("small"),
            command=lambda i=idx: self._delete_scene(i)
        )
        del_btn.pack(side="right")

        # 모든 자식 위젯에도 클릭 이벤트 바인딩
        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, i=idx: self._select_scene(i))
            for subchild in child.winfo_children():
                subchild.bind("<Button-1>", lambda e, i=idx: self._select_scene(i))

    def _create_scene_editor(self, parent):
        """장면 에디터 패널"""
        # 헤더
        self.editor_header = ctk.CTkFrame(parent, height=50, fg_color=COLORS["bg_card"])
        self.editor_header.pack(fill="x", padx=5, pady=5)
        self.editor_header.pack_propagate(False)

        self.editor_title_label = ctk.CTkLabel(
            self.editor_header, text="장면을 선택하세요",
            font=get_font("large", bold=True)
        )
        self.editor_title_label.pack(side="left", padx=15, pady=10)

        # 장면 컨트롤 버튼
        self.scene_controls = ctk.CTkFrame(self.editor_header, fg_color="transparent")
        self.scene_controls.pack(side="right", padx=10)

        # v58: AI 재생성 미구현 - 버튼 숨김
        # ctk.CTkButton(
        #     self.scene_controls, text="🔄 이 장면 재생성", width=130,
        #     font=get_font("normal"), fg_color=COLORS["warning"],
        #     command=self._regenerate_current_scene
        # ).pack(side="left", padx=2)

        ctk.CTkButton(
            self.scene_controls, text="➕ 대사 추가", width=100,
            font=get_font("normal"), fg_color=COLORS["success"],
            command=self._add_line
        ).pack(side="left", padx=2)

        # 대사 목록 (스크롤)
        self.lines_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.lines_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 안내 메시지
        self.editor_placeholder = ctk.CTkLabel(
            self.lines_scroll, text="좌측에서 장면을 선택하세요",
            font=get_font("medium"), text_color="gray"
        )
        self.editor_placeholder.pack(pady=100)

    def _render_scene_lines(self, scene: Scene):
        """장면의 대사 목록 렌더링"""
        # 기존 위젯 제거
        for widget in self.lines_scroll.winfo_children():
            widget.destroy()

        if not scene.lines:
            ctk.CTkLabel(
                self.lines_scroll, text="대사가 없습니다. 대사를 추가하세요.",
                font=get_font("normal"), text_color="gray"
            ).pack(pady=50)
            return

        for idx, line in enumerate(scene.lines):
            self._create_line_card(idx, line)

    def _create_line_card(self, idx: int, line: SceneLine):
        """대사 카드 생성"""
        is_selected = idx == self.selected_line_idx

        # 카드 프레임
        card = ctk.CTkFrame(
            self.lines_scroll,
            fg_color=COLORS["bg_hover"] if is_selected else COLORS["bg_card"],
            corner_radius=8,
            border_width=2 if is_selected else 0,
            border_color=COLORS["primary"] if is_selected else None
        )
        card.pack(fill="x", pady=2, padx=5)

        # 클릭 이벤트
        card.bind("<Button-1>", lambda e, i=idx: self._select_line(i))

        # 좌측: 라인 번호 + 역할
        left_frame = ctk.CTkFrame(card, fg_color="transparent", width=120)
        left_frame.pack(side="left", fill="y", padx=5, pady=5)
        left_frame.pack_propagate(False)

        # 라인 번호
        ctk.CTkLabel(
            left_frame, text=f"{idx+1:03d}", font=get_font("small"),
            text_color="#666666"
        ).pack(anchor="w")

        # 역할 + 아이콘
        role_color = COLORS.get(line.role, "#888888")
        role_icon = ROLE_ICONS.get(line.role, "👤")

        role_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        role_frame.pack(anchor="w", pady=2)

        ctk.CTkLabel(role_frame, text=role_icon, font=get_font("normal")).pack(side="left")
        ctk.CTkLabel(
            role_frame, text=line.role, font=get_font("small"),
            text_color=role_color
        ).pack(side="left", padx=3)

        # 감정 태그
        emotion_color = COLORS.get(line.emotion, "#888888")
        ctk.CTkLabel(
            left_frame, text=line.emotion, font=get_font("small"),
            fg_color=emotion_color, corner_radius=4, text_color="white",
            padx=5, pady=2
        ).pack(anchor="w", pady=2)

        # 중앙: 대사 텍스트
        text_frame = ctk.CTkFrame(card, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        text_label = ctk.CTkLabel(
            text_frame, text=line.text, font=get_font("normal"),
            anchor="w", justify="left", wraplength=600
        )
        text_label.pack(anchor="w", fill="x")

        # 시간 표시
        duration = line.estimate_duration()
        ctk.CTkLabel(
            text_frame, text=f"⏱️ {duration:.1f}초", font=get_font("small"),
            text_color="#666666"
        ).pack(anchor="w", pady=(5, 0))

        # 우측: 버튼
        btn_frame = ctk.CTkFrame(card, fg_color="transparent", width=100)
        btn_frame.pack(side="right", fill="y", padx=5, pady=5)
        btn_frame.pack_propagate(False)

        ctk.CTkButton(
            btn_frame, text="✏️", width=30, height=28,
            fg_color="#555555", hover_color="#666666",
            command=lambda i=idx: self._edit_line(i)
        ).pack(pady=2)

        ctk.CTkButton(
            btn_frame, text="🗑️", width=30, height=28,
            fg_color="#555555", hover_color=COLORS["danger"],
            command=lambda i=idx: self._delete_line(i)
        ).pack(pady=2)

        # v58: AI 재생성 미구현 - 버튼 숨김
        # ctk.CTkButton(
        #     btn_frame, text="🔄", width=30, height=28,
        #     fg_color="#555555", hover_color=COLORS["warning"],
        #     command=lambda i=idx: self._regenerate_line(i)
        # ).pack(pady=2)

        # 자식 위젯에도 클릭 이벤트
        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, i=idx: self._select_line(i))

    def _create_property_panel(self, parent):
        """속성 패널"""
        # 헤더
        header = ctk.CTkFrame(parent, height=40, fg_color=COLORS["bg_card"])
        header.pack(fill="x", padx=5, pady=5)
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="⚙️ 속성", font=get_font("medium", bold=True)
        ).pack(side="left", padx=10, pady=5)

        # 탭뷰
        self.property_tabs = ctk.CTkTabview(parent, fg_color=COLORS["bg_card"])
        self.property_tabs.pack(fill="both", expand=True, padx=5, pady=5)

        self.property_tabs.add("장면")
        self.property_tabs.add("전체")
        self.property_tabs.add("미리보기")

        # 장면 속성 탭
        self._create_scene_properties(self.property_tabs.tab("장면"))

        # 전체 속성 탭
        self._create_global_properties(self.property_tabs.tab("전체"))

        # 미리보기 탭
        self._create_preview_tab(self.property_tabs.tab("미리보기"))

    def _create_scene_properties(self, parent):
        """장면 속성"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # 장면 제목
        ctk.CTkLabel(scroll, text="장면 제목:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.scene_title_entry = ctk.CTkEntry(scroll, font=get_font("normal"))
        self.scene_title_entry.pack(fill="x", padx=5, pady=2)

        # 장면 설명
        ctk.CTkLabel(scroll, text="설명:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.scene_desc_entry = ctk.CTkTextbox(scroll, height=80, font=get_font("small"))
        self.scene_desc_entry.pack(fill="x", padx=5, pady=2)

        # 이미지 프롬프트
        ctk.CTkLabel(scroll, text="이미지 프롬프트:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.scene_prompt_entry = ctk.CTkTextbox(scroll, height=100, font=get_font("small"))
        self.scene_prompt_entry.pack(fill="x", padx=5, pady=2)

        # 적용 버튼
        ctk.CTkButton(
            scroll, text="변경사항 적용", font=get_font("normal"),
            fg_color=COLORS["primary"], command=self._apply_scene_properties
        ).pack(fill="x", padx=5, pady=10)

    def _create_global_properties(self, parent):
        """전체 속성"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # 시나리오 제목
        ctk.CTkLabel(scroll, text="제목:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.global_title_entry = ctk.CTkEntry(scroll, font=get_font("normal"))
        self.global_title_entry.pack(fill="x", padx=5, pady=2)
        if self.scenario:
            self.global_title_entry.insert(0, self.scenario.title)

        # 주제
        ctk.CTkLabel(scroll, text="주제:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.global_topic_entry = ctk.CTkEntry(scroll, font=get_font("normal"))
        self.global_topic_entry.pack(fill="x", padx=5, pady=2)
        if self.scenario:
            self.global_topic_entry.insert(0, self.scenario.topic)

        # 장르
        ctk.CTkLabel(scroll, text="장르:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.global_genre_combo = ctk.CTkComboBox(
            scroll, values=["horror", "mystery", "emotional", "comedy", "documentary"],
            font=get_font("normal")
        )
        self.global_genre_combo.pack(fill="x", padx=5, pady=2)
        if self.scenario:
            self.global_genre_combo.set(self.scenario.genre)

        # 스토리 바이블
        ctk.CTkLabel(scroll, text="스토리 바이블:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.global_bible_entry = ctk.CTkTextbox(scroll, height=120, font=get_font("small"))
        self.global_bible_entry.pack(fill="x", padx=5, pady=2)
        if self.scenario and self.scenario.story_bible:
            self.global_bible_entry.insert("1.0", self.scenario.story_bible)

        # 훅
        ctk.CTkLabel(scroll, text="오프닝 훅:", font=get_font("normal")).pack(anchor="w", padx=5, pady=(10, 2))
        self.global_hook_entry = ctk.CTkEntry(scroll, font=get_font("normal"))
        self.global_hook_entry.pack(fill="x", padx=5, pady=2)
        if self.scenario:
            self.global_hook_entry.insert(0, self.scenario.hook)

        # 적용 버튼
        ctk.CTkButton(
            scroll, text="변경사항 적용", font=get_font("normal"),
            fg_color=COLORS["primary"], command=self._apply_global_properties
        ).pack(fill="x", padx=5, pady=10)

    def _create_preview_tab(self, parent):
        """미리보기 탭"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # 통계 요약
        stats_frame = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=8)
        stats_frame.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(
            stats_frame, text="📊 전체 통계", font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.stats_content = ctk.CTkFrame(stats_frame, fg_color="transparent")
        self.stats_content.pack(fill="x", padx=10, pady=(0, 10))

        self._update_preview_stats()

        # 대본 미리보기
        preview_frame = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=8)
        preview_frame.pack(fill="both", expand=True, padx=5, pady=5)

        ctk.CTkLabel(
            preview_frame, text="📜 대본 미리보기", font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.preview_textbox = ctk.CTkTextbox(preview_frame, font=get_font("small"), height=300)
        self.preview_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._update_preview_text()

    def _update_preview_stats(self):
        """미리보기 통계 업데이트"""
        for widget in self.stats_content.winfo_children():
            widget.destroy()

        if not self.scenario:
            return

        total_scenes = len(self.scenario.scenes)
        total_lines = self.scenario.get_total_lines()
        total_duration = self.scenario.get_total_duration()
        total_chars = sum(scene.get_char_count() for scene in self.scenario.scenes)

        stats = [
            ("장면 수", f"{total_scenes}개"),
            ("총 대사", f"{total_lines}줄"),
            ("총 글자", f"{total_chars:,}자"),
            ("예상 시간", f"{total_duration/60:.1f}분"),
        ]

        for label, value in stats:
            row = ctk.CTkFrame(self.stats_content, fg_color="transparent")
            row.pack(fill="x", pady=1)

            ctk.CTkLabel(row, text=label, font=get_font("small"), text_color="#888888", width=70, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=get_font("small"), anchor="w").pack(side="left")

    def _update_preview_text(self):
        """대본 미리보기 텍스트 업데이트"""
        self.preview_textbox.configure(state="normal")
        self.preview_textbox.delete("1.0", "end")

        if not self.scenario:
            return

        lines = []
        for scene in self.scenario.scenes:
            lines.append(f"\n=== {scene.title} ===\n")
            for line in scene.lines:
                lines.append(f"[{line.role}:{line.emotion}] {line.text}\n")

        self.preview_textbox.insert("1.0", "".join(lines))
        self.preview_textbox.configure(state="disabled")

    def _create_statusbar(self, parent):
        """상태바"""
        statusbar = ctk.CTkFrame(parent, height=30, fg_color=COLORS["bg_card"])
        statusbar.pack(fill="x", pady=(10, 0))
        statusbar.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            statusbar, text="준비", font=get_font("small"), text_color="#888888"
        )
        self.status_label.pack(side="left", padx=10, pady=5)

        # 총 시간
        if self.scenario:
            duration = self.scenario.get_total_duration()
            ctk.CTkLabel(
                statusbar, text=f"총 시간: {duration/60:.1f}분",
                font=get_font("small"), text_color="#888888"
            ).pack(side="right", padx=10, pady=5)

    # ============================================================
    # 이벤트 핸들러
    # ============================================================

    def _select_scene(self, idx: int):
        """장면 선택"""
        if not self.scenario or idx >= len(self.scenario.scenes):
            return

        self.selected_scene_idx = idx
        self.selected_line_idx = None

        scene = self.scenario.scenes[idx]

        # 에디터 헤더 업데이트
        self.editor_title_label.configure(text=f"🎬 {scene.title} (장면 {scene.scene_number})")

        # 장면 목록 다시 렌더링
        self._render_scene_list()

        # 대사 목록 렌더링
        self._render_scene_lines(scene)

        # 속성 패널 업데이트
        self._update_scene_properties(scene)

        self._set_status(f"장면 {scene.scene_number} 선택됨")

    def _select_line(self, idx: int):
        """대사 선택"""
        self.selected_line_idx = idx

        # 대사 목록 다시 렌더링
        if self.selected_scene_idx is not None and self.scenario:
            scene = self.scenario.scenes[self.selected_scene_idx]
            self._render_scene_lines(scene)

    def _update_scene_properties(self, scene: Scene):
        """장면 속성 업데이트"""
        self.scene_title_entry.delete(0, "end")
        self.scene_title_entry.insert(0, scene.title)

        self.scene_desc_entry.delete("1.0", "end")
        self.scene_desc_entry.insert("1.0", scene.description)

        self.scene_prompt_entry.delete("1.0", "end")
        self.scene_prompt_entry.insert("1.0", scene.image_prompt)

    def _apply_scene_properties(self):
        """장면 속성 적용"""
        if self.selected_scene_idx is None or not self.scenario:
            return

        scene = self.scenario.scenes[self.selected_scene_idx]
        scene.title = self.scene_title_entry.get()
        scene.description = self.scene_desc_entry.get("1.0", "end-1c")
        scene.image_prompt = self.scene_prompt_entry.get("1.0", "end-1c")
        scene.is_modified = True

        self._render_scene_list()
        self._save_to_history()
        self._set_status("장면 속성 적용됨")

    def _apply_global_properties(self):
        """전체 속성 적용"""
        if not self.scenario:
            return

        self.scenario.title = self.global_title_entry.get()
        self.scenario.topic = self.global_topic_entry.get()
        self.scenario.genre = self.global_genre_combo.get()
        self.scenario.story_bible = self.global_bible_entry.get("1.0", "end-1c")
        self.scenario.hook = self.global_hook_entry.get()
        self.scenario.modified_at = datetime.now().isoformat()

        self._save_to_history()
        self._set_status("전체 속성 적용됨")

    def _add_scene(self):
        """장면 추가"""
        if not self.scenario:
            return

        new_scene = Scene(
            scene_id=f"scene_{len(self.scenario.scenes)+1:03d}",
            scene_number=len(self.scenario.scenes) + 1,
            title=f"새 장면 {len(self.scenario.scenes)+1}",
            description="",
            lines=[SceneLine(role="narrator", text="새로운 대사를 입력하세요.", emotion="calm")],
        )

        self.scenario.scenes.append(new_scene)
        self._render_scene_list()
        self._select_scene(len(self.scenario.scenes) - 1)
        self._save_to_history()
        self._set_status("새 장면 추가됨")

    def _delete_scene(self, idx: int):
        """장면 삭제"""
        if not self.scenario or idx >= len(self.scenario.scenes):
            return

        if len(self.scenario.scenes) <= 1:
            messagebox.showwarning("경고", "최소 1개의 장면이 필요합니다.")
            return

        if messagebox.askyesno("확인", f"장면 {idx+1}을(를) 삭제하시겠습니까?"):
            del self.scenario.scenes[idx]

            # 장면 번호 재정렬
            for i, scene in enumerate(self.scenario.scenes):
                scene.scene_number = i + 1

            self._render_scene_list()

            # 선택 조정
            if self.selected_scene_idx == idx:
                self.selected_scene_idx = max(0, idx - 1)
                if self.scenario.scenes:
                    self._select_scene(self.selected_scene_idx)

            self._save_to_history()
            self._set_status("장면 삭제됨")

    def _add_line(self):
        """대사 추가"""
        if self.selected_scene_idx is None or not self.scenario:
            messagebox.showwarning("경고", "먼저 장면을 선택하세요.")
            return

        scene = self.scenario.scenes[self.selected_scene_idx]
        new_line = SceneLine(role="narrator", text="새로운 대사를 입력하세요.", emotion="calm")
        scene.lines.append(new_line)
        scene.is_modified = True

        self._render_scene_lines(scene)
        self._render_scene_list()
        self._save_to_history()
        self._set_status("새 대사 추가됨")

    def _edit_line(self, idx: int):
        """대사 편집"""
        if self.selected_scene_idx is None or not self.scenario:
            return

        scene = self.scenario.scenes[self.selected_scene_idx]
        if idx >= len(scene.lines):
            return

        line = scene.lines[idx]

        # 편집 다이얼로그 (간단 버전)
        dialog = LineEditDialog(
            self, line,
            on_save=lambda edited: self._save_edited_line(idx, edited)
        )

    def _save_edited_line(self, idx: int, edited: SceneLine):
        """편집된 대사 저장"""
        if self.selected_scene_idx is None or not self.scenario:
            return

        scene = self.scenario.scenes[self.selected_scene_idx]
        scene.lines[idx] = edited
        scene.is_modified = True

        self._render_scene_lines(scene)
        self._render_scene_list()
        self._update_preview_stats()
        self._update_preview_text()
        self._save_to_history()
        self._set_status("대사 수정됨")

    def _delete_line(self, idx: int):
        """대사 삭제"""
        if self.selected_scene_idx is None or not self.scenario:
            return

        scene = self.scenario.scenes[self.selected_scene_idx]
        if idx >= len(scene.lines):
            return

        if len(scene.lines) <= 1:
            messagebox.showwarning("경고", "최소 1개의 대사가 필요합니다.")
            return

        if messagebox.askyesno("확인", f"대사 {idx+1}을(를) 삭제하시겠습니까?"):
            del scene.lines[idx]
            scene.is_modified = True

            self._render_scene_lines(scene)
            self._render_scene_list()
            self._save_to_history()
            self._set_status("대사 삭제됨")

    def _regenerate_line(self, idx: int):
        """대사 재생성"""
        if self.selected_scene_idx is None or not self.scenario:
            return

        # NOTE: AI 재생성은 orchestrator.py + Gemini 통합 후 구현 예정 (Phase U)
        messagebox.showinfo("알림", "AI 대사 재생성 기능은 추후 업데이트됩니다.")

    def _regenerate_current_scene(self):
        """현재 장면 재생성"""
        if self.selected_scene_idx is None:
            messagebox.showwarning("경고", "먼저 장면을 선택하세요.")
            return

        if messagebox.askyesno("확인", "이 장면을 AI가 다시 생성하시겠습니까?\n현재 내용은 대체됩니다."):
            # NOTE: AI 재생성은 orchestrator.py + Gemini 통합 후 구현 예정 (Phase U)
            if self.regenerate_callback:
                self.regenerate_callback(self.selected_scene_idx, self._get_current_plan_data())
            messagebox.showinfo("알림", "AI 장면 재생성 기능은 추후 업데이트됩니다.")

    def _regenerate_all(self):
        """전체 재생성"""
        if messagebox.askyesno("확인", "전체 시나리오를 AI가 다시 생성하시겠습니까?\n현재 내용은 모두 대체됩니다."):
            # NOTE: AI 재생성은 orchestrator.py + Gemini 통합 후 구현 예정 (Phase U)
            messagebox.showinfo("알림", "AI 전체 재생성 기능은 추후 업데이트됩니다.")

    def _edit_scene_title(self, idx: int):
        """장면 제목 편집 (더블클릭)"""
        if not self.scenario or idx >= len(self.scenario.scenes):
            return

        scene = self.scenario.scenes[idx]

        # 간단한 입력 다이얼로그
        dialog = ctk.CTkInputDialog(
            text=f"장면 {scene.scene_number} 제목:",
            title="장면 제목 편집"
        )
        new_title = dialog.get_input()

        if new_title:
            scene.title = new_title
            scene.is_modified = True
            self._render_scene_list()
            self._save_to_history()

    # ============================================================
    # 드래그 & 드롭
    # ============================================================

    def _on_drag_start(self, idx: int, event):
        """드래그 시작"""
        self.drag_data["scene_idx"] = idx
        self.drag_data["dragging"] = True

    def _on_drag_motion(self, event):
        """드래그 중"""
        if not self.drag_data["dragging"]:
            return
        # NOTE: 드래그 비주얼 피드백 미구현 (이벤트 바인딩 없음)

    def _on_drag_end(self, event):
        """드래그 종료"""
        if not self.drag_data["dragging"]:
            return

        self.drag_data["dragging"] = False

        # NOTE: 드롭 순서 변경 미구현 (이벤트 바인딩 없음)
        self.drag_data["scene_idx"] = None

    # ============================================================
    # 히스토리 (Undo/Redo)
    # ============================================================

    def _save_to_history(self):
        """히스토리에 현재 상태 저장"""
        if not self.scenario:
            return

        # 현재 인덱스 이후 히스토리 삭제
        self.history = self.history[:self.history_index + 1]

        # 현재 상태 저장
        state = self._serialize_scenario()
        self.history.append(state)
        self.history_index = len(self.history) - 1

        # 히스토리 제한 (최대 50개)
        if len(self.history) > 50:
            self.history = self.history[-50:]
            self.history_index = len(self.history) - 1

    def _undo(self):
        """실행취소"""
        if self.history_index <= 0:
            return

        self.history_index -= 1
        state = self.history[self.history_index]
        self._deserialize_scenario(state)

        self._render_scene_list()
        if self.selected_scene_idx is not None and self.scenario:
            self._select_scene(min(self.selected_scene_idx, len(self.scenario.scenes) - 1))

        self._set_status("실행취소")

    def _redo(self):
        """다시실행"""
        if self.history_index >= len(self.history) - 1:
            return

        self.history_index += 1
        state = self.history[self.history_index]
        self._deserialize_scenario(state)

        self._render_scene_list()
        if self.selected_scene_idx is not None and self.scenario:
            self._select_scene(min(self.selected_scene_idx, len(self.scenario.scenes) - 1))

        self._set_status("다시실행")

    def _serialize_scenario(self) -> Dict:
        """시나리오를 딕셔너리로 직렬화"""
        if not self.scenario:
            return {}

        return {
            "scenario_id": self.scenario.scenario_id,
            "title": self.scenario.title,
            "topic": self.scenario.topic,
            "genre": self.scenario.genre,
            "story_bible": self.scenario.story_bible,
            "hook": self.scenario.hook,
            "tags": self.scenario.tags,
            "scenes": [
                {
                    "scene_id": s.scene_id,
                    "scene_number": s.scene_number,
                    "title": s.title,
                    "description": s.description,
                    "image_prompt": s.image_prompt,
                    "lines": [asdict(l) for l in s.lines]
                }
                for s in self.scenario.scenes
            ]
        }

    def _deserialize_scenario(self, data: Dict):
        """딕셔너리에서 시나리오 복원"""
        if not data:
            return

        self.scenario.title = data.get("title", "")
        self.scenario.topic = data.get("topic", "")
        self.scenario.genre = data.get("genre", "")
        self.scenario.story_bible = data.get("story_bible", "")
        self.scenario.hook = data.get("hook", "")
        self.scenario.tags = data.get("tags", [])

        self.scenario.scenes = []
        for scene_data in data.get("scenes", []):
            scene = Scene(
                scene_id=scene_data.get("scene_id", ""),
                scene_number=scene_data.get("scene_number", 0),
                title=scene_data.get("title", ""),
                description=scene_data.get("description", ""),
                image_prompt=scene_data.get("image_prompt", ""),
                lines=[SceneLine(**l) for l in scene_data.get("lines", [])]
            )
            self.scenario.scenes.append(scene)

    # ============================================================
    # 파일 작업
    # ============================================================

    def _save_scenario(self):
        """시나리오 저장"""
        if not self.scenario:
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"{self.scenario.scenario_id}.json"
        )

        if filepath:
            data = self._serialize_scenario()
            data["modified_at"] = datetime.now().isoformat()

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("저장 완료", f"저장됨: {filepath}")
            self._set_status(f"저장됨: {Path(filepath).name}")

    def _load_scenario(self):
        """시나리오 불러오기"""
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self._deserialize_scenario(data)
                self._render_scene_list()
                if self.scenario and self.scenario.scenes:
                    self._select_scene(0)

                self._save_to_history()
                self._set_status(f"불러옴: {Path(filepath).name}")

            except Exception as e:
                messagebox.showerror("오류", f"파일 로드 실패:\n{e}")

    def _export_json(self):
        """JSON 내보내기"""
        self._save_scenario()

    def _get_current_plan_data(self) -> Dict:
        """현재 상태를 plan_data 형식으로 변환"""
        if not self.scenario:
            return {}

        # 모든 대사를 flat list로 변환
        script_list = []
        for scene in self.scenario.scenes:
            for line in scene.lines:
                script_list.append({
                    "role": line.role,
                    "text": line.text,
                    "emotion": line.emotion
                })

        return {
            "project_name": self.scenario.scenario_id,
            "title": self.scenario.title,
            "topic": self.scenario.topic,
            "genre": self.scenario.genre,
            "story_bible": self.scenario.story_bible,
            "hook": self.scenario.hook,
            "tags": ",".join(self.scenario.tags) if self.scenario.tags else "",
            "script_list": script_list
        }

    def _approve_and_produce(self):
        """승인 및 제작 진행"""
        if not self.scenario:
            return

        if messagebox.askyesno("확인", "이 시나리오로 영상 제작을 진행하시겠습니까?"):
            plan_data = self._get_current_plan_data()

            if self.on_approve:
                self.on_approve(plan_data)

            self.destroy()

    def _on_close(self):
        """창 닫기"""
        if messagebox.askyesno("확인", "변경사항이 저장되지 않을 수 있습니다.\n종료하시겠습니까?"):
            self.destroy()

    def _set_status(self, text: str):
        """상태 메시지 설정"""
        self.status_label.configure(text=text)


# ============================================================
# 대사 편집 다이얼로그
# ============================================================

class LineEditDialog(ctk.CTkToplevel):
    """대사 편집 다이얼로그"""

    ROLES = ["narrator", "grandma", "grandpa", "man", "woman", "child"]
    EMOTIONS = ["calm", "sad", "angry", "happy", "fear", "whisper"]

    def __init__(self, parent, line: SceneLine, on_save: Callable[[SceneLine], None] = None):
        super().__init__(parent)

        self.line = SceneLine(
            role=line.role,
            text=line.text,
            emotion=line.emotion
        )
        self.on_save = on_save

        self.title("✏️ 대사 편집")
        self.geometry("550x400")
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

        ctk.CTkLabel(role_row, text="역할:", width=60, anchor="w", font=get_font("normal")).pack(side="left")

        self.role_var = ctk.StringVar(value=self.line.role)
        ctk.CTkComboBox(
            role_row, values=self.ROLES, variable=self.role_var,
            width=200, font=get_font("normal")
        ).pack(side="left", padx=10)

        # 감정 선택
        emotion_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        emotion_row.pack(fill="x", pady=5)

        ctk.CTkLabel(emotion_row, text="감정:", width=60, anchor="w", font=get_font("normal")).pack(side="left")

        self.emotion_var = ctk.StringVar(value=self.line.emotion)
        ctk.CTkComboBox(
            emotion_row, values=self.EMOTIONS, variable=self.emotion_var,
            width=200, font=get_font("normal")
        ).pack(side="left", padx=10)

        # 대사 텍스트
        ctk.CTkLabel(main_frame, text="대사:", anchor="w", font=get_font("normal")).pack(anchor="w", pady=(15, 5))

        self.text_box = ctk.CTkTextbox(main_frame, height=150, font=get_font("normal"))
        self.text_box.pack(fill="x", pady=5)
        self.text_box.insert("1.0", self.line.text)

        # 예상 시간
        self.duration_label = ctk.CTkLabel(
            main_frame, text="예상 시간: 0.0초", font=get_font("small"), text_color="gray"
        )
        self.duration_label.pack(anchor="w", pady=5)

        # 텍스트 변경 시 시간 업데이트
        self.text_box.bind("<KeyRelease>", self._update_duration)
        self._update_duration()

        # 버튼
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame, text="취소", width=100, font=get_font("normal"),
            fg_color="#757575", command=self.destroy
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="저장", width=100, font=get_font("normal"),
            fg_color=COLORS["success"], command=self._save
        ).pack(side="right", padx=5)

    def _update_duration(self, event=None):
        """예상 시간 업데이트"""
        text = self.text_box.get("1.0", "end-1c")
        duration = len(text) / 4.0
        self.duration_label.configure(text=f"예상 시간: {duration:.1f}초")

    def _save(self):
        """저장"""
        self.line.role = self.role_var.get()
        self.line.emotion = self.emotion_var.get()
        self.line.text = self.text_box.get("1.0", "end-1c").strip()
        self.line.estimate_duration()

        if self.on_save:
            self.on_save(self.line)

        self.destroy()


# ============================================================
# 테스트용
# ============================================================

def main():
    """독립 실행 테스트"""
    if not CTK_AVAILABLE:
        print("customtkinter가 필요합니다.")
        return

    # 테스트 데이터
    test_plan = {
        "project_name": "test_scenario",
        "title": "테스트 시나리오",
        "topic": "밤에 울려 퍼지는 목소리",
        "genre": "horror",
        "story_bible": "어두운 밤, 이상한 소리가 들려온다.",
        "hook": "그날 밤, 나는 무언가가 다가오는 것을 느꼈다.",
        "tags": "공포,도시괴담,밤",
        "script_list": [
            {"role": "narrator", "text": "이것은 테스트 대사입니다.", "emotion": "calm"},
            {"role": "narrator", "text": "어둠 속에서 무언가 움직였다.", "emotion": "fear"},
            {"role": "woman", "text": "누구세요?", "emotion": "fear"},
            {"role": "narrator", "text": "대답은 없었다.", "emotion": "calm"},
            {"role": "narrator", "text": "하지만 발소리는 점점 가까워졌다.", "emotion": "fear"},
            {"role": "woman", "text": "제발... 대답해 주세요.", "emotion": "sad"},
            {"role": "narrator", "text": "그리고 그 순간.", "emotion": "calm"},
            {"role": "narrator", "text": "그녀는 보았다.", "emotion": "fear"},
        ]
    }

    root = ctk.CTk()
    root.title("Scenario Editor Test")
    root.geometry("400x200")

    def open_editor():
        editor = ScenarioEditorWindow(
            root,
            plan_data=test_plan,
            on_approve=lambda d: print("Approved:", d)
        )

    ctk.CTkButton(root, text="시나리오 에디터 열기", command=open_editor).pack(pady=50)

    root.mainloop()


if __name__ == "__main__":
    main()
