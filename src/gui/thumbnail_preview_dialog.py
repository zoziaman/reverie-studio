# src/gui/thumbnail_preview_dialog.py
"""
썸네일 확인 및 조정 팝업 (개선판)
- REAL / ART 2종 미리보기
- 텍스트 내용 수정
- 색상 선택 (프리셋 + 팔레트)
- 위치/크기 조정
- 외곽선/그림자 조정
- 빠른 재생성 (30초)
- [NEW] 줌 인/아웃 기능
- [NEW] 동시 편집 모드
- [NEW] 실행취소/재실행 (Undo/Redo)
- [NEW] 프리셋 저장/불러오기
- [NEW] 실시간 미리보기 개선
"""
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageColor
import os
import textwrap
import copy
import json
import logging
from tkinter import colorchooser
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 크로스 플랫폼 폰트
try:
    from utils.font_helper import KOREAN_FONT_BOLD
    DEFAULT_FONT = KOREAN_FONT_BOLD
except ImportError:
    DEFAULT_FONT = None


class ThumbnailPreviewDialog(ctk.CTkToplevel):
    """
    썸네일 확인 및 조정 다이얼로그 (개선판)
    """

    # 색상 프리셋
    PRESET_COLORS = {
        "🟡": "#FFD700",    # 금색
        "🔴": "#FF0000",    # 빨강
        "⚪": "#FFFFFF",    # 흰색
        "⚫": "#000000",    # 검정
        "🟠": "#FF8C00",    # 주황
        "🟢": "#00FF00",    # 초록
        "🔵": "#1E90FF",    # 파랑
        "🟣": "#9400D3",    # 보라
        "🟤": "#8B4513",    # 갈색
        "🩷": "#FF69B4",    # 분홍
    }

    # v50: 채널별 클릭률 높은 썸네일 스타일 프리셋
    CHANNEL_STYLE_PRESETS = {
        "horror": {
            "top_text": {
                "content": "실화",
                "x": 640, "y": 60,
                "font_size": 80,
                "text_color": "#FFD700",  # 금색 - 시선 강탈
                "stroke_width": 6,
                "stroke_color": "#000000",
                "shadow_range": 5,
                "shadow_opacity": 0.9,
                "shadow_color": "#000000"
            },
            "main_text": {
                "content": "",  # 동적으로 설정
                "x": 640, "y": 200,
                "font_size": 140,  # 크게
                "text_color": "#FF0000",  # 빨간색
                "stroke_width": 10,
                "stroke_color": "#000000",
                "shadow_range": 8,
                "shadow_opacity": 0.95,
                "shadow_color": "#000000",
                "wrap_width": 8  # 더 짧게 끊어서 임팩트
            },
            "background": {"brightness": 0.35}  # 더 어둡게
        },
        "daily_life_toon": {
            "top_text": {
                "content": "일상툰",
                "x": 640, "y": 70,
                "font_size": 70,
                "text_color": "#FFFFFF",  # 흰색
                "stroke_width": 5,
                "stroke_color": "#FF6B35",  # 따뜻한 주황
                "shadow_range": 4,
                "shadow_opacity": 0.8,
                "shadow_color": "#000000"
            },
            "main_text": {
                "content": "",
                "x": 640, "y": 220,
                "font_size": 120,
                "text_color": "#FFD700",  # 금색
                "stroke_width": 8,
                "stroke_color": "#8B4513",  # 갈색
                "shadow_range": 6,
                "shadow_opacity": 0.85,
                "shadow_color": "#000000",
                "wrap_width": 10
            },
            "background": {"brightness": 0.45}
        },
        "mystery_toon": {
            "top_text": {
                "content": "미스터리툰",
                "x": 640, "y": 55,
                "font_size": 90,
                "text_color": "#FF0000",  # 빨간색
                "stroke_width": 7,
                "stroke_color": "#FFFFFF",  # 흰색 외곽선
                "shadow_range": 6,
                "shadow_opacity": 0.9,
                "shadow_color": "#000000"
            },
            "main_text": {
                "content": "",
                "x": 640, "y": 200,
                "font_size": 135,
                "text_color": "#FFFFFF",  # 흰색
                "stroke_width": 9,
                "stroke_color": "#FF0000",  # 빨간 외곽선
                "shadow_range": 7,
                "shadow_opacity": 0.9,
                "shadow_color": "#000000",
                "wrap_width": 9
            },
            "background": {"brightness": 0.38}
        }
    }

    # 줌 레벨
    ZOOM_LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    def __init__(self, parent, real_path: str, art_path: str, font_path: str = None,
                 scenario_summary: str = None, channel_type: str = None, main_title: str = None):
        super().__init__(parent)

        self.title("📸 썸네일 확인 및 조정")

        # 화면 크기에 맞게 창 크기 조정
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # 창 크기를 화면의 90%로 제한
        window_width = min(1700, int(screen_width * 0.9))
        window_height = min(950, int(screen_height * 0.9))

        self.geometry(f"{window_width}x{window_height}")
        self.minsize(1200, 700)  # 최소 크기 설정

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        self.real_path = real_path
        self.art_path = art_path
        self.font_path = font_path or DEFAULT_FONT
        self.scenario_summary = scenario_summary or "시나리오 정보 없음"
        self.channel_type = channel_type or "daily_life_toon"  # VideoToon default
        self.main_title = main_title  # v50: 메인 제목
        self.user_choice = None

        # 현재 조정 대상
        self.current_target = "REAL"  # "REAL" or "ART"

        # 동시 편집 모드
        self.sync_edit_mode = False

        # 줌 레벨
        self.zoom_level = 1.0
        self.zoom_index = 2  # 1.0 = 100%

        # 기본 이미지 저장 (배경 재사용용)
        self.base_real_img = None
        self.base_art_img = None

        # 원본 배경 이미지 (텍스트 없는 깨끗한 배경)
        self.clean_real_bg = None
        self.clean_art_bg = None

        # v50: 채널별 프리셋 적용
        # 현재 설정값 (REAL)
        self.real_settings = self._get_channel_preset_settings()

        # 현재 설정값 (ART)
        self.art_settings = self._get_channel_preset_settings()

        # 히스토리 (실행취소/재실행)
        self.history: List[Dict[str, Any]] = []
        self.history_index = -1
        self.max_history = 50

        # 프리셋 경로
        try:
            from config.settings import config
            self.preset_path = os.path.join(config.CONFIG_DIR, "thumbnail_presets.json")
        except Exception:
            self.preset_path = "config/thumbnail_presets.json"

        # 미리보기 업데이트 지연 (성능 최적화)
        self._preview_update_pending = False
        self._preview_update_delay = 50  # ms

        self._create_ui()

        # 초기 상태 저장
        self._save_history()

        # 창 중앙 배치 (동적 크기 사용)
        self.update_idletasks()
        current_width = self.winfo_width()
        current_height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (current_width // 2)
        y = (self.winfo_screenheight() // 2) - (current_height // 2)
        self.geometry(f"+{x}+{y}")

        # 키보드 단축키 바인딩
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<Control-plus>", lambda e: self._zoom_in())
        self.bind("<Control-minus>", lambda e: self._zoom_out())
        self.bind("<Control-0>", lambda e: self._zoom_reset())
    
    def _get_default_settings(self):
        """기본 설정값 (폴백용)"""
        return {
            "top_text": {
                "content": "실화 공포",
                "x": 640,
                "y": 80,
                "font_size": 70,
                "text_color": "#FFD700",
                "stroke_width": 4,
                "stroke_color": "#000000",
                "shadow_range": 3,
                "shadow_opacity": 0.7,
                "shadow_color": "#000000"
            },
            "main_text": {
                "content": "충격적인 결말",
                "x": 640,
                "y": 200,
                "font_size": 130,
                "text_color": "#FF0000",
                "stroke_width": 8,
                "stroke_color": "#000000",
                "shadow_range": 5,
                "shadow_opacity": 0.8,
                "shadow_color": "#000000",
                "wrap_width": 10
            },
            "background": {
                "brightness": 0.4
            }
        }

    def _get_channel_preset_settings(self):
        """v50: 채널별 클릭률 높은 프리셋 적용"""
        import copy

        # 채널 프리셋 가져오기
        preset = self.CHANNEL_STYLE_PRESETS.get(self.channel_type, None)

        if preset:
            settings = copy.deepcopy(preset)
            # 메인 제목이 있으면 적용
            if self.main_title:
                settings["main_text"]["content"] = self.main_title
            else:
                settings["main_text"]["content"] = "충격적인 결말"
            return settings
        else:
            # 프리셋 없으면 기본값
            return self._get_default_settings()

    def _get_preset_display_name(self, channel_type: str) -> str:
        """채널 타입에 해당하는 표시 이름 반환"""
        mapping = {
            "daily_life_toon": "일상 영상툰",
            "mystery_toon": "미스터리 영상툰",
        }
        return mapping.get(channel_type, "커스텀")

    def _apply_style_preset(self, preset_name: str):
        """v50: 스타일 프리셋 원클릭 적용"""
        import copy

        # 프리셋 이름 → 채널 타입 매핑
        name_to_channel = {
            "일상 영상툰": "daily_life_toon",
            "미스터리 영상툰": "mystery_toon",
        }

        channel = name_to_channel.get(preset_name)
        if not channel:
            # 커스텀 - 아무것도 안함
            return

        # 프리셋 가져오기
        preset = self.CHANNEL_STYLE_PRESETS.get(channel)
        if not preset:
            return

        # 현재 메인 텍스트 내용 보존
        current_main_content = self.real_settings.get("main_text", {}).get("content", "")

        # 프리셋 적용
        self.real_settings = copy.deepcopy(preset)
        self.art_settings = copy.deepcopy(preset)

        # 메인 텍스트 내용 복원
        if current_main_content:
            self.real_settings["main_text"]["content"] = current_main_content
            self.art_settings["main_text"]["content"] = current_main_content

        # UI 슬라이더/입력 필드 업데이트
        self._update_controls_from_settings()

        # 미리보기 업데이트
        self._update_preview()

        # 히스토리 저장
        self._save_history()

    def _update_controls_from_settings(self):
        """설정값에 맞게 UI 컨트롤 업데이트"""
        settings = self.real_settings if self.current_target == "REAL" else self.art_settings

        try:
            # 상단 텍스트
            top = settings.get("top_text", {})
            if hasattr(self, "top_text_entry"):
                self.top_text_entry.delete(0, "end")
                self.top_text_entry.insert(0, top.get("content", ""))
            if hasattr(self, "top_size_slider"):
                self.top_size_slider.set(top.get("font_size", 70))
            if hasattr(self, "top_stroke_slider"):
                self.top_stroke_slider.set(top.get("stroke_width", 4))

            # 메인 텍스트
            main = settings.get("main_text", {})
            if hasattr(self, "main_text_entry"):
                self.main_text_entry.delete(0, "end")
                self.main_text_entry.insert(0, main.get("content", ""))
            if hasattr(self, "main_size_slider"):
                self.main_size_slider.set(main.get("font_size", 130))
            if hasattr(self, "main_stroke_slider"):
                self.main_stroke_slider.set(main.get("stroke_width", 8))

            # 배경 밝기
            bg = settings.get("background", {})
            if hasattr(self, "brightness_slider"):
                self.brightness_slider.set(bg.get("brightness", 0.4))

        except Exception as e:
            print(f"컨트롤 업데이트 오류: {e}")

    def _create_ui(self):
        """UI 구성"""
        # 메인 컨테이너
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # ★ 버튼 영역을 먼저 pack (하단 고정) - 항상 보이도록
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(side="bottom", fill="x", pady=(10, 0))

        center_frame = ctk.CTkFrame(button_frame, fg_color="transparent")
        center_frame.pack(expand=True)

        regenerate_btn = ctk.CTkButton(
            center_frame,
            text="🔄 조정 후 재생성 (30초)",
            width=200,
            height=40,
            font=ctk.CTkFont(size=14),
            command=self._on_regenerate
        )
        regenerate_btn.pack(side="left", padx=10)

        cancel_btn = ctk.CTkButton(
            center_frame,
            text="❌ 취소",
            width=150,
            height=40,
            font=ctk.CTkFont(size=14),
            fg_color="gray",
            hover_color="darkgray",
            command=self._on_cancel
        )
        cancel_btn.pack(side="left", padx=10)

        proceed_btn = ctk.CTkButton(
            center_frame,
            text="✅ 이대로 진행",
            width=180,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="green",
            hover_color="darkgreen",
            command=self._on_proceed
        )
        proceed_btn.pack(side="left", padx=10)

        # 상단: 제목 + 도구 버튼
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        title_label = ctk.CTkLabel(
            header_frame,
            text="🖼️ 썸네일이 생성되었습니다. 조정 후 진행하세요.",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title_label.pack(side="left")

        # 도구 버튼 (오른쪽)
        tools_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        tools_frame.pack(side="right")

        # 실행취소/재실행
        self.undo_btn = ctk.CTkButton(
            tools_frame,
            text="↩ 실행취소",
            width=90,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="gray40",
            command=self._undo
        )
        self.undo_btn.pack(side="left", padx=2)

        self.redo_btn = ctk.CTkButton(
            tools_frame,
            text="↪ 재실행",
            width=80,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="gray40",
            command=self._redo
        )
        self.redo_btn.pack(side="left", padx=2)

        # 줌 컨트롤
        ctk.CTkLabel(tools_frame, text="|", text_color="gray50").pack(side="left", padx=5)

        zoom_out_btn = ctk.CTkButton(
            tools_frame,
            text="-",
            width=30,
            height=28,
            command=self._zoom_out
        )
        zoom_out_btn.pack(side="left", padx=2)

        self.zoom_label = ctk.CTkLabel(
            tools_frame,
            text="100%",
            width=50,
            font=ctk.CTkFont(size=11)
        )
        self.zoom_label.pack(side="left", padx=2)

        zoom_in_btn = ctk.CTkButton(
            tools_frame,
            text="+",
            width=30,
            height=28,
            command=self._zoom_in
        )
        zoom_in_btn.pack(side="left", padx=2)

        # 프리셋 버튼
        ctk.CTkLabel(tools_frame, text="|", text_color="gray50").pack(side="left", padx=5)

        # v50: 채널별 스타일 프리셋 선택 (딸깍 적용)
        ctk.CTkLabel(
            tools_frame,
            text="스타일:",
            font=ctk.CTkFont(size=11)
        ).pack(side="left", padx=(0, 3))

        self.style_preset_var = ctk.StringVar(value=self._get_preset_display_name(self.channel_type))
        style_preset_menu = ctk.CTkOptionMenu(
            tools_frame,
            variable=self.style_preset_var,
            values=["공포 (금+빨강)", "감동 (흰+금)", "막장 (빨강+흰)", "커스텀"],
            width=130,
            height=28,
            font=ctk.CTkFont(size=11),
            command=self._apply_style_preset
        )
        style_preset_menu.pack(side="left", padx=2)

        ctk.CTkLabel(tools_frame, text="|", text_color="gray50").pack(side="left", padx=5)

        preset_save_btn = ctk.CTkButton(
            tools_frame,
            text="💾 저장",
            width=60,
            height=28,
            font=ctk.CTkFont(size=11),
            command=self._save_preset_dialog
        )
        preset_save_btn.pack(side="left", padx=2)

        preset_load_btn = ctk.CTkButton(
            tools_frame,
            text="📂 불러오기",
            width=80,
            height=28,
            font=ctk.CTkFont(size=11),
            command=self._load_preset_dialog
        )
        preset_load_btn.pack(side="left", padx=2)

        # 시나리오 요약 (접기)
        scenario_frame = ctk.CTkFrame(main_frame, fg_color="#2b2b2b")
        scenario_frame.pack(fill="x", pady=(0, 10))
        
        scenario_title = ctk.CTkLabel(
            scenario_frame,
            text="📖 시나리오 요약",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        scenario_title.pack(anchor="w", padx=10, pady=(8, 5))
        
        scenario_text = ctk.CTkTextbox(
            scenario_frame,
            height=80,
            font=ctk.CTkFont(size=12),
            fg_color="#1a1a1a"
        )
        scenario_text.pack(fill="x", padx=10, pady=(0, 8))
        scenario_text.insert("1.0", self.scenario_summary)
        scenario_text.configure(state="disabled")  # 읽기 전용
        
        # 미리보기 + 조정 영역 (좌우 분할)
        content_frame = ctk.CTkFrame(main_frame)
        content_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # 왼쪽: 미리보기
        left_frame = ctk.CTkFrame(content_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        preview_label = ctk.CTkLabel(
            left_frame,
            text="미리보기",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        preview_label.pack(pady=(5, 5))
        
        # REAL / ART 이미지
        images_container = ctk.CTkFrame(left_frame)
        images_container.pack(fill="both", expand=True, padx=10, pady=5)
        
        # REAL
        real_container = ctk.CTkFrame(images_container)
        real_container.pack(side="left", fill="both", expand=True, padx=5)
        
        real_label = ctk.CTkLabel(real_container, text="REAL", font=ctk.CTkFont(size=12, weight="bold"))
        real_label.pack()
        
        self.real_preview = ctk.CTkLabel(real_container, text="")
        self.real_preview.pack(pady=5)
        
        # ART
        art_container = ctk.CTkFrame(images_container)
        art_container.pack(side="right", fill="both", expand=True, padx=5)
        
        art_label = ctk.CTkLabel(art_container, text="ART", font=ctk.CTkFont(size=12, weight="bold"))
        art_label.pack()
        
        self.art_preview = ctk.CTkLabel(art_container, text="")
        self.art_preview.pack(pady=5)
        
        # 오른쪽: 조정 컨트롤
        right_frame = ctk.CTkFrame(content_frame, width=500)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))
        right_frame.pack_propagate(False)
        
        # 조정 대상 선택
        target_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        target_frame.pack(fill="x", padx=10, pady=5)

        target_label = ctk.CTkLabel(target_frame, text="조정 대상:", font=ctk.CTkFont(size=13))
        target_label.pack(side="left", padx=(0, 10))

        self.target_var = ctk.StringVar(value="REAL")

        real_radio = ctk.CTkRadioButton(
            target_frame,
            text="REAL",
            variable=self.target_var,
            value="REAL",
            command=self._on_target_change
        )
        real_radio.pack(side="left", padx=5)

        art_radio = ctk.CTkRadioButton(
            target_frame,
            text="ART",
            variable=self.target_var,
            value="ART",
            command=self._on_target_change
        )
        art_radio.pack(side="left", padx=5)

        # 동시 편집 모드 체크박스
        self.sync_var = ctk.BooleanVar(value=False)
        sync_check = ctk.CTkCheckBox(
            target_frame,
            text="동시 편집",
            variable=self.sync_var,
            command=self._on_sync_mode_change,
            font=ctk.CTkFont(size=11),
            width=80
        )
        sync_check.pack(side="left", padx=(20, 0))
        
        # 스크롤 가능한 조정 영역
        scroll_frame = ctk.CTkScrollableFrame(right_frame, height=600)
        scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 상단 텍스트 설정
        self._create_text_controls(scroll_frame, "상단 텍스트", "top_text")
        
        # 메인 제목 설정
        self._create_text_controls(scroll_frame, "메인 제목", "main_text", has_wrap=True)
        
        # 배경 설정
        self._create_background_controls(scroll_frame)
        
        # 초기 미리보기 로드
        self._load_initial_previews()
    
    def _create_text_controls(self, parent, title: str, text_type: str, has_wrap: bool = False):
        """텍스트 설정 컨트롤 생성"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(0, 15))
        
        # 제목
        title_label = ctk.CTkLabel(section, text=f"📝 {title}", font=ctk.CTkFont(size=14, weight="bold"))
        title_label.pack(anchor="w", padx=10, pady=(10, 10))
        
        # 내용 입력
        content_label = ctk.CTkLabel(section, text="내용:", font=ctk.CTkFont(size=12))
        content_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        content_entry = ctk.CTkEntry(section, width=400)
        content_entry.pack(anchor="w", padx=20, pady=(0, 10))
        content_entry.insert(0, self.real_settings[text_type]["content"])
        
        # 내용 변경 시 콜백
        content_entry.bind("<KeyRelease>", lambda e: self._on_content_change(text_type, content_entry.get()))
        
        # 색상 선택
        self._create_color_selector(section, "텍스트 색상:", text_type, "text_color")
        
        # 위치 조정
        pos_frame = ctk.CTkFrame(section, fg_color="transparent")
        pos_frame.pack(fill="x", padx=20, pady=(5, 5))
        
        # X축
        x_label = ctk.CTkLabel(pos_frame, text="X축:", font=ctk.CTkFont(size=11), width=40)
        x_label.grid(row=0, column=0, padx=(0, 5), sticky="w")
        
        x_slider = ctk.CTkSlider(pos_frame, from_=0, to=1280, number_of_steps=128,
                                  command=lambda v: self._on_slider_change(text_type, "x", int(v)))
        x_slider.set(self.real_settings[text_type]["x"])
        x_slider.grid(row=0, column=1, padx=5, sticky="ew")
        
        x_value = ctk.CTkLabel(pos_frame, text=f"{self.real_settings[text_type]['x']}px", width=60)
        x_value.grid(row=0, column=2, padx=(5, 0))
        
        # Y축
        y_label = ctk.CTkLabel(pos_frame, text="Y축:", font=ctk.CTkFont(size=11), width=40)
        y_label.grid(row=1, column=0, padx=(0, 5), pady=(5, 0), sticky="w")
        
        y_slider = ctk.CTkSlider(pos_frame, from_=0, to=720, number_of_steps=72,
                                  command=lambda v: self._on_slider_change(text_type, "y", int(v)))
        y_slider.set(self.real_settings[text_type]["y"])
        y_slider.grid(row=1, column=1, padx=5, pady=(5, 0), sticky="ew")
        
        y_value = ctk.CTkLabel(pos_frame, text=f"{self.real_settings[text_type]['y']}px", width=60)
        y_value.grid(row=1, column=2, padx=(5, 0), pady=(5, 0))
        
        pos_frame.columnconfigure(1, weight=1)
        
        # 폰트 크기
        font_frame = ctk.CTkFrame(section, fg_color="transparent")
        font_frame.pack(fill="x", padx=20, pady=(5, 5))
        
        font_label = ctk.CTkLabel(font_frame, text="폰트:", font=ctk.CTkFont(size=11), width=40)
        font_label.pack(side="left", padx=(0, 5))
        
        font_slider = ctk.CTkSlider(font_frame, from_=30, to=200, number_of_steps=170,
                                     command=lambda v: self._on_slider_change(text_type, "font_size", int(v)))
        font_slider.set(self.real_settings[text_type]["font_size"])
        font_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        font_value = ctk.CTkLabel(font_frame, text=f"{self.real_settings[text_type]['font_size']}px", width=60)
        font_value.pack(side="left", padx=(5, 0))
        
        # 줄바꿈 (메인 제목만)
        if has_wrap:
            wrap_frame = ctk.CTkFrame(section, fg_color="transparent")
            wrap_frame.pack(fill="x", padx=20, pady=(5, 5))
            
            wrap_label = ctk.CTkLabel(wrap_frame, text="줄바꿈:", font=ctk.CTkFont(size=11), width=40)
            wrap_label.pack(side="left", padx=(0, 5))
            
            wrap_slider = ctk.CTkSlider(wrap_frame, from_=5, to=20, number_of_steps=15,
                                         command=lambda v: self._on_slider_change(text_type, "wrap_width", int(v)))
            wrap_slider.set(self.real_settings[text_type]["wrap_width"])
            wrap_slider.pack(side="left", fill="x", expand=True, padx=5)
            
            wrap_value = ctk.CTkLabel(wrap_frame, text=f"{self.real_settings[text_type]['wrap_width']}자", width=60)
            wrap_value.pack(side="left", padx=(5, 0))
        
        # 외곽선
        stroke_label = ctk.CTkLabel(section, text="외곽선 (테두리):", font=ctk.CTkFont(size=12, weight="bold"))
        stroke_label.pack(anchor="w", padx=20, pady=(10, 5))
        
        stroke_width_frame = ctk.CTkFrame(section, fg_color="transparent")
        stroke_width_frame.pack(fill="x", padx=20, pady=(0, 5))
        
        sw_label = ctk.CTkLabel(stroke_width_frame, text="두께:", font=ctk.CTkFont(size=11), width=40)
        sw_label.pack(side="left", padx=(0, 5))
        
        sw_slider = ctk.CTkSlider(stroke_width_frame, from_=0, to=15, number_of_steps=15,
                                   command=lambda v: self._on_slider_change(text_type, "stroke_width", int(v)))
        sw_slider.set(self.real_settings[text_type]["stroke_width"])
        sw_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        sw_value = ctk.CTkLabel(stroke_width_frame, text=f"{self.real_settings[text_type]['stroke_width']}px", width=60)
        sw_value.pack(side="left", padx=(5, 0))
        
        self._create_color_selector(section, "외곽선 색상:", text_type, "stroke_color")
        
        # 그림자
        shadow_label = ctk.CTkLabel(section, text="그림자:", font=ctk.CTkFont(size=12, weight="bold"))
        shadow_label.pack(anchor="w", padx=20, pady=(10, 5))
        
        shadow_range_frame = ctk.CTkFrame(section, fg_color="transparent")
        shadow_range_frame.pack(fill="x", padx=20, pady=(0, 5))
        
        sr_label = ctk.CTkLabel(shadow_range_frame, text="범위:", font=ctk.CTkFont(size=11), width=40)
        sr_label.pack(side="left", padx=(0, 5))
        
        sr_slider = ctk.CTkSlider(shadow_range_frame, from_=0, to=20, number_of_steps=20,
                                   command=lambda v: self._on_slider_change(text_type, "shadow_range", int(v)))
        sr_slider.set(self.real_settings[text_type]["shadow_range"])
        sr_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        sr_value = ctk.CTkLabel(shadow_range_frame, text=f"{self.real_settings[text_type]['shadow_range']}px", width=60)
        sr_value.pack(side="left", padx=(5, 0))
        
        shadow_opacity_frame = ctk.CTkFrame(section, fg_color="transparent")
        shadow_opacity_frame.pack(fill="x", padx=20, pady=(0, 5))
        
        so_label = ctk.CTkLabel(shadow_opacity_frame, text="투명도:", font=ctk.CTkFont(size=11), width=40)
        so_label.pack(side="left", padx=(0, 5))
        
        so_slider = ctk.CTkSlider(shadow_opacity_frame, from_=0, to=100, number_of_steps=100,
                                   command=lambda v: self._on_slider_change(text_type, "shadow_opacity", v / 100))
        so_slider.set(self.real_settings[text_type]["shadow_opacity"] * 100)
        so_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        so_value = ctk.CTkLabel(shadow_opacity_frame, text=f"{int(self.real_settings[text_type]['shadow_opacity']*100)}%", width=60)
        so_value.pack(side="left", padx=(5, 0))
        
        self._create_color_selector(section, "그림자 색상:", text_type, "shadow_color")
    
    def _create_color_selector(self, parent, label_text: str, text_type: str, color_key: str):
        """색상 선택기"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=(5, 5))
        
        label = ctk.CTkLabel(frame, text=label_text, font=ctk.CTkFont(size=11))
        label.pack(anchor="w", pady=(0, 3))
        
        # 프리셋 버튼
        preset_frame = ctk.CTkFrame(frame, fg_color="transparent")
        preset_frame.pack(fill="x", pady=(0, 3))
        
        for emoji, hex_color in self.PRESET_COLORS.items():
            btn = ctk.CTkButton(
                preset_frame,
                text=emoji,
                width=30,
                height=25,
                fg_color=hex_color,
                hover_color=hex_color,
                command=lambda c=hex_color, tt=text_type, ck=color_key: self._set_color(tt, ck, c)
            )
            btn.pack(side="left", padx=2)
        
        # 색상 선택기 버튼 + 현재 색상 표시
        picker_frame = ctk.CTkFrame(frame, fg_color="transparent")
        picker_frame.pack(fill="x")
        
        picker_btn = ctk.CTkButton(
            picker_frame,
            text="🎨 선택...",
            width=80,
            height=25,
            command=lambda tt=text_type, ck=color_key: self._open_color_picker(tt, ck)
        )
        picker_btn.pack(side="left", padx=(0, 10))
        
        current_color = self.real_settings[text_type][color_key]
        
        color_preview = ctk.CTkLabel(picker_frame, text="███", text_color=current_color, font=ctk.CTkFont(size=14))
        color_preview.pack(side="left", padx=3)
        
        color_code = ctk.CTkLabel(picker_frame, text=current_color, font=ctk.CTkFont(size=10))
        color_code.pack(side="left")
    
    def _create_background_controls(self, parent):
        """배경 설정 (제거됨 - 텍스트만 오버레이)"""
        # 배경 어둡기 기능 제거
        # 썸네일 이미지는 그대로 유지하고 텍스트만 추가
        pass
    
    def _load_initial_previews(self):
        """초기 미리보기 로드"""
        if os.path.exists(self.real_path):
            # 배경 이미지 찾기
            real_bg_path = self.real_path.replace(".jpg", "_bg.jpg")
            if os.path.exists(real_bg_path):
                print(f"   [OK] 배경 이미지 발견: {real_bg_path}")
                self.clean_real_bg = Image.open(real_bg_path).copy()
            else:
                print(f"   [INFO] 배경 이미지 없음, 원본 사용")
                self.clean_real_bg = None
            
            real_img = Image.open(self.real_path)
            self.base_real_img = real_img.copy()
            real_resized = real_img.resize((640, 360), Image.LANCZOS)
            self.real_photo = ctk.CTkImage(real_resized, real_resized, size=(640, 360))
            self.real_preview.configure(image=self.real_photo)
        
        if os.path.exists(self.art_path):
            # 배경 이미지 찾기
            art_bg_path = self.art_path.replace(".jpg", "_bg.jpg")
            if os.path.exists(art_bg_path):
                print(f"   [OK] 배경 이미지 발견: {art_bg_path}")
                self.clean_art_bg = Image.open(art_bg_path).copy()
            else:
                print(f"   [INFO] 배경 이미지 없음, 원본 사용")
                self.clean_art_bg = None
            
            art_img = Image.open(self.art_path)
            self.base_art_img = art_img.copy()
            art_resized = art_img.resize((640, 360), Image.LANCZOS)
            self.art_photo = ctk.CTkImage(art_resized, art_resized, size=(640, 360))
            self.art_preview.configure(image=self.art_photo)
    
    def _on_target_change(self):
        """조정 대상 변경"""
        self.current_target = self.target_var.get()
        # UI 업데이트 필요 시 여기서 처리
    
    def _on_content_change(self, text_type: str, content: str):
        """텍스트 내용 변경"""
        settings = self.real_settings if self.current_target == "REAL" else self.art_settings
        settings[text_type]["content"] = content

        # 동시 편집 모드
        if self.sync_edit_mode:
            other_settings = self.art_settings if self.current_target == "REAL" else self.real_settings
            other_settings[text_type]["content"] = content

        # 미리보기 업데이트 (디바운싱)
        self._schedule_preview_update()

    def _on_slider_change(self, text_type: str, param: str, value):
        """슬라이더 값 변경"""
        settings = self.real_settings if self.current_target == "REAL" else self.art_settings
        settings[text_type][param] = value

        # 동시 편집 모드
        if self.sync_edit_mode:
            other_settings = self.art_settings if self.current_target == "REAL" else self.real_settings
            other_settings[text_type][param] = value

        # 미리보기 업데이트 (디바운싱)
        self._schedule_preview_update()
    
    def _on_brightness_change(self, value: float):
        """배경 어둡기 변경"""
        settings = self.real_settings if self.current_target == "REAL" else self.art_settings
        settings["background"]["brightness"] = value
        # 미리보기 즉시 업데이트
        self._update_preview()
    
    def _set_color(self, text_type: str, color_key: str, hex_color: str):
        """색상 설정"""
        settings = self.real_settings if self.current_target == "REAL" else self.art_settings
        settings[text_type][color_key] = hex_color

        # 동시 편집 모드
        if self.sync_edit_mode:
            other_settings = self.art_settings if self.current_target == "REAL" else self.real_settings
            other_settings[text_type][color_key] = hex_color

        # 히스토리 저장
        self._save_history()

        # 미리보기 업데이트
        if self.sync_edit_mode:
            self._update_both_previews()
        else:
            self._update_preview()
    
    def _open_color_picker(self, text_type: str, color_key: str):
        """색상 선택기 팝업"""
        settings = self.real_settings if self.current_target == "REAL" else self.art_settings
        current_color = settings[text_type][color_key]
        
        color = colorchooser.askcolor(title="색상 선택", initialcolor=current_color)
        
        if color and color[1]:
            self._set_color(text_type, color_key, color[1])
    
    def _update_preview(self):
        """미리보기 즉시 업데이트 (재생성 없이)"""
        # 동시 편집 모드면 둘 다 업데이트
        if self.sync_edit_mode:
            self._update_both_previews()
            return

        target = self.current_target
        settings = self.real_settings if target == "REAL" else self.art_settings

        # 깨끗한 배경 이미지 사용
        if target == "REAL":
            if self.clean_real_bg is None:
                # 배경 이미지 없으면 원본에서 텍스트 영역 지우기
                if self.base_real_img:
                    self.clean_real_bg = self._extract_background(self.base_real_img)
            base_img = self.clean_real_bg
        else:
            if self.clean_art_bg is None:
                if self.base_art_img:
                    self.clean_art_bg = self._extract_background(self.base_art_img)
            base_img = self.clean_art_bg

        if base_img is None:
            return

        # 임시 썸네일 생성
        preview_img = self._generate_thumbnail(base_img.copy(), settings)

        # 줌 적용
        base_w, base_h = 640, 360
        new_w = int(base_w * self.zoom_level)
        new_h = int(base_h * self.zoom_level)
        preview_resized = preview_img.resize((new_w, new_h), Image.LANCZOS)

        if target == "REAL":
            self.real_photo = ctk.CTkImage(preview_resized, preview_resized, size=(new_w, new_h))
            self.real_preview.configure(image=self.real_photo)
        else:
            self.art_photo = ctk.CTkImage(preview_resized, preview_resized, size=(new_w, new_h))
            self.art_preview.configure(image=self.art_photo)
    
    def _extract_background(self, img: Image.Image) -> Image.Image:
        """배경만 추출 (텍스트 영역을 검은색으로 덮어씌움)
        
        기존 썸네일 이미지의 텍스트 영역을 지우고 깨끗한 배경 반환
        """
        # 원본 이미지 복사
        clean_img = img.copy()
        
        # 텍스트 영역을 검은 사각형으로 덮기
        from PIL import ImageDraw
        draw = ImageDraw.Draw(clean_img)
        
        # 상단 텍스트 영역 (대략적인 위치)
        draw.rectangle([(0, 0), (1280, 150)], fill="black")
        
        # 중앙 텍스트 영역 (대략적인 위치)  
        draw.rectangle([(0, 150), (1280, 550)], fill="black")
        
        return clean_img

    def _generate_thumbnail(self, img: Image.Image, settings: dict) -> Image.Image:
        """썸네일 생성 (텍스트 오버레이만)"""
        W, H = 1280, 720
        
        # 배경 어둡기 제거 - 원본 이미지 그대로 사용
        # 텍스트만 오버레이
        
        # 상단 텍스트 그리기
        img = self._draw_text_with_effects(
            img,
            settings["top_text"]["content"],
            settings["top_text"]["x"],
            settings["top_text"]["y"],
            settings["top_text"]["font_size"],
            settings["top_text"]["text_color"],
            settings["top_text"]["stroke_width"],
            settings["top_text"]["stroke_color"],
            settings["top_text"]["shadow_range"],
            settings["top_text"]["shadow_opacity"],
            settings["top_text"]["shadow_color"]
        )
        
        # 메인 제목 그리기 (줄바꿈 적용)
        main_text = settings["main_text"]["content"]
        wrap_width = settings["main_text"]["wrap_width"]
        main_lines = textwrap.wrap(main_text, width=wrap_width) if main_text else [main_text]
        
        curr_y = settings["main_text"]["y"]
        font_size = settings["main_text"]["font_size"]
        
        for line in main_lines:
            img = self._draw_text_with_effects(
                img,
                line,
                settings["main_text"]["x"],
                curr_y,
                font_size,
                settings["main_text"]["text_color"],
                settings["main_text"]["stroke_width"],
                settings["main_text"]["stroke_color"],
                settings["main_text"]["shadow_range"],
                settings["main_text"]["shadow_opacity"],
                settings["main_text"]["shadow_color"]
            )
            curr_y += font_size + 20
        
        return img
    
    def _draw_text_with_effects(
        self,
        img: Image.Image,
        text: str,
        x: int,
        y: int,
        font_size: int,
        text_color: str,
        stroke_width: int,
        stroke_color: str,
        shadow_range: int,
        shadow_opacity: float,
        shadow_color: str
    ) -> Image.Image:
        """텍스트 그리기 (외곽선 + 그림자)"""
        if not text:
            return img
        
        # 이모지/특수문자 제거
        import re
        text = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', text)
        
        if not text:  # 제거 후 빈 문자열이면 리턴
            return img
        
        # RGBA 변환
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype(self.font_path, font_size)
        except Exception:
            if DEFAULT_FONT:
                font = ImageFont.truetype(DEFAULT_FONT, font_size)
            else:
                font = ImageFont.load_default()
        
        # 텍스트 크기 측정
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        
        # X축: 중심 기준으로 조정
        text_x = x - (text_w // 2)
        
        # 1. 그림자 그리기
        if shadow_range > 0:
            shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            
            # 그림자 색상 + 투명도
            try:
                r, g, b = ImageColor.getrgb(shadow_color)
                shadow_rgba = (r, g, b, int(255 * shadow_opacity))
            except Exception:
                shadow_rgba = (0, 0, 0, int(255 * shadow_opacity))
            
            # 그림자 범위만큼 여러 번 그리기
            for offset_x in range(-shadow_range, shadow_range + 1):
                for offset_y in range(-shadow_range, shadow_range + 1):
                    shadow_draw.text(
                        (text_x + offset_x, y + offset_y),
                        text,
                        font=font,
                        fill=shadow_rgba
                    )
            
            # 합성
            img = Image.alpha_composite(img, shadow_layer)
            draw = ImageDraw.Draw(img)
        
        # 2. 본문 + 외곽선
        draw.text(
            (text_x, y),
            text,
            font=font,
            fill=text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color
        )
        
        return img.convert("RGB")
    
    def _on_regenerate(self):
        """조정 후 재생성 버튼 클릭"""
        # print 대신 로깅 사용 (cp949 인코딩 에러 방지)

        target = self.current_target
        settings = self.real_settings if target == "REAL" else self.art_settings
        base_img = self.base_real_img if target == "REAL" else self.base_art_img

        if base_img is None:
            return
        
        # 새 썸네일 생성
        new_img = self._generate_thumbnail(base_img.copy(), settings)
        
        # 저장 및 미리보기 업데이트
        if target == "REAL":
            new_img.save(self.real_path, quality=95)
            new_resized = new_img.resize((640, 360), Image.LANCZOS)
            self.real_photo = ctk.CTkImage(new_resized, new_resized, size=(640, 360))
            self.real_preview.configure(image=self.real_photo)
            self.base_real_img = new_img  # 기본 이미지 업데이트
        else:
            new_img.save(self.art_path, quality=95)
            new_resized = new_img.resize((640, 360), Image.LANCZOS)
            self.art_photo = ctk.CTkImage(new_resized, new_resized, size=(640, 360))
            self.art_preview.configure(image=self.art_photo)
            self.base_art_img = new_img  # 기본 이미지 업데이트
    
    def _on_cancel(self):
        """취소 버튼 클릭"""
        self.user_choice = "cancel"
        self.destroy()
    
    def _on_proceed(self):
        """확정 버튼 클릭"""
        self.user_choice = "proceed"
        self.destroy()
    
    def get_choice(self) -> str:
        """사용자 선택 반환"""
        self.wait_window()
        return self.user_choice if self.user_choice else "cancel"

    # ============================================================
    # 히스토리 (실행취소/재실행)
    # ============================================================
    def _save_history(self):
        """현재 상태를 히스토리에 저장"""
        # 현재 위치 이후의 히스토리 삭제
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]

        # 상태 저장
        state = {
            "real_settings": copy.deepcopy(self.real_settings),
            "art_settings": copy.deepcopy(self.art_settings)
        }
        self.history.append(state)

        # 최대 히스토리 수 제한
        if len(self.history) > self.max_history:
            self.history.pop(0)
        else:
            self.history_index += 1

        self._update_history_buttons()

    def _undo(self):
        """실행취소"""
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_state(self.history[self.history_index])
            self._update_history_buttons()
            self._update_both_previews()

    def _redo(self):
        """재실행"""
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._restore_state(self.history[self.history_index])
            self._update_history_buttons()
            self._update_both_previews()

    def _restore_state(self, state: dict):
        """상태 복원"""
        self.real_settings = copy.deepcopy(state["real_settings"])
        self.art_settings = copy.deepcopy(state["art_settings"])

    def _update_history_buttons(self):
        """히스토리 버튼 상태 업데이트"""
        if hasattr(self, 'undo_btn'):
            if self.history_index > 0:
                self.undo_btn.configure(state="normal", fg_color="gray40")
            else:
                self.undo_btn.configure(state="disabled", fg_color="gray60")

        if hasattr(self, 'redo_btn'):
            if self.history_index < len(self.history) - 1:
                self.redo_btn.configure(state="normal", fg_color="gray40")
            else:
                self.redo_btn.configure(state="disabled", fg_color="gray60")

    # ============================================================
    # 줌 기능
    # ============================================================
    def _zoom_in(self):
        """줌 인"""
        if self.zoom_index < len(self.ZOOM_LEVELS) - 1:
            self.zoom_index += 1
            self.zoom_level = self.ZOOM_LEVELS[self.zoom_index]
            self._update_zoom_label()
            self._update_both_previews()

    def _zoom_out(self):
        """줌 아웃"""
        if self.zoom_index > 0:
            self.zoom_index -= 1
            self.zoom_level = self.ZOOM_LEVELS[self.zoom_index]
            self._update_zoom_label()
            self._update_both_previews()

    def _zoom_reset(self):
        """줌 리셋 (100%)"""
        self.zoom_index = 2
        self.zoom_level = 1.0
        self._update_zoom_label()
        self._update_both_previews()

    def _update_zoom_label(self):
        """줌 레벨 표시 업데이트"""
        if hasattr(self, 'zoom_label'):
            self.zoom_label.configure(text=f"{int(self.zoom_level * 100)}%")

    def _update_both_previews(self):
        """REAL과 ART 미리보기 모두 업데이트"""
        # REAL 업데이트
        if self.clean_real_bg is not None or self.base_real_img is not None:
            bg = self.clean_real_bg if self.clean_real_bg else self.base_real_img
            if bg:
                preview_img = self._generate_thumbnail(bg.copy(), self.real_settings)
                base_w, base_h = 640, 360
                new_w = int(base_w * self.zoom_level)
                new_h = int(base_h * self.zoom_level)
                preview_resized = preview_img.resize((new_w, new_h), Image.LANCZOS)
                self.real_photo = ctk.CTkImage(preview_resized, preview_resized, size=(new_w, new_h))
                self.real_preview.configure(image=self.real_photo)

        # ART 업데이트
        if self.clean_art_bg is not None or self.base_art_img is not None:
            bg = self.clean_art_bg if self.clean_art_bg else self.base_art_img
            if bg:
                preview_img = self._generate_thumbnail(bg.copy(), self.art_settings)
                base_w, base_h = 640, 360
                new_w = int(base_w * self.zoom_level)
                new_h = int(base_h * self.zoom_level)
                preview_resized = preview_img.resize((new_w, new_h), Image.LANCZOS)
                self.art_photo = ctk.CTkImage(preview_resized, preview_resized, size=(new_w, new_h))
                self.art_preview.configure(image=self.art_photo)

    # ============================================================
    # 동시 편집 모드
    # ============================================================
    def _on_sync_mode_change(self):
        """동시 편집 모드 변경"""
        self.sync_edit_mode = self.sync_var.get()

    # ============================================================
    # 프리셋 저장/불러오기
    # ============================================================
    def _get_presets(self) -> dict:
        """저장된 프리셋 목록 가져오기"""
        if os.path.exists(self.preset_path):
            try:
                with open(self.preset_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"프리셋 JSON 로드 실패: {e}")
        return {}

    def _save_presets(self, presets: dict):
        """프리셋 저장"""
        os.makedirs(os.path.dirname(self.preset_path), exist_ok=True)
        with open(self.preset_path, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)

    def _save_preset_dialog(self):
        """프리셋 저장 다이얼로그"""
        dialog = ctk.CTkInputDialog(
            text="프리셋 이름을 입력하세요:",
            title="프리셋 저장"
        )
        name = dialog.get_input()

        if name:
            presets = self._get_presets()
            presets[name] = {
                "real_settings": copy.deepcopy(self.real_settings),
                "art_settings": copy.deepcopy(self.art_settings)
            }
            self._save_presets(presets)
            from tkinter import messagebox
            messagebox.showinfo("저장 완료", f"프리셋 '{name}'이(가) 저장되었습니다.")

    def _load_preset_dialog(self):
        """프리셋 불러오기 다이얼로그"""
        presets = self._get_presets()

        if not presets:
            from tkinter import messagebox
            messagebox.showinfo("프리셋 없음", "저장된 프리셋이 없습니다.")
            return

        # 프리셋 선택 다이얼로그
        preset_window = ctk.CTkToplevel(self)
        preset_window.title("프리셋 불러오기")
        preset_window.geometry("400x350")
        preset_window.transient(self)
        preset_window.grab_set()

        # 중앙 배치
        preset_window.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 350) // 2
        preset_window.geometry(f"400x350+{x}+{y}")

        ctk.CTkLabel(
            preset_window,
            text="프리셋 선택",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(15, 10))

        # 프리셋 리스트
        list_frame = ctk.CTkScrollableFrame(preset_window, height=200)
        list_frame.pack(fill="x", padx=20, pady=10)

        selected_preset = ctk.StringVar(value="")

        for name in presets.keys():
            btn = ctk.CTkRadioButton(
                list_frame,
                text=name,
                variable=selected_preset,
                value=name,
                font=ctk.CTkFont(size=13)
            )
            btn.pack(anchor="w", pady=3)

        def apply_preset():
            name = selected_preset.get()
            if name and name in presets:
                self.real_settings = copy.deepcopy(presets[name]["real_settings"])
                self.art_settings = copy.deepcopy(presets[name]["art_settings"])
                self._save_history()
                self._update_both_previews()
                preset_window.destroy()

        def delete_preset():
            name = selected_preset.get()
            if name and name in presets:
                from tkinter import messagebox
                if messagebox.askyesno("삭제 확인", f"프리셋 '{name}'을(를) 삭제하시겠습니까?"):
                    del presets[name]
                    self._save_presets(presets)
                    preset_window.destroy()
                    self._load_preset_dialog()

        # 버튼
        btn_frame = ctk.CTkFrame(preset_window, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(
            btn_frame,
            text="적용",
            width=100,
            command=apply_preset
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="삭제",
            width=100,
            fg_color="red",
            hover_color="darkred",
            command=delete_preset
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="gray",
            command=preset_window.destroy
        ).pack(side="right", padx=5)

    # ============================================================
    # 지연된 미리보기 업데이트 (성능 최적화)
    # ============================================================
    def _schedule_preview_update(self):
        """미리보기 업데이트 예약 (디바운싱)"""
        if not self._preview_update_pending:
            self._preview_update_pending = True
            self.after(self._preview_update_delay, self._execute_preview_update)

    def _execute_preview_update(self):
        """예약된 미리보기 업데이트 실행"""
        self._preview_update_pending = False
        self._update_preview()
