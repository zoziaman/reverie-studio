# src/gui/tab_subtitle.py
"""
자막 설정 탭
- 실시간 미리보기 캔버스
- Y축 위치 / 폰트 크기 / 색상 / 외곽선 두께 조정
"""
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont
import os
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


class SubtitleSettingsTab:
    """
    자막 설정 탭
    """
    
    def __init__(self, parent_frame, settings_manager, font_path: str):
        self.parent = parent_frame
        self.settings_manager = settings_manager
        self.font_path = font_path
        
        # 현재 채널/모드 (기본값)
        self.current_channel = "daily_life_toon"
        self.current_mode = "daily_life_toon"
        
        # 현재 설정값
        self.current_settings = self.settings_manager.get_subtitle_settings("daily_life_toon", "daily_life_toon")
        
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
        
        # === 왼쪽: 미리보기 캔버스 ===
        preview_label = ctk.CTkLabel(
            left_frame,
            text="📺 실시간 미리보기 (1280x720)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        preview_label.pack(pady=(10, 10))
        
        # 캔버스 (미리보기 이미지 표시)
        self.preview_canvas = ctk.CTkLabel(left_frame, text="")
        self.preview_canvas.pack(padx=20, pady=10)
        
        # 샘플 텍스트 선택
        sample_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        sample_frame.pack(fill="x", padx=20, pady=10)
        
        sample_label = ctk.CTkLabel(sample_frame, text="샘플 텍스트:", font=ctk.CTkFont(size=12))
        sample_label.pack(side="left", padx=(0, 10))
        
        self.sample_var = ctk.StringVar(value="hook")
        
        hook_radio = ctk.CTkRadioButton(
            sample_frame,
            text="후크",
            variable=self.sample_var,
            value="hook",
            command=self._update_preview
        )
        hook_radio.pack(side="left", padx=5)
        
        narrator_radio = ctk.CTkRadioButton(
            sample_frame,
            text="나레이터",
            variable=self.sample_var,
            value="narrator",
            command=self._update_preview
        )
        narrator_radio.pack(side="left", padx=5)
        
        dialogue_radio = ctk.CTkRadioButton(
            sample_frame,
            text="대사",
            variable=self.sample_var,
            value="dialogue",
            command=self._update_preview
        )
        dialogue_radio.pack(side="left", padx=5)
        
        # === 오른쪽: 조정 컨트롤 ===
        control_label = ctk.CTkLabel(
            right_frame,
            text="⚙️ 자막 설정",
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
        
        # === 후크 자막 설정 ===
        self._create_subtitle_controls(scrollable_frame, "후크 자막", "hook")
        
        # === 나레이터 자막 설정 ===
        self._create_subtitle_controls(scrollable_frame, "나레이터 자막", "narrator")
        
        # === 대사 자막 설정 ===
        self._create_subtitle_controls(scrollable_frame, "대사 자막", "dialogue")

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
    
    def _create_subtitle_controls(self, parent, title: str, subtitle_type: str):
        """자막 타입별 조정 컨트롤"""
        # 섹션 프레임
        section_frame = ctk.CTkFrame(parent)
        section_frame.pack(fill="x", pady=(0, 20))
        
        # 제목
        title_label = ctk.CTkLabel(
            section_frame,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        title_label.pack(anchor="w", padx=10, pady=(10, 10))
        
        # Y축 위치
        y_label = ctk.CTkLabel(section_frame, text="Y축 위치 (%):", font=ctk.CTkFont(size=12))
        y_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        y_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        y_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        settings = self.current_settings.get(subtitle_type, {})
        default_y = settings.get("y_ratio", 0.5) * 100
        
        y_slider = ctk.CTkSlider(
            y_frame,
            from_=0,
            to=100,
            number_of_steps=100,
            command=lambda v: self._on_slider_change(subtitle_type, "y_ratio", v / 100, y_value_label)
        )
        y_slider.set(default_y)
        y_slider.pack(side="left", fill="x", expand=True)
        
        y_value_label = ctk.CTkLabel(y_frame, text=f"{int(default_y)}%", width=50)
        y_value_label.pack(side="left", padx=(10, 0))
        
        # 폰트 크기
        font_label = ctk.CTkLabel(section_frame, text="폰트 크기 (px):", font=ctk.CTkFont(size=12))
        font_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        font_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        font_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_font = settings.get("font_size", 56)
        
        font_slider = ctk.CTkSlider(
            font_frame,
            from_=20,
            to=150,
            number_of_steps=130,
            command=lambda v: self._on_slider_change(subtitle_type, "font_size", int(v), font_value_label)
        )
        font_slider.set(default_font)
        font_slider.pack(side="left", fill="x", expand=True)
        
        font_value_label = ctk.CTkLabel(font_frame, text=f"{default_font}px", width=50)
        font_value_label.pack(side="left", padx=(10, 0))
        
        # 외곽선 두께
        stroke_label = ctk.CTkLabel(section_frame, text="외곽선 두께 (px):", font=ctk.CTkFont(size=12))
        stroke_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        stroke_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        stroke_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_stroke = settings.get("stroke", 6)
        
        stroke_slider = ctk.CTkSlider(
            stroke_frame,
            from_=0,
            to=15,
            number_of_steps=15,
            command=lambda v: self._on_slider_change(subtitle_type, "stroke", int(v), stroke_value_label)
        )
        stroke_slider.set(default_stroke)
        stroke_slider.pack(side="left", fill="x", expand=True)
        
        stroke_value_label = ctk.CTkLabel(stroke_frame, text=f"{default_stroke}px", width=50)
        stroke_value_label.pack(side="left", padx=(10, 0))
        
        # 그림자 범위
        shadow_label = ctk.CTkLabel(section_frame, text="그림자 범위 (px):", font=ctk.CTkFont(size=12))
        shadow_label.pack(anchor="w", padx=20, pady=(5, 0))
        
        shadow_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        shadow_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        default_shadow = settings.get("shadow", 4)
        
        shadow_slider = ctk.CTkSlider(
            shadow_frame,
            from_=0,
            to=10,
            number_of_steps=10,
            command=lambda v: self._on_slider_change(subtitle_type, "shadow", int(v), shadow_value_label)
        )
        shadow_slider.set(default_shadow)
        shadow_slider.pack(side="left", fill="x", expand=True)
        
        shadow_value_label = ctk.CTkLabel(shadow_frame, text=f"{default_shadow}px", width=50)
        shadow_value_label.pack(side="left", padx=(10, 0))
        
        # 색상 (읽기 전용 표시)
        color_label = ctk.CTkLabel(
            section_frame,
            text=f"색상: {settings.get('color', '#FFFFFF')}",
            font=ctk.CTkFont(size=12)
        )
        color_label.pack(anchor="w", padx=20, pady=(5, 10))
    
    def _on_slider_change(self, subtitle_type: str, param: str, value, label_widget):
        """슬라이더 값 변경 시"""
        # 현재 설정 업데이트
        if subtitle_type not in self.current_settings:
            self.current_settings[subtitle_type] = {}
        
        self.current_settings[subtitle_type][param] = value
        
        # 라벨 업데이트
        if param == "y_ratio":
            label_widget.configure(text=f"{int(value * 100)}%")
        else:
            label_widget.configure(text=f"{value}px")
        
        # 미리보기 업데이트
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

        # 설정 불러오기
        self.current_settings = self.settings_manager.get_subtitle_settings(
            self.current_channel,
            self.current_mode
        )
        
        # UI 재구성 (간단하게는 미리보기만 업데이트)
        self._update_preview()
    
    def _update_preview(self):
        """미리보기 캔버스 업데이트"""
        W, H = 1280, 720
        
        # 배경 이미지 생성 (어두운 그라데이션)
        img = Image.new("RGB", (W, H), (20, 20, 25))
        draw = ImageDraw.Draw(img)
        
        # 선택된 샘플 타입
        sample_type = self.sample_var.get()
        settings = self.current_settings.get(sample_type, {})
        
        # 샘플 텍스트
        sample_texts = {
            "hook": "이 문장은 후크 자막입니다",
            "narrator": "이것은 나레이터 자막입니다",
            "dialogue": "이것은 대사 자막입니다"
        }
        text = sample_texts.get(sample_type, "샘플 자막")
        
        # 설정값 가져오기
        y_ratio = settings.get("y_ratio", 0.5)
        font_size = settings.get("font_size", 56)
        color = settings.get("color", "#FFFFFF")
        stroke = settings.get("stroke", 6)
        shadow = settings.get("shadow", 4)
        
        # 폰트 로드
        try:
            font = ImageFont.truetype(self.font_path, font_size)
        except Exception:
            if DEFAULT_FONT:
                font = ImageFont.truetype(DEFAULT_FONT, font_size)
            else:
                font = ImageFont.load_default()
        
        # Y축 위치 계산
        y_pos = int(H * y_ratio)
        
        # 텍스트 크기 측정
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        # X축 중앙 정렬
        x_pos = (W - text_w) // 2
        
        # Y축 위치 조정 (텍스트 높이 고려)
        y_pos = y_pos - text_h // 2
        
        # 그림자 그리기
        for ax in range(-shadow, shadow + 1):
            for ay in range(-shadow, shadow + 1):
                draw.text((x_pos + ax, y_pos + ay), text, font=font, fill="black")
        
        # 본문 그리기
        draw.text((x_pos, y_pos), text, font=font, fill=color, stroke_width=stroke, stroke_fill="black")
        
        # 미리보기 이미지로 변환 (640x360으로 축소)
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
        """기본값으로 복원"""
        from tkinter import messagebox
        if messagebox.askyesno("확인", "모든 자막 설정을 기본값으로 복원하시겠습니까?"):
            # 기본값 가져오기
            self.settings_manager.reset_to_default()
            self.current_settings = self.settings_manager.get_subtitle_settings(
                self.current_channel,
                self.current_mode
            )
            
            # UI 재구성 필요 (간단하게는 페이지 새로고침)
            messagebox.showinfo("완료", "기본값으로 복원되었습니다.\n페이지를 다시 열어주세요.")
    
    def _save_settings(self):
        """설정 저장"""
        self.settings_manager.set_subtitle_settings(
            self.current_channel,
            self.current_mode,
            self.current_settings
        )

        from tkinter import messagebox
        messagebox.showinfo("저장 완료", "자막 설정이 저장되었습니다.")

    def _get_preset_names(self) -> list:
        """프리셋 이름 목록 반환"""
        presets = self.settings_manager.get_subtitle_presets()
        names = ["사용자 정의"] + list(presets.keys())

        # 기본 프리셋 추가
        default_presets = ["공포 기본", "감동 기본", "막장 기본", "큰 글씨", "작은 글씨"]
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
                "hook": {"y_ratio": 0.50, "font_size": 86, "color": "#FF0000", "stroke": 8, "shadow": 5},
                "narrator": {"y_ratio": 0.80, "font_size": 46, "color": "#FFFFFF", "stroke": 6, "shadow": 4},
                "dialogue": {"y_ratio": 0.84, "font_size": 46, "color": "#90EE90", "stroke": 6, "shadow": 4}
            },
            "감동 기본": {
                "hook": {"y_ratio": 0.50, "font_size": 80, "color": "#FF0000", "stroke": 8, "shadow": 5},
                "narrator": {"y_ratio": 0.80, "font_size": 56, "color": "#FFFFFF", "stroke": 6, "shadow": 4},
                "dialogue": {"y_ratio": 0.84, "font_size": 56, "color": "#FFB6C1", "stroke": 6, "shadow": 4}
            },
            "막장 기본": {
                "hook": {"y_ratio": 0.50, "font_size": 80, "color": "#FF0000", "stroke": 8, "shadow": 5},
                "narrator": {"y_ratio": 0.80, "font_size": 54, "color": "#FFFFFF", "stroke": 6, "shadow": 4},
                "dialogue": {"y_ratio": 0.84, "font_size": 54, "color": "#FFB6C1", "stroke": 6, "shadow": 4}
            },
            "큰 글씨": {
                "hook": {"y_ratio": 0.45, "font_size": 100, "color": "#FF0000", "stroke": 10, "shadow": 6},
                "narrator": {"y_ratio": 0.78, "font_size": 70, "color": "#FFFFFF", "stroke": 8, "shadow": 5},
                "dialogue": {"y_ratio": 0.82, "font_size": 70, "color": "#90EE90", "stroke": 8, "shadow": 5}
            },
            "작은 글씨": {
                "hook": {"y_ratio": 0.55, "font_size": 60, "color": "#FF0000", "stroke": 5, "shadow": 3},
                "narrator": {"y_ratio": 0.82, "font_size": 40, "color": "#FFFFFF", "stroke": 4, "shadow": 3},
                "dialogue": {"y_ratio": 0.86, "font_size": 40, "color": "#90EE90", "stroke": 4, "shadow": 3}
            }
        }

        # 사용자 저장 프리셋 또는 기본 프리셋
        presets = self.settings_manager.get_subtitle_presets()

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

        if name in ["사용자 정의", "공포 기본", "감동 기본", "막장 기본", "큰 글씨", "작은 글씨"]:
            messagebox.showerror("오류", "기본 프리셋 이름은 사용할 수 없습니다.")
            return

        # 프리셋 저장
        self.settings_manager.save_subtitle_preset(name, self.current_settings)

        # 드롭다운 업데이트
        self.preset_dropdown.configure(values=self._get_preset_names())
        self.preset_var.set(name)

        messagebox.showinfo("저장 완료", f"'{name}' 프리셋이 저장되었습니다.")

    def _delete_preset(self):
        """프리셋 삭제"""
        from tkinter import messagebox

        name = self.preset_var.get()

        if name in ["사용자 정의", "공포 기본", "감동 기본", "막장 기본", "큰 글씨", "작은 글씨"]:
            messagebox.showwarning("알림", "기본 프리셋은 삭제할 수 없습니다.")
            return

        if not messagebox.askyesno("확인", f"'{name}' 프리셋을 삭제하시겠습니까?"):
            return

        # 프리셋 삭제
        self.settings_manager.delete_subtitle_preset(name)

        # 드롭다운 업데이트
        self.preset_dropdown.configure(values=self._get_preset_names())
        self.preset_var.set("사용자 정의")

        messagebox.showinfo("삭제 완료", f"'{name}' 프리셋이 삭제되었습니다.")
