# src/gui/sd_model_dialog.py
"""
v37 - Stable Diffusion 모델 관리 다이얼로그

기능:
1. 설치된 SD 모델 목록 표시
2. 채널별 모델 설정 (동적 패키지 기반)
3. LoRA/VAE 관리
4. 프롬프트 프리셋 관리
5. 비동기 모델 로딩 + 로딩 오버레이 (제미나이 피드백)
6. 모델 썸네일 표시
"""

import customtkinter as ctk
from tkinter import messagebox
import threading
import logging
from typing import Optional, List, Dict, Callable, Tuple
from PIL import Image, ImageTk
import io

logger = logging.getLogger(__name__)

# 폰트 설정
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    """통일된 폰트 반환"""
    sizes = {"small": 12, "normal": 13, "medium": 14, "large": 16, "title": 20}
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


class LoadingOverlay(ctk.CTkToplevel):
    """
    모델 로딩 중 표시할 오버레이 다이얼로그 (v36 제미나이 피드백)

    SD/Flux 모델은 로딩에 시간이 오래 걸리므로,
    사용자에게 진행 상태를 보여주고 UI 블로킹을 방지
    """

    def __init__(self, parent, title: str = "로딩 중"):
        super().__init__(parent)

        self.title(title)
        self.geometry("350x150")
        self.resizable(False, False)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 닫기 버튼 비활성화
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        # 중앙 배치
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 175
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 75
        self.geometry(f"+{x}+{y}")

        # 컨텐츠
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 스피너 (뺑글이 애니메이션 효과)
        self.spinner_label = ctk.CTkLabel(
            main_frame,
            text="⏳",
            font=ctk.CTkFont(family=FONT_FAMILY, size=32)
        )
        self.spinner_label.pack(pady=(10, 15))

        # 메시지
        self.message_label = ctk.CTkLabel(
            main_frame,
            text="모델 로딩 중입니다...",
            font=get_font("medium")
        )
        self.message_label.pack()

        # 서브 메시지
        self.sub_message_label = ctk.CTkLabel(
            main_frame,
            text="잠시만 기다려주세요 (최대 5분 소요)",
            font=get_font("small"),
            text_color="#888888"
        )
        self.sub_message_label.pack(pady=(5, 0))

        # 스피너 애니메이션
        self._spinner_chars = ["⏳", "⌛"]
        self._spinner_idx = 0
        self._animate()

    def _animate(self):
        """스피너 애니메이션"""
        if self.winfo_exists():
            self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
            self.spinner_label.configure(text=self._spinner_chars[self._spinner_idx])
            self.after(500, self._animate)

    def set_message(self, message: str, sub_message: str = ""):
        """메시지 업데이트"""
        self.message_label.configure(text=message)
        if sub_message:
            self.sub_message_label.configure(text=sub_message)

    def close(self):
        """오버레이 닫기"""
        try:
            self.grab_release()
            self.destroy()
        except Exception as e:
            logger.debug(f"다이얼로그 닫기 실패: {e}")


class SDModelDialog(ctk.CTkToplevel):
    """SD 모델 관리 다이얼로그"""

    def __init__(self, parent, on_close_callback: Optional[Callable] = None):
        super().__init__(parent)

        self.on_close_callback = on_close_callback

        # 윈도우 설정
        self.title("🎨 이미지 모델 관리")
        self.geometry("900x700")
        self.resizable(True, True)

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        # SD 모델 매니저
        try:
            from utils.sd_model_manager import get_sd_model_manager
            self.manager = get_sd_model_manager()
        except Exception as e:
            logger.error(f"[SDModelDialog] 매니저 로드 실패: {e}")
            self.manager = None

        # 상태
        self._models: List = []
        self._loras: List = []
        self._vaes: List = []
        self._is_loading = False
        self._loading_overlay: Optional[LoadingOverlay] = None
        self._thumbnail_images: Dict[str, ctk.CTkImage] = {}  # 썸네일 캐시

        # 동적 채널 목록 (설치된 패키지 기반)
        self._available_channels: List[Tuple[str, str]] = []  # (channel_id, display_name)
        self._load_available_channels()

        # UI 생성
        self._create_ui()

        # 데이터 로드
        self._load_data()

        # 닫기 이벤트
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_available_channels(self):
        """설치된 패키지에서 채널 목록 로드"""
        self._available_channels = []

        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            installed = pm.list_installed_packages()

            if installed:
                for pkg_id, pkg_info in installed.items():
                    channel_id = pkg_info.get('channel_id', pkg_id)
                    channel_name = pkg_info.get('channel_name', '')
                    pkg_name = pkg_info.get('package_name', pkg_id)

                    # 표시명 결정: channel_name > package_name > channel_id
                    display_name = channel_name if channel_name else pkg_name if pkg_name else channel_id

                    # 중복 체크
                    existing_ids = [c[0] for c in self._available_channels]
                    if channel_id not in existing_ids:
                        self._available_channels.append((channel_id, display_name))

            logger.info(f"[SDModelDialog] 로드된 채널: {len(self._available_channels)}개")

        except Exception as e:
            logger.error(f"[SDModelDialog] 채널 목록 로드 실패: {e}")
            # 폴백: 기본 채널
            self._available_channels = [("default", "기본 채널")]

    def _create_ui(self):
        """UI 생성"""
        # 메인 컨테이너
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 헤더
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        title_label = ctk.CTkLabel(
            header_frame,
            text="🎨 Stable Diffusion 모델 관리",
            font=get_font("title", bold=True)
        )
        title_label.pack(side="left")

        # 새로고침 버튼
        refresh_btn = ctk.CTkButton(
            header_frame,
            text="🔄 새로고침",
            width=100,
            font=get_font("normal"),
            command=self._refresh_all
        )
        refresh_btn.pack(side="right")

        # 연결 상태 표시
        self.status_label = ctk.CTkLabel(
            header_frame,
            text="연결 확인 중...",
            font=get_font("small"),
            text_color="#888888"
        )
        self.status_label.pack(side="right", padx=20)

        # 탭 뷰
        self.tabview = ctk.CTkTabview(main_frame)
        self.tabview.pack(fill="both", expand=True)

        # 탭 추가
        self.tab_models = self.tabview.add("모델 목록")
        self.tab_channels = self.tabview.add("채널별 설정")
        self.tab_lora = self.tabview.add("LoRA")
        self.tab_presets = self.tabview.add("프롬프트 프리셋")

        # 각 탭 UI 생성
        self._create_models_tab()
        self._create_channels_tab()
        self._create_lora_tab()
        self._create_presets_tab()

    # ==================== 모델 목록 탭 ====================

    def _create_models_tab(self):
        """모델 목록 탭 생성"""
        tab = self.tab_models

        # 현재 모델 표시
        current_frame = ctk.CTkFrame(tab)
        current_frame.pack(fill="x", pady=(10, 15))

        ctk.CTkLabel(
            current_frame,
            text="현재 로드된 모델:",
            font=get_font("normal", bold=True)
        ).pack(side="left", padx=10)

        self.current_model_label = ctk.CTkLabel(
            current_frame,
            text="확인 중...",
            font=get_font("normal"),
            text_color="#4CAF50"
        )
        self.current_model_label.pack(side="left", padx=10)

        # 모델 리스트
        list_frame = ctk.CTkFrame(tab)
        list_frame.pack(fill="both", expand=True, pady=10)

        # 리스트 헤더 (v36: 썸네일 칼럼 추가)
        header = ctk.CTkFrame(list_frame, fg_color="#2B2B2B", height=35)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="", width=60).pack(side="left")  # 썸네일 공간
        ctk.CTkLabel(header, text="모델 정보", anchor="w").pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(header, text="동작", width=100, anchor="center").pack(side="right", padx=10)

        # 스크롤 영역
        self.models_scroll = ctk.CTkScrollableFrame(list_frame, height=350)
        self.models_scroll.pack(fill="both", expand=True)

        # 로딩 표시
        self.models_loading_label = ctk.CTkLabel(
            self.models_scroll,
            text="모델 목록 로딩 중...",
            font=get_font("medium"),
            text_color="#888888"
        )
        self.models_loading_label.pack(pady=50)

    def _populate_models_list(self):
        """모델 목록 채우기 (v36: 썸네일 지원)"""
        # 기존 위젯 제거
        for widget in self.models_scroll.winfo_children():
            widget.destroy()

        if not self._models:
            ctk.CTkLabel(
                self.models_scroll,
                text="설치된 모델이 없거나 WebUI에 연결할 수 없습니다.",
                font=get_font("medium"),
                text_color="#888888"
            ).pack(pady=50)
            return

        current_model = self.manager.get_current_model() if self.manager else None

        for model in self._models:
            row = ctk.CTkFrame(self.models_scroll, fg_color="transparent", height=50)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            # 썸네일 플레이스홀더 (v36 제미나이 피드백)
            thumb_label = ctk.CTkLabel(
                row,
                text="📦",
                width=50,
                height=50,
                font=get_font("title")
            )
            thumb_label.pack(side="left", padx=5)

            # 비동기 썸네일 로드
            self._load_thumbnail_async(model, thumb_label)

            # 현재 모델 표시
            is_current = model.title == current_model or model.filename == current_model
            name_color = "#4CAF50" if is_current else "#FFFFFF"
            name_suffix = " ★" if is_current else ""

            # 모델 정보 프레임
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="x", expand=True, padx=5)

            ctk.CTkLabel(
                info_frame,
                text=f"{model.title}{name_suffix}",
                anchor="w",
                text_color=name_color,
                font=get_font("small", bold=is_current)
            ).pack(anchor="w")

            ctk.CTkLabel(
                info_frame,
                text=model.filename[:50] + "..." if len(model.filename) > 50 else model.filename,
                anchor="w",
                text_color="#888888",
                font=get_font("small")
            ).pack(anchor="w")

            # 버튼 프레임
            btn_frame = ctk.CTkFrame(row, fg_color="transparent", width=100)
            btn_frame.pack(side="right", padx=10)
            btn_frame.pack_propagate(False)

            if not is_current:
                load_btn = ctk.CTkButton(
                    btn_frame,
                    text="로드",
                    width=70,
                    height=30,
                    font=get_font("small"),
                    fg_color="#2196F3",
                    command=lambda m=model: self._load_model(m)
                )
                load_btn.pack(side="left", padx=5)
            else:
                ctk.CTkLabel(
                    btn_frame,
                    text="사용중",
                    text_color="#4CAF50",
                    font=get_font("small")
                ).pack(side="left", padx=5)

    def _load_thumbnail_async(self, model, label: ctk.CTkLabel):
        """비동기 썸네일 로드"""
        if not self.manager:
            return

        cache_key = model.model_name or model.filename

        # 이미 캐시에 있으면 바로 적용
        if cache_key in self._thumbnail_images:
            label.configure(image=self._thumbnail_images[cache_key], text="")
            return

        def on_thumbnail_loaded(thumb_data: Optional[bytes]):
            if thumb_data and self.winfo_exists():
                try:
                    # PIL로 이미지 로드
                    img = Image.open(io.BytesIO(thumb_data))
                    img.thumbnail((45, 45))

                    # CTkImage로 변환
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(45, 45))

                    # 캐시에 저장
                    self._thumbnail_images[cache_key] = ctk_img

                    # 라벨 업데이트
                    self.after(0, lambda: label.configure(image=ctk_img, text=""))

                except Exception as e:
                    logger.debug(f"썸네일 처리 실패: {e}")

        self.manager.get_thumbnail_async(model, on_thumbnail_loaded)

    def _load_model(self, model):
        """
        비동기 모델 로드 (v36 제미나이 피드백)

        로딩 오버레이를 표시하고 별도 스레드에서 모델 로드
        """
        if not self.manager:
            return

        # 이미 로딩 중이면 무시
        if self.manager.is_loading():
            messagebox.showinfo("알림", "다른 모델을 로딩 중입니다. 잠시 후 다시 시도하세요.")
            return

        # 로딩 오버레이 표시
        self._show_loading_overlay(f"모델 로딩: {model.title[:30]}...")

        def on_complete(success: bool, message: str):
            """로딩 완료 콜백"""
            self.after(0, self._hide_loading_overlay)

            if success:
                self.after(0, lambda: self._update_current_model(model.title))
                self.after(0, self._populate_models_list)
                self.after(0, lambda: self._show_toast("모델 로딩 완료", "#4CAF50"))
            else:
                self.after(0, lambda: messagebox.showerror("오류", f"모델 로딩 실패:\n{message}"))

        def on_progress(message: str):
            """진행 상태 콜백"""
            if self._loading_overlay:
                self.after(0, lambda: self._loading_overlay.set_message(message))

        # 비동기 로드 시작
        self.manager.set_model_async(
            model.title,
            on_complete=on_complete,
            on_progress=on_progress
        )

    def _show_loading_overlay(self, message: str = "로딩 중..."):
        """로딩 오버레이 표시"""
        if self._loading_overlay:
            self._loading_overlay.close()

        self._loading_overlay = LoadingOverlay(self, title="모델 로딩")
        self._loading_overlay.set_message(message, "SD/Flux 모델은 용량이 커서 시간이 걸립니다")

    def _hide_loading_overlay(self):
        """로딩 오버레이 숨김"""
        if self._loading_overlay:
            self._loading_overlay.close()
            self._loading_overlay = None

    def _show_toast(self, message: str, color: str = "#4CAF50"):
        """토스트 알림 표시"""
        toast = ctk.CTkLabel(
            self,
            text=f"  {message}  ",
            font=get_font("small"),
            fg_color=color,
            corner_radius=8,
            text_color="white"
        )
        toast.place(relx=0.5, rely=0.95, anchor="center")
        self.after(2000, toast.destroy)

    def _update_current_model(self, model_name: str):
        """현재 모델 표시 업데이트"""
        self.current_model_label.configure(text=model_name or "없음")

    # ==================== 채널별 설정 탭 ====================

    def _create_channels_tab(self):
        """채널별 설정 탭 생성"""
        tab = self.tab_channels

        # 설명
        ctk.CTkLabel(
            tab,
            text="각 채널에서 사용할 이미지 생성 모델과 설정을 지정합니다.",
            font=get_font("normal"),
            text_color="#888888"
        ).pack(pady=(10, 15))

        # 채널 선택
        channel_select_frame = ctk.CTkFrame(tab, fg_color="transparent")
        channel_select_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            channel_select_frame,
            text="채널 선택:",
            font=get_font("normal", bold=True)
        ).pack(side="left", padx=10)

        # 동적 채널 목록 구성
        channel_ids = [c[0] for c in self._available_channels] if self._available_channels else ["default"]
        default_channel = channel_ids[0] if channel_ids else "default"

        self.channel_var = ctk.StringVar(value=default_channel)
        self.channel_combo = ctk.CTkComboBox(
            channel_select_frame,
            values=channel_ids,
            variable=self.channel_var,
            width=200,
            font=get_font("normal"),
            command=self._on_channel_select
        )
        self.channel_combo.pack(side="left", padx=10)

        # 채널 이름 매핑 (동적)
        self.channel_names = {c[0]: c[1] for c in self._available_channels}

        # 기본 표시명
        default_display = self.channel_names.get(default_channel, default_channel)

        channel_name_label = ctk.CTkLabel(
            channel_select_frame,
            text=default_display,
            font=get_font("normal"),
            text_color="#AAAAAA"
        )
        channel_name_label.pack(side="left", padx=10)
        self.channel_name_label = channel_name_label

        # 채널 새로고침 버튼
        ctk.CTkButton(
            channel_select_frame,
            text="🔄",
            width=35,
            height=28,
            font=get_font("normal"),
            fg_color="#555555",
            hover_color="#666666",
            command=self._refresh_channels
        ).pack(side="left", padx=5)

        # 설정 프레임
        self.channel_settings_frame = ctk.CTkScrollableFrame(tab, height=400)
        self.channel_settings_frame.pack(fill="both", expand=True, pady=10)

        # 설정 입력 필드들
        self._create_channel_settings_fields()

        # 저장 버튼
        save_frame = ctk.CTkFrame(tab, fg_color="transparent")
        save_frame.pack(fill="x", pady=10)

        ctk.CTkButton(
            save_frame,
            text="💾 설정 저장",
            width=150,
            font=get_font("normal"),
            fg_color="#4CAF50",
            command=self._save_channel_config
        ).pack(side="right", padx=10)

        ctk.CTkButton(
            save_frame,
            text="🔄 초기화",
            width=100,
            font=get_font("normal"),
            fg_color="#757575",
            command=self._reset_channel_config
        ).pack(side="right", padx=10)

    def _create_channel_settings_fields(self):
        """채널 설정 입력 필드 생성"""
        frame = self.channel_settings_frame

        # 모델 설정 섹션
        model_section = ctk.CTkFrame(frame)
        model_section.pack(fill="x", pady=10, padx=5)

        ctk.CTkLabel(
            model_section,
            text="📦 모델 설정",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        # 일러스트 모델
        row1 = ctk.CTkFrame(model_section, fg_color="transparent")
        row1.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(row1, text="일러스트 모델:", width=150, anchor="w", font=get_font("normal")).pack(side="left")
        self.illust_model_combo = ctk.CTkComboBox(row1, values=["로딩 중..."], width=350, font=get_font("normal"))
        self.illust_model_combo.pack(side="left", padx=10)

        # 실사 모델
        row2 = ctk.CTkFrame(model_section, fg_color="transparent")
        row2.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(row2, text="실사 모델:", width=150, anchor="w", font=get_font("normal")).pack(side="left")
        self.realistic_model_combo = ctk.CTkComboBox(row2, values=["로딩 중..."], width=350, font=get_font("normal"))
        self.realistic_model_combo.pack(side="left", padx=10)

        # VAE
        row3 = ctk.CTkFrame(model_section, fg_color="transparent")
        row3.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(row3, text="VAE:", width=150, anchor="w", font=get_font("normal")).pack(side="left")
        self.vae_combo = ctk.CTkComboBox(row3, values=["Automatic"], width=350, font=get_font("normal"))
        self.vae_combo.pack(side="left", padx=10)

        # 프롬프트 섹션
        prompt_section = ctk.CTkFrame(frame)
        prompt_section.pack(fill="x", pady=10, padx=5)

        ctk.CTkLabel(
            prompt_section,
            text="✍️ 기본 프롬프트",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        # 긍정 프롬프트
        pos_frame = ctk.CTkFrame(prompt_section, fg_color="transparent")
        pos_frame.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(pos_frame, text="긍정 프롬프트:", anchor="w", font=get_font("normal")).pack(anchor="w")
        self.positive_prompt_text = ctk.CTkTextbox(pos_frame, height=60, font=get_font("normal"))
        self.positive_prompt_text.pack(fill="x", pady=5)

        # 부정 프롬프트
        neg_frame = ctk.CTkFrame(prompt_section, fg_color="transparent")
        neg_frame.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(neg_frame, text="부정 프롬프트:", anchor="w", font=get_font("normal")).pack(anchor="w")
        self.negative_prompt_text = ctk.CTkTextbox(neg_frame, height=60, font=get_font("normal"))
        self.negative_prompt_text.pack(fill="x", pady=5)

        # 생성 설정 섹션
        gen_section = ctk.CTkFrame(frame)
        gen_section.pack(fill="x", pady=10, padx=5)

        ctk.CTkLabel(
            gen_section,
            text="⚙️ 생성 설정",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        # 샘플러, 스텝, CFG
        gen_row1 = ctk.CTkFrame(gen_section, fg_color="transparent")
        gen_row1.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(gen_row1, text="샘플러:", width=80, anchor="w", font=get_font("normal")).pack(side="left")
        self.sampler_combo = ctk.CTkComboBox(
            gen_row1,
            values=["DPM++ 2M Karras", "DPM++ SDE Karras", "Euler a", "Euler", "DDIM"],
            width=180,
            font=get_font("normal")
        )
        self.sampler_combo.pack(side="left", padx=5)

        ctk.CTkLabel(gen_row1, text="Steps:", width=60, anchor="w", font=get_font("normal")).pack(side="left", padx=(20, 0))
        self.steps_entry = ctk.CTkEntry(gen_row1, width=60, font=get_font("normal"))
        self.steps_entry.pack(side="left", padx=5)
        self.steps_entry.insert(0, "30")

        ctk.CTkLabel(gen_row1, text="CFG:", width=50, anchor="w", font=get_font("normal")).pack(side="left", padx=(20, 0))
        self.cfg_entry = ctk.CTkEntry(gen_row1, width=60, font=get_font("normal"))
        self.cfg_entry.pack(side="left", padx=5)
        self.cfg_entry.insert(0, "7")

        # 해상도
        gen_row2 = ctk.CTkFrame(gen_section, fg_color="transparent")
        gen_row2.pack(fill="x", pady=5, padx=20)

        ctk.CTkLabel(gen_row2, text="해상도:", width=80, anchor="w", font=get_font("normal")).pack(side="left")
        self.width_entry = ctk.CTkEntry(gen_row2, width=80, font=get_font("normal"))
        self.width_entry.pack(side="left", padx=5)
        self.width_entry.insert(0, "1280")

        ctk.CTkLabel(gen_row2, text="x", width=20, font=get_font("normal")).pack(side="left")
        self.height_entry = ctk.CTkEntry(gen_row2, width=80, font=get_font("normal"))
        self.height_entry.pack(side="left", padx=5)
        self.height_entry.insert(0, "720")

    def _on_channel_select(self, channel_id: str):
        """채널 선택 시"""
        self.channel_name_label.configure(text=self.channel_names.get(channel_id, channel_id))
        self._load_channel_config(channel_id)

    def _refresh_channels(self):
        """채널 목록 새로고침"""
        self._load_available_channels()

        # 콤보박스 업데이트
        channel_ids = [c[0] for c in self._available_channels] if self._available_channels else ["default"]
        self.channel_combo.configure(values=channel_ids)

        # 채널 이름 매핑 갱신
        self.channel_names = {c[0]: c[1] for c in self._available_channels}

        # 현재 선택이 유효하지 않으면 첫번째 채널로 변경
        current = self.channel_var.get()
        if current not in channel_ids and channel_ids:
            self.channel_var.set(channel_ids[0])
            self._on_channel_select(channel_ids[0])

    def _load_channel_config(self, channel_id: str):
        """채널 설정 로드"""
        if not self.manager:
            return

        cfg = self.manager.get_channel_config(channel_id)

        # 모델 콤보박스 설정
        if cfg.checkpoint_illustration:
            self.illust_model_combo.set(cfg.checkpoint_illustration)
        if cfg.checkpoint_realistic:
            self.realistic_model_combo.set(cfg.checkpoint_realistic)
        if cfg.vae:
            self.vae_combo.set(cfg.vae)

        # 프롬프트
        self.positive_prompt_text.delete("1.0", "end")
        self.positive_prompt_text.insert("1.0", cfg.positive_prompt)

        self.negative_prompt_text.delete("1.0", "end")
        self.negative_prompt_text.insert("1.0", cfg.negative_prompt)

        # 생성 설정
        self.sampler_combo.set(cfg.sampler)

        self.steps_entry.delete(0, "end")
        self.steps_entry.insert(0, str(cfg.steps))

        self.cfg_entry.delete(0, "end")
        self.cfg_entry.insert(0, str(cfg.cfg_scale))

        self.width_entry.delete(0, "end")
        self.width_entry.insert(0, str(cfg.width))

        self.height_entry.delete(0, "end")
        self.height_entry.insert(0, str(cfg.height))

    def _save_channel_config(self):
        """채널 설정 저장"""
        if not self.manager:
            return

        from utils.sd_model_manager import ChannelSDConfig

        channel_id = self.channel_var.get()

        try:
            cfg = ChannelSDConfig(
                channel_id=channel_id,
                checkpoint_illustration=self.illust_model_combo.get(),
                checkpoint_realistic=self.realistic_model_combo.get(),
                vae=self.vae_combo.get(),
                positive_prompt=self.positive_prompt_text.get("1.0", "end-1c"),
                negative_prompt=self.negative_prompt_text.get("1.0", "end-1c"),
                sampler=self.sampler_combo.get(),
                steps=int(self.steps_entry.get() or 30),
                cfg_scale=float(self.cfg_entry.get() or 7),
                width=int(self.width_entry.get() or 1280),
                height=int(self.height_entry.get() or 720),
            )

            if self.manager.set_channel_config(channel_id, cfg):
                messagebox.showinfo("저장 완료", f"{self.channel_names.get(channel_id, channel_id)} 설정이 저장되었습니다.")
            else:
                messagebox.showerror("오류", "설정 저장에 실패했습니다.")

        except ValueError as e:
            messagebox.showerror("입력 오류", f"잘못된 입력값이 있습니다: {e}")

    def _reset_channel_config(self):
        """채널 설정 초기화"""
        channel_id = self.channel_var.get()
        self._load_channel_config(channel_id)

    # ==================== LoRA 탭 ====================

    def _create_lora_tab(self):
        """LoRA 탭 생성"""
        tab = self.tab_lora

        # 설명
        ctk.CTkLabel(
            tab,
            text="설치된 LoRA 목록입니다. LoRA는 채널 설정에서 추가할 수 있습니다.",
            font=get_font("normal"),
            text_color="#888888"
        ).pack(pady=(10, 15))

        # 새로고침 버튼
        btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        btn_frame.pack(fill="x", pady=5)

        ctk.CTkButton(
            btn_frame,
            text="🔄 LoRA 새로고침",
            width=150,
            font=get_font("normal"),
            command=self._refresh_loras
        ).pack(side="left", padx=10)

        # LoRA 리스트
        self.lora_scroll = ctk.CTkScrollableFrame(tab, height=400)
        self.lora_scroll.pack(fill="both", expand=True, pady=10)

        # 로딩 표시
        self.lora_loading_label = ctk.CTkLabel(
            self.lora_scroll,
            text="LoRA 목록 로딩 중...",
            font=get_font("medium"),
            text_color="#888888"
        )
        self.lora_loading_label.pack(pady=50)

    def _populate_lora_list(self):
        """LoRA 목록 채우기"""
        for widget in self.lora_scroll.winfo_children():
            widget.destroy()

        if not self._loras:
            ctk.CTkLabel(
                self.lora_scroll,
                text="설치된 LoRA가 없거나 WebUI에 연결할 수 없습니다.",
                font=get_font("medium"),
                text_color="#888888"
            ).pack(pady=50)
            return

        for lora in self._loras:
            row = ctk.CTkFrame(self.lora_scroll, fg_color="#2B2B2B", height=45)
            row.pack(fill="x", pady=2, padx=5)
            row.pack_propagate(False)

            ctk.CTkLabel(
                row,
                text=f"📦 {lora.name}",
                font=get_font("normal"),
                anchor="w"
            ).pack(side="left", padx=15, pady=10)

            ctk.CTkLabel(
                row,
                text=lora.filename,
                font=get_font("small"),
                text_color="#888888",
                anchor="w"
            ).pack(side="left", padx=10)

    def _refresh_loras(self):
        """LoRA 새로고침"""
        if not self.manager:
            return

        def refresh_task():
            self.manager.refresh_loras()
            self._loras = self.manager.get_loras(force_refresh=True)
            self.after(0, self._populate_lora_list)

        threading.Thread(target=refresh_task, daemon=True).start()

    # ==================== 프리셋 탭 ====================

    def _create_presets_tab(self):
        """프리셋 탭 생성"""
        tab = self.tab_presets

        # 설명
        ctk.CTkLabel(
            tab,
            text="자주 사용하는 프롬프트를 프리셋으로 저장하고 관리합니다.",
            font=get_font("normal"),
            text_color="#888888"
        ).pack(pady=(10, 15))

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        btn_frame.pack(fill="x", pady=5)

        ctk.CTkButton(
            btn_frame,
            text="➕ 새 프리셋",
            width=120,
            font=get_font("normal"),
            fg_color="#4CAF50",
            command=self._create_new_preset
        ).pack(side="left", padx=10)

        # 프리셋 리스트
        self.presets_scroll = ctk.CTkScrollableFrame(tab, height=400)
        self.presets_scroll.pack(fill="both", expand=True, pady=10)

    def _populate_presets_list(self):
        """프리셋 목록 채우기"""
        for widget in self.presets_scroll.winfo_children():
            widget.destroy()

        if not self.manager:
            return

        presets = self.manager.get_presets()

        if not presets:
            ctk.CTkLabel(
                self.presets_scroll,
                text="저장된 프리셋이 없습니다.",
                font=get_font("medium"),
                text_color="#888888"
            ).pack(pady=50)
            return

        for name, preset in presets.items():
            row = ctk.CTkFrame(self.presets_scroll, fg_color="#2B2B2B")
            row.pack(fill="x", pady=3, padx=5)

            # 정보
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(fill="x", padx=10, pady=8)

            ctk.CTkLabel(
                info_frame,
                text=f"📝 {preset.name}",
                font=get_font("normal", bold=True),
                anchor="w"
            ).pack(anchor="w")

            if preset.description:
                ctk.CTkLabel(
                    info_frame,
                    text=preset.description,
                    font=get_font("small"),
                    text_color="#888888",
                    anchor="w"
                ).pack(anchor="w")

            # 프롬프트 미리보기
            preview = preset.positive[:80] + "..." if len(preset.positive) > 80 else preset.positive
            ctk.CTkLabel(
                info_frame,
                text=f"+ {preview}",
                font=get_font("small"),
                text_color="#4CAF50",
                anchor="w"
            ).pack(anchor="w", pady=(5, 0))

            # 버튼
            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=10, pady=8)

            ctk.CTkButton(
                btn_frame,
                text="삭제",
                width=60,
                height=28,
                font=get_font("small"),
                fg_color="#F44336",
                command=lambda n=name: self._delete_preset(n)
            ).pack(side="right", padx=5)

    def _create_new_preset(self):
        """새 프리셋 생성 다이얼로그"""
        dialog = ctk.CTkInputDialog(
            text="프리셋 이름을 입력하세요:",
            title="새 프리셋"
        )
        name = dialog.get_input()

        if name and self.manager:
            from utils.sd_model_manager import PromptPreset
            preset = PromptPreset(
                name=name,
                positive="",
                negative="",
                description=""
            )
            self.manager.save_preset(preset)
            self._populate_presets_list()

    def _delete_preset(self, name: str):
        """프리셋 삭제"""
        if messagebox.askyesno("삭제 확인", f"'{name}' 프리셋을 삭제하시겠습니까?"):
            if self.manager and self.manager.delete_preset(name):
                self._populate_presets_list()

    # ==================== 데이터 로드 ====================

    def _safe_after(self, delay: int, callback):
        """안전한 after 호출 - 위젯이 존재할 때만 실행"""
        try:
            if self.winfo_exists():
                self.after(delay, callback)
        except Exception as e:
            logger.debug(f"safe_after 호출 실패: {e}")

    def _load_data(self):
        """데이터 로드"""
        def load_task():
            if not self.manager:
                self._safe_after(0, lambda: self.status_label.configure(
                    text="❌ 매니저 로드 실패",
                    text_color="#F44336"
                ))
                return

            # 연결 확인
            if self.manager.check_connection():
                self._safe_after(0, lambda: self.status_label.configure(
                    text="✅ WebUI 연결됨",
                    text_color="#4CAF50"
                ))

                # 모델 목록 로드
                self._models = self.manager.get_models()
                self._loras = self.manager.get_loras()
                self._vaes = self.manager.get_vaes()

                # 현재 모델
                current = self.manager.get_current_model()
                self._safe_after(0, lambda: self._update_current_model(current))

                # UI 업데이트
                self._safe_after(0, self._populate_models_list)
                self._safe_after(0, self._populate_lora_list)
                self._safe_after(0, self._populate_presets_list)
                self._safe_after(0, self._update_combos)

                # 채널 설정 로드 (첫 번째 채널)
                default_channel = self._available_channels[0][0] if self._available_channels else "default"
                self._safe_after(0, lambda c=default_channel: self._load_channel_config(c))

            else:
                self._safe_after(0, lambda: self.status_label.configure(
                    text="❌ WebUI 연결 실패",
                    text_color="#F44336"
                ))

        threading.Thread(target=load_task, daemon=True).start()

    def _update_combos(self):
        """콤보박스 옵션 업데이트"""
        # 모델 콤보박스
        model_names = ["(선택 안 함)"] + [m.title for m in self._models]
        self.illust_model_combo.configure(values=model_names)
        self.realistic_model_combo.configure(values=model_names)

        # VAE 콤보박스
        vae_names = ["Automatic"] + [v.model_name for v in self._vaes]
        self.vae_combo.configure(values=vae_names)

    def _refresh_all(self):
        """전체 새로고침"""
        if not self.manager:
            return

        def refresh_task():
            self._set_loading(True, "새로고침 중...")
            self.manager.refresh_models()
            self._models = self.manager.get_models(force_refresh=True)
            self._loras = self.manager.get_loras(force_refresh=True)
            self._vaes = self.manager.get_vaes(force_refresh=True)
            self._set_loading(False)

            self._safe_after(0, self._populate_models_list)
            self._safe_after(0, self._populate_lora_list)
            self._safe_after(0, self._update_combos)

        threading.Thread(target=refresh_task, daemon=True).start()

    def _set_loading(self, is_loading: bool, message: str = ""):
        """로딩 상태 설정"""
        self._is_loading = is_loading
        if is_loading:
            self._safe_after(0, lambda: self.status_label.configure(
                text=f"⏳ {message}",
                text_color="#FFA500"
            ))
        else:
            self._safe_after(0, lambda: self.status_label.configure(
                text="✅ WebUI 연결됨",
                text_color="#4CAF50"
            ))

    def _on_close(self):
        """다이얼로그 닫기"""
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()
