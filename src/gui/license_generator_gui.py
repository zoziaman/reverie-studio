# src/gui/license_generator_gui.py
"""
라이센스 관리 GUI (관리자 전용)

관리자용 라이센스 키 생성/관리 도구
- 라이센스 생성
- 발급 내역 관리 (조회, 연장, 삭제)
- 라이센스 검증
- 패키지 관리 (v37)
- Insight 탭: 트렌드 분석, AI 분석, 딥 분석 (v38)
- Factory 탭: 채널 팩 설계, .revpack 생성 (v39)

v39 변경사항:
- Factory 탭 추가 (팩 설계 AI)
- Insight → Factory 연동 (분석 결과를 Factory로 전송)
"""
import customtkinter as ctk
import os
import json
import datetime
import hmac
import logging
import threading
from tkinter import messagebox
from typing import Optional, Dict, List, Any, Callable

logger = logging.getLogger(__name__)

from utils.license_generator import LicenseGenerator
from utils.hardware_id import get_hardware_id
from config.settings import config

# Firebase 연동 (선택적)
try:
    from utils.firebase_license import FirebaseLicenseValidator
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

# Insight 모듈 (선택적)
try:
    from insight.insight_tab import InsightTab
    INSIGHT_AVAILABLE = True
except ImportError:
    INSIGHT_AVAILABLE = False

# Factory 모듈 (선택적) - v1.1.0 추가
try:
    from factory.factory_tab import FactoryTab
    FACTORY_AVAILABLE = True
except ImportError:
    FACTORY_AVAILABLE = False

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

def _get_license_history_file() -> str:
    """Return the runtime license history path, never the source tree path."""
    return os.path.join(config.DATA_DIR, "license_history.json")


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


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class LicenseManagerGUI(ctk.CTk):
    """라이센스 관리 GUI"""

    def __init__(self):
        super().__init__()

        self.title("Reverie Automation - 라이센스 관리자")
        self.geometry("1000x800")
        self.resizable(True, True)
        self.minsize(900, 700)

        # 테마 설정
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        try:
            self._ensure_admin_access()
        except PermissionError as exc:
            self.withdraw()
            messagebox.showerror("관리자 인증", str(exc))
            self.after(0, self.destroy)
            raise

        # 생성기 초기화
        self.generator = LicenseGenerator()

        # Firebase 검증기 초기화
        self.firebase_validator = None
        if FIREBASE_AVAILABLE:
            try:
                self.firebase_validator = FirebaseLicenseValidator()
                if not self.firebase_validator.is_available():
                    self.firebase_validator = None
            except Exception as e:
                print(f"Firebase 초기화 실패: {e}")
                self.firebase_validator = None

        # 발급 내역 저장 경로는 런타임 data/를 사용한다. src/data는 배포 소스 영역이다.
        self.history_file = _get_license_history_file()

        # 발급 내역 로드
        self.license_history: List[Dict] = self._load_history()
        self._ai_prompt_thread = None
        self._ai_prompt_result = None
        self._ai_prompt_error = None
        self._ai_prompt_concept = ""
        self._async_jobs: Dict[str, Dict[str, Any]] = {}

        # UI 구성
        self._create_widgets()

    def _ensure_admin_access(self):
        """Require an explicit admin session before the tool opens."""
        if not _is_truthy_env("REVERIE_ADMIN_ENABLED"):
            raise PermissionError("REVERIE_ADMIN_ENABLED=1 이 필요합니다.")

        admin_secret = os.environ.get("REVERIE_ADMIN_PASSWORD", "").strip()
        if not admin_secret:
            admin_secret = os.environ.get("REVERIE_SECRET_KEY", "").strip()
        if not admin_secret:
            raise PermissionError("REVERIE_SECRET_KEY 또는 REVERIE_ADMIN_PASSWORD 가 필요합니다.")

        if _is_truthy_env("REVERIE_ADMIN_SKIP_PROMPT"):
            return

        dialog = ctk.CTkInputDialog(
            text="관리자 암호를 입력하세요.",
            title="관리자 인증",
        )
        entered = (dialog.get_input() or "").strip()
        if not entered or not hmac.compare_digest(entered, admin_secret):
            raise PermissionError("관리자 인증에 실패했습니다.")

    def _safe_after(self, delay_ms: int, callback: Callable[[], None]):
        try:
            if self.winfo_exists():
                self.after(delay_ms, callback)
        except Exception:
            return None
        return None

    def _start_async_job(
        self,
        job_name: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Optional[Callable[[Exception], None]] = None,
        on_finally: Optional[Callable[[], None]] = None,
        busy_callback: Optional[Callable[[], None]] = None,
    ):
        current = self._async_jobs.get(job_name)
        if current and not current.get("done", False):
            return

        if busy_callback is not None:
            busy_callback()

        job_state: Dict[str, Any] = {
            "done": False,
            "result": None,
            "error": None,
        }
        self._async_jobs[job_name] = job_state

        def worker():
            try:
                job_state["result"] = task()
            except Exception as exc:
                job_state["error"] = exc
            finally:
                job_state["done"] = True

        threading.Thread(target=worker, daemon=True).start()
        self._safe_after(
            50,
            lambda: self._poll_async_job(job_name, on_success, on_error, on_finally),
        )

    def _poll_async_job(
        self,
        job_name: str,
        on_success: Callable[[Any], None],
        on_error: Optional[Callable[[Exception], None]],
        on_finally: Optional[Callable[[], None]],
    ):
        job_state = self._async_jobs.get(job_name)
        if not job_state:
            return

        if not job_state.get("done", False):
            self._safe_after(
                50,
                lambda: self._poll_async_job(job_name, on_success, on_error, on_finally),
            )
            return

        self._async_jobs.pop(job_name, None)
        error = job_state.get("error")
        result = job_state.get("result")

        try:
            if error is not None:
                if on_error is not None:
                    on_error(error)
            else:
                on_success(result)
        finally:
            if on_finally is not None:
                on_finally()

    def _create_widgets(self):
        """위젯 생성"""
        # 탭뷰 생성
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        # 탭 추가
        self.tab_generate = self.tabview.add("라이센스 생성")
        self.tab_manage = self.tabview.add("발급 내역 관리")
        self.tab_verify = self.tabview.add("라이센스 검증")
        self.tab_package = self.tabview.add("패키지 관리")  # v37 추가
        self.tab_firebase = self.tabview.add("Firebase 서버")
        self.tab_insight = self.tabview.add("🔍 Insight")  # Insight 1.0.0 추가
        self.tab_factory = self.tabview.add("🏭 Factory")  # Factory 1.1.0 추가
        # v56.1: 배포용 GUI에서 이동된 관리자 전용 기능들
        self.tab_admin = self.tabview.add("🏢 Admin")  # B2B 대시보드
        self.tab_training = self.tabview.add("🎓 학습")  # 음성 모델 학습

        # 각 탭 UI 구성
        self._create_generate_tab()
        self._create_manage_tab()
        self._create_verify_tab()
        self._create_package_tab()  # v37 추가
        self._create_firebase_tab()
        self._create_insight_tab()  # Insight 1.0.0 추가
        self._create_factory_tab()  # Factory 1.1.0 추가
        # v56.1: 관리자 전용 탭
        self._create_admin_tab()
        self._create_training_tab()

    # ============================================================
    # 라이센스 생성 탭
    # ============================================================
    def _create_generate_tab(self):
        """라이센스 생성 탭 UI"""
        main_frame = ctk.CTkScrollableFrame(self.tab_generate)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 제목
        title_label = ctk.CTkLabel(
            main_frame,
            text="새 라이센스 생성",
            font=get_font("title", bold=True)
        )
        title_label.pack(pady=(0, 15))

        # 경고 문구
        warning_frame = ctk.CTkFrame(main_frame, fg_color="#8B0000")
        warning_frame.pack(fill="x", pady=(0, 15))

        warning_label = ctk.CTkLabel(
            warning_frame,
            text="[관리자 전용] 이 도구는 배포하지 마세요!",
            font=get_font("medium", bold=True),
            text_color="white"
        )
        warning_label.pack(pady=8)

        # === 사용자 정보 섹션 ===
        info_section = ctk.CTkFrame(main_frame)
        info_section.pack(fill="x", pady=8)

        ctk.CTkLabel(
            info_section,
            text="사용자 정보",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        # 사용자 ID
        user_frame = ctk.CTkFrame(info_section, fg_color="transparent")
        user_frame.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(user_frame, text="사용자 ID:", width=110, font=get_font("normal")).pack(side="left")
        self.user_id_entry = ctk.CTkEntry(user_frame, placeholder_text="이메일 또는 이름", width=260, height=32, font=get_font("normal"))
        self.user_id_entry.pack(side="left", padx=5)

        # 메모
        memo_frame = ctk.CTkFrame(info_section, fg_color="transparent")
        memo_frame.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(memo_frame, text="메모:", width=110, font=get_font("normal")).pack(side="left")
        self.memo_entry = ctk.CTkEntry(memo_frame, placeholder_text="결제정보, 연락처 등 (선택)", width=360, height=32, font=get_font("normal"))
        self.memo_entry.pack(side="left", padx=5)

        # 하드웨어 ID
        hw_frame = ctk.CTkFrame(info_section, fg_color="transparent")
        hw_frame.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(hw_frame, text="하드웨어 ID:", width=110, font=get_font("normal")).pack(side="left")
        self.hw_id_entry = ctk.CTkEntry(hw_frame, placeholder_text="16자리 하드웨어 ID", width=210, height=32, font=get_font("normal"))
        self.hw_id_entry.pack(side="left", padx=5)

        get_hw_btn = ctk.CTkButton(
            hw_frame,
            text="현재 PC",
            width=80,
            height=32,
            font=get_font("normal"),
            command=self._get_current_hw_id
        )
        get_hw_btn.pack(side="left", padx=5)

        # === 라이센스 옵션 섹션 ===
        option_section = ctk.CTkFrame(main_frame)
        option_section.pack(fill="x", pady=8)

        ctk.CTkLabel(
            option_section,
            text="라이센스 옵션",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        # === 포함할 패키지 선택 ===
        pack_frame = ctk.CTkFrame(option_section, fg_color="transparent")
        pack_frame.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(pack_frame, text="포함할 패키지:", width=110, font=get_font("normal")).pack(side="left", anchor="n")

        pack_checkboxes_frame = ctk.CTkFrame(pack_frame, fg_color="transparent")
        pack_checkboxes_frame.pack(side="left", fill="x", expand=True)

        # 패키지 체크박스 (동적 로드)
        self.pack_vars = {}

        # Firebase 또는 패키지 매니저에서 사용 가능한 패키지 목록 로드
        available_packs = self._load_available_packs()

        for pack_id, pack_name in available_packs:
            var = ctk.BooleanVar(value=True)  # 기본값: 선택됨
            self.pack_vars[pack_id] = var
            ctk.CTkCheckBox(
                pack_checkboxes_frame,
                text=pack_name,
                variable=var,
                font=get_font("normal")
            ).pack(anchor="w", pady=2)

        # 패키지가 없으면 안내 메시지
        if not available_packs:
            ctk.CTkLabel(
                pack_checkboxes_frame,
                text="📭 등록된 패키지가 없습니다.",
                font=get_font("normal"),
                text_color="#aaaaaa"
            ).pack(anchor="w", pady=5)

        # 전체 선택/해제 버튼
        select_btn_frame = ctk.CTkFrame(pack_checkboxes_frame, fg_color="transparent")
        select_btn_frame.pack(anchor="w", pady=5)

        ctk.CTkButton(
            select_btn_frame, text="전체 선택", width=90, height=30,
            font=get_font("normal"),
            command=lambda: self._toggle_all_packs(True)
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            select_btn_frame, text="전체 해제", width=90, height=30,
            font=get_font("normal"),
            fg_color="gray40",
            command=lambda: self._toggle_all_packs(False)
        ).pack(side="left", padx=2)

        # 유효 기간
        duration_frame = ctk.CTkFrame(option_section, fg_color="transparent")
        duration_frame.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(duration_frame, text="유효 기간:", width=110, font=get_font("normal")).pack(side="left")
        self.duration_var = ctk.StringVar(value="30일 (1개월)")
        self.duration_combo = ctk.CTkComboBox(
            duration_frame,
            values=[
                "30일 (1개월)",
                "90일 (3개월)",
                "180일 (6개월)",
                "365일 (1년)",
                "직접 입력"
            ],
            variable=self.duration_var,
            command=self._on_duration_change,
            width=190,
            height=32,
            font=get_font("normal")
        )
        self.duration_combo.pack(side="left", padx=5)

        # 직접 입력 필드
        self.custom_duration_frame = ctk.CTkFrame(option_section, fg_color="transparent")

        ctk.CTkLabel(self.custom_duration_frame, text="일 수:", width=110, font=get_font("normal")).pack(side="left")
        self.custom_duration_entry = ctk.CTkEntry(
            self.custom_duration_frame,
            placeholder_text="일 수 입력",
            width=90,
            height=32,
            font=get_font("normal")
        )
        self.custom_duration_entry.pack(side="left", padx=5)
        ctk.CTkLabel(self.custom_duration_frame, text="일", font=get_font("normal")).pack(side="left")

        # === 생성 버튼 ===
        generate_btn = ctk.CTkButton(
            main_frame,
            text="라이센스 키 생성",
            font=get_font("medium", bold=True),
            height=45,
            command=self._generate_license
        )
        generate_btn.pack(fill="x", pady=15)

        # === 결과 섹션 ===
        result_section = ctk.CTkFrame(main_frame)
        result_section.pack(fill="x", pady=8)

        ctk.CTkLabel(
            result_section,
            text="생성된 라이센스",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        # 라이센스 키 표시
        key_frame = ctk.CTkFrame(result_section, fg_color="transparent")
        key_frame.pack(fill="x", padx=10, pady=3)

        self.license_key_entry = ctk.CTkEntry(
            key_frame,
            font=get_font("medium", bold=True),
            height=38
        )
        self.license_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        copy_btn = ctk.CTkButton(
            key_frame,
            text="복사",
            width=80,
            height=38,
            font=get_font("normal"),
            command=self._copy_license
        )
        copy_btn.pack(side="left")

        # 라이센스 정보 표시
        self.info_text = ctk.CTkTextbox(result_section, height=120, font=get_font("normal"))
        self.info_text.pack(fill="x", padx=10, pady=8)

        # 상태 메시지
        self.gen_status_label = ctk.CTkLabel(main_frame, text="", font=get_font("normal"))
        self.gen_status_label.pack(pady=3)

    # ============================================================
    # 발급 내역 관리 탭
    # ============================================================
    def _create_manage_tab(self):
        """발급 내역 관리 탭 UI"""
        main_frame = ctk.CTkFrame(self.tab_manage)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 상단: 제목 + 버튼
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            header_frame,
            text="발급 내역",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # 데이터 소스 선택
        self.data_source_var = ctk.StringVar(value="Firebase")
        ctk.CTkLabel(header_frame, text="  데이터 소스:").pack(side="left", padx=(20, 5))
        source_combo = ctk.CTkComboBox(
            header_frame,
            values=["Firebase", "로컬"],
            variable=self.data_source_var,
            width=100,
            command=lambda v: self._refresh_history()
        )
        source_combo.pack(side="left", padx=5)

        # 버튼들
        btn_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        btn_frame.pack(side="right")

        refresh_btn = ctk.CTkButton(
            btn_frame, text="새로고침", width=80, height=30,
            command=self._refresh_history
        )
        refresh_btn.pack(side="left", padx=3)

        export_btn = ctk.CTkButton(
            btn_frame, text="내보내기", width=80, height=30,
            fg_color="gray40",
            command=self._export_history
        )
        export_btn.pack(side="left", padx=3)

        # 검색 프레임
        search_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        search_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(search_frame, text="검색:").pack(side="left", padx=(0, 5))
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="사용자 ID, 메모로 검색...", width=250)
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind("<Return>", lambda e: self._search_history())

        search_btn = ctk.CTkButton(
            search_frame, text="검색", width=60, height=28,
            command=self._search_history
        )
        search_btn.pack(side="left", padx=5)

        clear_btn = ctk.CTkButton(
            search_frame, text="초기화", width=60, height=28,
            fg_color="gray40",
            command=self._clear_search
        )
        clear_btn.pack(side="left", padx=5)

        # 필터
        ctk.CTkLabel(search_frame, text="  상태:").pack(side="left", padx=(20, 5))
        self.filter_var = ctk.StringVar(value="전체")
        filter_combo = ctk.CTkComboBox(
            search_frame,
            values=["전체", "유효", "만료", "곧 만료 (7일 이내)"],
            variable=self.filter_var,
            width=150,
            command=lambda v: self._refresh_history()
        )
        filter_combo.pack(side="left", padx=5)

        # 라이센스 목록 (스크롤)
        list_frame = ctk.CTkScrollableFrame(main_frame, height=350)
        list_frame.pack(fill="both", expand=True, pady=5)

        # 헤더
        header_row = ctk.CTkFrame(list_frame, fg_color="#333333")
        header_row.pack(fill="x", pady=(0, 5))

        headers = [("사용자", 100), ("하드웨어 ID", 120), ("보유 팩", 120),
                   ("만료일", 85), ("상태", 60), ("메모", 100), ("액션", 160)]

        for text, width in headers:
            ctk.CTkLabel(
                header_row, text=text, width=width,
                font=ctk.CTkFont(size=11, weight="bold")
            ).pack(side="left", padx=2, pady=5)

        # 목록 컨테이너
        self.history_list_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
        self.history_list_frame.pack(fill="both", expand=True)

        # 목록 표시
        self._refresh_history()

        # 선택된 라이센스 정보
        detail_frame = ctk.CTkFrame(main_frame)
        detail_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            detail_frame,
            text="선택된 라이센스 상세",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=10, pady=5)

        self.detail_text = ctk.CTkTextbox(detail_frame, height=100)
        self.detail_text.pack(fill="x", padx=10, pady=5)

    # ============================================================
    # 라이센스 검증 탭
    # ============================================================
    def _create_verify_tab(self):
        """라이센스 검증 탭 UI"""
        main_frame = ctk.CTkScrollableFrame(self.tab_verify)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            main_frame,
            text="라이센스 키 검증",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(0, 15))

        # 라이센스 키 입력
        input_frame = ctk.CTkFrame(main_frame)
        input_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(input_frame, text="라이센스 키:").pack(anchor="w", padx=10, pady=5)

        key_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        key_frame.pack(fill="x", padx=10, pady=5)

        self.verify_key_entry = ctk.CTkEntry(
            key_frame,
            placeholder_text="XXXXX-XXXXX-XXXXX-X-XXXXX 형식",
            height=35
        )
        self.verify_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        verify_btn = ctk.CTkButton(
            key_frame,
            text="검증",
            width=80,
            command=self._verify_license
        )
        verify_btn.pack(side="left")

        # 하드웨어 ID 입력 (선택)
        hw_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        hw_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(hw_frame, text="하드웨어 ID (선택):", width=130).pack(side="left")
        self.verify_hw_entry = ctk.CTkEntry(hw_frame, placeholder_text="비워두면 현재 PC로 검증", width=200)
        self.verify_hw_entry.pack(side="left", padx=5)

        get_hw_btn2 = ctk.CTkButton(
            hw_frame, text="현재 PC", width=70, height=28,
            command=lambda: self._fill_hw_entry(self.verify_hw_entry)
        )
        get_hw_btn2.pack(side="left", padx=5)

        # 검증 결과
        result_frame = ctk.CTkFrame(main_frame)
        result_frame.pack(fill="x", pady=15)

        ctk.CTkLabel(
            result_frame,
            text="검증 결과",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=5)

        self.verify_result_text = ctk.CTkTextbox(result_frame, height=200)
        self.verify_result_text.pack(fill="x", padx=10, pady=10)

    # ============================================================
    # 라이센스 생성 관련 메서드
    # ============================================================
    def _get_current_hw_id(self):
        """현재 PC의 하드웨어 ID 가져오기"""
        try:
            hw_id = get_hardware_id()
            self.hw_id_entry.delete(0, "end")
            self.hw_id_entry.insert(0, hw_id)
            self._show_gen_status("현재 PC의 하드웨어 ID를 가져왔습니다.", "green")
        except Exception as e:
            self._show_gen_status(f"하드웨어 ID 가져오기 실패: {e}", "red")

    def _fill_hw_entry(self, entry):
        """하드웨어 ID 입력란 채우기"""
        try:
            hw_id = get_hardware_id()
            entry.delete(0, "end")
            entry.insert(0, hw_id)
        except Exception as e:
            messagebox.showerror("오류", f"하드웨어 ID 가져오기 실패: {e}")

    def _on_duration_change(self, value):
        """유효 기간 선택 변경"""
        if value == "직접 입력":
            self.custom_duration_frame.pack(fill="x", padx=10, pady=3)
        else:
            self.custom_duration_frame.pack_forget()

    def _get_duration_days(self) -> int:
        """선택된 유효 기간 (일) 반환"""
        duration_str = self.duration_var.get()

        if duration_str == "직접 입력":
            try:
                return int(self.custom_duration_entry.get())
            except ValueError:
                return 30
        elif "30일" in duration_str:
            return 30
        elif "90일" in duration_str:
            return 90
        elif "180일" in duration_str:
            return 180
        elif "365일" in duration_str:
            return 365
        else:
            return 30

    def _get_selected_packs(self) -> list:
        """선택된 패키지 목록 반환"""
        selected = []
        for pack_id, var in self.pack_vars.items():
            if var.get():
                selected.append(pack_id)
        return selected

    def _load_available_packs(self) -> List[tuple]:
        """사용 가능한 패키지 목록 로드 (Firebase + 패키지 매니저)"""
        packs = []

        # 1. 패키지 매니저에서 설치된 패키지 가져오기
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            installed = pm.list_installed_packages()

            for pkg_id, pkg_info in installed.items():
                pkg_name = pkg_info.get('package_name', pkg_id)
                pack_id = pkg_info.get('package_id', pkg_id)
                packs.append((pack_id, f"📦 {pkg_name}"))
        except Exception as e:
            print(f"패키지 매니저 로드 실패: {e}")

        # 2. Firebase에서 추가 패키지 가져오기
        if self.firebase_validator and self.firebase_validator.is_available():
            try:
                registered_packs = self.firebase_validator.get_registered_packages()
                existing_ids = [p[0] for p in packs]

                for pack_id in registered_packs:
                    if pack_id not in existing_ids:
                        packs.append((pack_id, f"📦 {pack_id}"))
            except Exception as e:
                print(f"Firebase 패키지 로드 실패: {e}")

        return packs

    def _toggle_all_packs(self, select: bool):
        """모든 팩 체크박스 선택/해제"""
        for var in self.pack_vars.values():
            var.set(select)

    def _generate_license(self):
        """라이센스 키 생성 - 팩 기반"""
        user_id = self.user_id_entry.get().strip()
        hardware_id = self.hw_id_entry.get().strip().upper()
        memo = self.memo_entry.get().strip()

        if not user_id:
            self._show_gen_status("사용자 ID를 입력하세요.", "red")
            return

        if len(hardware_id) != 16:
            self._show_gen_status("하드웨어 ID는 정확히 16자여야 합니다.", "red")
            return

        # 선택된 팩 확인
        selected_packs = self._get_selected_packs()
        if not selected_packs:
            self._show_gen_status("최소 1개 이상의 패키지를 선택하세요.", "red")
            return

        try:
            duration = self._get_duration_days()

            # 라이센스 키 생성 (타입 없이)
            license_key = self.generator.generate(
                user_id=user_id,
                hardware_id=hardware_id,
                duration_days=duration,
                license_type='P'  # P = Pack-based (팩 기반)
            )

            # 결과 표시
            self.license_key_entry.delete(0, "end")
            self.license_key_entry.insert(0, license_key)

            expire_date = datetime.datetime.now() + datetime.timedelta(days=duration)

            # 팩 이름 매핑
            pack_display_names = {
                'daily_life_toon_pack': '일상 영상툰',
                'mystery_toon_pack': '미스터리 영상툰'
            }
            pack_names = [pack_display_names.get(p, p) for p in selected_packs]

            info_text = f"""사용자: {user_id}
하드웨어 ID: {hardware_id}
포함 패키지: {', '.join(pack_names)} ({len(selected_packs)}개)
유효 기간: {duration}일 / 만료일: {expire_date.strftime('%Y-%m-%d')}
메모: {memo if memo else '없음'}"""

            self.info_text.delete("1.0", "end")
            self.info_text.insert("1.0", info_text)

            # 발급 내역에 추가
            self._add_to_history({
                "user_id": user_id,
                "hardware_id": hardware_id,
                "license_key": license_key,
                "owned_packs": selected_packs,
                "duration": duration,
                "expire_date": expire_date.strftime('%Y-%m-%d'),
                "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "memo": memo
            })

            # Firebase에도 자동 등록
            fb_msg = ""
            if self.firebase_validator and self.firebase_validator.is_available():
                try:
                    fb_success, fb_result = self.firebase_validator.register_license(
                        license_key=license_key,
                        user_id=user_id,
                        hardware_id=hardware_id,
                        license_type='P',  # 팩 기반
                        duration_days=duration,
                        memo=memo,
                        owned_packs=selected_packs
                    )
                    fb_msg = " + Firebase 동기화 완료" if fb_success else f" (Firebase 실패: {fb_result})"
                except Exception as e:
                    fb_msg = f" (Firebase 오류: {e})"

            self._show_gen_status(f"라이센스 키가 생성되었습니다! (팩 {len(selected_packs)}개){fb_msg}", "green")

            # 입력 필드 초기화 (선택)
            # self.user_id_entry.delete(0, "end")
            # self.memo_entry.delete(0, "end")

        except Exception as e:
            self._show_gen_status(f"라이센스 생성 실패: {e}", "red")

    def _copy_license(self):
        """라이센스 키 클립보드에 복사"""
        license_key = self.license_key_entry.get()

        if license_key:
            self.clipboard_clear()
            self.clipboard_append(license_key)
            self._show_gen_status("라이센스 키가 클립보드에 복사되었습니다!", "green")
        else:
            self._show_gen_status("복사할 라이센스 키가 없습니다.", "red")

    def _show_gen_status(self, message: str, color: str = "white"):
        """생성 탭 상태 메시지 표시"""
        self.gen_status_label.configure(text=message, text_color=color)

    # ============================================================
    # 발급 내역 관련 메서드
    # ============================================================
    def _load_history(self) -> List[Dict]:
        """발급 내역 로드"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"이력 JSON 로드 실패: {e}")
        return []

    def _save_history(self):
        """발급 내역 저장"""
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.license_history, f, ensure_ascii=False, indent=2)

    def _add_to_history(self, record: Dict):
        """발급 내역에 추가"""
        self.license_history.insert(0, record)  # 최신순
        self._save_history()
        self._refresh_history()

    def _refresh_history(self):
        """발급 내역 새로고침 - Firebase 또는 로컬"""
        # 데이터 소스 확인
        use_firebase = hasattr(self, 'data_source_var') and self.data_source_var.get() == "Firebase"

        # 데이터 로드
        if use_firebase and self.firebase_validator and self.firebase_validator.is_available():
            # Firebase에서 라이센스 목록 가져오기
            try:
                firebase_licenses = self.firebase_validator.get_all_licenses()
                # Firebase 데이터를 로컬 형식으로 변환
                data_source = []
                for lic in firebase_licenses:
                    expire_date = lic.get('expire_date')
                    if expire_date:
                        if hasattr(expire_date, 'strftime'):
                            expire_str = expire_date.strftime('%Y-%m-%d')
                        else:
                            expire_str = str(expire_date)[:10]
                    else:
                        expire_str = ""

                    data_source.append({
                        "user_id": lic.get('user_id', ''),
                        "hardware_id": lic.get('hardware_id', ''),
                        "license_key": lic.get('license_key', ''),
                        "license_type": lic.get('license_type', 'A'),
                        "expire_date": expire_str,
                        "is_active": lic.get('is_active', True),
                        "memo": lic.get('memo', ''),
                        "owned_packs": lic.get('owned_packs', []),
                        "source": "firebase"
                    })
            except Exception as e:
                ctk.CTkLabel(
                    self.history_list_frame,
                    text=f"Firebase 데이터 로드 실패: {e}",
                    text_color="red"
                ).pack(pady=20)
                return
        else:
            # 로컬 파일에서 로드
            data_source = self.license_history

        # 기존 목록 삭제는 데이터 로드 성공 후 수행한다.
        # Firebase 일시 장애가 기존 정상 목록을 빈 목록처럼 보이게 만들면 운영 판단을 흐린다.
        for widget in self.history_list_frame.winfo_children():
            widget.destroy()

        # 필터링
        filter_val = self.filter_var.get()
        search_val = self.search_entry.get().strip().lower() if hasattr(self, 'search_entry') else ""

        today = datetime.datetime.now()
        filtered = []

        for record in data_source:
            # 검색 필터
            if search_val:
                if search_val not in record.get("user_id", "").lower() and \
                   search_val not in record.get("memo", "").lower():
                    continue

            # 상태 필터
            try:
                expire_str = record.get("expire_date", "")
                if expire_str:
                    expire_date = datetime.datetime.strptime(expire_str, '%Y-%m-%d')
                    days_left = (expire_date - today).days

                    if filter_val == "유효" and days_left < 0:
                        continue
                    elif filter_val == "만료" and days_left >= 0:
                        continue
                    elif filter_val == "곧 만료 (7일 이내)" and (days_left < 0 or days_left > 7):
                        continue
            except (ValueError, TypeError) as e:
                logger.debug(f"필터링 날짜 비교 실패: {e}")

            filtered.append(record)

        # 목록 표시
        if not filtered:
            source_name = "Firebase" if use_firebase else "로컬"
            ctk.CTkLabel(
                self.history_list_frame,
                text=f"발급 내역이 없습니다. ({source_name})",
                text_color="gray"
            ).pack(pady=20)
            return

        for i, record in enumerate(filtered):
            self._create_history_row(record, i)

    def _create_history_row(self, record: Dict, index: int):
        """발급 내역 행 생성"""
        row_color = "#2b2b2b" if index % 2 == 0 else "#333333"
        row = ctk.CTkFrame(self.history_list_frame, fg_color=row_color, height=35)
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        # 상태 계산
        try:
            expire_date = datetime.datetime.strptime(record.get("expire_date", ""), '%Y-%m-%d')
            days_left = (expire_date - datetime.datetime.now()).days

            if days_left < 0:
                status = "만료"
                status_color = "red"
            elif days_left <= 7:
                status = f"{days_left}일"
                status_color = "orange"
            else:
                status = "유효"
                status_color = "green"
        except Exception:
            status = "?"
            status_color = "gray"

        # 보유 팩 표시
        owned_packs = record.get("owned_packs", [])
        if owned_packs:
            # 팩 이름 축약
            pack_abbr = {
                'daily_life_toon_pack': '🎬',
                'mystery_toon_pack': '🔎'
            }
            pack_display = ''.join([pack_abbr.get(p, '📦') for p in owned_packs[:5]])
            if len(owned_packs) > 5:
                pack_display += f"+{len(owned_packs)-5}"
        else:
            # 레거시: license_type으로 폴백
            type_abbr = {'A': '전체', 'H': '👻', 'T': '💝', 'M': '😱', 'P': '📦'}
            pack_display = type_abbr.get(record.get("license_type", "?"), "?")

        # 데이터 표시
        data = [
            (record.get("user_id", "")[:12], 100),
            (record.get("hardware_id", "")[:14], 120),
            (pack_display, 120),
            (record.get("expire_date", ""), 85),
        ]

        for text, width in data:
            ctk.CTkLabel(
                row, text=text, width=width,
                font=ctk.CTkFont(size=10)
            ).pack(side="left", padx=2)

        # 상태 (색상)
        ctk.CTkLabel(
            row, text=status, width=60,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=status_color
        ).pack(side="left", padx=2)

        # 메모
        memo = record.get("memo", "")[:12]
        ctk.CTkLabel(
            row, text=memo, width=100,
            font=ctk.CTkFont(size=10)
        ).pack(side="left", padx=2)

        # 액션 버튼
        action_frame = ctk.CTkFrame(row, fg_color="transparent", width=170)
        action_frame.pack(side="left", padx=2)

        # 수정 버튼
        edit_btn = ctk.CTkButton(
            action_frame, text="수정", width=45, height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#1565C0",
            command=lambda r=record: self._edit_license(r)
        )
        edit_btn.pack(side="left", padx=1)

        # 연장 버튼
        extend_btn = ctk.CTkButton(
            action_frame, text="연장", width=45, height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#2E7D32",
            command=lambda r=record: self._extend_license(r)
        )
        extend_btn.pack(side="left", padx=1)

        # 삭제 버튼
        delete_btn = ctk.CTkButton(
            action_frame, text="삭제", width=45, height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#C62828",
            command=lambda r=record: self._delete_license(r)
        )
        delete_btn.pack(side="left", padx=1)

        # 클릭 시 상세 정보 표시
        row.bind("<Button-1>", lambda e, r=record: self._show_detail(r))
        for child in row.winfo_children():
            if not isinstance(child, ctk.CTkButton):
                child.bind("<Button-1>", lambda e, r=record: self._show_detail(r))

    def _show_detail(self, record: Dict):
        """상세 정보 표시"""
        # 보유 팩 정보
        owned_packs = record.get('owned_packs', [])
        pack_names = {
            'daily_life_toon_pack': '일상 영상툰',
            'mystery_toon_pack': '미스터리 영상툰'
        }

        if owned_packs:
            packs_display = ', '.join([pack_names.get(p, p) for p in owned_packs])
            packs_display = f"{packs_display} ({len(owned_packs)}개)"
        else:
            # 레거시 타입으로 폴백
            type_names = {'A': '전체 이용권', 'H': '공포', 'T': '감동', 'M': '막장', 'P': '팩 기반'}
            packs_display = type_names.get(record.get('license_type', ''), '미설정')

        detail = f"""사용자 ID: {record.get('user_id', '')}
하드웨어 ID: {record.get('hardware_id', '')}
라이센스 키: {record.get('license_key', '')}
보유 패키지: {packs_display}
유효 기간: {record.get('duration', '')}일
만료일: {record.get('expire_date', '')}
생성일: {record.get('created_at', '')}
메모: {record.get('memo', '없음')}"""

        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", detail)

    def _edit_license(self, record: Dict):
        """라이센스 정보 수정"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("라이센스 정보 수정")
        dialog.geometry("500x550")
        dialog.transient(self)
        dialog.grab_set()

        # 중앙 배치
        dialog.update_idletasks()
        x = (self.winfo_screenwidth() - 500) // 2
        y = (self.winfo_screenheight() - 550) // 2
        dialog.geometry(f"500x550+{x}+{y}")

        # 스크롤 가능한 프레임
        main_frame = ctk.CTkScrollableFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        ctk.CTkLabel(
            main_frame,
            text="라이센스 정보 수정",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(0, 15))

        # 사용자 ID
        ctk.CTkLabel(main_frame, text="사용자 ID:", anchor="w").pack(fill="x", pady=(5, 0))
        user_entry = ctk.CTkEntry(main_frame, width=400)
        user_entry.insert(0, record.get('user_id', ''))
        user_entry.pack(fill="x", pady=(0, 10))

        # 하드웨어 ID (읽기 전용 - 변경 시 새 라이센스 필요)
        ctk.CTkLabel(main_frame, text="하드웨어 ID: (변경 불가)", anchor="w", text_color="gray").pack(fill="x", pady=(5, 0))
        hw_label = ctk.CTkEntry(main_frame, width=400, state="disabled")
        hw_label.configure(state="normal")
        hw_label.insert(0, record.get('hardware_id', ''))
        hw_label.configure(state="disabled")
        hw_label.pack(fill="x", pady=(0, 10))

        # 라이센스 키 (읽기 전용)
        ctk.CTkLabel(main_frame, text="라이센스 키: (변경 불가)", anchor="w", text_color="gray").pack(fill="x", pady=(5, 0))
        key_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        key_frame.pack(fill="x", pady=(0, 10))

        key_entry = ctk.CTkEntry(key_frame, width=330, state="disabled")
        key_entry.configure(state="normal")
        key_entry.insert(0, record.get('license_key', ''))
        key_entry.configure(state="disabled")
        key_entry.pack(side="left")

        def copy_key():
            self.clipboard_clear()
            self.clipboard_append(record.get('license_key', ''))
            messagebox.showinfo("복사 완료", "라이센스 키가 클립보드에 복사되었습니다.")

        ctk.CTkButton(key_frame, text="복사", width=70, height=32, font=get_font("normal"), command=copy_key).pack(side="left", padx=5)

        # 보유 팩 표시 (읽기 전용)
        ctk.CTkLabel(main_frame, text="보유 팩:", anchor="w", font=get_font("normal")).pack(fill="x", pady=(5, 0))
        owned_packs = record.get('owned_packs', [])
        if owned_packs:
            packs_text = ", ".join([f"📦 {p}" for p in owned_packs])
        else:
            packs_text = "(정보 없음)"
        ctk.CTkLabel(
            main_frame,
            text=packs_text,
            font=get_font("normal"),
            text_color="#aaaaaa",
            wraplength=400
        ).pack(anchor="w", pady=(0, 10))

        # 만료일
        ctk.CTkLabel(main_frame, text="만료일:", anchor="w").pack(fill="x", pady=(5, 0))
        expire_entry = ctk.CTkEntry(main_frame, width=150, placeholder_text="YYYY-MM-DD")
        expire_entry.insert(0, record.get('expire_date', ''))
        expire_entry.pack(anchor="w", pady=(0, 10))

        # 메모
        ctk.CTkLabel(main_frame, text="메모:", anchor="w").pack(fill="x", pady=(5, 0))
        memo_text = ctk.CTkTextbox(main_frame, height=100, width=400)
        memo_text.insert("1.0", record.get('memo', ''))
        memo_text.pack(fill="x", pady=(0, 10))

        # 변경 이력 추가 옵션
        add_log_var = ctk.BooleanVar(value=True)
        add_log_check = ctk.CTkCheckBox(
            main_frame,
            text="변경 이력 자동 추가 (메모에 수정일시 기록)",
            variable=add_log_var
        )
        add_log_check.pack(anchor="w", pady=10)

        def save_changes():
            try:
                new_user_id = user_entry.get().strip()
                new_expire = expire_entry.get().strip()
                new_memo = memo_text.get("1.0", "end").strip()

                # 만료일 형식 검증
                try:
                    datetime.datetime.strptime(new_expire, '%Y-%m-%d')
                except ValueError:
                    messagebox.showerror("오류", "만료일 형식이 잘못되었습니다. (YYYY-MM-DD)")
                    return

                # 변경 이력 추가
                if add_log_var.get():
                    change_log = f"\n[수정됨 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}]"
                    new_memo += change_log

                # 내역에서 찾아서 업데이트
                for r in self.license_history:
                    if r.get('license_key') == record.get('license_key'):
                        r['user_id'] = new_user_id
                        r['expire_date'] = new_expire
                        r['memo'] = new_memo
                        break

                self._save_history()
                self._refresh_history()
                dialog.destroy()

                messagebox.showinfo("저장 완료", "라이센스 정보가 수정되었습니다.")

            except Exception as e:
                messagebox.showerror("오류", f"저장 실패: {e}")

        # 버튼
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=15)

        ctk.CTkButton(
            btn_frame, text="저장", width=100,
            fg_color="#1565C0",
            command=save_changes
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="취소", width=100,
            fg_color="gray",
            command=dialog.destroy
        ).pack(side="left", padx=10)

    def _extend_license(self, record: Dict):
        """라이센스 연장"""
        # 연장 다이얼로그
        dialog = ctk.CTkToplevel(self)
        dialog.title("라이센스 연장")
        dialog.geometry("400x250")
        dialog.transient(self)
        dialog.grab_set()

        # 중앙 배치
        dialog.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 250) // 2
        dialog.geometry(f"400x250+{x}+{y}")

        ctk.CTkLabel(
            dialog,
            text=f"'{record.get('user_id', '')}' 라이센스 연장",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=15)

        ctk.CTkLabel(
            dialog,
            text=f"현재 만료일: {record.get('expire_date', '')}"
        ).pack(pady=5)

        # 연장 기간 선택
        duration_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        duration_frame.pack(pady=15)

        ctk.CTkLabel(duration_frame, text="연장 기간:").pack(side="left", padx=5)

        extend_var = ctk.StringVar(value="30")
        extend_combo = ctk.CTkComboBox(
            duration_frame,
            values=["30", "60", "90", "180", "365"],
            variable=extend_var,
            width=100
        )
        extend_combo.pack(side="left", padx=5)

        ctk.CTkLabel(duration_frame, text="일").pack(side="left", padx=5)

        def do_extend():
            try:
                days = int(extend_var.get())

                # 새 라이센스 생성
                new_license_key = self.generator.generate(
                    user_id=record.get('user_id', ''),
                    hardware_id=record.get('hardware_id', ''),
                    duration_days=days,
                    license_type=record.get('license_type', 'A')
                )

                new_expire = datetime.datetime.now() + datetime.timedelta(days=days)

                # 기존 내역에서 찾아서 업데이트
                for r in self.license_history:
                    if r.get('license_key') == record.get('license_key'):
                        r['license_key'] = new_license_key
                        r['expire_date'] = new_expire.strftime('%Y-%m-%d')
                        r['duration'] = days
                        r['memo'] = f"{r.get('memo', '')} [연장됨 {datetime.datetime.now().strftime('%Y-%m-%d')}]"
                        break

                self._save_history()
                self._refresh_history()

                dialog.destroy()

                # 새 키 표시
                messagebox.showinfo(
                    "연장 완료",
                    f"라이센스가 연장되었습니다.\n\n새 라이센스 키:\n{new_license_key}\n\n새 만료일: {new_expire.strftime('%Y-%m-%d')}"
                )

            except Exception as e:
                messagebox.showerror("오류", f"연장 실패: {e}")

        # 버튼
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=20)

        ctk.CTkButton(
            btn_frame, text="연장하기", width=100,
            fg_color="#2E7D32",
            command=do_extend
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="취소", width=100,
            fg_color="gray",
            command=dialog.destroy
        ).pack(side="left", padx=10)

    def _delete_license(self, record: Dict):
        """라이센스 삭제"""
        if messagebox.askyesno(
            "삭제 확인",
            f"'{record.get('user_id', '')}' 라이센스를 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없습니다."
        ):
            self.license_history = [r for r in self.license_history
                                    if r.get('license_key') != record.get('license_key')]
            self._save_history()
            self._refresh_history()
            self.detail_text.delete("1.0", "end")
            messagebox.showinfo("삭제 완료", "라이센스가 삭제되었습니다.")

    def _search_history(self):
        """검색 실행"""
        self._refresh_history()

    def _clear_search(self):
        """검색 초기화"""
        self.search_entry.delete(0, "end")
        self.filter_var.set("전체")
        self._refresh_history()

    def _export_history(self):
        """발급 내역 내보내기"""
        from tkinter import filedialog

        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 파일", "*.json"), ("CSV 파일", "*.csv")],
            title="발급 내역 내보내기"
        )

        if not filepath:
            return

        try:
            if filepath.endswith(".csv"):
                import csv
                with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        'user_id', 'hardware_id', 'license_key', 'license_type',
                        'duration', 'expire_date', 'created_at', 'memo'
                    ])
                    writer.writeheader()
                    writer.writerows(self.license_history)
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.license_history, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("내보내기 완료", f"발급 내역이 저장되었습니다.\n{filepath}")

        except Exception as e:
            messagebox.showerror("오류", f"내보내기 실패: {e}")

    # ============================================================
    # 라이센스 검증 관련 메서드
    # ============================================================
    def _verify_license(self):
        """라이센스 검증"""
        license_key = self.verify_key_entry.get().strip().upper()
        hardware_id = self.verify_hw_entry.get().strip().upper()

        if not license_key:
            self.verify_result_text.delete("1.0", "end")
            self.verify_result_text.insert("1.0", "라이센스 키를 입력하세요.")
            return

        # 하드웨어 ID가 비어있으면 현재 PC 사용
        if not hardware_id:
            try:
                hardware_id = get_hardware_id()
            except Exception:
                hardware_id = "UNKNOWN_HW_ID___"

        # 디코딩
        decoded = self.generator.decode_license(license_key)

        if "error" in decoded:
            result = f"오류: {decoded['error']}"
        else:
            # 상세 검증
            import hashlib

            parts = license_key.split('-')
            if len(parts) != 5:
                result = "형식 오류: 라이센스 키 형식이 잘못되었습니다."
            else:
                user_hash, expire_encoded, hw_hash, l_type, verification = parts

                # 하드웨어 검증
                current_hw_hash = hashlib.sha256(hardware_id.encode()).hexdigest()[:5].upper()
                hw_match = hw_hash == current_hw_hash

                # 만료일 확인
                try:
                    expire_int = int(expire_encoded, 36)
                    expire_str = str(expire_int).zfill(8)
                    expire_date = datetime.datetime.strptime(expire_str, "%Y%m%d")
                    days_left = (expire_date - datetime.datetime.now()).days
                    expired = days_left < 0
                except Exception:
                    expire_date = None
                    days_left = 0
                    expired = True

                # 검증 해시 확인
                secret_key = self.generator.secret_key
                verification_string = f"{user_hash}{expire_encoded}{hw_hash}{l_type}{secret_key}"
                expected_verification = hashlib.sha256(verification_string.encode()).hexdigest()[:5].upper()
                valid_hash = verification == expected_verification

                # 타입 이름
                type_names = {
                    'A': '전체 이용',
                    'H': '공포 채널',
                    'T': '감동 채널',
                    'M': '막장 채널',
                    'P': '팩 기반',
                }

                result = f"""라이센스 검증 결과
{'=' * 50}

[기본 정보]
라이센스 키: {license_key}
검증 대상 하드웨어 ID: {hardware_id}

[디코딩 정보]
사용자 해시: {user_hash}
하드웨어 해시: {hw_hash}
라이센스 타입: {type_names.get(l_type, '알 수 없음')} ({l_type})
만료일: {expire_date.strftime('%Y-%m-%d') if expire_date else '파싱 오류'}
남은 일수: {days_left}일

[검증 결과]
해시 검증: {'통과' if valid_hash else '실패 (변조됨)'}
하드웨어 일치: {'일치' if hw_match else '불일치'}
만료 상태: {'유효' if not expired else '만료됨'}

{'=' * 50}
최종 결과: {'유효한 라이센스입니다.' if (valid_hash and hw_match and not expired) else '무효한 라이센스입니다.'}"""

        self.verify_result_text.delete("1.0", "end")
        self.verify_result_text.insert("1.0", result)

    # ============================================================
    # 패키지 관리 탭 (v37) - AI 기반 패키지 생성
    # ============================================================
    def _create_package_tab(self):
        """패키지 관리 탭 UI - AI 패키지 생성기"""
        main_frame = ctk.CTkScrollableFrame(self.tab_package)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="AI 채널 패키지 생성기",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=(0, 5))

        ctk.CTkLabel(
            main_frame,
            text="원하는 채널 컨셉을 입력하면 AI가 자동으로 프롬프트를 생성합니다",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(pady=(0, 15))

        # === 기본 팩 자동 생성 섹션 ===
        default_section = ctk.CTkFrame(main_frame, fg_color="#1a2e1a")
        default_section.pack(fill="x", pady=10)

        ctk.CTkLabel(
            default_section,
            text="🎁 기본 팩 자동 생성",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            default_section,
            text="공포/감동/막장 기본 3개 팩을 한번에 생성합니다 (기존 프로필 사용)",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 5))

        ctk.CTkButton(
            default_section,
            text="🚀 기본 팩 3개 자동 생성",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=35,
            fg_color="#2E7D32",
            command=self._create_default_packs
        ).pack(fill="x", padx=10, pady=10)

        # === AI 패키지 생성 섹션 ===
        create_section = ctk.CTkFrame(main_frame)
        create_section.pack(fill="x", pady=10)

        ctk.CTkLabel(
            create_section,
            text="1단계: 채널 컨셉 입력",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        # 채널 컨셉 입력
        row0 = ctk.CTkFrame(create_section, fg_color="transparent")
        row0.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row0, text="채널 컨셉:", width=100).pack(side="left")
        self.pkg_concept_entry = ctk.CTkEntry(
            row0, width=400,
            placeholder_text="예: 로맨스 드라마, 국내 역사, 해외 미스터리, SF 공상과학..."
        )
        self.pkg_concept_entry.pack(side="left", padx=5)

        # AI 생성 버튼
        ai_generate_btn = ctk.CTkButton(
            create_section, text="🤖 AI가 프롬프트 생성", width=200, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#9C27B0",
            command=self._generate_prompts_with_ai
        )
        ai_generate_btn.pack(fill="x", padx=10, pady=10)

        # 2단계 라벨
        ctk.CTkLabel(
            create_section,
            text="2단계: 패키지 정보 확인/수정",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(15, 5))

        ctk.CTkLabel(
            create_section,
            text="AI가 생성한 정보를 확인하고 필요시 수정하세요",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 5))

        # 패키지 ID
        row1 = ctk.CTkFrame(create_section, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row1, text="패키지 ID:", width=100).pack(side="left")
        self.pkg_id_entry = ctk.CTkEntry(row1, width=250, placeholder_text="예: daily_life_toon_pack")
        self.pkg_id_entry.pack(side="left", padx=5)
        ctk.CTkLabel(row1, text="(Firebase owned_packs에 사용됨)", text_color="gray", font=ctk.CTkFont(size=10)).pack(side="left", padx=5)

        # 패키지 이름
        row2 = ctk.CTkFrame(create_section, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row2, text="표시 이름:", width=100).pack(side="left")
        self.pkg_name_entry = ctk.CTkEntry(row2, width=250, placeholder_text="예: 공포 스토리 채널 팩")
        self.pkg_name_entry.pack(side="left", padx=5)

        # 버전
        row4 = ctk.CTkFrame(create_section, fg_color="transparent")
        row4.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row4, text="버전:", width=100).pack(side="left")
        self.pkg_version_entry = ctk.CTkEntry(row4, width=100, placeholder_text="1.0.0")
        self.pkg_version_entry.insert(0, "1.0.0")
        self.pkg_version_entry.pack(side="left", padx=5)

        # 설명
        row5 = ctk.CTkFrame(create_section, fg_color="transparent")
        row5.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row5, text="설명:", width=100).pack(side="left", anchor="n")
        self.pkg_desc_text = ctk.CTkTextbox(row5, height=60, width=350)
        self.pkg_desc_text.pack(side="left", padx=5)

        # === AI 생성 결과 미리보기 ===
        preview_section = ctk.CTkFrame(create_section, fg_color="#1a1a2e")
        preview_section.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(
            preview_section,
            text="AI 생성 결과 미리보기",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.pkg_preview_text = ctk.CTkTextbox(preview_section, height=180, width=450)
        self.pkg_preview_text.pack(fill="x", padx=10, pady=(0, 10))
        self.pkg_preview_text.insert("1.0", "채널 컨셉을 입력하고 'AI가 프롬프트 생성' 버튼을 누르세요.\n\n예시:\n- 로맨스 드라마\n- 국내 역사\n- 해외 미스터리\n- SF 공상과학\n- 판타지 모험")

        # 옵션들
        row6 = ctk.CTkFrame(create_section, fg_color="transparent")
        row6.pack(fill="x", padx=10, pady=5)

        self.pkg_encrypt_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row6, text="AES-256 암호화",
            variable=self.pkg_encrypt_var,
            font=get_font("normal")
        ).pack(side="left")

        self.pkg_firebase_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row6, text="Firebase 등록",
            variable=self.pkg_firebase_var,
            font=get_font("normal")
        ).pack(side="left", padx=15)

        self.pkg_auto_install_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row6, text="생성 후 자동 설치",
            variable=self.pkg_auto_install_var,
            font=get_font("normal")
        ).pack(side="left", padx=15)

        # 3단계 라벨
        ctk.CTkLabel(
            create_section,
            text="3단계: 패키지 생성",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(15, 5))

        # 생성 버튼
        ctk.CTkButton(
            create_section,
            text="패키지 생성 (.revpack)",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            fg_color="#2E7D32",
            command=self._create_package
        ).pack(fill="x", padx=10, pady=10)

        # === 라이센스에 패키지 연결 섹션 ===
        link_section = ctk.CTkFrame(main_frame)
        link_section.pack(fill="x", pady=10)

        ctk.CTkLabel(
            link_section,
            text="라이센스에 패키지 연결",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            link_section,
            text="특정 라이센스의 owned_packs에 패키지 ID를 추가합니다",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 5))

        # 라이센스 키
        row_lic = ctk.CTkFrame(link_section, fg_color="transparent")
        row_lic.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_lic, text="라이센스 키:", width=100).pack(side="left")
        self.link_license_entry = ctk.CTkEntry(row_lic, width=300, placeholder_text="XXXXX-XXXXX-XXXXX-X-XXXXX")
        self.link_license_entry.pack(side="left", padx=5)

        # 패키지 ID (추가할)
        row_pkg = ctk.CTkFrame(link_section, fg_color="transparent")
        row_pkg.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_pkg, text="패키지 ID:", width=100).pack(side="left")
        self.link_package_entry = ctk.CTkEntry(row_pkg, width=200, placeholder_text="예: daily_life_toon_pack")
        self.link_package_entry.pack(side="left", padx=5)

        # 버튼들
        btn_frame = ctk.CTkFrame(link_section, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(
            btn_frame, text="패키지 추가", width=100,
            fg_color="#2E7D32",
            command=self._add_package_to_license
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="패키지 제거", width=100,
            fg_color="#C62828",
            command=self._remove_package_from_license
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="보유 패키지 조회", width=120,
            fg_color="#1565C0",
            command=self._view_license_packages
        ).pack(side="left", padx=5)

        # === 패키지 배포 현황 섹션 ===
        dist_section = ctk.CTkFrame(main_frame)
        dist_section.pack(fill="x", pady=10)

        dist_header = ctk.CTkFrame(dist_section, fg_color="transparent")
        dist_header.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            dist_header,
            text="📊 패키지 배포 현황",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            dist_header, text="통계 새로고침", width=100,
            command=self._refresh_distribution_stats
        ).pack(side="right")

        # 통계 프레임
        self.dist_stats_frame = ctk.CTkFrame(dist_section, fg_color="#1a1a2e")
        self.dist_stats_frame.pack(fill="x", padx=10, pady=5)

        # 초기 텍스트
        self.dist_stats_label = ctk.CTkLabel(
            self.dist_stats_frame,
            text="통계 로드 중...",
            font=ctk.CTkFont(size=11)
        )
        self.dist_stats_label.pack(pady=10)

        # === 일괄 배포 섹션 ===
        bulk_section = ctk.CTkFrame(main_frame)
        bulk_section.pack(fill="x", pady=10)

        ctk.CTkLabel(
            bulk_section,
            text="🚀 일괄 배포",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            bulk_section,
            text="선택한 모든 라이센스에 패키지를 한번에 추가/제거합니다",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 5))

        # 패키지 선택
        bulk_row1 = ctk.CTkFrame(bulk_section, fg_color="transparent")
        bulk_row1.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(bulk_row1, text="배포할 패키지:", width=100).pack(side="left")
        self.bulk_package_var = ctk.StringVar(value="")
        self.bulk_package_combo = ctk.CTkComboBox(
            bulk_row1,
            values=["daily_life_toon_pack", "mystery_toon_pack"],
            variable=self.bulk_package_var,
            width=200
        )
        self.bulk_package_combo.pack(side="left", padx=5)

        ctk.CTkButton(
            bulk_row1, text="목록 갱신", width=80, height=28,
            command=self._refresh_bulk_package_list
        ).pack(side="left", padx=5)

        # 대상 선택
        bulk_row2 = ctk.CTkFrame(bulk_section, fg_color="transparent")
        bulk_row2.pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(bulk_row2, text="대상 선택:", width=100).pack(side="left")
        self.bulk_target_var = ctk.StringVar(value="active")
        ctk.CTkRadioButton(
            bulk_row2, text="활성 라이센스", variable=self.bulk_target_var, value="active"
        ).pack(side="left", padx=5)
        ctk.CTkRadioButton(
            bulk_row2, text="모든 라이센스", variable=self.bulk_target_var, value="all"
        ).pack(side="left", padx=5)

        # 일괄 액션 버튼
        bulk_btn_frame = ctk.CTkFrame(bulk_section, fg_color="transparent")
        bulk_btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(
            bulk_btn_frame, text="📦 일괄 추가", width=120,
            fg_color="#2E7D32",
            command=self._bulk_add_package
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            bulk_btn_frame, text="🗑️ 일괄 제거", width=120,
            fg_color="#C62828",
            command=self._bulk_remove_package
        ).pack(side="left", padx=5)

        # === 생성된 패키지 목록 ===
        list_section = ctk.CTkFrame(main_frame)
        list_section.pack(fill="both", expand=True, pady=10)

        header = ctk.CTkFrame(list_section, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            header,
            text="생성된 패키지 목록",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            header, text="새로고침", width=80,
            command=self._refresh_package_list
        ).pack(side="right")

        # 패키지 목록 프레임
        self.pkg_list_frame = ctk.CTkScrollableFrame(list_section, height=150)
        self.pkg_list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # 상태 메시지
        self.pkg_status_label = ctk.CTkLabel(main_frame, text="", font=ctk.CTkFont(size=11))
        self.pkg_status_label.pack(pady=5)

        # 초기 데이터 로드
        self._refresh_package_list()
        self._refresh_distribution_stats()
        self._refresh_bulk_package_list()

    def _generate_prompts_with_ai(self):
        """AI를 사용하여 채널 컨셉에 맞는 프롬프트 자동 생성"""
        concept = self.pkg_concept_entry.get().strip()

        if not concept:
            self._show_pkg_status("채널 컨셉을 입력해주세요.", "red")
            return

        self._show_pkg_status("🤖 AI가 프롬프트를 생성하는 중...", "#9C27B0")
        self.update_idletasks()
        self._ai_prompt_result = None
        self._ai_prompt_error = None
        self._ai_prompt_concept = concept

        def worker():
            try:
                self._ai_prompt_result = self._run_ai_prompt_generation(concept)
            except Exception as e:
                self._ai_prompt_error = e
                import traceback
                traceback.print_exc()

        self._ai_prompt_thread = threading.Thread(target=worker, daemon=True)
        self._ai_prompt_thread.start()
        self.after(50, self._poll_ai_prompt_generation)

    def _poll_ai_prompt_generation(self):
        """Poll background AI prompt generation from the Tk main thread."""
        if self._ai_prompt_result is not None:
            generated = self._ai_prompt_result
            concept = self._ai_prompt_concept
            self._ai_prompt_result = None
            self._ai_prompt_thread = None
            self._apply_ai_generated_prompts(generated, concept)
            return

        if self._ai_prompt_error is not None:
            error = self._ai_prompt_error
            self._ai_prompt_error = None
            self._ai_prompt_thread = None
            self._show_pkg_status(f"❌ AI 생성 실패: {error}", "red")
            return

        if self._ai_prompt_thread and self._ai_prompt_thread.is_alive():
            self.after(50, self._poll_ai_prompt_generation)
            return

        self._ai_prompt_thread = None

    def _run_ai_prompt_generation(self, concept: str) -> Dict[str, object]:
        """Run the Gemini request off the UI thread and return parsed JSON."""
        import re
        from config.settings import config
        from utils.gemini_compat import configure_gemini, get_gemini_model

        if not configure_gemini(config.GEMINI_API_KEY):
            raise RuntimeError("Gemini API를 초기화하지 못했습니다.")

        model = get_gemini_model("gemini-2.0-flash")
        if model is None:
            raise RuntimeError("Gemini 모델을 불러오지 못했습니다.")

        prompt = f"""당신은 유튜브 자동화 콘텐츠 채널 전문가입니다.
사용자가 "{concept}" 컨셉의 채널 패키지를 만들려고 합니다.

다음 정보를 JSON 형식으로 생성해주세요:

1. package_id: 영문 소문자와 언더스코어로 구성된 패키지 ID (예: romance_drama_pack)
2. display_name: 한글 표시 이름 (예: "로맨스 드라마 채널 팩")
3. description: 간단한 설명 (1~2문장)
4. pd_system_prompt: 총괄 PD 역할의 시스템 프롬프트 (이 채널의 주제/소재를 기획하는 역할)
5. writer_system_prompt: 작가 역할의 시스템 프롬프트 (대본을 작성하는 역할)
6. sd_positive: Stable Diffusion 이미지 생성용 긍정 프롬프트 (영문, 스타일/분위기 키워드)
7. sd_negative: Stable Diffusion 이미지 생성용 부정 프롬프트 (영문, 피해야 할 요소)
8. topic_templates: 주제 생성에 사용할 템플릿 리스트 (3~5개)
9. banned_keywords: 이 채널에서 금지할 키워드 리스트 (5~10개)

[참고 예시 - 공포 채널]
- sd_positive: "eerie high-contrast horror comic style, dark atmosphere, cinematic shadows, detailed linework, 8k"
- sd_negative: "bright, sunny, cute, colorful, photo"

[참고 예시 - 감동 채널]
- sd_positive: "warm watercolor painting, soft sunlight, nostalgic, bright and peaceful colors, 2d, masterpiece"
- sd_negative: "dark, scary, horror, intense, messy, photo, realistic"

[참고 예시 - 막장 드라마 채널]
- sd_positive: "dramatic webtoon style, intense cinematic lighting, sharp shadows, tense atmosphere"
- sd_negative: "peaceful, calm, monochrome, cute"

Output JSON ONLY (다른 텍스트 없이):
{{"package_id":"","display_name":"","description":"","pd_system_prompt":"","writer_system_prompt":"","sd_positive":"","sd_negative":"","topic_templates":[],"banned_keywords":[]}}
"""

        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        json_match = re.search(r'\{[\s\S]*\}', raw_text)
        if not json_match:
            raise ValueError("JSON 형식을 찾을 수 없습니다.")
        return json.loads(json_match.group())

    def _apply_ai_generated_prompts(self, generated: Dict[str, object], concept: str):
        """Apply Gemini prompt output back onto the package designer widgets."""
        self.pkg_id_entry.delete(0, "end")
        self.pkg_id_entry.insert(0, str(generated.get("package_id", "")))

        self.pkg_name_entry.delete(0, "end")
        self.pkg_name_entry.insert(0, str(generated.get("display_name", "")))

        self.pkg_desc_text.delete("1.0", "end")
        self.pkg_desc_text.insert("1.0", str(generated.get("description", "")))

        self._ai_generated_prompts = {
            "pd_system_prompt": generated.get("pd_system_prompt", ""),
            "writer_system_prompt": generated.get("writer_system_prompt", ""),
            "sd_positive": generated.get("sd_positive", ""),
            "sd_negative": generated.get("sd_negative", ""),
            "topic_templates": generated.get("topic_templates", []),
            "banned_keywords": generated.get("banned_keywords", []),
        }

        preview_text = f"""[AI 생성 결과]

📌 패키지 ID: {generated.get('package_id', '')}
📌 표시 이름: {generated.get('display_name', '')}

🎬 PD 프롬프트:
{str(generated.get('pd_system_prompt', ''))[:200]}...

✍️ 작가 프롬프트:
{str(generated.get('writer_system_prompt', ''))[:200]}...

🎨 SD 긍정: {generated.get('sd_positive', '')}
🎨 SD 부정: {generated.get('sd_negative', '')}

📋 주제 템플릿: {len(generated.get('topic_templates', []))}개
🚫 금지 키워드: {', '.join(generated.get('banned_keywords', [])[:5])}...
"""
        self.pkg_preview_text.delete("1.0", "end")
        self.pkg_preview_text.insert("1.0", preview_text)
        self._show_pkg_status(f"✅ AI가 '{concept}' 컨셉의 프롬프트를 생성했습니다!", "green")

    def _create_package(self):
        """패키지 생성 - AI 생성 프롬프트 또는 기존 프리셋 기반"""
        package_id = self.pkg_id_entry.get().strip()
        display_name = self.pkg_name_entry.get().strip()
        version = self.pkg_version_entry.get().strip() or "1.0.0"
        description = self.pkg_desc_text.get("1.0", "end").strip()
        use_encryption = self.pkg_encrypt_var.get()
        register_firebase = self.pkg_firebase_var.get()

        # 검증
        if not package_id:
            self._show_pkg_status("패키지 ID를 입력하세요.", "red")
            return

        if not display_name:
            self._show_pkg_status("표시 이름을 입력하세요.", "red")
            return

        # AI 생성 프롬프트가 있는지 확인
        ai_prompts = getattr(self, '_ai_generated_prompts', None)
        if not ai_prompts:
            self._show_pkg_status("먼저 'AI가 프롬프트 생성' 버튼을 눌러 프롬프트를 생성하세요.", "red")
            return

        try:
            # 패키지 매니저 import
            from utils.package_manager import get_package_manager, ChannelPackage, PromptConfig

            # 출력 경로 선택
            from tkinter import filedialog
            output_path = filedialog.asksaveasfilename(
                defaultextension=".revpack",
                filetypes=[("Reverie Package", "*.revpack")],
                initialfile=f"{package_id}.revpack",
                title="패키지 저장 위치"
            )

            if not output_path:
                return

            # PromptConfig 생성 (AI 생성 프롬프트 사용)
            prompts = PromptConfig(
                pd_system_prompt=ai_prompts.get('pd_system_prompt', ''),
                writer_system_prompt=ai_prompts.get('writer_system_prompt', ''),
                sd_positive=ai_prompts.get('sd_positive', ''),
                sd_negative=ai_prompts.get('sd_negative', ''),
                topic_templates=ai_prompts.get('topic_templates', []),
                banned_keywords=ai_prompts.get('banned_keywords', [])
            )

            # v57.7.6: 기본 채널 타입 추론 (horror/senior/custom)
            # AI 생성 프롬프트에서 채널 타입 힌트를 가져오거나 custom 사용
            base_channel = ai_prompts.get('base_channel_type', 'senior')  # 기본값: senior
            if base_channel not in ('horror', 'senior'):
                base_channel = 'senior'  # 안전한 기본값

            # v57.7.6: 오디오 설정 - 기존 채널 리소스 사용 (기본값)
            audio_config = {
                'use_channel_bgm': base_channel,   # 해당 채널의 BGM 사용
                'use_channel_sfx': base_channel,   # 해당 채널의 SFX 사용
                'use_channel_tts': base_channel,   # 해당 채널의 TTS 모델 사용
                'bgm_path': '',                     # 커스텀 BGM 경로 (비어있으면 기본값)
                'sfx_path': '',                     # 커스텀 SFX 경로 (비어있으면 기본값)
            }

            # v57.7.6: 캐릭터-TTS 매핑 기본값 (기존 채널 매핑 사용)
            # 팩에서 특별히 지정하지 않으면 script_writers의 role_to_voice_type 사용
            character_config = ai_prompts.get('character_config', {})

            # ChannelPackage 객체 생성 - AI 생성 프롬프트 포함
            package = ChannelPackage(
                package_id=package_id,
                package_name=display_name,
                version=version,
                author="Admin",
                description=description,
                channel_type="custom",  # AI 생성은 custom 타입
                channel_display_name=display_name,
                prompts=prompts,
                audio_config=audio_config,           # v57.7.6: 오디오 설정
                character_config=character_config,   # v57.7.6: 캐릭터-TTS 매핑
            )

            # 패키지 매니저로 내보내기
            pm = get_package_manager()
            success, msg = pm.export_package(
                package=package,
                output_path=output_path,
                require_license=use_encryption  # 암호화 = 라이선스 필요
            )

            if success:
                status_msg = f"패키지 생성 완료: {os.path.basename(output_path)}"

                # Firebase에 패키지 ID 등록 안내 (선택적)
                if register_firebase and self.firebase_validator and self.firebase_validator.is_available():
                    status_msg += f"\nFirebase: 라이센스의 owned_packs에 '{package_id}'를 추가하세요."

                self._show_pkg_status(status_msg, "green")

                # 목록 새로고침
                self._refresh_package_list()

                # 입력 필드 일부 초기화
                self.pkg_desc_text.delete("1.0", "end")

                # 자동 설치 옵션 확인
                if hasattr(self, 'pkg_auto_install_var') and self.pkg_auto_install_var.get():
                    self._auto_install_package(output_path, package_id, display_name)

            else:
                self._show_pkg_status(f"패키지 생성 실패: {msg}", "red")

        except ImportError as e:
            self._show_pkg_status(f"패키지 매니저를 찾을 수 없습니다: {e}", "red")
        except Exception as e:
            self._show_pkg_status(f"패키지 생성 오류: {e}", "red")

    def _auto_install_package(self, package_path: str, package_id: str, display_name: str):
        """생성된 패키지 자동 설치"""
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()

            # 패키지 가져오기 (설치)
            result = pm.import_package(package_path)

            if result.success:
                self._show_pkg_status(
                    f"✅ 패키지 '{display_name}' 생성 및 설치 완료!\n"
                    f"채널 ID: {result.channel_id}",
                    "green"
                )
                # 목록 새로고침
                self._refresh_package_list()
            else:
                self._show_pkg_status(
                    f"패키지 생성됨, 자동 설치 실패: {result.error}\n"
                    f"수동으로 설치하세요: {package_path}",
                    "orange"
                )

        except Exception as e:
            self._show_pkg_status(
                f"패키지 생성됨, 자동 설치 오류: {e}\n"
                f"수동으로 설치하세요: {package_path}",
                "orange"
            )

    def _add_package_to_license(self):
        """라이센스에 패키지 추가"""
        license_key = self.link_license_entry.get().strip().upper()
        package_id = self.link_package_entry.get().strip()

        if not license_key:
            self._show_pkg_status("라이센스 키를 입력하세요.", "red")
            return

        if not package_id:
            self._show_pkg_status("패키지 ID를 입력하세요.", "red")
            return

        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_pkg_status("Firebase에 연결되지 않았습니다.", "red")
            return

        try:
            success, msg = self.firebase_validator.add_package_to_license(license_key, package_id)
            if success:
                self._show_pkg_status(f"패키지 '{package_id}' 추가 완료", "green")
            else:
                self._show_pkg_status(msg, "red")
        except Exception as e:
            self._show_pkg_status(f"오류: {e}", "red")

    def _remove_package_from_license(self):
        """라이센스에서 패키지 제거"""
        license_key = self.link_license_entry.get().strip().upper()
        package_id = self.link_package_entry.get().strip()

        if not license_key:
            self._show_pkg_status("라이센스 키를 입력하세요.", "red")
            return

        if not package_id:
            self._show_pkg_status("패키지 ID를 입력하세요.", "red")
            return

        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_pkg_status("Firebase에 연결되지 않았습니다.", "red")
            return

        try:
            success, msg = self.firebase_validator.remove_package_from_license(license_key, package_id)
            if success:
                self._show_pkg_status(f"패키지 '{package_id}' 제거 완료", "green")
            else:
                self._show_pkg_status(msg, "red")
        except Exception as e:
            self._show_pkg_status(f"오류: {e}", "red")

    def _view_license_packages(self):
        """라이센스의 보유 패키지 조회"""
        license_key = self.link_license_entry.get().strip().upper()

        if not license_key:
            self._show_pkg_status("라이센스 키를 입력하세요.", "red")
            return

        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_pkg_status("Firebase에 연결되지 않았습니다.", "red")
            return

        try:
            license_info = self.firebase_validator.get_license_info(license_key)
            if license_info:
                owned_packs = license_info.get('owned_packs', [])
                license_type = license_info.get('license_type', '?')

                if license_type == 'A':
                    self._show_pkg_status(f"전체 이용권 (A타입) - 모든 패키지 접근 가능", "green")
                elif owned_packs:
                    packs_str = ", ".join(owned_packs)
                    self._show_pkg_status(f"보유 패키지: {packs_str}", "green")
                else:
                    self._show_pkg_status("보유한 패키지가 없습니다.", "orange")
            else:
                self._show_pkg_status("라이센스를 찾을 수 없습니다.", "red")
        except Exception as e:
            self._show_pkg_status(f"조회 오류: {e}", "red")

    # ============================================================
    # 패키지 배포 관리 메서드 (v38)
    # ============================================================

    def _refresh_distribution_stats(self):
        """패키지 배포 통계 새로고침"""
        if not self.firebase_validator or not self.firebase_validator.is_available():
            self.dist_stats_label.configure(text="Firebase 연결 안됨", text_color="red")
            return

        try:
            stats = self.firebase_validator.get_all_package_stats()

            if not stats:
                self.dist_stats_label.configure(
                    text="배포된 패키지 없음\n(라이센스에 owned_packs가 설정되지 않음)",
                    text_color="gray"
                )
                return

            # 통계 텍스트 생성
            lines = []
            total_active = 0
            total_all = 0

            # 패키지 이름 매핑
            pack_names = {
                'daily_life_toon_pack': '🎬 일상 영상툰',
                'mystery_toon_pack': '🔎 미스터리 영상툰'
            }

            for stat in sorted(stats, key=lambda x: x['total_count'], reverse=True):
                pack_id = stat['pack_id']
                name = pack_names.get(pack_id, f'📦 {pack_id}')
                lines.append(f"{name}: {stat['active_count']}/{stat['total_count']} (활성/전체)")
                total_active += stat['active_count']
                total_all += stat['total_count']

            lines.insert(0, f"=== 전체 통계: {total_active}/{total_all} 활성 ===\n")

            self.dist_stats_label.configure(
                text="\n".join(lines),
                text_color="white"
            )

        except Exception as e:
            self.dist_stats_label.configure(text=f"통계 로드 실패: {e}", text_color="red")

    def _refresh_bulk_package_list(self):
        """일괄 배포용 패키지 목록 갱신"""
        packs = ["daily_life_toon_pack", "mystery_toon_pack"]

        if self.firebase_validator and self.firebase_validator.is_available():
            try:
                registered = self.firebase_validator.get_registered_packages()
                for p in registered:
                    if p not in packs:
                        packs.append(p)
            except Exception as e:
                logger.debug(f"등록된 팩 목록 로드 실패: {e}")

        self.bulk_package_combo.configure(values=packs)
        self._show_pkg_status(f"패키지 목록 갱신됨 ({len(packs)}개)", "green")

    def _bulk_add_package(self):
        """여러 라이센스에 패키지 일괄 추가"""
        pack_id = self.bulk_package_var.get().strip()
        target = self.bulk_target_var.get()

        if not pack_id:
            self._show_pkg_status("배포할 패키지를 선택하세요.", "red")
            return

        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_pkg_status("Firebase에 연결되지 않았습니다.", "red")
            return

        # 확인 메시지
        target_desc = "활성 라이센스" if target == "active" else "모든 라이센스"
        from tkinter import messagebox
        if not messagebox.askyesno(
            "일괄 추가 확인",
            f"'{pack_id}' 패키지를 {target_desc}에 추가하시겠습니까?"
        ):
            return

        try:
            # 대상 라이센스 가져오기
            all_licenses = self.firebase_validator.get_all_licenses()

            if target == "active":
                license_keys = [
                    lic['license_key'] for lic in all_licenses
                    if lic.get('is_active', False)
                ]
            else:
                license_keys = [lic['license_key'] for lic in all_licenses]

            if not license_keys:
                self._show_pkg_status("대상 라이센스가 없습니다.", "orange")
                return

            # 일괄 추가
            success, failed, failed_keys = self.firebase_validator.bulk_add_package(license_keys, pack_id)

            self._show_pkg_status(
                f"일괄 추가 완료: {success}개 성공, {failed}개 실패",
                "green" if failed == 0 else "orange"
            )

            # 통계 갱신
            self._refresh_distribution_stats()

        except Exception as e:
            self._show_pkg_status(f"일괄 추가 오류: {e}", "red")

    def _bulk_remove_package(self):
        """여러 라이센스에서 패키지 일괄 제거"""
        pack_id = self.bulk_package_var.get().strip()
        target = self.bulk_target_var.get()

        if not pack_id:
            self._show_pkg_status("제거할 패키지를 선택하세요.", "red")
            return

        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_pkg_status("Firebase에 연결되지 않았습니다.", "red")
            return

        # 확인 메시지
        target_desc = "활성 라이센스" if target == "active" else "모든 라이센스"
        from tkinter import messagebox
        if not messagebox.askyesno(
            "일괄 제거 확인",
            f"'{pack_id}' 패키지를 {target_desc}에서 제거하시겠습니까?\n이 작업은 되돌릴 수 없습니다!"
        ):
            return

        try:
            # 대상 라이센스 가져오기
            all_licenses = self.firebase_validator.get_all_licenses()

            if target == "active":
                license_keys = [
                    lic['license_key'] for lic in all_licenses
                    if lic.get('is_active', False)
                ]
            else:
                license_keys = [lic['license_key'] for lic in all_licenses]

            if not license_keys:
                self._show_pkg_status("대상 라이센스가 없습니다.", "orange")
                return

            # 일괄 제거
            success, failed, failed_keys = self.firebase_validator.bulk_remove_package(license_keys, pack_id)

            self._show_pkg_status(
                f"일괄 제거 완료: {success}개 성공, {failed}개 실패",
                "green" if failed == 0 else "orange"
            )

            # 통계 갱신
            self._refresh_distribution_stats()

        except Exception as e:
            self._show_pkg_status(f"일괄 제거 오류: {e}", "red")

    def _create_default_packs(self):
        """기본 3개 팩(공포/감동/막장) 자동 생성"""
        from tkinter import messagebox, filedialog

        # 저장 폴더 선택
        output_dir = filedialog.askdirectory(
            title="기본 팩 저장 폴더 선택"
        )

        if not output_dir:
            return

        try:
            from utils.package_manager import get_package_manager, ChannelPackage, PromptConfig
            from config.settings import config

            pm = get_package_manager()

            # 기본 팩 정의
            default_packs = [
                {
                    'package_id': 'daily_life_toon_pack',
                    'package_name': '일상 영상툰 팩',
                    'channel_type': 'daily_life_toon',
                    'description': '배경+캐릭터 레이어 기반 일상 웹툰 드라마 패키지',
                    'profile_key': 'daily_life_toon'
                },
                {
                    'package_id': 'mystery_toon_pack',
                    'package_name': '미스터리 영상툰 팩',
                    'channel_type': 'mystery_toon',
                    'description': '생활형 미스터리 영상툰 패키지',
                    'profile_key': 'mystery_toon'
                }
            ]

            created = []
            failed = []

            for pack_def in default_packs:
                try:
                    # 프로필에서 SD 프롬프트 가져오기
                    profile = config.PROFILES.get(pack_def['profile_key'], {})

                    prompts = PromptConfig(
                        sd_positive=profile.get('sd_positive', ''),
                        sd_negative=profile.get('sd_negative', ''),
                        pd_system_prompt=f"{pack_def['package_name']} 전용 PD 프롬프트",
                        writer_system_prompt=f"{pack_def['package_name']} 전용 작가 프롬프트"
                    )

                    # v57.7.6: 채널 타입에 따른 기본 오디오 설정
                    base_channel = pack_def.get('channel_type') or 'daily_life_toon'
                    audio_config = {
                        'use_channel_bgm': base_channel,
                        'use_channel_sfx': base_channel,
                        'use_channel_tts': base_channel,
                        'bgm_path': '',
                        'sfx_path': '',
                    }

                    package = ChannelPackage(
                        package_id=pack_def['package_id'],
                        package_name=pack_def['package_name'],
                        version="1.0.0",
                        author="Reverie System",
                        description=pack_def['description'],
                        channel_type=pack_def['channel_type'],
                        channel_display_name=pack_def['package_name'],
                        prompts=prompts,
                        audio_config=audio_config,  # v57.7.6
                    )

                    output_path = os.path.join(output_dir, f"{pack_def['package_id']}.revpack")

                    success, msg = pm.export_package(
                        package=package,
                        output_path=output_path,
                        require_license=False
                    )

                    if success:
                        created.append(pack_def['package_name'])
                    else:
                        failed.append(f"{pack_def['package_name']}: {msg}")

                except Exception as e:
                    failed.append(f"{pack_def['package_name']}: {str(e)}")

            # 결과 표시
            result_msg = f"생성 완료: {len(created)}개"
            if created:
                result_msg += f"\n- " + "\n- ".join(created)
            if failed:
                result_msg += f"\n\n실패: {len(failed)}개"
                result_msg += f"\n- " + "\n- ".join(failed)

            messagebox.showinfo("기본 팩 생성 결과", result_msg)

            self._show_pkg_status(f"기본 팩 {len(created)}개 생성 완료", "green")
            self._refresh_package_list()

        except Exception as e:
            self._show_pkg_status(f"기본 팩 생성 실패: {e}", "red")
            messagebox.showerror("오류", str(e))

    def _refresh_package_list(self):
        """생성된 패키지 목록 새로고침"""
        # 기존 항목 삭제
        for widget in self.pkg_list_frame.winfo_children():
            widget.destroy()

        # packages 폴더 확인
        packages_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "packages"
        )

        if not os.path.exists(packages_dir):
            ctk.CTkLabel(
                self.pkg_list_frame,
                text="packages 폴더가 없습니다.",
                text_color="gray"
            ).pack(pady=20)
            return

        # .revpack 파일 검색
        revpack_files = [f for f in os.listdir(packages_dir) if f.endswith('.revpack')]

        if not revpack_files:
            ctk.CTkLabel(
                self.pkg_list_frame,
                text="생성된 패키지가 없습니다.",
                text_color="gray"
            ).pack(pady=20)
            return

        # 헤더
        header = ctk.CTkFrame(self.pkg_list_frame, fg_color="#333333")
        header.pack(fill="x", pady=(0, 5))

        for text, width in [("파일명", 200), ("크기", 80), ("수정일", 120), ("액션", 100)]:
            ctk.CTkLabel(
                header, text=text, width=width,
                font=ctk.CTkFont(size=11, weight="bold")
            ).pack(side="left", padx=2, pady=5)

        # 파일 목록
        for i, filename in enumerate(revpack_files):
            filepath = os.path.join(packages_dir, filename)
            file_stat = os.stat(filepath)
            size_kb = file_stat.st_size / 1024
            mod_time = datetime.datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M')

            row_color = "#2b2b2b" if i % 2 == 0 else "#333333"
            row = ctk.CTkFrame(self.pkg_list_frame, fg_color=row_color, height=30)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=filename[:25], width=200, font=ctk.CTkFont(size=10)).pack(side="left", padx=2)
            ctk.CTkLabel(row, text=f"{size_kb:.1f} KB", width=80, font=ctk.CTkFont(size=10)).pack(side="left", padx=2)
            ctk.CTkLabel(row, text=mod_time, width=120, font=ctk.CTkFont(size=10)).pack(side="left", padx=2)

            # 삭제 버튼
            ctk.CTkButton(
                row, text="삭제", width=50, height=22,
                font=ctk.CTkFont(size=9), fg_color="#C62828",
                command=lambda p=filepath, f=filename: self._delete_package_file(p, f)
            ).pack(side="left", padx=5)

    def _delete_package_file(self, filepath: str, filename: str):
        """패키지 파일 삭제"""
        if messagebox.askyesno("삭제 확인", f"'{filename}' 파일을 삭제하시겠습니까?"):
            try:
                os.remove(filepath)
                self._refresh_package_list()
                self._show_pkg_status(f"'{filename}' 삭제 완료", "green")
            except Exception as e:
                self._show_pkg_status(f"삭제 실패: {e}", "red")

    def _show_pkg_status(self, message: str, color: str = "white"):
        """패키지 탭 상태 메시지 표시"""
        self.pkg_status_label.configure(text=message, text_color=color)

    # ============================================================
    # Firebase 서버 탭
    # ============================================================
    def _create_firebase_tab(self):
        """Firebase 서버 탭 UI"""
        main_frame = ctk.CTkScrollableFrame(self.tab_firebase)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="Firebase 서버 연동",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=(0, 15))

        # 연결 상태
        status_frame = ctk.CTkFrame(main_frame)
        status_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            status_frame,
            text="서버 연결 상태",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        if self.firebase_validator and self.firebase_validator.is_available():
            status_text = "연결됨"
            status_color = "green"
        else:
            status_text = "연결 안됨"
            status_color = "red"

        self.firebase_status_label = ctk.CTkLabel(
            status_frame,
            text=f"상태: {status_text}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=status_color
        )
        self.firebase_status_label.pack(anchor="w", padx=10, pady=(0, 10))

        if not self.firebase_validator or not self.firebase_validator.is_available():
            ctk.CTkLabel(
                status_frame,
                text="config/firebase_credentials.json 파일이 필요합니다.\n또는 pip install firebase-admin 실행",
                text_color="gray"
            ).pack(anchor="w", padx=10, pady=(0, 10))

        # === Firebase 라이센스 목록 ===
        list_section = ctk.CTkFrame(main_frame)
        list_section.pack(fill="both", expand=True, pady=10)

        header_frame = ctk.CTkFrame(list_section, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            header_frame,
            text="Firebase 라이센스 목록",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        refresh_btn = ctk.CTkButton(
            header_frame,
            text="새로고침",
            width=80,
            command=self._refresh_firebase_list
        )
        refresh_btn.pack(side="right", padx=5)

        sync_btn = ctk.CTkButton(
            header_frame,
            text="로컬 → Firebase 동기화",
            width=150,
            fg_color="#FF6F00",
            command=self._sync_to_firebase
        )
        sync_btn.pack(side="right", padx=5)

        # 목록 프레임
        self.firebase_list_frame = ctk.CTkScrollableFrame(list_section, height=250)
        self.firebase_list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # 헤더
        fb_header = ctk.CTkFrame(self.firebase_list_frame, fg_color="#333333")
        fb_header.pack(fill="x", pady=(0, 5))

        fb_headers = [("라이센스 키", 180), ("사용자", 90), ("보유 팩", 100),
                      ("만료일", 85), ("활성", 45), ("액션", 130)]

        for text, width in fb_headers:
            ctk.CTkLabel(
                fb_header, text=text, width=width,
                font=ctk.CTkFont(size=11, weight="bold")
            ).pack(side="left", padx=2, pady=5)

        # 목록 컨테이너
        self.firebase_items_frame = ctk.CTkFrame(self.firebase_list_frame, fg_color="transparent")
        self.firebase_items_frame.pack(fill="both", expand=True)

        # 초기 목록 로드
        self._refresh_firebase_list()

        # === 수동 등록 섹션 ===
        manual_section = ctk.CTkFrame(main_frame)
        manual_section.pack(fill="x", pady=10)

        ctk.CTkLabel(
            manual_section,
            text="수동 라이센스 등록 (Firebase 직접)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        # 입력 필드들
        input_frame = ctk.CTkFrame(manual_section, fg_color="transparent")
        input_frame.pack(fill="x", padx=10, pady=5)

        # 라이센스 키
        ctk.CTkLabel(input_frame, text="라이센스 키:", width=100).grid(row=0, column=0, sticky="w", pady=3)
        self.fb_license_entry = ctk.CTkEntry(input_frame, width=250, placeholder_text="XXXXX-XXXXX-XXXXX-X-XXXXX")
        self.fb_license_entry.grid(row=0, column=1, pady=3, padx=5)

        # 사용자 ID
        ctk.CTkLabel(input_frame, text="사용자 ID:", width=100).grid(row=1, column=0, sticky="w", pady=3)
        self.fb_user_entry = ctk.CTkEntry(input_frame, width=250, placeholder_text="이메일 또는 이름")
        self.fb_user_entry.grid(row=1, column=1, pady=3, padx=5)

        # 하드웨어 ID
        ctk.CTkLabel(input_frame, text="하드웨어 ID:", width=100).grid(row=2, column=0, sticky="w", pady=3)
        self.fb_hw_entry = ctk.CTkEntry(input_frame, width=200, placeholder_text="16자리")
        self.fb_hw_entry.grid(row=2, column=1, pady=3, padx=5, sticky="w")

        # 유효 기간
        ctk.CTkLabel(input_frame, text="유효 기간:", width=100).grid(row=3, column=0, sticky="w", pady=3)
        dur_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        dur_frame.grid(row=3, column=1, pady=3, sticky="w")

        self.fb_duration_entry = ctk.CTkEntry(dur_frame, width=60, placeholder_text="30")
        self.fb_duration_entry.pack(side="left", padx=(0, 5))
        ctk.CTkLabel(dur_frame, text="일").pack(side="left")

        # 포함할 팩
        ctk.CTkLabel(input_frame, text="포함할 팩:", width=100).grid(row=4, column=0, sticky="nw", pady=3)
        fb_pack_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        fb_pack_frame.grid(row=4, column=1, pady=3, sticky="w")

        self.fb_pack_vars = {}
        fb_default_packs = [
            ("daily_life_toon_pack", "🎬 일상 영상툰"),
            ("mystery_toon_pack", "🔎 미스터리 영상툰"),
        ]
        for pack_id, pack_name in fb_default_packs:
            var = ctk.BooleanVar(value=True)
            self.fb_pack_vars[pack_id] = var
            ctk.CTkCheckBox(
                fb_pack_frame, text=pack_name, variable=var,
                font=ctk.CTkFont(size=11)
            ).pack(side="left", padx=5)

        # 등록 버튼
        ctk.CTkButton(
            manual_section,
            text="Firebase에 등록",
            width=150,
            fg_color="#1565C0",
            command=self._register_to_firebase
        ).pack(anchor="w", padx=10, pady=10)

        # 상태 메시지
        self.fb_status_label = ctk.CTkLabel(main_frame, text="", font=ctk.CTkFont(size=11))
        self.fb_status_label.pack(pady=5)

    def _refresh_firebase_list(self):
        """Firebase 라이센스 목록 새로고침"""
        # 기존 항목 삭제
        for widget in self.firebase_items_frame.winfo_children():
            widget.destroy()

        if not self.firebase_validator or not self.firebase_validator.is_available():
            ctk.CTkLabel(
                self.firebase_items_frame,
                text="Firebase에 연결되지 않았습니다.",
                text_color="gray"
            ).pack(pady=20)
            return

        try:
            licenses = self.firebase_validator.get_all_licenses()

            if not licenses:
                ctk.CTkLabel(
                    self.firebase_items_frame,
                    text="등록된 라이센스가 없습니다.",
                    text_color="gray"
                ).pack(pady=20)
                return

            for i, lic in enumerate(licenses):
                self._create_firebase_row(lic, i)

        except Exception as e:
            ctk.CTkLabel(
                self.firebase_items_frame,
                text=f"목록 로드 실패: {e}",
                text_color="red"
            ).pack(pady=20)

    def _create_firebase_row(self, license_data: Dict, index: int):
        """Firebase 라이센스 행 생성"""
        row_color = "#2b2b2b" if index % 2 == 0 else "#333333"
        row = ctk.CTkFrame(self.firebase_items_frame, fg_color=row_color, height=35)
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        license_key = license_data.get('license_key', '')
        user_id = license_data.get('user_id', '')[:10]
        is_active = license_data.get('is_active', False)

        # 보유 팩 표시
        owned_packs = license_data.get('owned_packs', [])
        pack_abbr = {
            'daily_life_toon_pack': '🎬',
            'mystery_toon_pack': '🔎'
        }
        if owned_packs:
            pack_display = ''.join([pack_abbr.get(p, '📦') for p in owned_packs[:4]])
            if len(owned_packs) > 4:
                pack_display += f"+{len(owned_packs)-4}"
        else:
            # 레거시 타입으로 폴백
            l_type = license_data.get('license_type', '?')
            type_display = {'A': '전체', 'H': '👻', 'T': '💝', 'M': '😱', 'P': '📦'}
            pack_display = type_display.get(l_type, l_type)

        # 만료일
        expire_date = license_data.get('expire_date')
        if expire_date:
            if hasattr(expire_date, 'strftime'):
                expire_str = expire_date.strftime('%Y-%m-%d')
            else:
                expire_str = str(expire_date)[:10]
        else:
            expire_str = "무제한"

        # 라이센스 키 (클릭 가능)
        key_label = ctk.CTkLabel(
            row, text=license_key[:22] + "..." if len(license_key) > 22 else license_key,
            width=180, font=ctk.CTkFont(size=10),
            cursor="hand2"
        )
        key_label.pack(side="left", padx=2)
        key_label.bind("<Button-1>", lambda e, d=license_data: self._show_license_detail_popup(d))

        # 사용자
        ctk.CTkLabel(row, text=user_id, width=90, font=ctk.CTkFont(size=10)).pack(side="left", padx=2)

        # 보유 팩 (클릭 시 상세)
        pack_label = ctk.CTkLabel(
            row, text=pack_display, width=100,
            font=ctk.CTkFont(size=10),
            cursor="hand2"
        )
        pack_label.pack(side="left", padx=2)
        pack_label.bind("<Button-1>", lambda e, d=license_data: self._show_license_detail_popup(d))

        # 만료일
        ctk.CTkLabel(row, text=expire_str, width=85, font=ctk.CTkFont(size=10)).pack(side="left", padx=2)

        # 활성 상태
        ctk.CTkLabel(row, text="O" if is_active else "X", width=45,
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="green" if is_active else "red").pack(side="left", padx=2)

        # 액션 버튼
        action_frame = ctk.CTkFrame(row, fg_color="transparent", width=130)
        action_frame.pack(side="left", padx=2)

        # 상세 보기
        ctk.CTkButton(
            action_frame, text="상세", width=35, height=24,
            font=ctk.CTkFont(size=9), fg_color="#1565C0",
            command=lambda d=license_data: self._show_license_detail_popup(d)
        ).pack(side="left", padx=1)

        # 활성화/비활성화 토글
        toggle_text = "OFF" if is_active else "ON"
        toggle_color = "#C62828" if is_active else "#2E7D32"
        ctk.CTkButton(
            action_frame, text=toggle_text, width=35, height=24,
            font=ctk.CTkFont(size=9), fg_color=toggle_color,
            command=lambda k=license_key, a=is_active: self._toggle_firebase_license(k, a)
        ).pack(side="left", padx=1)

        # 삭제
        ctk.CTkButton(
            action_frame, text="삭제", width=35, height=24,
            font=ctk.CTkFont(size=9), fg_color="#424242",
            command=lambda k=license_key: self._delete_firebase_license(k)
        ).pack(side="left", padx=1)

    def _show_license_detail_popup(self, license_data: Dict):
        """라이센스 상세 정보 팝업"""
        # 팝업 윈도우 생성
        popup = ctk.CTkToplevel(self)
        popup.title("라이센스 상세 정보")
        popup.geometry("500x450")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        # 중앙 정렬
        popup.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 500) // 2
        y = self.winfo_y() + (self.winfo_height() - 450) // 2
        popup.geometry(f"+{x}+{y}")

        main_frame = ctk.CTkScrollableFrame(popup)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="📋 라이센스 상세 정보",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(0, 15))

        # 기본 정보
        info_frame = ctk.CTkFrame(main_frame)
        info_frame.pack(fill="x", pady=5)

        license_key = license_data.get('license_key', '')
        user_id = license_data.get('user_id', '')
        hardware_id = license_data.get('hardware_id', '')
        is_active = license_data.get('is_active', False)
        memo = license_data.get('memo', '')

        # 만료일
        expire_date = license_data.get('expire_date')
        if expire_date:
            if hasattr(expire_date, 'strftime'):
                expire_str = expire_date.strftime('%Y-%m-%d %H:%M')
            else:
                expire_str = str(expire_date)
        else:
            expire_str = "무제한"

        info_items = [
            ("라이센스 키", license_key),
            ("사용자 ID", user_id),
            ("하드웨어 ID", hardware_id),
            ("만료일", expire_str),
            ("활성 상태", "✅ 활성" if is_active else "❌ 비활성"),
            ("메모", memo or "(없음)"),
        ]

        for label, value in info_items:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=f"{label}:", width=100, anchor="w",
                        font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=value, anchor="w",
                        font=ctk.CTkFont(size=11)).pack(side="left", fill="x", expand=True)

        # 보유 패키지 섹션
        pack_frame = ctk.CTkFrame(main_frame, fg_color="#1a2e1a")
        pack_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            pack_frame,
            text="📦 보유 패키지",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        owned_packs = license_data.get('owned_packs', [])

        # 팩 이름 매핑
        pack_names = {
            'daily_life_toon_pack': '🎬 일상 영상툰 팩',
            'mystery_toon_pack': '🔎 미스터리 영상툰 팩'
        }

        if owned_packs:
            for pack_id in owned_packs:
                pack_name = pack_names.get(pack_id, f'📦 {pack_id}')
                ctk.CTkLabel(
                    pack_frame,
                    text=f"  • {pack_name}",
                    font=ctk.CTkFont(size=12),
                    anchor="w"
                ).pack(anchor="w", padx=15, pady=2)
        else:
            # 레거시 타입 표시
            l_type = license_data.get('license_type', '?')
            type_desc = {
                'A': '전체 이용권 (모든 팩 접근 가능)',
                'H': '공포 채널 전용 (레거시)',
                'T': '감동 채널 전용 (레거시)',
                'M': '막장 채널 전용 (레거시)',
                'P': '팩 기반 (owned_packs 미설정)'
            }
            ctk.CTkLabel(
                pack_frame,
                text=f"  {type_desc.get(l_type, f'알 수 없는 타입: {l_type}')}",
                font=ctk.CTkFont(size=11),
                text_color="orange"
            ).pack(anchor="w", padx=15, pady=5)

        ctk.CTkLabel(
            pack_frame,
            text=f"  총 {len(owned_packs)}개 패키지 보유",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=15, pady=(5, 10))

        # 닫기 버튼
        ctk.CTkButton(
            main_frame,
            text="닫기",
            width=100,
            command=popup.destroy
        ).pack(pady=15)

    def _toggle_firebase_license(self, license_key: str, currently_active: bool):
        """Firebase 라이센스 활성화/비활성화 토글"""
        if not self.firebase_validator:
            return

        try:
            if currently_active:
                success, msg = self.firebase_validator.deactivate_license(license_key)
            else:
                success, msg = self.firebase_validator.activate_license(license_key)

            if success:
                self._refresh_firebase_list()
                self._show_fb_status(msg, "green")
            else:
                self._show_fb_status(msg, "red")

        except Exception as e:
            self._show_fb_status(f"오류: {e}", "red")

    def _delete_firebase_license(self, license_key: str):
        """Firebase 라이센스 삭제"""
        if not self.firebase_validator:
            return

        if messagebox.askyesno("삭제 확인", f"라이센스를 Firebase에서 삭제하시겠습니까?\n\n{license_key[:30]}..."):
            try:
                success, msg = self.firebase_validator.delete_license(license_key)
                if success:
                    self._refresh_firebase_list()
                    self._show_fb_status(msg, "green")
                else:
                    self._show_fb_status(msg, "red")
            except Exception as e:
                self._show_fb_status(f"삭제 실패: {e}", "red")

    def _register_to_firebase(self):
        """Firebase에 라이센스 수동 등록"""
        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_fb_status("Firebase에 연결되지 않았습니다.", "red")
            return

        license_key = self.fb_license_entry.get().strip().upper()
        user_id = self.fb_user_entry.get().strip()
        hardware_id = self.fb_hw_entry.get().strip().upper()

        # 선택된 팩 가져오기
        selected_packs = [pack_id for pack_id, var in self.fb_pack_vars.items() if var.get()]

        try:
            duration = int(self.fb_duration_entry.get() or "30")
        except ValueError:
            duration = 30

        if not license_key:
            self._show_fb_status("라이센스 키를 입력하세요.", "red")
            return

        if not user_id:
            self._show_fb_status("사용자 ID를 입력하세요.", "red")
            return

        if not selected_packs:
            self._show_fb_status("최소 1개 이상의 팩을 선택하세요.", "red")
            return

        try:
            success, msg = self.firebase_validator.register_license(
                license_key=license_key,
                user_id=user_id,
                hardware_id=hardware_id,
                license_type='P',  # 팩 기반
                duration_days=duration,
                owned_packs=selected_packs
            )

            if success:
                self._refresh_firebase_list()
                self._show_fb_status(f"{msg} (팩 {len(selected_packs)}개)", "green")
                # 입력 필드 초기화
                self.fb_license_entry.delete(0, "end")
                self.fb_user_entry.delete(0, "end")
                self.fb_hw_entry.delete(0, "end")
                self.fb_duration_entry.delete(0, "end")
            else:
                self._show_fb_status(msg, "red")

        except Exception as e:
            self._show_fb_status(f"등록 실패: {e}", "red")

    def _sync_to_firebase(self):
        """로컬 발급 내역을 Firebase에 동기화"""
        if not self.firebase_validator or not self.firebase_validator.is_available():
            self._show_fb_status("Firebase에 연결되지 않았습니다.", "red")
            return

        if not self.license_history:
            self._show_fb_status("동기화할 로컬 내역이 없습니다.", "orange")
            return

        if not messagebox.askyesno(
            "동기화 확인",
            f"로컬 발급 내역 {len(self.license_history)}개를 Firebase에 동기화하시겠습니까?\n\n"
            "이미 존재하는 라이센스는 덮어씌워집니다."
        ):
            return

        success_count = 0
        fail_count = 0

        for record in self.license_history:
            try:
                # 만료일 계산
                expire_str = record.get('expire_date', '')
                if expire_str:
                    expire_date = datetime.datetime.strptime(expire_str, '%Y-%m-%d')
                    days_left = (expire_date - datetime.datetime.now()).days
                    if days_left < 0:
                        days_left = 0
                else:
                    days_left = 30

                success, _ = self.firebase_validator.register_license(
                    license_key=record.get('license_key', ''),
                    user_id=record.get('user_id', ''),
                    hardware_id=record.get('hardware_id', ''),
                    license_type=record.get('license_type', 'A'),
                    duration_days=max(days_left, 1),
                    memo=record.get('memo', '')
                )

                if success:
                    success_count += 1
                else:
                    fail_count += 1

            except Exception:
                fail_count += 1

        self._refresh_firebase_list()
        self._show_fb_status(f"동기화 완료: 성공 {success_count}개, 실패 {fail_count}개", "green" if fail_count == 0 else "orange")

    def _show_fb_status(self, message: str, color: str = "white"):
        """Firebase 탭 상태 메시지 표시"""
        self.fb_status_label.configure(text=message, text_color=color)

    # ============================================================
    # Insight 탭 (Insight 1.0.0)
    # ============================================================
    def _create_insight_tab(self):
        """Insight 탭 UI - YouTube 트렌드 수집"""
        if INSIGHT_AVAILABLE:
            # v57.6.8: GUI 콜백 정의 (레이어 분리)
            def on_open_scenario_editor(parent, plan_data, on_approve):
                from gui.scenario_editor import ScenarioEditorWindow
                ScenarioEditorWindow(parent, plan_data=plan_data, on_approve=on_approve)

            def on_open_script_preview(parent, plan_data):
                from gui.script_preview_dialog import ScriptPreviewDialog
                ScriptPreviewDialog(parent, plan_data)

            # InsightTab 컴포넌트 사용 (InsightTab은 내부에서 UI를 parent에 직접 생성)
            self.insight_component = InsightTab(
                self.tab_insight,
                on_open_scenario_editor=on_open_scenario_editor,
                on_open_script_preview=on_open_script_preview
            )
        else:
            # Insight 모듈 없음 안내
            main_frame = ctk.CTkFrame(self.tab_insight)
            main_frame.pack(fill="both", expand=True, padx=20, pady=20)

            ctk.CTkLabel(
                main_frame,
                text="Insight 모듈",
                font=get_font("title", bold=True)
            ).pack(pady=(20, 10))

            ctk.CTkLabel(
                main_frame,
                text="Insight 모듈이 설치되지 않았습니다.",
                font=get_font("medium"),
                text_color="orange"
            ).pack(pady=10)

            ctk.CTkLabel(
                main_frame,
                text="필요한 패키지:\n- google-api-python-client\n\n설치 방법:\npip install google-api-python-client",
                font=get_font("normal"),
                text_color="gray",
                justify="left"
            ).pack(pady=10)

    # ============================================================
    # Factory 탭 (Factory 1.1.0)
    # ============================================================
    def _create_factory_tab(self):
        """Factory 탭 UI - 채널 팩 설계 AI"""
        if FACTORY_AVAILABLE:
            # FactoryTab 컴포넌트 사용
            self.factory_component = FactoryTab(self.tab_factory)
            # Factory 탭 위젯 참조 저장 (Insight에서 접근용)
            self.factory_tab_widget = self.factory_component
        else:
            # Factory 모듈 없음 안내
            main_frame = ctk.CTkFrame(self.tab_factory)
            main_frame.pack(fill="both", expand=True, padx=20, pady=20)

            ctk.CTkLabel(
                main_frame,
                text="🏭 Factory 모듈",
                font=get_font("title", bold=True)
            ).pack(pady=(20, 10))

            ctk.CTkLabel(
                main_frame,
                text="Factory 모듈이 설치되지 않았습니다.",
                font=get_font("medium"),
                text_color="orange"
            ).pack(pady=10)

            ctk.CTkLabel(
                main_frame,
                text="Factory 모듈은 Insight 분석 결과를 바탕으로\n"
                     "채널 팩(.revpack)을 자동 설계합니다.\n\n"
                     "src/factory/ 폴더를 확인해주세요.",
                font=get_font("normal"),
                text_color="gray",
                justify="left"
            ).pack(pady=10)

    # ============================================================
    # v56.1: Admin 대시보드 탭 (배포용 GUI에서 이동)
    # ============================================================
    def _create_admin_tab(self):
        """B2B 관리자 대시보드 탭"""
        try:
            from gui.admin_dashboard import AdminDashboard
            # AdminDashboard는 Toplevel이므로 Frame으로 임베드
            main_frame = ctk.CTkFrame(self.tab_admin)
            main_frame.pack(fill="both", expand=True, padx=10, pady=10)

            ctk.CTkLabel(
                main_frame,
                text="🏢 B2B 관리자 대시보드",
                font=get_font("title", bold=True)
            ).pack(pady=(20, 10))

            ctk.CTkLabel(
                main_frame,
                text="멀티 채널 관리, 하위 계정 목록, 전체 수익 통계",
                font=get_font("medium"),
                text_color="gray"
            ).pack(pady=10)

            ctk.CTkButton(
                main_frame,
                text="대시보드 열기",
                font=get_font("medium"),
                width=200,
                height=40,
                command=self._open_admin_dashboard_window
            ).pack(pady=20)

        except ImportError as e:
            main_frame = ctk.CTkFrame(self.tab_admin)
            main_frame.pack(fill="both", expand=True, padx=10, pady=10)

            ctk.CTkLabel(
                main_frame,
                text="🏢 Admin Dashboard",
                font=get_font("title", bold=True)
            ).pack(pady=(20, 10))

            ctk.CTkLabel(
                main_frame,
                text=f"Admin 모듈 로드 실패: {e}",
                font=get_font("normal"),
                text_color="orange"
            ).pack(pady=10)

    def _open_admin_dashboard_window(self):
        """Admin 대시보드 창 열기"""
        try:
            from gui.admin_dashboard import AdminDashboard
            dialog = AdminDashboard(self, None)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("오류", f"Admin 대시보드 오류: {e}")

    # ============================================================
    # v56.1: 학습 탭 (배포용 GUI에서 이동)
    # ============================================================
    def _create_training_tab(self):
        """음성 모델 학습 탭 (VRAM 독점 작업)"""
        try:
            from gui.training_wizard import TrainingWizard
            main_frame = ctk.CTkFrame(self.tab_training)
            main_frame.pack(fill="both", expand=True, padx=10, pady=10)

            ctk.CTkLabel(
                main_frame,
                text="🎓 음성 모델 학습",
                font=get_font("title", bold=True)
            ).pack(pady=(20, 10))

            # 경고 문구
            warning_frame = ctk.CTkFrame(main_frame, fg_color="#8B4513")
            warning_frame.pack(fill="x", padx=20, pady=10)

            ctk.CTkLabel(
                warning_frame,
                text="⚠️ 학습 중에는 VRAM을 독점합니다.\n"
                     "Studio에서 영상 생성과 동시에 실행하지 마세요.",
                font=get_font("medium"),
                text_color="white",
                justify="center"
            ).pack(pady=10)

            ctk.CTkLabel(
                main_frame,
                text="GPT-SoVITS 기반 음성 모델 학습\n"
                     "3~5초 샘플 오디오로 새 음성 생성 가능",
                font=get_font("normal"),
                text_color="gray"
            ).pack(pady=10)

            ctk.CTkButton(
                main_frame,
                text="학습 마법사 시작",
                font=get_font("medium"),
                width=200,
                height=40,
                fg_color="#E65100",
                hover_color="#BF360C",
                command=self._open_training_wizard_window
            ).pack(pady=20)

        except ImportError as e:
            main_frame = ctk.CTkFrame(self.tab_training)
            main_frame.pack(fill="both", expand=True, padx=10, pady=10)

            ctk.CTkLabel(
                main_frame,
                text="🎓 학습 마법사",
                font=get_font("title", bold=True)
            ).pack(pady=(20, 10))

            ctk.CTkLabel(
                main_frame,
                text=f"Training 모듈 로드 실패: {e}",
                font=get_font("normal"),
                text_color="orange"
            ).pack(pady=10)

    def _open_training_wizard_window(self):
        """학습 마법사 창 열기"""
        try:
            from gui.training_wizard import TrainingWizard
            wizard = TrainingWizard(self, on_complete=self._on_training_complete)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("오류", f"학습 마법사 오류: {e}")

    def _on_training_complete(self, config):
        """학습 완료 콜백"""
        from tkinter import messagebox
        messagebox.showinfo("완료", f"🎓 음성 모델 '{config.model_name}' 학습 완료!")


def _lg_apply_distribution_stats(self, stats: List[Dict[str, Any]]):
    if not stats:
        self.dist_stats_label.configure(
            text="배포된 패키지가 없습니다.\n(owned_packs 설정이 비어 있습니다)",
            text_color="gray",
        )
        return

    lines = []
    total_active = 0
    total_all = 0
    pack_names = {
        "daily_life_toon_pack": "일상 영상툰",
        "mystery_toon_pack": "미스터리 영상툰",
    }

    for stat in sorted(stats, key=lambda item: item["total_count"], reverse=True):
        pack_id = stat["pack_id"]
        name = pack_names.get(pack_id, pack_id)
        lines.append(f"{name}: {stat['active_count']}/{stat['total_count']} (활성/전체)")
        total_active += stat["active_count"]
        total_all += stat["total_count"]

    lines.insert(0, f"=== 전체 통계: {total_active}/{total_all} 활성 ===\n")
    self.dist_stats_label.configure(text="\n".join(lines), text_color="white")


def _lg_refresh_distribution_stats(self):
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self.dist_stats_label.configure(text="Firebase 연결 안됨", text_color="red")
        return

    self._start_async_job(
        "dist_stats_refresh",
        lambda: self.firebase_validator.get_all_package_stats(),
        on_success=lambda stats: _lg_apply_distribution_stats(self, stats),
        on_error=lambda exc: self.dist_stats_label.configure(
            text=f"통계 로드 실패: {exc}",
            text_color="red",
        ),
        busy_callback=lambda: self.dist_stats_label.configure(
            text="통계 로드 중...",
            text_color="orange",
        ),
    )


def _lg_apply_firebase_list(self, licenses: List[Dict[str, Any]]):
    self._firebase_list_loaded_once = True
    for widget in self.firebase_items_frame.winfo_children():
        widget.destroy()

    if not licenses:
        ctk.CTkLabel(
            self.firebase_items_frame,
            text="등록된 라이센스가 없습니다.",
            text_color="gray",
        ).pack(pady=20)
        return

    for index, license_data in enumerate(licenses):
        self._create_firebase_row(license_data, index)


def _lg_render_firebase_placeholder(self, message: str, color: str = "gray"):
    for widget in self.firebase_items_frame.winfo_children():
        widget.destroy()

    ctk.CTkLabel(
        self.firebase_items_frame,
        text=message,
        text_color=color,
    ).pack(pady=20)


def _lg_refresh_firebase_list(self):
    if not self.firebase_validator or not self.firebase_validator.is_available():
        _lg_render_firebase_placeholder(self, "Firebase 연결 안됨")
        return

    has_loaded_before = bool(getattr(self, "_firebase_list_loaded_once", False))
    if not has_loaded_before:
        _lg_render_firebase_placeholder(self, "목록 로드 중...", "orange")
    self._show_fb_status("목록 로드 중...", "orange")

    self._start_async_job(
        "firebase_list_refresh",
        lambda: self.firebase_validator.get_all_licenses(),
        on_success=lambda licenses: _lg_apply_firebase_list(self, licenses),
        on_error=lambda exc: (
            None
            if has_loaded_before
            else _lg_render_firebase_placeholder(self, "라이센스 목록을 불러오지 못했습니다.", "red")
        ) or self._show_fb_status(f"목록 로드 실패: {exc}", "red"),
    )


def _lg_add_package_to_license(self):
    license_key = self.link_license_entry.get().strip().upper()
    package_id = self.link_package_entry.get().strip()

    if not license_key:
        self._show_pkg_status("라이센스 키를 입력하세요.", "red")
        return
    if not package_id:
        self._show_pkg_status("패키지 ID를 입력하세요.", "red")
        return
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_pkg_status("Firebase 연결 안됨", "red")
        return

    self._start_async_job(
        "pkg_add_single",
        lambda: self.firebase_validator.add_package_to_license(license_key, package_id),
        on_success=lambda result: self._show_pkg_status(
            result[1] if not result[0] else f"패키지 '{package_id}' 추가 완료",
            "green" if result[0] else "red",
        ),
        on_error=lambda exc: self._show_pkg_status(f"오류: {exc}", "red"),
        busy_callback=lambda: self._show_pkg_status("패키지 추가 중...", "orange"),
    )


def _lg_remove_package_from_license(self):
    license_key = self.link_license_entry.get().strip().upper()
    package_id = self.link_package_entry.get().strip()

    if not license_key:
        self._show_pkg_status("라이센스 키를 입력하세요.", "red")
        return
    if not package_id:
        self._show_pkg_status("패키지 ID를 입력하세요.", "red")
        return
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_pkg_status("Firebase 연결 안됨", "red")
        return

    self._start_async_job(
        "pkg_remove_single",
        lambda: self.firebase_validator.remove_package_from_license(license_key, package_id),
        on_success=lambda result: self._show_pkg_status(
            result[1] if not result[0] else f"패키지 '{package_id}' 제거 완료",
            "green" if result[0] else "red",
        ),
        on_error=lambda exc: self._show_pkg_status(f"오류: {exc}", "red"),
        busy_callback=lambda: self._show_pkg_status("패키지 제거 중...", "orange"),
    )


def _lg_view_license_packages(self):
    license_key = self.link_license_entry.get().strip().upper()
    if not license_key:
        self._show_pkg_status("라이센스 키를 입력하세요.", "red")
        return
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_pkg_status("Firebase 연결 안됨", "red")
        return

    def apply_result(license_info):
        if not license_info:
            self._show_pkg_status("라이센스를 찾을 수 없습니다.", "red")
            return
        owned_packs = license_info.get("owned_packs", [])
        license_type = license_info.get("license_type", "?")
        if license_type == "A":
            self._show_pkg_status("전체 이용권(A타입) - 모든 패키지 접근 가능", "green")
        elif owned_packs:
            self._show_pkg_status(f"보유 패키지: {', '.join(owned_packs)}", "green")
        else:
            self._show_pkg_status("보유한 패키지가 없습니다.", "orange")

    self._start_async_job(
        f"pkg_view_{license_key}",
        lambda: self.firebase_validator.get_license_info(license_key),
        on_success=apply_result,
        on_error=lambda exc: self._show_pkg_status(f"조회 오류: {exc}", "red"),
        busy_callback=lambda: self._show_pkg_status("보유 패키지 조회 중...", "orange"),
    )


def _lg_refresh_bulk_package_list(self):
    base_packs = ["daily_life_toon_pack", "mystery_toon_pack"]

    if not self.firebase_validator or not self.firebase_validator.is_available():
        self.bulk_package_combo.configure(values=base_packs)
        self._show_pkg_status("Firebase 연결 안됨", "red")
        return

    def apply_result(registered):
        packs = list(base_packs)
        for pack_id in registered or []:
            if pack_id not in packs:
                packs.append(pack_id)
        self.bulk_package_combo.configure(values=packs)
        self._show_pkg_status(f"패키지 목록 갱신됨 ({len(packs)}개)", "green")

    self._start_async_job(
        "bulk_pack_refresh",
        lambda: self.firebase_validator.get_registered_packages(),
        on_success=apply_result,
        on_error=lambda exc: self._show_pkg_status(f"패키지 목록 조회 실패: {exc}", "red"),
        busy_callback=lambda: self._show_pkg_status("패키지 목록 갱신 중...", "orange"),
    )


def _lg_collect_bulk_target_license_keys(self, target: str):
    all_licenses = self.firebase_validator.get_all_licenses()
    if target == "active":
        return [item["license_key"] for item in all_licenses if item.get("is_active", False)]
    return [item["license_key"] for item in all_licenses]


def _lg_bulk_add_package(self):
    pack_id = self.bulk_package_var.get().strip()
    target = self.bulk_target_var.get()

    if not pack_id:
        self._show_pkg_status("배포할 패키지를 선택하세요.", "red")
        return
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_pkg_status("Firebase 연결 안됨", "red")
        return

    target_desc = "활성 라이센스" if target == "active" else "모든 라이센스"
    if not messagebox.askyesno("일괄 추가 확인", f"'{pack_id}' 패키지를 {target_desc}에 일괄 추가할까요?"):
        return

    def task():
        license_keys = _lg_collect_bulk_target_license_keys(self, target)
        if not license_keys:
            return {"empty": True}
        success, failed, failed_keys = self.firebase_validator.bulk_add_package(license_keys, pack_id)
        return {"empty": False, "success": success, "failed": failed, "failed_keys": failed_keys}

    def on_success(result):
        if result.get("empty"):
            self._show_pkg_status("대상 라이센스가 없습니다.", "orange")
            return
        self._show_pkg_status(
            f"일괄 추가 완료: {result['success']}개 성공, {result['failed']}개 실패",
            "green" if result["failed"] == 0 else "orange",
        )
        self._refresh_distribution_stats()
        self._refresh_firebase_list()

    self._start_async_job(
        f"bulk_add_{pack_id}_{target}",
        task,
        on_success=on_success,
        on_error=lambda exc: self._show_pkg_status(f"일괄 추가 오류: {exc}", "red"),
        busy_callback=lambda: self._show_pkg_status("패키지 일괄 추가 중...", "orange"),
    )


def _lg_bulk_remove_package(self):
    pack_id = self.bulk_package_var.get().strip()
    target = self.bulk_target_var.get()

    if not pack_id:
        self._show_pkg_status("제거할 패키지를 선택하세요.", "red")
        return
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_pkg_status("Firebase 연결 안됨", "red")
        return

    target_desc = "활성 라이센스" if target == "active" else "모든 라이센스"
    if not messagebox.askyesno(
        "일괄 제거 확인",
        f"'{pack_id}' 패키지를 {target_desc}에서 일괄 제거할까요?\n이 작업은 되돌릴 수 없습니다.",
    ):
        return

    def task():
        license_keys = _lg_collect_bulk_target_license_keys(self, target)
        if not license_keys:
            return {"empty": True}
        success, failed, failed_keys = self.firebase_validator.bulk_remove_package(license_keys, pack_id)
        return {"empty": False, "success": success, "failed": failed, "failed_keys": failed_keys}

    def on_success(result):
        if result.get("empty"):
            self._show_pkg_status("대상 라이센스가 없습니다.", "orange")
            return
        self._show_pkg_status(
            f"일괄 제거 완료: {result['success']}개 성공, {result['failed']}개 실패",
            "green" if result["failed"] == 0 else "orange",
        )
        self._refresh_distribution_stats()
        self._refresh_firebase_list()

    self._start_async_job(
        f"bulk_remove_{pack_id}_{target}",
        task,
        on_success=on_success,
        on_error=lambda exc: self._show_pkg_status(f"일괄 제거 오류: {exc}", "red"),
        busy_callback=lambda: self._show_pkg_status("패키지 일괄 제거 중...", "orange"),
    )


def _lg_toggle_firebase_license(self, license_key: str, currently_active: bool):
    if not self.firebase_validator:
        return

    actual_task = (
        (lambda: self.firebase_validator.deactivate_license(license_key))
        if currently_active
        else (lambda: self.firebase_validator.activate_license(license_key))
    )

    self._start_async_job(
        f"firebase_toggle_{license_key}",
        actual_task,
        on_success=lambda result: (
            self._refresh_firebase_list(),
            self._refresh_distribution_stats(),
            self._show_fb_status(result[1], "green" if result[0] else "red"),
        ),
        on_error=lambda exc: self._show_fb_status(f"오류: {exc}", "red"),
        busy_callback=lambda: self._show_fb_status("라이센스 상태 변경 중...", "orange"),
    )


def _lg_delete_firebase_license(self, license_key: str):
    if not self.firebase_validator:
        return

    if not messagebox.askyesno("삭제 확인", f"Firebase에서 라이센스를 삭제하시겠습니까?\n\n{license_key[:30]}..."):
        return

    self._start_async_job(
        f"firebase_delete_{license_key}",
        lambda: self.firebase_validator.delete_license(license_key),
        on_success=lambda result: (
            self._refresh_firebase_list(),
            self._refresh_distribution_stats(),
            self._show_fb_status(result[1], "green" if result[0] else "red"),
        ),
        on_error=lambda exc: self._show_fb_status(f"삭제 실패: {exc}", "red"),
        busy_callback=lambda: self._show_fb_status("라이센스 삭제 중...", "orange"),
    )


def _lg_register_to_firebase(self):
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_fb_status("Firebase 연결 안됨", "red")
        return

    license_key = self.fb_license_entry.get().strip().upper()
    user_id = self.fb_user_entry.get().strip()
    hardware_id = self.fb_hw_entry.get().strip().upper()
    selected_packs = [pack_id for pack_id, var in self.fb_pack_vars.items() if var.get()]

    try:
        duration = int(self.fb_duration_entry.get() or "30")
    except ValueError:
        duration = 30

    if not license_key:
        self._show_fb_status("라이센스 키를 입력하세요.", "red")
        return
    if not user_id:
        self._show_fb_status("사용자 ID를 입력하세요.", "red")
        return
    if not selected_packs:
        self._show_fb_status("최소 1개 이상의 팩을 선택하세요.", "red")
        return

    self._start_async_job(
        f"firebase_register_{license_key}",
        lambda: self.firebase_validator.register_license(
            license_key=license_key,
            user_id=user_id,
            hardware_id=hardware_id,
            license_type="P",
            duration_days=duration,
            owned_packs=selected_packs,
        ),
        on_success=lambda result: (
            self._refresh_firebase_list(),
            self._refresh_distribution_stats(),
            self._show_fb_status(
                f"{result[1]} (팩 {len(selected_packs)}개)" if result[0] else result[1],
                "green" if result[0] else "red",
            ),
            self.fb_license_entry.delete(0, "end") if result[0] else None,
            self.fb_user_entry.delete(0, "end") if result[0] else None,
            self.fb_hw_entry.delete(0, "end") if result[0] else None,
            self.fb_duration_entry.delete(0, "end") if result[0] else None,
        ),
        on_error=lambda exc: self._show_fb_status(f"등록 실패: {exc}", "red"),
        busy_callback=lambda: self._show_fb_status("Firebase 등록 중...", "orange"),
    )


def _lg_sync_history_records(self):
    success_count = 0
    fail_count = 0

    for record in self.license_history:
        try:
            expire_str = record.get("expire_date", "")
            if expire_str:
                expire_date = datetime.datetime.strptime(expire_str, "%Y-%m-%d")
                days_left = max((expire_date - datetime.datetime.now()).days, 0)
            else:
                days_left = 30

            success, _msg = self.firebase_validator.register_license(
                license_key=record.get("license_key", ""),
                user_id=record.get("user_id", ""),
                hardware_id=record.get("hardware_id", ""),
                license_type=record.get("license_type", "A"),
                duration_days=max(days_left, 1),
                memo=record.get("memo", ""),
            )
            if success:
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    return success_count, fail_count


def _lg_sync_to_firebase(self):
    if not self.firebase_validator or not self.firebase_validator.is_available():
        self._show_fb_status("Firebase 연결 안됨", "red")
        return
    if not self.license_history:
        self._show_fb_status("동기화할 로컬 이력이 없습니다.", "orange")
        return
    if not messagebox.askyesno(
        "동기화 확인",
        f"로컬 발급 이력 {len(self.license_history)}개를 Firebase로 동기화하시겠습니까?\n\n"
        "이미 존재하는 라이센스는 덮어씁니다.",
    ):
        return

    self._start_async_job(
        "firebase_sync_all",
        lambda: _lg_sync_history_records(self),
        on_success=lambda result: (
            self._refresh_firebase_list(),
            self._refresh_distribution_stats(),
            self._show_fb_status(
                f"동기화 완료: 성공 {result[0]}개 / 실패 {result[1]}개",
                "green" if result[1] == 0 else "orange",
            ),
        ),
        on_error=lambda exc: self._show_fb_status(f"동기화 실패: {exc}", "red"),
        busy_callback=lambda: self._show_fb_status("Firebase 동기화 중...", "orange"),
    )


def _lg_create_admin_tab(self):
    main_frame = ctk.CTkFrame(self.tab_admin)
    main_frame.pack(fill="both", expand=True, padx=10, pady=10)

    ctk.CTkLabel(
        main_frame,
        text="운영 패널",
        font=get_font("title", bold=True),
    ).pack(pady=(20, 10))

    ctk.CTkLabel(
        main_frame,
        text="실데이터 기반 운영 패널을 엽니다.\n채널 상태, 라이센스 계정, 생산 통계를 관리합니다.",
        font=get_font("medium"),
        text_color="gray",
        justify="center",
    ).pack(pady=10)

    ctk.CTkButton(
        main_frame,
        text="운영 패널 열기",
        font=get_font("medium"),
        width=220,
        height=42,
        command=self._open_admin_dashboard_window,
    ).pack(pady=20)


def _lg_open_admin_dashboard_window(self):
    from gui.admin_dashboard import AdminDashboard

    license_info = {
        "org_name": os.environ.get("REVERIE_ADMIN_ORG_NAME", os.environ.get("COMPUTERNAME", "Reverie Admin")),
        "license_type": "Admin",
    }
    AdminDashboard(
        self,
        license_info=license_info,
        services={"firebase_validator": self.firebase_validator},
    )


LicenseManagerGUI._refresh_distribution_stats = _lg_refresh_distribution_stats
LicenseManagerGUI._refresh_firebase_list = _lg_refresh_firebase_list
LicenseManagerGUI._add_package_to_license = _lg_add_package_to_license
LicenseManagerGUI._remove_package_from_license = _lg_remove_package_from_license
LicenseManagerGUI._view_license_packages = _lg_view_license_packages
LicenseManagerGUI._refresh_bulk_package_list = _lg_refresh_bulk_package_list
LicenseManagerGUI._bulk_add_package = _lg_bulk_add_package
LicenseManagerGUI._bulk_remove_package = _lg_bulk_remove_package
LicenseManagerGUI._toggle_firebase_license = _lg_toggle_firebase_license
LicenseManagerGUI._delete_firebase_license = _lg_delete_firebase_license
LicenseManagerGUI._register_to_firebase = _lg_register_to_firebase
LicenseManagerGUI._sync_to_firebase = _lg_sync_to_firebase
LicenseManagerGUI._create_admin_tab = _lg_create_admin_tab
LicenseManagerGUI._open_admin_dashboard_window = _lg_open_admin_dashboard_window


def main():
    """메인 함수"""
    app = LicenseManagerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
