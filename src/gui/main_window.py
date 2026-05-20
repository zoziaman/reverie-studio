# src/gui/main_window.py
"""
Reverie Automation GUI - 메인 윈도우 (v40)
- 생산 통계 대시보드
- 배치 큐 관리
- 템플릿 시스템
- YouTube 분석 연동
- AI 제목/태그 추천
- 테마 전환
- 최근 프로젝트 목록
- 드래그앤드롭 지원

v40 변경사항:
- Insight/Factory 탭 제거 (관리자 GUI 전용)
- 사용자 GUI는 .revpack 기반 영상 생산만 지원
- 트렌드 분석, 팩 설계는 license_generator_gui.py에서 진행
"""
import customtkinter as ctk
import os
import sys
import json
import threading
import shutil
import requests
from datetime import datetime
from tkinter import messagebox
from tkinter import TclError
from typing import Optional, Dict, Any


from config.settings import config

# 로깅 시스템 초기화
from utils.logger import init_logger, get_logger, set_gui_callback, get_user_friendly_error
init_logger(os.path.join(config.DATA_DIR, "logs"))
logger = get_logger("main_window")
from modules_pro.scenario_planner import ScenarioPlanner, PromptMode
from modules_pro.media_factory import MediaFactory
from gui.thumbnail_preview_dialog import ThumbnailPreviewDialog
from gui.settings_manager import SettingsManager
from gui.tab_subtitle import SubtitleSettingsTab
from gui.tab_thumbnail import ThumbnailSettingsTab
from gui.setup_wizard import SetupWizard, should_show_wizard

# 새로운 유틸리티
from utils.production_stats import ProductionStats
from utils.batch_queue import BatchQueue
from utils.template_manager import TemplateManager
from utils.server_runtime_patch import apply_server_runtime_patch

# 새로운 다이얼로그 (선택적 임포트)
try:
    from gui.stats_dashboard import StatsDashboard
    from gui.queue_manager_dialog import QueueManagerDialog
    from gui.template_dialog import TemplateDialog
    from gui.youtube_analytics_dialog import YouTubeAnalyticsDialog
except ImportError:
    pass

# ============================================================
# 공통 폰트 설정 (가독성 개선)
# ============================================================
FONT_FAMILY = "맑은 고딕"
FONT_SIZE_SMALL = 12
FONT_SIZE_NORMAL = 13
FONT_SIZE_MEDIUM = 14
FONT_SIZE_LARGE = 16
FONT_SIZE_TITLE = 20
FONT_SIZE_HEADER = 24


# 자주 사용하는 폰트 프리셋
def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    """폰트 프리셋 반환"""
    sizes = {
        "small": FONT_SIZE_SMALL,
        "normal": FONT_SIZE_NORMAL,
        "medium": FONT_SIZE_MEDIUM,
        "large": FONT_SIZE_LARGE,
        "title": FONT_SIZE_TITLE,
        "header": FONT_SIZE_HEADER,
    }
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, FONT_SIZE_NORMAL),
        weight="bold" if bold else "normal"
    )


# v60.1.0: Mixin import
from gui.mixins.server_mixin import ServerMixin, probe_http_endpoints
from gui.mixins.sd_model_mixin import SDModelMixin
from gui.mixins.auth_mixin import AuthMixin
from gui.mixins.channel_mixin import ChannelMixin
from gui.mixins.production_mixin import ProductionMixin
from gui.mixins.settings_mixin import SettingsMixin


class ReverieGUI(ServerMixin, SDModelMixin, AuthMixin, ChannelMixin, ProductionMixin, SettingsMixin, ctk.CTk):
    """
    Reverie Automation 메인 GUI
    v60.1.0: ServerMixin으로 서버 관리 메서드 분리
    """
    
    def __init__(self):
        super().__init__()
        apply_server_runtime_patch()

        # 라이센스 검증 (최우선) - 온라인 우선, 오프라인 폴백
        self.license_info = None

        # 개발 모드 확인 (dev_mode.txt 파일 또는 환경변수)
        if config.DEV_MODE:
            # 개발 모드: 전체 기능 라이센스로 설정
            valid = True
            self.license_info = {
                'license_type': 'A',
                'license_type_name': '전체 이용 (개발모드)',
                'expire_date': '2099-12-31',
                'hardware_id': 'DEV_MODE'
            }
            print("[DEV] Development mode - License bypassed")
        else:
            try:
                from utils.firebase_license import HybridLicenseValidator
                self.license_validator = HybridLicenseValidator(config.DATA_DIR)
                valid, msg, self.license_info = self.license_validator.validate()
            except ImportError:
                # Firebase 모듈 없으면 기존 오프라인 검증 사용
                from utils.license_validator import LicenseValidator
                self.license_validator = LicenseValidator(config.DATA_DIR)
                valid, msg = self.license_validator.validate()
                if valid:
                    self.license_info = self.license_validator.get_license_info()

            if not valid:
                # 라이센스 입력 다이얼로그 표시
                if not self._show_license_dialog(msg):
                    # 라이센스 입력 취소 시 프로그램 종료
                    self.destroy()
                    os._exit(0)

        # 설정 관리자
        self.settings_manager = SettingsManager(config.DATA_DIR)

        # v56.5: TTS 엔진 설정 로드 (GUI → 런타임 config 동기화)
        saved_tts_engine = self.settings_manager.get_tts_engine()
        config.TTS_ENGINE = saved_tts_engine

        # 새로운 유틸리티 초기화
        self.production_stats = ProductionStats(config.DATA_DIR)
        self.batch_queue = BatchQueue(config.DATA_DIR)
        self.template_manager = TemplateManager(config.DATA_DIR)

        # 테마 설정 (다크/라이트)
        self.current_theme = "dark"

        # API 설정 로드
        self._load_api_settings()

        # 첫 실행 마법사 표시
        if should_show_wizard(config.DATA_DIR):
            self.withdraw()  # 메인 창 숨김
            wizard = SetupWizard(self, config.DATA_DIR)
            self.wait_window(wizard)  # 마법사 완료 대기
            self.deiconify()  # 메인 창 표시
            # 설정이 변경되었을 수 있으므로 API 설정 다시 로드
            self._load_api_settings()
        
        # 라이센스 정보 저장 (UI 제어용)
        # 개발 모드에서는 이미 license_info가 설정되어 있음
        if not config.DEV_MODE and hasattr(self, 'license_validator'):
            self.license_info = self.license_validator.get_license_info()

        # v62.24: 팩 암호화 런타임 키 설정 (라이선스+HWID 기반)
        # 목적: 암호화된 .revpack은 앱에서만 읽고, 외부 복호화 난이도 상승
        try:
            from config.pack_config import configure_pack_crypto
            if isinstance(self.license_info, dict):
                _lk = self.license_info.get("license_key", "")
                _hw = self.license_info.get("hardware_id", "")
                if not _hw and hasattr(self, 'license_validator'):
                    _hw = getattr(self.license_validator, 'current_hw_id', "")
                configure_pack_crypto(_lk, _hw)
        except Exception as e:
            logger.debug(f"[main_window] pack crypto runtime key 설정 스킵: {e}")

        # 창 설정
        self.title("Reverie Automation")
        window_size = (1400, 850)  # 새 UI에 맞는 크기
        self.geometry(f"{window_size[0]}x{window_size[1]}")
        self.minsize(1200, 750)
        
        # 창 중앙 배치
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - window_size[0]) // 2
        y = (screen_height - window_size[1]) // 2
        self.geometry(f"{window_size[0]}x{window_size[1]}+{x}+{y}")
        
        # 테마 설정
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # 제작 상태
        self.is_producing = False
        self.current_project = None
        self._is_shutting_down = False
        
        # UI 생성
        self._create_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
    
    def _load_api_settings(self):
        """저장된 API 설정 로드"""
        try:
            settings_path = os.path.join(config.DATA_DIR, "api_settings.json")
            
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                provider = (
                    settings.get("story_llm_provider", getattr(config, "STORY_LLM_PROVIDER", "claude_cli"))
                    or getattr(config, "STORY_LLM_PROVIDER", "claude_cli")
                )
                provider = str(provider).strip().lower()
                if provider == "claude":
                    provider = "claude_cli"

                timeout_raw = settings.get(
                    "story_llm_timeout_sec",
                    getattr(config, "STORY_LLM_TIMEOUT_SEC", 600)
                )
                try:
                    story_llm_timeout = int(timeout_raw)
                    if story_llm_timeout <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    story_llm_timeout = int(getattr(config, "STORY_LLM_TIMEOUT_SEC", 600) or 600)
                
                # config 업데이트
                config.SD_URL = settings.get("sd_url", config.SD_URL)
                config.SOVITS_URL = settings.get("sovits_url", config.SOVITS_URL)
                config.GEMINI_API_KEY = settings.get("gemini_api_key", config.GEMINI_API_KEY)
                config.STORY_LLM_PROVIDER = provider
                config.CLAUDE_CLI_PATH = settings.get(
                    "claude_cli_path",
                    getattr(config, "CLAUDE_CLI_PATH", "claude")
                )
                config.CLAUDE_CLI_MODEL = settings.get(
                    "claude_cli_model",
                    getattr(config, "CLAUDE_CLI_MODEL", "sonnet")
                )
                config.STORY_LLM_MODEL = settings.get(
                    "story_llm_model",
                    config.CLAUDE_CLI_MODEL if provider == "claude_cli" else getattr(config, "STORY_LLM_MODEL", "")
                )
                config.STORY_LLM_TIMEOUT_SEC = story_llm_timeout
                # ComfyUI URL도 로드 (v50)
                config.COMFYUI_URL = settings.get("comfyui_url", config.COMFYUI_URL)

                logger.info("API 설정 로드 완료")

        except Exception as e:
            logger.warning(f"API 설정 로드 실패 (기본값 사용): {e}")
    
    def _create_ui(self):
        """UI 구성"""
        # 메인 컨테이너
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 상단: 제목
        title_frame = ctk.CTkFrame(main_container, height=60, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 10))
        title_frame.pack_propagate(False)
        
        title_label = ctk.CTkLabel(
            title_frame,
            text="🎬 Reverie Studio",
            font=get_font("header", bold=True)
        )
        title_label.pack(side="left", padx=10)

        self.version_label = ctk.CTkLabel(
            title_frame,
            text="v60.1.0",
            font=get_font("small"),
            text_color="#666666"
        )
        self.version_label.pack(side="left", padx=(0, 10))

        # v60.1.0: 도구 버튼 (오른쪽) — 핵심 3개 + "도구" 드롭다운
        tools_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        tools_frame.pack(side="right", padx=10)

        # 핵심 버튼 1: 팩 관리 (가장 자주 사용)
        package_btn = ctk.CTkButton(
            tools_frame,
            text="📦 팩 관리",
            width=95,
            height=32,
            font=get_font("normal"),
            fg_color="#00796B",
            hover_color="#00695C",
            command=self._open_package_menu
        )
        package_btn.pack(side="left", padx=2)
        self.package_btn = package_btn

        # 핵심 버튼 2: 배치 큐
        queue_btn = ctk.CTkButton(
            tools_frame,
            text="📋 큐",
            width=65,
            height=32,
            font=get_font("normal"),
            command=self._open_queue_manager
        )
        queue_btn.pack(side="left", padx=2)

        # 핵심 버튼 3: 통계
        stats_btn = ctk.CTkButton(
            tools_frame,
            text="📊 통계",
            width=75,
            height=32,
            font=get_font("normal"),
            command=self._open_stats_dashboard
        )
        stats_btn.pack(side="left", padx=2)

        # "도구" 드롭다운 메뉴 (나머지 기능 통합)
        from tkinter import Menu
        self._tools_menu = Menu(self, tearoff=0)
        self._tools_menu.configure(
            bg="#2b2b2b", fg="white",
            activebackground="#3b3b3b", activeforeground="white",
            font=("맑은 고딕", 11)
        )
        self._tools_menu.add_command(label="🎤  TTS 모델 관리", command=self._open_model_manager)
        self._tools_menu.add_command(label="🎨  SD 모델 관리", command=self._open_sd_model_manager)
        self._tools_menu.add_separator()
        self._tools_menu.add_command(label="📄  템플릿", command=self._open_template_dialog)
        self._tools_menu.add_command(label="📺  YouTube 분석", command=self._open_youtube_analytics)
        self._tools_menu.add_command(label="🤖  자동 최적화", command=self._open_auto_optimizer)
        self._tools_menu.add_separator()
        self._tools_menu.add_command(label="🌐  언어 설정", command=self._show_language_dialog)

        def _show_tools_menu():
            """도구 드롭다운 메뉴 표시"""
            try:
                btn = self._tools_dropdown_btn
                x = btn.winfo_rootx()
                y = btn.winfo_rooty() + btn.winfo_height()
                self._tools_menu.tk_popup(x, y)
            except Exception:
                pass

        self._tools_dropdown_btn = ctk.CTkButton(
            tools_frame,
            text="🔧 도구 ▾",
            width=85,
            height=32,
            font=get_font("normal"),
            fg_color="gray35",
            hover_color="gray45",
            command=_show_tools_menu
        )
        self._tools_dropdown_btn.pack(side="left", padx=(8, 2))

        # 테마 전환 버튼
        self.theme_btn = ctk.CTkButton(
            tools_frame,
            text="🌙",
            width=36,
            height=32,
            font=get_font("medium"),
            fg_color="gray40",
            command=self._toggle_theme
        )
        self.theme_btn.pack(side="left", padx=2)

        # v60.1.0: lang_btn은 도구 메뉴 안으로 이동 → 별도 버튼 없음
        # SettingsMixin에서 lang_btn.configure() 호출 시 무시
        self.lang_btn = None
        
        # 중앙: 탭뷰
        self.tabview = ctk.CTkTabview(main_container)
        self.tabview.pack(fill="both", expand=True)

        # 탭 생성
        # v40: Insight/Factory 탭은 관리자 GUI 전용으로 이동
        # 사용자 GUI에서는 .revpack 기반 영상 생산만 가능
        self.tab_production = self.tabview.add("🚀 생산")
        self.tab_subtitle = self.tabview.add("💬 자막")
        self.tab_thumbnail = self.tabview.add("🖼️ 썸네일")
        self.tab_system = self.tabview.add("⚙️ 시스템")

        # 각 탭 내용 구성
        self._create_production_tab()
        self._create_subtitle_tab()
        self._create_thumbnail_tab()
        self._create_system_tab()
    
    def _create_production_tab(self):
        """생산 탭 구성 - 개선된 UI/UX"""
        # v60.1.0: 서버 상태 인디케이터 (상단 바)
        status_bar = ctk.CTkFrame(self.tab_production, height=32, fg_color="#1a1a2e", corner_radius=8)
        status_bar.pack(fill="x", padx=10, pady=(5, 0))
        status_bar.pack_propagate(False)

        ctk.CTkLabel(
            status_bar, text="서버:", font=get_font("small"),
            text_color="#888888"
        ).pack(side="left", padx=(10, 5))

        # SD WebUI 상태 dot
        self.sd_dot = ctk.CTkLabel(
            status_bar, text="● SD WebUI", font=get_font("small"),
            text_color="#666666"
        )
        self.sd_dot.pack(side="left", padx=(0, 12))

        # GPT-SoVITS 상태 dot
        self.tts_dot = ctk.CTkLabel(
            status_bar, text="● TTS", font=get_font("small"),
            text_color="#666666"
        )
        self.tts_dot.pack(side="left", padx=(0, 12))

        # Gemini API 상태 dot
        self.story_llm_dot = ctk.CTkLabel(
            status_bar, text="● Story LLM", font=get_font("small"),
            text_color="#666666"
        )
        self.story_llm_dot.pack(side="left", padx=(0, 12))

        # 상태 새로고침 버튼 (우측)
        ctk.CTkButton(
            status_bar, text="🔄", width=28, height=24,
            font=get_font("small"), fg_color="transparent",
            hover_color="gray30",
            command=self._refresh_status_indicators
        ).pack(side="right", padx=5)

        # 비동기 상태 체크 시작
        self.after(1000, self._refresh_status_indicators)

        # 메인 컨테이너 (3단 구조: 좌측 설정 | 중앙 컨트롤 | 우측 로그)
        main_container = ctk.CTkFrame(self.tab_production, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=10, pady=10)

        # === 좌측: 설정 패널 (폭 고정) ===
        left_panel = ctk.CTkFrame(main_container, width=320, fg_color="#1a1a2e")
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)

        left_scroll = ctk.CTkScrollableFrame(left_panel, fg_color="transparent")
        left_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 헤더
        ctk.CTkLabel(
            left_scroll,
            text="⚙️ 설정",
            font=get_font("title", bold=True)
        ).pack(pady=(10, 15))

        # --- 채널 선택 카드 ---
        channel_card = ctk.CTkFrame(left_scroll, fg_color="#252542", corner_radius=10)
        channel_card.pack(fill="x", pady=5, padx=5)

        ctk.CTkLabel(
            channel_card,
            text="📺 채널",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=12, pady=(10, 5))

        # 채널 목록 로드
        self.channel_options = self._load_channel_options()
        self.channel_var = ctk.StringVar(value=self.channel_options[0][0] if self.channel_options else "daily_life_toon")

        channel_row = ctk.CTkFrame(channel_card, fg_color="transparent")
        channel_row.pack(fill="x", padx=10, pady=(0, 10))

        channel_display_names = [opt[1] for opt in self.channel_options]
        self.channel_dropdown = ctk.CTkComboBox(
            channel_row,
            variable=ctk.StringVar(value=channel_display_names[0] if channel_display_names else ""),
            values=channel_display_names,
            width=220,
            height=34,
            font=get_font("normal"),
            command=self._on_channel_selected
        )
        self.channel_dropdown.pack(side="left")

        ctk.CTkButton(
            channel_row, text="🔄", width=34, height=34,
            font=get_font("normal"),
            command=self._refresh_channel_list
        ).pack(side="left", padx=(5, 0))

        # v59.1.0: SD 모델 선택 UI
        sd_model_section = ctk.CTkFrame(channel_card, fg_color="transparent")
        sd_model_section.pack(fill="x", padx=10, pady=(5, 10))

        ctk.CTkLabel(
            sd_model_section,
            text="🎨 SD 모델",
            font=get_font("small"),
            text_color="#AAAAAA"
        ).pack(anchor="w")

        sd_model_row = ctk.CTkFrame(sd_model_section, fg_color="transparent")
        sd_model_row.pack(fill="x", pady=(3, 0))

        self.sd_model_var = ctk.StringVar(value="로딩 중...")
        self.sd_model_dropdown = ctk.CTkComboBox(
            sd_model_row,
            variable=self.sd_model_var,
            values=["로딩 중..."],
            width=220,
            height=30,
            font=get_font("small"),
            command=self._on_sd_model_selected
        )
        self.sd_model_dropdown.pack(side="left")

        ctk.CTkButton(
            sd_model_row, text="🔄", width=30, height=30,
            font=get_font("small"),
            command=self._refresh_sd_models
        ).pack(side="left", padx=(5, 0))

        # SD 모델 상태/안내 레이블
        self.sd_model_status_label = ctk.CTkLabel(
            sd_model_section,
            text="",
            font=get_font("small"),
            text_color="#888888",
            wraplength=260
        )
        self.sd_model_status_label.pack(anchor="w", pady=(3, 0))

        # v59.1.0: SD WebUI 자동 시작 + 모델 목록 초기화 (비동기)
        self.after(500, self._ensure_sd_webui_and_refresh)

        # 라이센스 제한 적용
        self._apply_license_restrictions()

        # --- 생산 설정 카드 ---
        prod_card = ctk.CTkFrame(left_scroll, fg_color="#252542", corner_radius=10)
        prod_card.pack(fill="x", pady=5, padx=5)

        ctk.CTkLabel(
            prod_card,
            text="🎬 생산 설정",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=12, pady=(10, 5))

        # 수량
        qty_row = ctk.CTkFrame(prod_card, fg_color="transparent")
        qty_row.pack(fill="x", padx=12, pady=3)

        ctk.CTkLabel(qty_row, text="수량", width=60, anchor="w", font=get_font("normal")).pack(side="left")
        self.quantity_var = ctk.IntVar(value=1)
        ctk.CTkEntry(
            qty_row, textvariable=self.quantity_var, width=80, height=32, font=get_font("normal")
        ).pack(side="left", padx=5)
        ctk.CTkLabel(qty_row, text="개", width=30, font=get_font("normal")).pack(side="left")

        self.quantity_var.trace_add("write", lambda *args: self._update_estimated_time())

        # 주제 모드
        self.topic_mode_var = ctk.StringVar(value="auto")

        topic_row = ctk.CTkFrame(prod_card, fg_color="transparent")
        topic_row.pack(fill="x", padx=12, pady=5)

        ctk.CTkRadioButton(
            topic_row, text="자동", variable=self.topic_mode_var, value="auto",
            font=get_font("normal"), width=70
        ).pack(side="left")

        ctk.CTkRadioButton(
            topic_row, text="수동", variable=self.topic_mode_var, value="manual",
            font=get_font("normal"), width=70
        ).pack(side="left")

        self.manual_topic_entry = ctk.CTkEntry(
            prod_card,
            placeholder_text="수동 주제 입력...",
            height=32,
            font=get_font("normal")
        )
        self.manual_topic_entry.pack(fill="x", padx=12, pady=(0, 10))

        # --- 옵션 카드 ---
        option_card = ctk.CTkFrame(left_scroll, fg_color="#252542", corner_radius=10)
        option_card.pack(fill="x", pady=5, padx=5)

        ctk.CTkLabel(
            option_card,
            text="🔧 옵션",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=12, pady=(10, 5))

        # 자동 업로드
        self.auto_upload_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            option_card, text="유튜브 자동 업로드",
            variable=self.auto_upload_var,
            font=get_font("normal")
        ).pack(anchor="w", padx=12, pady=3)

        # v53: 업로드 공개 설정
        upload_privacy_row = ctk.CTkFrame(option_card, fg_color="transparent")
        upload_privacy_row.pack(fill="x", padx=12, pady=3)

        ctk.CTkLabel(upload_privacy_row, text="공개 설정", width=65, anchor="w", font=get_font("normal")).pack(side="left")

        self.upload_privacy_var = ctk.StringVar(value="private")
        ctk.CTkOptionMenu(
            upload_privacy_row,
            variable=self.upload_privacy_var,
            values=["private", "unlisted", "public"],
            width=100,
            font=get_font("normal")
        ).pack(side="left", padx=5)

        # v50: 썸네일 팝업 건너뛰기 (자동 진행)
        self.skip_thumbnail_popup_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            option_card, text="썸네일 팝업 건너뛰기",
            variable=self.skip_thumbnail_popup_var,
            font=get_font("normal")
        ).pack(anchor="w", padx=12, pady=3)

        self.resume_from_checkpoint_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            option_card, text="실패 시 체크포인트부터 재개",
            variable=self.resume_from_checkpoint_var,
            font=get_font("normal")
        ).pack(anchor="w", padx=12, pady=3)

        # 템플릿
        template_row = ctk.CTkFrame(option_card, fg_color="transparent")
        template_row.pack(fill="x", padx=12, pady=(5, 10))

        ctk.CTkLabel(template_row, text="템플릿", width=55, anchor="w", font=get_font("normal")).pack(side="left")

        self.template_var = ctk.StringVar(value="기본값")
        templates = self.template_manager.get_template_names()
        template_values = ["기본값"] + templates if templates else ["기본값"]

        self.template_dropdown = ctk.CTkOptionMenu(
            template_row, variable=self.template_var,
            values=template_values, width=160, height=32,
            font=get_font("normal"),
            command=self._on_template_select
        )
        self.template_dropdown.pack(side="left", padx=5)

        # v60.1.0: AI 모드는 Enhanced 고정 (UI 숨김, 변수만 유지)
        self.prompt_mode_var = ctk.StringVar(value="enhanced")
        self.prompt_mode_desc = None  # SettingsMixin 호환용

        # v60.1.0: 프리미엄 변수 유지 (하위 호환, UI 없음)
        self.premium_video_var = ctk.BooleanVar(value=False)

        # v50: 테스트 모드 체크박스 (빠른 검증용 - 1분 영상) - 별도 행
        test_mode_row = ctk.CTkFrame(option_card, fg_color="transparent")
        test_mode_row.pack(fill="x", padx=12, pady=(0, 8))

        self.test_mode_var = ctk.BooleanVar(value=config.TEST_MODE)
        self.test_mode_checkbox = ctk.CTkCheckBox(
            test_mode_row,
            text="🧪 테스트 모드 (약 1분 영상 - 빠른 검증용)",
            variable=self.test_mode_var,
            font=get_font("normal"),
            text_color="#FFA500",
            command=self._on_test_mode_change
        )
        self.test_mode_checkbox.pack(side="left")

        # v59.1.2: Visual Storytelling 체크박스
        vs_row = ctk.CTkFrame(option_card, fg_color="transparent")
        vs_row.pack(fill="x", padx=12, pady=(0, 8))

        # 설정에서 v59 활성화 여부 로드
        vs_enabled = self.settings_manager.get_visual_storytelling_enabled()
        self.visual_storytelling_var = ctk.BooleanVar(value=vs_enabled)
        self.visual_storytelling_checkbox = ctk.CTkCheckBox(
            vs_row,
            text="🎬 v59 Visual Storytelling (캐릭터 일관성 + 씬 분석)",
            variable=self.visual_storytelling_var,
            font=get_font("normal"),
            text_color="#00BFFF",  # DeepSkyBlue
            command=self._on_visual_storytelling_change
        )
        self.visual_storytelling_checkbox.pack(side="left")

        # v59 상태 라벨 (팩 지원 여부 표시)
        self.vs_status_label = ctk.CTkLabel(
            vs_row,
            text="",
            font=get_font("small"),
            text_color="#888888"
        )
        self.vs_status_label.pack(side="left", padx=(10, 0))

        # VideoToon-only mode. Legacy dynamic/video generation is retired.
        vt_row = ctk.CTkFrame(option_card, fg_color="transparent")
        vt_row.pack(fill="x", padx=12, pady=(0, 6))

        vt_enabled = True
        self.settings_manager.set_videotoon_local_enabled(True)
        self.videotoon_local_var = ctk.BooleanVar(value=vt_enabled)
        self.videotoon_local_checkbox = ctk.CTkCheckBox(
            vt_row,
            text="🎞️ 영상툰 전용 모드 (항상 ON)",
            variable=self.videotoon_local_var,
            font=get_font("normal"),
            text_color="#66D9EF",
            command=self._on_videotoon_local_change,
            state="disabled",
        )
        self.videotoon_local_checkbox.pack(side="left")

        self.videotoon_status_label = ctk.CTkLabel(
            vt_row,
            text="",
            font=get_font("small"),
            text_color="#888888",
        )
        self.videotoon_status_label.pack(side="left", padx=(10, 0))

        vt_backend_row = ctk.CTkFrame(option_card, fg_color="transparent")
        vt_backend_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            vt_backend_row,
            text="영상툰 백엔드",
            width=90,
            anchor="w",
            font=get_font("small"),
            text_color="#AAAAAA",
        ).pack(side="left")

        self.videotoon_backend_map = {
            "ComfyUI (권장)": "comfyui",
            "SD WebUI (호환)": "sd_webui",
        }
        current_vt_backend = self.settings_manager.get_videotoon_generation_backend()
        config.VIDEOTOON_LOCAL_MODE_OVERRIDE = vt_enabled
        config.VIDEOTOON_IMAGE_BACKEND = current_vt_backend
        current_vt_label = next(
            (label for label, value in self.videotoon_backend_map.items() if value == current_vt_backend),
            "ComfyUI (권장)",
        )
        self.videotoon_backend_var = ctk.StringVar(value=current_vt_label)
        self.videotoon_backend_dropdown = ctk.CTkOptionMenu(
            vt_backend_row,
            variable=self.videotoon_backend_var,
            values=list(self.videotoon_backend_map.keys()),
            width=150,
            height=28,
            font=get_font("small"),
            command=self._on_videotoon_backend_change,
        )
        self.videotoon_backend_dropdown.pack(side="left", padx=5)

        self.videotoon_progress_label = ctk.CTkLabel(
            option_card,
            text="",
            font=get_font("small"),
            text_color="#888888",
            wraplength=260,
        )
        self.videotoon_progress_label.pack(anchor="w", padx=12, pady=(0, 8))
        self._update_videotoon_status()

        # v63.1: 모션툰 GUI 제거 — 기능 비활성화됨
        # 하위호환: 변수만 유지, UI 없음
        self.motiontoon_render_mode_map = {}
        self.motiontoon_render_mode_var = ctk.StringVar(value="videotoon_layered")
        self.motiontoon_render_mode_dropdown = None
        self.motiontoon_status_label = None
        config.MOTIONTOON_RENDER_MODE_OVERRIDE = "videotoon_layered"

        # v60.1.0: 프리미엄 모드 변수 유지 (하위 호환, UI 없음)
        self.premium_options_frame = None
        self.premium_mode_var = ctk.StringVar(value="speed")
        self.comfyui_status_label = None

        # TTS 엔진 선택값은 설정 탭의 드롭다운과 공유한다.
        current_tts = self.settings_manager.get_tts_engine()
        if current_tts not in {"sovits", "supertonic"}:
            current_tts = "sovits"
        self.tts_engine_var = ctk.StringVar(value=current_tts)
        self.tts_engine_dropdown = None
        self.tts_desc_label = None

        # 음성 설정 변수 유지 (하위 호환)
        self.voice_settings_frame = None
        self.voice_emotion_vars = {}

        # === 중앙: 컨트롤 패널 ===
        center_panel = ctk.CTkFrame(main_container, fg_color="#16213e")
        center_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # 상단: 상태 표시
        status_frame = ctk.CTkFrame(center_panel, fg_color="#1a1a2e", corner_radius=10)
        status_frame.pack(fill="x", padx=15, pady=15)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="⏸️ 대기 중",
            font=get_font("header", bold=True),
            text_color="#888"
        )
        self.status_label.pack(pady=20)

        # 프로그레스
        progress_container = ctk.CTkFrame(status_frame, fg_color="transparent")
        progress_container.pack(fill="x", padx=30, pady=(0, 15))

        self.progress_bar = ctk.CTkProgressBar(progress_container, height=20, corner_radius=10)
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)

        self.progress_percent_label = ctk.CTkLabel(
            status_frame,
            text="0%",
            font=get_font("large", bold=True)
        )
        self.progress_percent_label.pack(pady=(0, 15))

        # 예상 시간
        self.estimated_time_label = ctk.CTkLabel(
            status_frame,
            text="예상 시간: --",
            font=get_font("normal"),
            text_color="#aaaaaa"
        )
        self.estimated_time_label.pack(pady=(0, 10))
        self._update_estimated_time()

        # 컨트롤 버튼
        btn_frame = ctk.CTkFrame(center_panel, fg_color="transparent")
        btn_frame.pack(pady=20)

        self.start_button = ctk.CTkButton(
            btn_frame,
            text="▶️  생산 시작",
            width=280,
            height=60,
            font=get_font("title", bold=True),
            fg_color="#00a86b",
            hover_color="#008855",
            corner_radius=15,
            command=self._start_production
        )
        self.start_button.pack(pady=5)

        # v37: 대본 미리보기 버튼
        self.preview_button = ctk.CTkButton(
            btn_frame,
            text="👁️  대본 미리보기",
            width=280,
            height=45,
            font=get_font("medium"),
            fg_color="#2196F3",
            hover_color="#1976D2",
            corner_radius=10,
            command=self._preview_script
        )
        self.preview_button.pack(pady=5)

        self.stop_button = ctk.CTkButton(
            btn_frame,
            text="⏹  중단",
            width=280,
            height=45,
            font=get_font("medium"),
            fg_color="#c0392b",
            hover_color="#a93226",
            corner_radius=10,
            state="disabled",
            command=self._stop_production
        )
        self.stop_button.pack(pady=5)

        # v58.3: 큐에 추가 버튼
        self.add_queue_button = ctk.CTkButton(
            btn_frame,
            text="➕ 큐에 추가",
            width=280,
            height=45,
            font=get_font("medium"),
            fg_color="#FF9800",
            hover_color="#F57C00",
            corner_radius=10,
            command=self._add_to_queue
        )
        self.add_queue_button.pack(pady=5)

        # 최근 프로젝트
        recent_frame = ctk.CTkFrame(center_panel, fg_color="#1a1a2e", corner_radius=10)
        recent_frame.pack(fill="both", expand=True, padx=15, pady=(10, 15))

        ctk.CTkLabel(
            recent_frame,
            text="📂 최근 프로젝트",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=15, pady=(10, 5))

        self.recent_projects_frame = ctk.CTkScrollableFrame(recent_frame, fg_color="transparent")
        self.recent_projects_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._load_recent_projects()

        # === 우측: 로그 + 자율주행 패널 ===
        right_panel = ctk.CTkFrame(main_container, width=400, fg_color="#1a1a2e")
        right_panel.pack(side="right", fill="y")
        right_panel.pack_propagate(False)

        # v37: AI 자율주행 패널
        try:
            from gui.autopilot_panel import AutopilotPanel
            self.autopilot_panel = AutopilotPanel(
                right_panel,
                on_approve_callback=self._on_autopilot_approve,
                fg_color="#252542",
                corner_radius=10
            )
            self.autopilot_panel.pack(fill="x", padx=10, pady=(10, 5))
        except ImportError:
            self.autopilot_panel = None

        # 로그 헤더
        log_header = ctk.CTkFrame(right_panel, fg_color="transparent")
        log_header.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            log_header,
            text="📝 로그",
            font=get_font("large", bold=True)
        ).pack(side="left")

        ctk.CTkButton(
            log_header, text="지우기", width=70, height=28,
            font=get_font("small"),
            fg_color="#444",
            command=self._clear_log
        ).pack(side="right")

        # 로그 텍스트
        self.log_textbox = ctk.CTkTextbox(
            right_panel,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#0d1117",
            corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 드래그앤드롭 설정
        self._setup_drag_drop()
    
    # v60.1.0: _create_insight_tab, _create_factory_tab 삭제 (v40에서 관리자 GUI로 이동 → dead code)

    def _create_subtitle_tab(self):
        """자막 탭 구성"""
        # SubtitleSettingsTab 클래스 인스턴스 생성
        self.subtitle_tab = SubtitleSettingsTab(
            self.tab_subtitle,
            self.settings_manager,
            config.FONT_PATH
        )
    
    def _create_thumbnail_tab(self):
        """썸네일 탭 구성"""
        # ThumbnailSettingsTab 클래스 인스턴스 생성
        self.thumbnail_tab_widget = ThumbnailSettingsTab(
            self.tab_thumbnail,
            self.settings_manager,
            config.FONT_PATH
        )
        
        # 하단에 테스트 생성 버튼 추가
        test_frame = ctk.CTkFrame(self.tab_thumbnail, fg_color="transparent")
        test_frame.pack(side="bottom", fill="x", padx=20, pady=10)
        
        test_btn = ctk.CTkButton(
            test_frame,
            text="🎨 테스트 생성 (30초)",
            width=200,
            height=40,
            font=get_font("medium", bold=True),
            fg_color="#FF8C00",
            hover_color="#FF6600",
            command=self._on_test_thumbnail
        )
        test_btn.pack()
    
    # v60.1.0: _on_test_thumbnail, _test_thumbnail_worker, _show_test_thumbnail_dialog → SettingsMixin

    def _create_system_tab(self):
        """시스템 탭 구성"""
        # 스크롤 가능한 컨테이너
        system_frame = ctk.CTkScrollableFrame(self.tab_system)
        system_frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_label = ctk.CTkLabel(
            system_frame,
            text="⚙️ 시스템 상태",
            font=get_font("title", bold=True)
        )
        title_label.pack(pady=(0, 20))

        # 라이센스 정보
        license_info_frame = ctk.CTkFrame(system_frame)
        license_info_frame.pack(fill="x", pady=(0, 20), padx=20)

        ctk.CTkLabel(
            license_info_frame,
            text="🔐 라이센스 정보",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 5), padx=10)

        # 개발 모드에서는 self.license_info 사용
        if config.DEV_MODE:
            license_info = self.license_info
        elif hasattr(self, 'license_validator'):
            license_info = self.license_validator.get_license_info()
        else:
            license_info = self.license_info

        if license_info:
            # 개발 모드와 일반 모드에서 키 이름이 다를 수 있음
            status = license_info.get('status', '활성')
            license_key = license_info.get('license_key', license_info.get('hardware_id', 'N/A'))
            hardware_id = license_info.get('hardware_id', 'N/A')
            expire_date = license_info.get('expire_date', 'N/A')
            days_left = license_info.get('days_left', 9999)

            license_text = f"""
✅ 상태: {status}
🔑 라이센스: {license_info.get('license_type_name', license_info.get('license_type', 'N/A'))}
💻 하드웨어 ID: {hardware_id}
📅 만료일: {expire_date}
⏰ 남은 기간: {days_left if days_left < 9999 else '무제한'}일
            """
            text_color = "green" if days_left > 7 else "orange"
        else:
            license_text = "❌ 라이센스 정보 없음"
            text_color = "red"
        
        license_label = ctk.CTkLabel(
            license_info_frame,
            text=license_text,
            font=get_font("normal"),
            justify="left",
            text_color=text_color
        )
        license_label.pack(anchor="w", pady=5, padx=20)
        
        # 라이센스 관리 버튼
        license_btn_frame = ctk.CTkFrame(license_info_frame, fg_color="transparent")
        license_btn_frame.pack(pady=10, padx=20)
        
        def reenter_license():
            if self._show_license_dialog("라이센스 재등록"):
                # 정보 새로고침
                self._create_system_tab()
                messagebox.showinfo("성공", "라이센스가 갱신되었습니다.")
        
        reenter_btn = ctk.CTkButton(
            license_btn_frame,
            text="🔄 라이센스 재등록",
            command=reenter_license
        )
        reenter_btn.pack(side="left", padx=5)
        
        # 구분선
        separator = ctk.CTkFrame(system_frame, height=2, fg_color="gray")
        separator.pack(fill="x", padx=20, pady=20)

        # ==================== 서버 상태 ====================
        status_frame = ctk.CTkFrame(system_frame)
        status_frame.pack(fill="x", pady=(0, 20), padx=20)

        ctk.CTkLabel(
            status_frame,
            text="🖥️ 서버 상태",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 10), padx=10)

        # SD WebUI 상태
        sd_status_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        sd_status_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            sd_status_frame,
            text="SD WebUI:",
            width=120,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left")

        self.sd_status_label = ctk.CTkLabel(
            sd_status_frame,
            text="⏳ 확인 중...",
            text_color="#aaaaaa",
            font=get_font("normal")
        )
        self.sd_status_label.pack(side="left", padx=10)

        self.sd_model_label = ctk.CTkLabel(
            sd_status_frame,
            text="",
            text_color="#aaaaaa",
            font=get_font("small")
        )
        self.sd_model_label.pack(side="left", padx=10)

        # SoVITS 상태
        sovits_status_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        sovits_status_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            sovits_status_frame,
            text="GPT-SoVITS:",
            width=120,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left")

        self.sovits_status_label = ctk.CTkLabel(
            sovits_status_frame,
            text="⏳ 확인 중...",
            text_color="#aaaaaa",
            font=get_font("normal")
        )
        self.sovits_status_label.pack(side="left", padx=10)

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        btn_frame.pack(pady=10)

        # 상태 새로고침 버튼
        refresh_btn = ctk.CTkButton(
            btn_frame,
            text="🔄 상태 새로고침",
            command=self._check_server_status,
            width=130
        )
        refresh_btn.pack(side="left", padx=5)

        # 서버 시작 버튼
        start_servers_btn = ctk.CTkButton(
            btn_frame,
            text="🚀 서버 시작",
            command=self._start_ai_servers,
            width=130,
            fg_color="#2196F3",
            hover_color="#1976D2"
        )
        start_servers_btn.pack(side="left", padx=5)

        # 초기 상태 체크 (백그라운드)
        threading.Thread(target=self._check_server_status, daemon=True).start()

        # 자동 시작 설정 확인
        if config.AUTO_START_SERVERS:
            self.after(2000, self._auto_start_servers)

        # 구분선
        separator_status = ctk.CTkFrame(system_frame, height=2, fg_color="gray")
        separator_status.pack(fill="x", padx=20, pady=20)

        # ==================== API 설정 ====================
        api_settings_frame = ctk.CTkFrame(system_frame)
        api_settings_frame.pack(fill="x", pady=(0, 20), padx=20)

        ctk.CTkLabel(
            api_settings_frame,
            text="🔧 API 설정",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 10), padx=10)

        # SD WebUI 주소
        sd_frame = ctk.CTkFrame(api_settings_frame, fg_color="transparent")
        sd_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            sd_frame,
            text="SD WebUI 주소:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))

        self.sd_url_entry = ctk.CTkEntry(
            sd_frame,
            placeholder_text="http://127.0.0.1:7860",
            height=32,
            font=get_font("normal")
        )
        self.sd_url_entry.insert(0, config.SD_URL)
        self.sd_url_entry.pack(side="left", fill="x", expand=True, padx=5)

        # SoVITS 주소
        sovits_frame = ctk.CTkFrame(api_settings_frame, fg_color="transparent")
        sovits_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            sovits_frame,
            text="SoVITS 주소:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))

        self.sovits_url_entry = ctk.CTkEntry(
            sovits_frame,
            placeholder_text="http://127.0.0.1:9880",
            height=32,
            font=get_font("normal")
        )
        self.sovits_url_entry.insert(0, config.SOVITS_URL)
        self.sovits_url_entry.pack(side="left", fill="x", expand=True, padx=5)

        # TTS 엔진 선택
        tts_engine_frame = ctk.CTkFrame(api_settings_frame, fg_color="transparent")
        tts_engine_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            tts_engine_frame,
            text="TTS 엔진:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))

        self.tts_engine_dropdown = ctk.CTkOptionMenu(
            tts_engine_frame,
            variable=self.tts_engine_var,
            values=["sovits", "supertonic"],
            height=32,
            width=160,
            font=get_font("normal"),
            command=self._on_tts_engine_change,
        )
        self.tts_engine_dropdown.pack(side="left", padx=5)

        self.tts_desc_label = ctk.CTkLabel(
            tts_engine_frame,
            text=self._get_tts_description(self.tts_engine_var.get()),
            anchor="w",
            font=get_font("small"),
            text_color="#AAB2C8",
        )
        self.tts_desc_label.pack(side="left", padx=10)

        # Gemini API 키
        provider_frame = ctk.CTkFrame(api_settings_frame, fg_color="transparent")
        provider_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            provider_frame,
            text="Story LLM:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))

        self.story_llm_provider_var = ctk.StringVar(
            value=getattr(config, "STORY_LLM_PROVIDER", "claude_cli")
        )
        self.story_llm_provider_dropdown = ctk.CTkOptionMenu(
            provider_frame,
            variable=self.story_llm_provider_var,
            values=["gemini", "claude_cli"],
            width=180,
            font=get_font("normal"),
            command=self._update_story_llm_fields_visibility
        )
        self.story_llm_provider_dropdown.pack(side="left", padx=5)

        self.gemini_settings_frame = ctk.CTkFrame(api_settings_frame, fg_color="transparent")
        self.gemini_settings_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            self.gemini_settings_frame,
            text="Gemini API 키:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))

        self.gemini_key_entry = ctk.CTkEntry(
            self.gemini_settings_frame,
            placeholder_text="AIza...",
            show="*",
            height=32,
            font=get_font("normal")
        )
        if config.GEMINI_API_KEY:
            self.gemini_key_entry.insert(0, config.GEMINI_API_KEY)
        self.gemini_key_entry.pack(side="left", fill="x", expand=True, padx=5)

        self.claude_settings_frame = ctk.CTkFrame(api_settings_frame, fg_color="transparent")

        claude_path_frame = ctk.CTkFrame(self.claude_settings_frame, fg_color="transparent")
        claude_path_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(
            claude_path_frame,
            text="Claude CLI 경로:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))
        self.claude_cli_path_entry = ctk.CTkEntry(
            claude_path_frame,
            placeholder_text="claude",
            height=32,
            font=get_font("normal")
        )
        self.claude_cli_path_entry.insert(0, getattr(config, "CLAUDE_CLI_PATH", "claude"))
        self.claude_cli_path_entry.pack(side="left", fill="x", expand=True, padx=5)

        claude_model_frame = ctk.CTkFrame(self.claude_settings_frame, fg_color="transparent")
        claude_model_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(
            claude_model_frame,
            text="Claude 모델:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))
        self.claude_cli_model_entry = ctk.CTkEntry(
            claude_model_frame,
            placeholder_text="sonnet",
            height=32,
            font=get_font("normal")
        )
        self.claude_cli_model_entry.insert(0, getattr(config, "CLAUDE_CLI_MODEL", "sonnet"))
        self.claude_cli_model_entry.pack(side="left", fill="x", expand=True, padx=5)

        timeout_frame = ctk.CTkFrame(self.claude_settings_frame, fg_color="transparent")
        timeout_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(
            timeout_frame,
            text="Story LLM Timeout:",
            width=150,
            anchor="w",
            font=get_font("normal")
        ).pack(side="left", padx=(0, 10))
        self.story_llm_timeout_entry = ctk.CTkEntry(
            timeout_frame,
            placeholder_text="600",
            width=120,
            height=32,
            font=get_font("normal")
        )
        self.story_llm_timeout_entry.insert(0, str(getattr(config, "STORY_LLM_TIMEOUT_SEC", 600)))
        self.story_llm_timeout_entry.pack(side="left", padx=5)

        self._update_story_llm_fields_visibility()

        # 저장 버튼
        save_btn = ctk.CTkButton(
            api_settings_frame,
            text="💾 설정 저장",
            command=self._save_api_settings,
            fg_color="green",
            hover_color="darkgreen",
            height=36,
            font=get_font("normal")
        )
        save_btn.pack(pady=10)

        # 구분선
        separator2 = ctk.CTkFrame(system_frame, height=2, fg_color="gray")
        separator2.pack(fill="x", padx=20, pady=20)

        # ==================== YouTube 자격증명 ====================
        youtube_frame = ctk.CTkFrame(system_frame)
        youtube_frame.pack(fill="x", pady=(0, 20), padx=20)

        ctk.CTkLabel(
            youtube_frame,
            text="📺 YouTube 자격증명",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 10), padx=10)

        # 자격증명 상태 표시
        cred_status_frame = ctk.CTkFrame(youtube_frame, fg_color="transparent")
        cred_status_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            cred_status_frame,
            text="credentials.json:",
            width=150,
            anchor="w"
        ).pack(side="left")

        # 자격증명 파일 경로
        self.youtube_cred_path = os.path.join(config.DATA_DIR, "credentials.json")
        self.youtube_token_path = os.path.join(config.DATA_DIR, "youtube_token.pickle")

        cred_exists = os.path.exists(self.youtube_cred_path)
        self.cred_status_label = ctk.CTkLabel(
            cred_status_frame,
            text="✅ 등록됨" if cred_exists else "❌ 없음",
            text_color="green" if cred_exists else "red"
        )
        self.cred_status_label.pack(side="left", padx=10)

        # 토큰 상태
        token_status_frame = ctk.CTkFrame(youtube_frame, fg_color="transparent")
        token_status_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            token_status_frame,
            text="인증 토큰:",
            width=150,
            anchor="w"
        ).pack(side="left")

        token_exists = os.path.exists(self.youtube_token_path)
        self.token_status_label = ctk.CTkLabel(
            token_status_frame,
            text="✅ 인증됨" if token_exists else "⚠️ 미인증",
            text_color="green" if token_exists else "orange"
        )
        self.token_status_label.pack(side="left", padx=10)

        # 버튼 영역
        youtube_btn_frame = ctk.CTkFrame(youtube_frame, fg_color="transparent")
        youtube_btn_frame.pack(fill="x", padx=20, pady=10)

        # 자격증명 파일 업로드 버튼
        upload_cred_btn = ctk.CTkButton(
            youtube_btn_frame,
            text="📁 credentials.json 등록",
            command=self._upload_youtube_credentials,
            width=180
        )
        upload_cred_btn.pack(side="left", padx=5)

        # OAuth 인증 버튼
        auth_btn = ctk.CTkButton(
            youtube_btn_frame,
            text="🔐 YouTube 인증",
            command=self._authenticate_youtube,
            width=150,
            fg_color="blue",
            hover_color="darkblue"
        )
        auth_btn.pack(side="left", padx=5)

        # 인증 초기화 버튼
        reset_auth_btn = ctk.CTkButton(
            youtube_btn_frame,
            text="🗑️ 인증 초기화",
            command=self._reset_youtube_auth,
            width=120,
            fg_color="gray",
            hover_color="darkgray"
        )
        reset_auth_btn.pack(side="left", padx=5)

        # 도움말
        help_label = ctk.CTkLabel(
            youtube_frame,
            text="💡 Google Cloud Console에서 OAuth 2.0 클라이언트 ID를 생성하고 credentials.json을 다운로드하세요.",
            font=get_font("small"),
            text_color="gray"
        )
        help_label.pack(anchor="w", padx=20, pady=(5, 10))

        # 구분선
        separator3 = ctk.CTkFrame(system_frame, height=2, fg_color="gray")
        separator3.pack(fill="x", padx=20, pady=20)

        # ==================== 채널 브랜딩 설정 (기본 채널 + 커스텀 패키지) ====================
        branding_frame = ctk.CTkFrame(system_frame)
        branding_frame.pack(fill="x", pady=(0, 20), padx=20)

        ctk.CTkLabel(
            branding_frame,
            text="📺 채널 브랜딩 설정",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 10), padx=10)

        # 채널 브랜딩 정보 로드
        branding_path = os.path.join(config.DATA_DIR, "branding.json")
        try:
            if os.path.exists(branding_path):
                with open(branding_path, "r", encoding="utf-8") as f:
                    branding_data = json.load(f)
            else:
                branding_data = {}
        except Exception as e:
            logger.warning(f"브랜딩 데이터 로드 실패: {e}")
            branding_data = {}

        # 채널명/인사말 입력 필드 저장
        self.channel_entries = {}
        self.greeting_entries = {}

        # 스크롤 가능한 프레임
        channels_scroll = ctk.CTkScrollableFrame(branding_frame, height=200, fg_color="transparent")
        channels_scroll.pack(fill="x", padx=10, pady=5)

        # VideoToon-only official channels.
        DEFAULT_CHANNELS = [
            ("daily_life_toon", "🎬 일상 영상툰"),
            ("mystery_toon", "🔎 미스터리 영상툰"),
        ]

        def _create_channel_row(parent, channel_id: str, display_name: str, branding_info: dict):
            """채널 행 UI 생성 헬퍼"""
            ch_frame = ctk.CTkFrame(parent, fg_color="transparent")
            ch_frame.pack(fill="x", pady=3)

            ctk.CTkLabel(
                ch_frame,
                text=f"{display_name}:",
                width=150,
                anchor="w",
                font=get_font("normal")
            ).pack(side="left", padx=(0, 10))

            # 채널명 입력
            ch_entry = ctk.CTkEntry(
                ch_frame,
                width=180,
                placeholder_text="채널명",
                height=32,
                font=get_font("normal")
            )
            ch_entry.insert(0, branding_info.get("channel_name", ""))
            ch_entry.pack(side="left", padx=5)
            self.channel_entries[channel_id] = ch_entry

            ctk.CTkLabel(
                ch_frame,
                text="인사말:",
                width=55,
                anchor="w",
                font=get_font("normal")
            ).pack(side="left", padx=(10, 5))

            # 인사말 입력
            greet_entry = ctk.CTkEntry(
                ch_frame,
                width=280,
                placeholder_text="안녕하세요, OOO입니다.",
                height=32,
                font=get_font("normal")
            )
            openings = branding_info.get("openings", [])
            if openings:
                greet_entry.insert(0, openings[0])
            greet_entry.pack(side="left", padx=5)
            self.greeting_entries[channel_id] = greet_entry

        # 1. 기본 채널 표시
        for channel_id, display_name in DEFAULT_CHANNELS:
            ch_branding = branding_data.get(channel_id, {"channel_name": "", "openings": []})
            _create_channel_row(channels_scroll, channel_id, display_name, ch_branding)

        # 2. 설치된 커스텀 패키지 표시
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            installed_packages = pm.list_installed_packages()

            for pkg_id, pkg_info in installed_packages.items():
                # 기본 채널과 중복 방지
                if pkg_id not in ['daily_life_toon', 'mystery_toon']:
                    pkg_name = pkg_info.get('package_name', pkg_id)
                    channel_id = pkg_info.get('channel_id', pkg_id)
                    ch_branding = branding_data.get(channel_id, {"channel_name": "", "openings": []})
                    _create_channel_row(channels_scroll, channel_id, f"📦 {pkg_name}", ch_branding)

        except Exception as e:
            logger.warning(f"패키지 목록 로드 실패: {e}")

        # 채널 설정 저장 버튼
        channel_btn_frame = ctk.CTkFrame(branding_frame, fg_color="transparent")
        channel_btn_frame.pack(fill="x", padx=20, pady=10)

        save_channel_btn = ctk.CTkButton(
            channel_btn_frame,
            text="💾 채널 설정 저장",
            command=self._save_channel_settings,
            fg_color="green",
            hover_color="darkgreen",
            width=160,
            height=36,
            font=get_font("normal")
        )
        save_channel_btn.pack(side="left", padx=5)

        branding_btn = ctk.CTkButton(
            channel_btn_frame,
            text="📺 상세 설정",
            command=self._open_branding_dialog,
            width=130,
            height=36,
            font=get_font("normal")
        )
        branding_btn.pack(side="left", padx=5)
        
        # 구분선
        separator3 = ctk.CTkFrame(system_frame, height=2, fg_color="gray")
        separator3.pack(fill="x", padx=20, pady=20)
        
        # ==================== 백업/복구 ====================
        backup_frame = ctk.CTkFrame(system_frame)
        backup_frame.pack(fill="x", pady=(0, 20), padx=20)

        ctk.CTkLabel(
            backup_frame,
            text="💾 설정 백업/복구",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", pady=(10, 10), padx=10)

        backup_btn_frame = ctk.CTkFrame(backup_frame, fg_color="transparent")
        backup_btn_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(
            backup_btn_frame,
            text="📥 백업 생성",
            command=self._create_backup,
            width=120
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            backup_btn_frame,
            text="📤 백업 복구",
            command=self._restore_backup,
            width=120
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            backup_btn_frame,
            text="🔄 설정 초기화",
            command=self._reset_settings,
            fg_color="gray",
            hover_color="darkgray",
            width=120
        ).pack(side="left", padx=5)

        # 구분선
        separator4 = ctk.CTkFrame(system_frame, height=2, fg_color="gray")
        separator4.pack(fill="x", padx=20, pady=20)

        # 시스템 정보
        info_text = f"""
🖥️ 작업 디렉토리: {config.BASE_DIR}
📊 데이터 디렉토리: {config.DATA_DIR}
        """

        info_label = ctk.CTkLabel(
            system_frame,
            text=info_text,
            font=get_font("normal"),
            justify="left"
        )
        info_label.pack(pady=10)
    
    # v60.1.0: _save_api_settings, _save_channel_settings, _open_branding_dialog → SettingsMixin

    # ============================================================
    # v60.1.0: 생산 로직 → ProductionMixin
    # _get_channel_mode_from_package, _add_to_queue, _run_queue,
    # _queue_worker, _activate_pack_for_job, _auto_upload_video,
    # _start_production, _production_worker, _thumbnail_callback,
    # _preview_script, _show_preview_dialog, _start_production_with_plan,
    # _stop_production, _on_autopilot_approve → ProductionMixin
    # ============================================================

    def _update_progress(self, message: str, percent: int):
        """진행 상황 업데이트 (스레드 안전)"""
        # v60.1.0: Tkinter는 비thread-safe → 반드시 메인 스레드에서 실행
        import threading
        if threading.current_thread() is not threading.main_thread():
            self.after(0, lambda m=message, p=percent: self._update_progress(m, p))
            return
        try:
            if getattr(self, "_is_shutting_down", False) or not self.winfo_exists():
                return
            self.status_label.configure(text=message)
            self.progress_bar.set(percent / 100.0)
            self.progress_percent_label.configure(text=f"{percent}%")
            self.update_idletasks()
        except Exception:
            pass

    def _add_log(self, message: str):
        """로그 추가 (GUI + 파일, 스레드 안전)"""
        # v60.1.0: Tkinter는 비thread-safe → 반드시 메인 스레드에서 실행
        import threading
        if threading.current_thread() is not threading.main_thread():
            self.after(0, lambda m=message: self._add_log(m))
            return
        # GUI에 표시 (log_textbox가 있을 때만)
        if hasattr(self, 'log_textbox') and self.log_textbox:
            self.log_textbox.insert("end", message + "\n")
            self.log_textbox.see("end")
            self.update_idletasks()

        # 파일 로그에도 기록 (이모지 제거하여 인코딩 문제 방지)
        import re
        log_message = re.sub(r'[^\x00-\x7F\uAC00-\uD7A3]+', '', message).strip()
        if not log_message:
            log_message = "log entry"

        if "오류" in message or "실패" in message:
            logger.error(log_message)
        elif "경고" in message:
            logger.warning(log_message)
        else:
            logger.info(log_message)
    
    def _refresh_status_indicators(self):
        """v60.1.0: 서버 상태 인디케이터 비동기 업데이트"""
        def _check():
            results = {}
            # SD WebUI 체크
            results["sd"] = probe_http_endpoints(
                config.SD_URL,
                ["/sdapi/v1/options"],
                timeout=3,
            )
            # GPT-SoVITS 체크
            sovits_url = getattr(config, 'SOVITS_URL', 'http://127.0.0.1:9880')
            results["tts"] = probe_http_endpoints(
                sovits_url,
                ["/", "/docs", "/ping", "/openapi.json"],
                timeout=3,
            )
            # Gemini API 체크
            provider = getattr(config, 'STORY_LLM_PROVIDER', 'claude_cli')
            if provider == "claude":
                provider = "claude_cli"
            results["story_llm_provider"] = provider
            if provider == "claude_cli":
                cli_path = getattr(config, 'CLAUDE_CLI_PATH', 'claude')
                results["story_llm_ready"] = bool(shutil.which(cli_path) or os.path.exists(cli_path))
                results["story_llm_label"] = "Claude CLI"
            else:
                results["story_llm_ready"] = bool(getattr(config, 'GEMINI_API_KEY', ''))
                results["story_llm_label"] = "Gemini API"
            # UI 업데이트 (메인 스레드에서)
            try:
                if getattr(self, "_is_shutting_down", False) or not self.winfo_exists():
                    return
                self.after(0, lambda: self._apply_status_dots(results))
            except RuntimeError:
                return

        threading.Thread(target=_check, daemon=True).start()

    def _apply_status_dots(self, results: dict):
        """v60.1.0: 서버 상태 dot 색상 업데이트"""
        try:
            green = "#4CAF50"
            red = "#F44336"
            yellow = "#FF9800"
            if hasattr(self, 'sd_dot'):
                self.sd_dot.configure(text_color=green if results.get("sd") else red)
            if hasattr(self, 'tts_dot'):
                self.tts_dot.configure(text_color=green if results.get("tts") else red)
            if hasattr(self, 'story_llm_dot'):
                ready = results.get("story_llm_ready", False)
                label = results.get("story_llm_label", "Story LLM")
                self.story_llm_dot.configure(
                    text=f"● {label}",
                    text_color=green if ready else yellow
                )
        except Exception:
            pass  # 창 닫힌 경우 무시

    def _on_app_close(self):
        """Shut down app-managed AI servers before closing the GUI."""
        if getattr(self, "is_producing", False):
            if not messagebox.askyesno(
                "종료 확인",
                "현재 작업이 진행 중입니다. 종료하면서 백그라운드 서버도 함께 종료할까요?",
            ):
                self._is_shutting_down = False
                return

        self._is_shutting_down = True
        try:
            shutdown_results = {}
            try:
                from utils.server_manager import get_server_manager, stop_registered_processes

                manager = get_server_manager()
                shutdown_results.update(
                    manager.stop_all_servers(["SD WebUI", "GPT-SoVITS", "ComfyUI"])
                )
                shutdown_results.update(
                    stop_registered_processes(["SD WebUI", "GPT-SoVITS", "ComfyUI"])
                )
            except Exception as e:
                logger.warning(f"[main_window] managed server shutdown failed: {e}")

            if shutdown_results:
                self._add_log(f"[EXIT] managed server shutdown: {shutdown_results}")
        finally:
            self.destroy()

    def _clear_log(self):
        """로그 지우기"""
        if hasattr(self, 'log_textbox') and self.log_textbox:
            try:
                self.log_textbox.delete("1.0", "end")
            except Exception:
                pass

    # v60.1.0: _create_backup, _restore_backup, _reset_settings → SettingsMixin

    # v60.1.0: _show_license_dialog → AuthMixin

    # v60.1.0: _check_server_status → ServerMixin (gui/mixins/server_mixin.py)

    # v60.1.0: _start_ai_servers, _auto_start_servers → ServerMixin

    # v60.1.0: _upload_youtube_credentials → AuthMixin
    # v60.1.0: _authenticate_youtube → AuthMixin
    # v60.1.0: _reset_youtube_auth → AuthMixin

    # v60.1.0: _quality_gate → ProductionMixin


    # ============================================================
    # 새로운 기능 메서드들
    # ============================================================

    # v60.1.0: _open_stats_dashboard, _open_queue_manager, _open_template_dialog, _refresh_template_list → SettingsMixin

    # v60.1.0: _open_model_manager → SDModelMixin
    # v60.1.0: _on_model_changed → SDModelMixin
    # v60.1.0: _open_sd_model_manager → SDModelMixin

    # v56.1: _open_training_wizard() → 관리자 GUI로 이동 (license_generator_gui.py)
    # 음성 학습은 VRAM을 독점하므로 배포용 Studio에서 제거
    # _on_training_complete() 콜백도 함께 제거

    # v56.1: _open_admin_dashboard() → 관리자 GUI로 이동 (license_generator_gui.py)
    # Admin Dashboard는 B2B 전용이므로 배포용 Studio에서 제거

    # v60.1.0: _open_package_menu, _open_package_import, _show_installed_packages, _on_package_imported → SettingsMixin

    # v56.1: _open_package_export() → 관리자 GUI로 이동 (license_generator_gui.py)
    # v57.7.6: _open_pack_creator() → 관리자 전용으로 이동 (사용자는 팩 생성 불가)
    # 패키지 내보내기는 관리자 전용 기능

    # v56.1: _on_package_exported() → 관리자 GUI로 이동

    # v60.1.0: _load_revpack_to_studio, _ask_revpack_topic, _open_editor_with_revpack → SettingsMixin

    # v60.1.0: _open_youtube_analytics, _open_auto_optimizer, _toggle_theme → SettingsMixin

    # v60.1.0: _on_prompt_mode_change, _on_tts_engine_change, _get_tts_description → SettingsMixin
    # v60.1.0: _on_premium_mode_change, _on_test_mode_change → SettingsMixin
    # v60.1.0: _on_visual_storytelling_change, _update_vs_status → SettingsMixin

    # v60.1.0: _check_comfyui_status, _boot_comfyui → ServerMixin

    # v60.1.0: _on_template_select, _update_estimated_time, _load_recent_projects → SettingsMixin

    # v60.1.0: _setup_drag_drop, _on_file_drop, _save_current_as_template, _show_language_dialog → SettingsMixin

    # ==================== v37: 동적 채널 관리 ====================

    # v60.1.0: _load_channel_options → ChannelMixin
    # v60.1.0: _on_channel_selected → ChannelMixin
    # v60.1.0: _load_default_pack_for_basic_channel → ChannelMixin
    # v60.1.0: _refresh_channel_list → ChannelMixin

    # ==================== v60.1.0: SD 모델 관리 → SDModelMixin ====================
    # _ensure_sd_webui_and_refresh → SDModelMixin
    # _refresh_sd_models → SDModelMixin
    # _update_sd_model_dropdown → SDModelMixin
    # _update_sd_model_status → SDModelMixin
    # _on_sd_model_selected → SDModelMixin

    # v60.1.0: _apply_license_restrictions → AuthMixin

    # v60.1.0: _apply_package_settings → ChannelMixin
    # v60.1.0: _load_package_to_active_pack → ChannelMixin
    # v60.1.0: _load_revpack_to_active → ChannelMixin
    # v60.1.0: _update_voice_settings_visibility → ChannelMixin


def main():
    """GUI 실행"""
    app = ReverieGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
