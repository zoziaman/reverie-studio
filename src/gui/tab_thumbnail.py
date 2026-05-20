# src/gui/tab_thumbnail.py
"""
썸네일 설정 탭
- 실시간 미리보기 (1280x720)
- 상단 텍스트 / 메인 제목 위치 조정
- 폰트 크기 / 색상 / 어둡기 조정
"""
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import textwrap
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# 크로스 플랫폼 폰트
try:
    from utils.font_helper import KOREAN_FONT_BOLD
    DEFAULT_FONT = KOREAN_FONT_BOLD
except ImportError:
    DEFAULT_FONT = None

# 채널 옵션 로드 유틸리티
def _load_channel_options_for_settings() -> List[Tuple[str, str, str, str]]:
    """
    설정 탭용 채널 옵션 로드
    Returns: [(display_name, channel_id, mode, channel_type), ...]
    """
    options = [
        ("🎬 일상 영상툰", "daily_life_toon", "daily_life_toon", "daily_life_toon"),
        ("🔎 미스터리 영상툰", "mystery_toon", "mystery_toon", "mystery_toon"),
    ]

    # 설치된 패키지 추가
    try:
        from config.settings import config
        from utils.package_manager import get_package_manager
        pm = get_package_manager()
        installed = pm.list_installed_packages()

        for pkg_id, pkg_info in installed.items():
            # 기본 채널과 중복 방지
            if pkg_id not in ['daily_life_toon', 'mystery_toon']:
                pkg_name = pkg_info.get('package_name', pkg_id)
                channel_type = pkg_info.get('channel_type', pkg_id)

                # channel_type 파싱
                if "_" in channel_type:
                    parts = channel_type.split("_", 1)
                    channel, mode = parts[0], parts[1]
                else:
                    channel, mode = channel_type, channel_type

                display = f"📦 {pkg_name}"
                options.append((display, channel, mode, pkg_id))
    except Exception as e:
        logger.warning(f"채널 옵션 로딩 실패: {e}")

    return options


class ThumbnailSettingsTab:
    """
    썸네일 설정 탭
    """
    
    def __init__(self, parent_frame, settings_manager, font_path: str):
        self.parent = parent_frame
        self.settings_manager = settings_manager
        self.font_path = font_path
        
        # 현재 채널/모드
        self.current_channel = "daily_life_toon"
        self.current_mode = "daily_life_toon"
        
        # 현재 설정값
        self.current_settings = self.settings_manager.get_thumbnail_settings("daily_life_toon", "daily_life_toon")
        
        self._create_ui()
        self._update_preview()
    
    def _create_ui(self):
        """UI 구성"""
        # 좌우 분할
        left_frame = ctk.CTkFrame(self.parent)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # 오른쪽을 스크롤 가능하게
        right_container = ctk.CTkFrame(self.parent)
        right_container.pack(side="right", fill="both", expand=True, padx=(5, 0))
        right_frame = ctk.CTkScrollableFrame(right_container)
        right_frame.pack(fill="both", expand=True)
        
        # === 왼쪽: 미리보기 ===
        preview_label = ctk.CTkLabel(
            left_frame,
            text="🖼️ 썸네일 미리보기 (1280x720)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        preview_label.pack(pady=(10, 10))
        
        # 캔버스
        self.preview_canvas = ctk.CTkLabel(left_frame, text="")
        self.preview_canvas.pack(padx=20, pady=10)
        
        # 샘플 텍스트 입력
        sample_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        sample_frame.pack(fill="x", padx=20, pady=10)
        
        top_label = ctk.CTkLabel(sample_frame, text="상단 텍스트:", font=ctk.CTkFont(size=12))
        top_label.pack(anchor="w", pady=(0, 5))
        
        self.top_text_var = ctk.StringVar(value="실화 공포")
        top_entry = ctk.CTkEntry(
            sample_frame,
            textvariable=self.top_text_var,
            width=300
        )
        top_entry.pack(anchor="w", pady=(0, 10))
        top_entry.bind("<KeyRelease>", lambda e: self._update_preview())
        
        main_label = ctk.CTkLabel(sample_frame, text="메인 제목:", font=ctk.CTkFont(size=12))
        main_label.pack(anchor="w", pady=(0, 5))
        
        self.main_text_var = ctk.StringVar(value="충격적인 결말")
        main_entry = ctk.CTkEntry(
            sample_frame,
            textvariable=self.main_text_var,
            width=300
        )
        main_entry.pack(anchor="w")
        main_entry.bind("<KeyRelease>", lambda e: self._update_preview())
        
        # === 오른쪽: 조정 컨트롤 ===
        control_label = ctk.CTkLabel(
            right_frame,
            text="⚙️ 썸네일 설정",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        control_label.pack(pady=(10, 20))
        
        # 채널 선택 (동적 로드)
        channel_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        channel_frame.pack(fill="x", padx=20, pady=(0, 15))

        channel_label = ctk.CTkLabel(channel_frame, text="채널:", font=ctk.CTkFont(size=13))
        channel_label.pack(side="left", padx=(0, 10))

        # 동적 채널 목록 로드
        self.channel_options_list = _load_channel_options_for_settings()
        channel_display_names = [opt[0] for opt in self.channel_options_list]

        self.channel_option = ctk.CTkOptionMenu(
            channel_frame,
            values=channel_display_names,
            command=self._on_channel_change,
            width=180
        )
        self.channel_option.set(channel_display_names[0] if channel_display_names else "👻 공포")
        self.channel_option.pack(side="left")
        
        # 스크롤 가능한 설정 영역
        scrollable_frame = ctk.CTkScrollableFrame(right_frame, height=500)
        scrollable_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        # === 상단 텍스트 설정 ===
        self._create_text_controls(scrollable_frame, "상단 텍스트 (노란색)", "top_text")
        
        # === 메인 제목 설정 ===
        self._create_text_controls(scrollable_frame, "메인 제목 (빨간색)", "main_title")
        
        # === 배경 설정 ===
        bg_section = ctk.CTkFrame(scrollable_frame)
        bg_section.pack(fill="x", pady=(0, 20))
        
        bg_label = ctk.CTkLabel(
            bg_section,
            text="배경 설정",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        bg_label.pack(anchor="w", padx=10, pady=(10, 10))
        
        # 어둡기
        bright_label = ctk.CTkLabel(bg_section, text="배경 어둡기:", font=ctk.CTkFont(size=12))
        bright_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        bright_frame = ctk.CTkFrame(bg_section, fg_color="transparent")
        bright_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_brightness = self.current_settings.get("brightness", 0.4) * 100
        
        bright_slider = ctk.CTkSlider(
            bright_frame,
            from_=0,
            to=100,
            number_of_steps=100,
            command=lambda v: self._on_brightness_change(v, bright_value_label)
        )
        bright_slider.set(default_brightness)
        bright_slider.pack(side="left", fill="x", expand=True)
        
        bright_value_label = ctk.CTkLabel(bright_frame, text=f"{int(default_brightness)}%", width=50)
        bright_value_label.pack(side="left", padx=(10, 0))
        
        # ==================== 스타일 프리셋 ====================
        preset_section = ctk.CTkFrame(scrollable_frame)
        preset_section.pack(fill="x", pady=(0, 20))

        preset_label = ctk.CTkLabel(
            preset_section,
            text="🎨 스타일 프리셋",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        preset_label.pack(anchor="w", padx=10, pady=(10, 10))

        # 프리셋 선택 드롭다운
        preset_frame = ctk.CTkFrame(preset_section, fg_color="transparent")
        preset_frame.pack(fill="x", padx=20, pady=5)

        self.preset_var = ctk.StringVar(value="사용자 정의")
        self.preset_dropdown = ctk.CTkOptionMenu(
            preset_frame,
            variable=self.preset_var,
            values=self._get_preset_names(),
            command=self._on_preset_select,
            width=200
        )
        self.preset_dropdown.pack(side="left", padx=(0, 10))

        # 프리셋 저장 버튼
        save_preset_btn = ctk.CTkButton(
            preset_frame,
            text="💾 프리셋 저장",
            width=100,
            command=self._save_preset
        )
        save_preset_btn.pack(side="left", padx=5)

        # 프리셋 삭제 버튼
        delete_preset_btn = ctk.CTkButton(
            preset_frame,
            text="🗑️ 삭제",
            width=80,
            fg_color="gray",
            hover_color="darkgray",
            command=self._delete_preset
        )
        delete_preset_btn.pack(side="left", padx=5)

        # 버튼 영역
        button_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=20, pady=10)

        reset_btn = ctk.CTkButton(
            button_frame,
            text="🔄 기본값 복원",
            width=120,
            command=self._reset_to_default
        )
        reset_btn.pack(side="left", padx=5)

        save_btn = ctk.CTkButton(
            button_frame,
            text="💾 저장",
            width=120,
            fg_color="green",
            hover_color="darkgreen",
            command=self._save_settings
        )
        save_btn.pack(side="left", padx=5)
    
    def _create_text_controls(self, parent, title: str, text_type: str):
        """텍스트 설정 컨트롤"""
        section_frame = ctk.CTkFrame(parent)
        section_frame.pack(fill="x", pady=(0, 20))
        
        # 제목
        title_label = ctk.CTkLabel(
            section_frame,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        title_label.pack(anchor="w", padx=10, pady=(10, 10))
        
        settings = self.current_settings.get(text_type, {})
        
        # X축 위치
        x_label = ctk.CTkLabel(section_frame, text="X축 위치 (px):", font=ctk.CTkFont(size=12))
        x_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        x_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        x_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_x = settings.get("x", 640)  # 기본값: 중앙 (1280/2)
        
        x_slider = ctk.CTkSlider(
            x_frame,
            from_=0,
            to=1280,
            number_of_steps=128,
            command=lambda v: self._on_slider_change(text_type, "x", int(v), x_value_label)
        )
        x_slider.set(default_x)
        x_slider.pack(side="left", fill="x", expand=True)
        
        x_value_label = ctk.CTkLabel(x_frame, text=f"{default_x}px", width=50)
        x_value_label.pack(side="left", padx=(10, 0))
        
        # Y축 위치
        y_label = ctk.CTkLabel(section_frame, text="Y축 위치 (px):", font=ctk.CTkFont(size=12))
        y_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        y_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        y_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_y = settings.get("y", 80)
        
        y_slider = ctk.CTkSlider(
            y_frame,
            from_=0,
            to=500,
            number_of_steps=500,
            command=lambda v: self._on_slider_change(text_type, "y", int(v), y_value_label)
        )
        y_slider.set(default_y)
        y_slider.pack(side="left", fill="x", expand=True)
        
        y_value_label = ctk.CTkLabel(y_frame, text=f"{default_y}px", width=50)
        y_value_label.pack(side="left", padx=(10, 0))
        
        # 폰트 크기
        font_label = ctk.CTkLabel(section_frame, text="폰트 크기 (px):", font=ctk.CTkFont(size=12))
        font_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        font_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        font_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_font = settings.get("font_size", 70)
        
        font_slider = ctk.CTkSlider(
            font_frame,
            from_=30,
            to=200,
            number_of_steps=170,
            command=lambda v: self._on_slider_change(text_type, "font_size", int(v), font_value_label)
        )
        font_slider.set(default_font)
        font_slider.pack(side="left", fill="x", expand=True)
        
        font_value_label = ctk.CTkLabel(font_frame, text=f"{default_font}px", width=50)
        font_value_label.pack(side="left", padx=(10, 0))
        
        # 줄바꿈 (메인 제목만)
        if text_type == "main_title":
            wrap_label = ctk.CTkLabel(section_frame, text="줄바꿈 기준 (글자 수):", font=ctk.CTkFont(size=12))
            wrap_label.pack(anchor="w", padx=20, pady=(5, 0))
            
            wrap_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
            wrap_frame.pack(fill="x", padx=20, pady=(0, 10))
            
            default_wrap = settings.get("wrap_width", 10)
            
            wrap_slider = ctk.CTkSlider(
                wrap_frame,
                from_=5,
                to=20,
                number_of_steps=15,
                command=lambda v: self._on_slider_change(text_type, "wrap_width", int(v), wrap_value_label)
            )
            wrap_slider.set(default_wrap)
            wrap_slider.pack(side="left", fill="x", expand=True)
            
            wrap_value_label = ctk.CTkLabel(wrap_frame, text=f"{default_wrap}자", width=50)
            wrap_value_label.pack(side="left", padx=(10, 0))
        
        # 색상 (읽기 전용)
        color_label = ctk.CTkLabel(
            section_frame,
            text=f"색상: {settings.get('color', '#FFFFFF')}",
            font=ctk.CTkFont(size=12)
        )
        color_label.pack(anchor="w", padx=20, pady=(5, 10))
    
    def _on_slider_change(self, text_type: str, param: str, value, label_widget):
        """슬라이더 값 변경 시"""
        if text_type not in self.current_settings:
            self.current_settings[text_type] = {}
        
        self.current_settings[text_type][param] = value
        
        # 라벨 업데이트
        if param == "wrap_width":
            label_widget.configure(text=f"{value}자")
        else:
            label_widget.configure(text=f"{value}px")
        
        # 미리보기 업데이트
        self._update_preview()
    
    def _on_brightness_change(self, value, label_widget):
        """어둡기 변경 시"""
        self.current_settings["brightness"] = value / 100.0
        label_widget.configure(text=f"{int(value)}%")
        self._update_preview()
    
    def _on_channel_change(self, choice: str):
        """채널 변경 시 (동적 채널 지원)"""
        # 동적 채널 목록에서 찾기
        for display, channel, mode, channel_type in self.channel_options_list:
            if display == choice:
                self.current_channel = channel
                self.current_mode = mode
                break
        else:
            # 폴백: 기존 하드코딩 방식
            if "공포" in choice:
                self.current_channel = "mystery_toon"
                self.current_mode = "mystery_toon"
            elif "감동" in choice:
                self.current_channel = "daily_life_toon"
                self.current_mode = "daily_life_toon"
            else:
                self.current_channel = "daily_life_toon"
                self.current_mode = "daily_life_toon"

        self.current_settings = self.settings_manager.get_thumbnail_settings(
            self.current_channel,
            self.current_mode
        )

        self._update_preview()
    
    def _update_preview(self):
        """미리보기 업데이트"""
        W, H = 1280, 720
        
        # 배경 이미지 (어두운 그라데이션)
        img = Image.new("RGB", (W, H), (30, 30, 35))
        
        # 어둡기 적용
        brightness = self.current_settings.get("brightness", 0.4)
        img = ImageEnhance.Brightness(img).enhance(brightness)
        
        draw = ImageDraw.Draw(img)
        
        # 상단 텍스트 설정
        top_settings = self.current_settings.get("top_text", {})
        top_x = top_settings.get("x", 640)  # 기본값: 중앙
        top_y = top_settings.get("y", 80)
        top_font_size = top_settings.get("font_size", 70)
        top_color = top_settings.get("color", "#FFD700")
        
        # 메인 제목 설정
        main_settings = self.current_settings.get("main_title", {})
        main_x = main_settings.get("x", 640)  # 기본값: 중앙
        main_y = main_settings.get("y", 200)
        main_font_size = main_settings.get("font_size", 130)
        main_color = main_settings.get("color", "#FF0000")
        main_wrap = main_settings.get("wrap_width", 10)
        
        # 폰트 로드
        try:
            font_top = ImageFont.truetype(self.font_path, top_font_size)
            font_main = ImageFont.truetype(self.font_path, main_font_size)
        except Exception:
            if DEFAULT_FONT:
                font_top = ImageFont.truetype(DEFAULT_FONT, top_font_size)
                font_main = ImageFont.truetype(DEFAULT_FONT, main_font_size)
            else:
                font_top = ImageFont.load_default()
                font_main = ImageFont.load_default()
        
        # 상단 텍스트 그리기
        top_text = self.top_text_var.get()
        
        # 이모지/특수문자 제거
        import re
        top_text = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', top_text)
        
        if top_text:  # 빈 문자열이 아닐 때만 그리기
            top_bbox = draw.textbbox((0, 0), top_text, font=font_top)
            top_w = top_bbox[2] - top_bbox[0]
            
            # X축: 사용자 설정값 중심으로 텍스트 배치
            top_x_pos = top_x - (top_w / 2)
            
            draw.text(
                (top_x_pos, top_y),
                top_text,
                fill=top_color,
                font=font_top,
                stroke_width=4,
                stroke_fill="black"
            )
        
        # 메인 제목 그리기 (줄바꿈 적용)
        main_text = self.main_text_var.get()
        
        # 이모지/특수문자 제거
        main_text = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', main_text)
        
        # 줄바꿈 (이모지 제거 후)
        main_lines = textwrap.wrap(main_text, width=main_wrap) if main_text else []
        
        curr_y = main_y
        for line in main_lines:
            line_bbox = draw.textbbox((0, 0), line, font=font_main)
            line_w = line_bbox[2] - line_bbox[0]
            
            # X축: 사용자 설정값 중심으로 텍스트 배치
            line_x_pos = main_x - (line_w / 2)
            
            draw.text(
                (line_x_pos, curr_y),
                line,
                fill=main_color,
                font=font_main,
                stroke_width=8,
                stroke_fill="black"
            )
            curr_y += main_font_size + 20
        
        # 미리보기 이미지로 변환 (640x360)
        img_resized = img.resize((640, 360), Image.LANCZOS)
        
        # CTkImage로 변환
        self.preview_image = ctk.CTkImage(
            light_image=img_resized,
            dark_image=img_resized,
            size=(640, 360)
        )
        
        # 캔버스에 표시
        self.preview_canvas.configure(image=self.preview_image)
    
    def _reset_to_default(self):
        """기본값 복원"""
        from tkinter import messagebox
        if messagebox.askyesno("확인", "모든 썸네일 설정을 기본값으로 복원하시겠습니까?"):
            self.settings_manager.reset_to_default()
            self.current_settings = self.settings_manager.get_thumbnail_settings(
                self.current_channel,
                self.current_mode
            )
            messagebox.showinfo("완료", "기본값으로 복원되었습니다.\n페이지를 다시 열어주세요.")
    
    def _save_settings(self):
        """설정 저장"""
        self.settings_manager.set_thumbnail_settings(
            self.current_channel,
            self.current_mode,
            self.current_settings
        )

        from tkinter import messagebox
        messagebox.showinfo("저장 완료", "썸네일 설정이 저장되었습니다.")

    def _get_preset_names(self) -> list:
        """프리셋 이름 목록 반환"""
        presets = self.settings_manager.get_thumbnail_presets()
        names = ["사용자 정의"] + list(presets.keys())

        # 기본 프리셋 추가
        default_presets = ["공포 기본", "감동 기본", "막장 기본", "밝은 스타일", "어두운 스타일"]
        for dp in default_presets:
            if dp not in names:
                names.append(dp)

        return names

    def _on_preset_select(self, choice: str):
        """프리셋 선택 시"""
        if choice == "사용자 정의":
            return

        from tkinter import messagebox

        # 기본 프리셋 정의
        default_presets = {
            "공포 기본": {
                "top_text": {"x": 640, "y": 80, "font_size": 70, "color": "#FFD700"},
                "main_title": {"x": 640, "y": 200, "font_size": 130, "color": "#FF0000", "wrap_width": 10},
                "brightness": 0.3
            },
            "감동 기본": {
                "top_text": {"x": 640, "y": 80, "font_size": 65, "color": "#FFEB3B"},
                "main_title": {"x": 640, "y": 220, "font_size": 120, "color": "#4CAF50", "wrap_width": 12},
                "brightness": 0.5
            },
            "막장 기본": {
                "top_text": {"x": 640, "y": 60, "font_size": 75, "color": "#FF5722"},
                "main_title": {"x": 640, "y": 180, "font_size": 140, "color": "#E91E63", "wrap_width": 8},
                "brightness": 0.35
            },
            "밝은 스타일": {
                "top_text": {"x": 640, "y": 100, "font_size": 60, "color": "#2196F3"},
                "main_title": {"x": 640, "y": 250, "font_size": 110, "color": "#FFFFFF", "wrap_width": 12},
                "brightness": 0.7
            },
            "어두운 스타일": {
                "top_text": {"x": 640, "y": 80, "font_size": 70, "color": "#B0BEC5"},
                "main_title": {"x": 640, "y": 200, "font_size": 130, "color": "#9E9E9E", "wrap_width": 10},
                "brightness": 0.2
            }
        }

        # 사용자 저장 프리셋 또는 기본 프리셋
        presets = self.settings_manager.get_thumbnail_presets()

        if choice in presets:
            preset_data = presets[choice]
        elif choice in default_presets:
            preset_data = default_presets[choice]
        else:
            messagebox.showwarning("알림", f"프리셋 '{choice}'을 찾을 수 없습니다.")
            return

        # 현재 설정에 적용
        self.current_settings.update(preset_data)
        self._update_preview()
        messagebox.showinfo("프리셋 적용", f"'{choice}' 프리셋이 적용되었습니다.\n저장하려면 '저장' 버튼을 눌러주세요.")

    def _save_preset(self):
        """현재 설정을 프리셋으로 저장"""
        from tkinter import simpledialog, messagebox

        # 프리셋 이름 입력
        name = simpledialog.askstring(
            "프리셋 저장",
            "프리셋 이름을 입력하세요:",
            parent=self.parent
        )

        if not name:
            return

        if name in ["사용자 정의", "공포 기본", "감동 기본", "막장 기본", "밝은 스타일", "어두운 스타일"]:
            messagebox.showerror("오류", "기본 프리셋 이름은 사용할 수 없습니다.")
            return

        # 프리셋 저장
        self.settings_manager.save_thumbnail_preset(name, self.current_settings)

        # 드롭다운 업데이트
        self.preset_dropdown.configure(values=self._get_preset_names())
        self.preset_var.set(name)

        messagebox.showinfo("저장 완료", f"'{name}' 프리셋이 저장되었습니다.")

    def _delete_preset(self):
        """프리셋 삭제"""
        from tkinter import messagebox

        name = self.preset_var.get()

        if name in ["사용자 정의", "공포 기본", "감동 기본", "막장 기본", "밝은 스타일", "어두운 스타일"]:
            messagebox.showwarning("알림", "기본 프리셋은 삭제할 수 없습니다.")
            return

        if not messagebox.askyesno("확인", f"'{name}' 프리셋을 삭제하시겠습니까?"):
            return

        # 프리셋 삭제
        self.settings_manager.delete_thumbnail_preset(name)

        # 드롭다운 업데이트
        self.preset_dropdown.configure(values=self._get_preset_names())
        self.preset_var.set("사용자 정의")

        messagebox.showinfo("삭제 완료", f"'{name}' 프리셋이 삭제되었습니다.")
