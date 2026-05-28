# Reverie Insight - GUI 탭 컴포넌트
# Version: 1.8.0

"""
라이센스 관리자 GUI에 삽입되는 Insight 탭 (관리자 전용)
트렌드 수집, AI 분석, 딥 분석, 클론 레시피 생성,
트렌드 리포트 + 경쟁자 분석 기능 제공

v1.8.0: 채널 분석기 추가
        - 채널 URL 입력 → 전체 영상/통계 수집
        - 댓글 감성 분석, 업로드 패턴 분석
        - AI 전략 리포트 생성
        - Factory로 "채널 클론 팩" 전송

v1.7.0: "승인 → .revpack" 버튼 제거, Factory로 통합
        - .revpack 생성은 Factory 탭에서만 진행
        - Insight는 분석 전용, Factory는 제작 전용
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional, List, Dict, Callable
from pathlib import Path

try:
    import customtkinter as ctk
    from tkinter import messagebox
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from insight.trend_collector import (
    TrendCollector,
    SUPPORTED_COUNTRIES,
    VIDEO_CATEGORIES,
    CollectionResult,
    VideoMetadata
)

# AI 문지기 (선택적)
try:
    from insight.ai_gatekeeper import AIGatekeeper, AnalysisResult
    AI_GATEKEEPER_AVAILABLE = True
except ImportError:
    AI_GATEKEEPER_AVAILABLE = False

# 스타일 분석기 (선택적)
try:
    from insight.style_analyzer import StyleAnalyzer, CloneRecipe
    STYLE_ANALYZER_AVAILABLE = True
except ImportError:
    STYLE_ANALYZER_AVAILABLE = False

# Revpack 생성기 (선택적)
try:
    from insight.revpack_generator import RevpackGenerator, get_revpack_generator
    REVPACK_GENERATOR_AVAILABLE = True
except ImportError:
    REVPACK_GENERATOR_AVAILABLE = False

# 트렌드 리포터 (선택적)
try:
    from insight.trend_reporter import (
        TrendReporter, TrendReport, SeasonalEvent,
        GenreRanking, GoldenZoneVideo, CompetitorAnalysis,
        format_report_summary, GENRE_KR_NAMES
    )
    TREND_REPORTER_AVAILABLE = True
except ImportError:
    TREND_REPORTER_AVAILABLE = False

# 채널 분석기 (v1.8.0)
try:
    from insight.channel_analyzer import ChannelAnalyzer, ChannelAnalysis
    CHANNEL_ANALYZER_AVAILABLE = True
except ImportError:
    CHANNEL_ANALYZER_AVAILABLE = False


# ============================================================
# 폰트 설정
# ============================================================
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False):
    """폰트 프리셋"""
    if not CTK_AVAILABLE:
        return None
    sizes = {
        "small": 12,
        "normal": 13,
        "medium": 14,
        "large": 16,
        "title": 20,
        "header": 24,
    }
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


def _format_api_key_status(api_key: str | None) -> tuple[str, str]:
    if (api_key or "").strip():
        return "연결됨 (값 숨김)", "#00AA00"
    return "API 키 없음 - settings.json에 youtube_api_key 추가 필요", "#AA0000"


# ============================================================
# Insight 탭 클래스
# ============================================================

class InsightTab:
    """Insight 탭 UI 컴포넌트"""

    def __init__(
        self,
        parent_frame,
        settings_path: str = None,
        on_open_scenario_editor: Callable[[any, dict, Callable], None] = None,
        on_open_script_preview: Callable[[any, dict], None] = None
    ):
        """
        Args:
            parent_frame: 부모 프레임 (탭 컨테이너)
            settings_path: 설정 파일 경로
            on_open_scenario_editor: GUI 콜백 - ScenarioEditor 열기
                (parent, plan_data, on_approve_callback) -> None
            on_open_script_preview: GUI 콜백 - ScriptPreviewDialog 열기
                (parent, plan_data) -> None

        Note (v57.6.8): GUI 모듈 직접 import 제거 - 콜백 패턴으로 레이어 분리
        """
        self.parent = parent_frame
        self.collector: Optional[TrendCollector] = None
        self.current_result: Optional[CollectionResult] = None
        self.is_collecting = False

        # v57.6.8: GUI 콜백 (레이어 분리)
        self._on_open_scenario_editor = on_open_scenario_editor
        self._on_open_script_preview = on_open_script_preview

        # 분석 결과 저장
        self.analysis_results: List = []
        self.analysis_stats: Dict = {}
        self.clone_recipes: List[CloneRecipe] = [] if STYLE_ANALYZER_AVAILABLE else []
        self.selected_video_index: Optional[int] = None

        # v1.8.0: 채널 분석 결과
        self.channel_analysis: Optional[ChannelAnalysis] = None if CHANNEL_ANALYZER_AVAILABLE else None

        # 설정 파일 경로
        if settings_path is None:
            base_dir = Path(__file__).parent.parent.parent
            settings_path = base_dir / "config" / "settings.json"
        self.settings_path = Path(settings_path)

        # API 키 로드
        self.api_key = self._load_api_key()

        # UI 생성
        self._create_ui()

    def _load_api_key(self) -> Optional[str]:
        """API 키 로드 (여러 위치에서 검색)"""
        # 먼저 환경변수 확인
        api_key = os.environ.get('YOUTUBE_API_KEY')
        if api_key:
            return api_key

        # settings.json 확인
        if self.settings_path.exists():
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    key = settings.get('youtube_api_key') or settings.get('gemini_api_key')
                    if key:
                        return key
            except (json.JSONDecodeError, OSError):
                pass

        # api_settings.json 확인 (src/data 폴더)
        base_dir = Path(__file__).parent.parent  # src 폴더
        api_settings_path = base_dir / "data" / "api_settings.json"
        try:
            from config.settings import config as app_config

            api_settings_path = Path(app_config.DATA_DIR) / "api_settings.json"
        except Exception:
            pass

        if api_settings_path.exists():
            try:
                with open(api_settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # youtube_api_key 또는 gemini_api_key (Google API 키는 YouTube에도 사용 가능)
                    key = settings.get('youtube_api_key') or settings.get('gemini_api_key')
                    if key:
                        return key
            except (json.JSONDecodeError, OSError):
                pass

        return None

    def _create_ui(self):
        """UI 생성"""
        # 메인 스크롤 프레임
        main_frame = ctk.CTkScrollableFrame(self.parent)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # ============================================================
        # 헤더 섹션
        # ============================================================
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        title_label = ctk.CTkLabel(
            header_frame,
            text="Reverie Insight",
            font=get_font("title", bold=True)
        )
        title_label.pack(side="left")

        version_label = ctk.CTkLabel(
            header_frame,
            text="v1.8.0",
            font=get_font("small"),
            text_color="gray"
        )
        version_label.pack(side="left", padx=(10, 0))

        # 트렌드 리포트 버튼 (오른쪽)
        if TREND_REPORTER_AVAILABLE:
            self.report_button = ctk.CTkButton(
                header_frame,
                text="📊 트렌드 리포트",
                font=get_font("normal"),
                width=140,
                height=32,
                fg_color="#F59E0B",
                hover_color="#D97706",
                command=self._open_report_window
            )
            self.report_button.pack(side="right", padx=(5, 0))

        # v1.8.0: 채널 분석 버튼
        if CHANNEL_ANALYZER_AVAILABLE:
            self.channel_analyze_button = ctk.CTkButton(
                header_frame,
                text="📺 채널 분석",
                font=get_font("normal"),
                width=120,
                height=32,
                fg_color="#10B981",
                hover_color="#059669",
                command=self._open_channel_analyzer
            )
            self.channel_analyze_button.pack(side="right", padx=(5, 0))

        # ============================================================
        # API 키 상태
        # ============================================================
        api_status_frame = ctk.CTkFrame(main_frame)
        api_status_frame.pack(fill="x", pady=(0, 15))

        api_label = ctk.CTkLabel(
            api_status_frame,
            text="YouTube API:",
            font=get_font("normal")
        )
        api_label.pack(side="left", padx=10, pady=8)

        status_text, status_color = _format_api_key_status(self.api_key)

        self.api_status_label = ctk.CTkLabel(
            api_status_frame,
            text=status_text,
            font=get_font("normal"),
            text_color=status_color
        )
        self.api_status_label.pack(side="left", padx=5, pady=8)

        # ============================================================
        # 수집 설정 섹션
        # ============================================================
        settings_frame = ctk.CTkFrame(main_frame)
        settings_frame.pack(fill="x", pady=(0, 15))

        settings_title = ctk.CTkLabel(
            settings_frame,
            text="수집 설정",
            font=get_font("medium", bold=True)
        )
        settings_title.pack(anchor="w", padx=10, pady=(10, 5))

        # 국가 선택
        country_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        country_frame.pack(fill="x", padx=10, pady=5)

        country_label = ctk.CTkLabel(
            country_frame,
            text="국가 선택:",
            font=get_font("normal"),
            width=100,
            anchor="w"
        )
        country_label.pack(side="left")

        # 국가 드롭다운
        country_options = [f"{code} - {info['name']}" for code, info in SUPPORTED_COUNTRIES.items()]
        self.country_var = ctk.StringVar(value="KR - 한국")
        self.country_dropdown = ctk.CTkComboBox(
            country_frame,
            values=country_options,
            variable=self.country_var,
            width=200,
            font=get_font("normal")
        )
        self.country_dropdown.pack(side="left", padx=(10, 0))

        # 수집 개수
        count_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        count_frame.pack(fill="x", padx=10, pady=5)

        count_label = ctk.CTkLabel(
            count_frame,
            text="수집 개수:",
            font=get_font("normal"),
            width=100,
            anchor="w"
        )
        count_label.pack(side="left")

        self.count_var = ctk.StringVar(value="50")
        self.count_entry = ctk.CTkEntry(
            count_frame,
            textvariable=self.count_var,
            width=100,
            font=get_font("normal")
        )
        self.count_entry.pack(side="left", padx=(10, 0))

        count_hint = ctk.CTkLabel(
            count_frame,
            text="(최대 50)",
            font=get_font("small"),
            text_color="gray"
        )
        count_hint.pack(side="left", padx=(5, 0))

        # 카테고리 필터
        category_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        category_frame.pack(fill="x", padx=10, pady=5)

        category_label = ctk.CTkLabel(
            category_frame,
            text="카테고리:",
            font=get_font("normal"),
            width=100,
            anchor="w"
        )
        category_label.pack(side="left")

        category_options = ["전체"] + [f"{cid} - {name}" for cid, name in VIDEO_CATEGORIES.items()]
        self.category_var = ctk.StringVar(value="전체")
        self.category_dropdown = ctk.CTkComboBox(
            category_frame,
            values=category_options,
            variable=self.category_var,
            width=200,
            font=get_font("normal")
        )
        self.category_dropdown.pack(side="left", padx=(10, 0))

        # Faceless 전용 체크박스
        self.faceless_only_var = ctk.BooleanVar(value=False)
        self.faceless_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="Faceless 친화 카테고리만 (Film, Entertainment, Education, Science)",
            variable=self.faceless_only_var,
            font=get_font("normal")
        )
        self.faceless_checkbox.pack(anchor="w", padx=10, pady=(5, 10))

        # ============================================================
        # 수집 버튼
        # ============================================================
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(0, 15))

        self.collect_button = ctk.CTkButton(
            button_frame,
            text="트렌드 수집 시작",
            font=get_font("medium", bold=True),
            width=200,
            height=40,
            command=self._on_collect_click
        )
        self.collect_button.pack(side="left")

        self.stop_button = ctk.CTkButton(
            button_frame,
            text="중지",
            font=get_font("normal"),
            width=80,
            height=40,
            fg_color="#AA0000",
            hover_color="#880000",
            command=self._on_stop_click,
            state="disabled"
        )
        self.stop_button.pack(side="left", padx=(10, 0))

        # AI 분석 버튼 (1단계: 썸네일 기반 빠른 분석)
        self.analyze_button = ctk.CTkButton(
            button_frame,
            text="AI 분석",
            font=get_font("medium", bold=True),
            width=120,
            height=40,
            fg_color="#6B21A8",
            hover_color="#7C3AED",
            command=self._on_analyze_click,
            state="disabled"
        )
        self.analyze_button.pack(side="left", padx=(20, 0))

        # 딥 분석 버튼 (2단계: 영상 다운로드 + 상세 분석)
        self.deep_analyze_button = ctk.CTkButton(
            button_frame,
            text="딥 분석",
            font=get_font("medium", bold=True),
            width=120,
            height=40,
            fg_color="#0891B2",
            hover_color="#0E7490",
            command=self._on_deep_analyze_click,
            state="disabled"
        )
        self.deep_analyze_button.pack(side="left", padx=(10, 0))

        # v1.7.0: Factory로 보내기 버튼 (승인 버튼 대체)
        # .revpack 생성은 Factory에서만 진행
        self.factory_button = ctk.CTkButton(
            button_frame,
            text="🏭 Factory로 전송",
            font=get_font("medium", bold=True),
            width=150,
            height=40,
            fg_color="#9333EA",
            hover_color="#7E22CE",
            command=self._send_to_factory,
            state="disabled"
        )
        self.factory_button.pack(side="left", padx=(10, 0))

        # 진행 상태
        self.progress_label = ctk.CTkLabel(
            button_frame,
            text="",
            font=get_font("normal"),
            text_color="gray"
        )
        self.progress_label.pack(side="left", padx=(15, 0))

        # ============================================================
        # 결과 섹션
        # ============================================================
        result_frame = ctk.CTkFrame(main_frame)
        result_frame.pack(fill="both", expand=True, pady=(0, 10))

        result_header = ctk.CTkFrame(result_frame, fg_color="transparent")
        result_header.pack(fill="x", padx=10, pady=(10, 5))

        result_title = ctk.CTkLabel(
            result_header,
            text="수집 결과",
            font=get_font("medium", bold=True)
        )
        result_title.pack(side="left")

        self.result_count_label = ctk.CTkLabel(
            result_header,
            text="",
            font=get_font("normal"),
            text_color="gray"
        )
        self.result_count_label.pack(side="left", padx=(10, 0))

        # 결과 리스트 (텍스트박스로 표시)
        self.result_textbox = ctk.CTkTextbox(
            result_frame,
            font=get_font("small"),
            height=300
        )
        self.result_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.result_textbox.configure(state="disabled")

        # ============================================================
        # 히스토리 섹션
        # ============================================================
        history_frame = ctk.CTkFrame(main_frame)
        history_frame.pack(fill="x", pady=(0, 10))

        history_title = ctk.CTkLabel(
            history_frame,
            text="수집 히스토리",
            font=get_font("medium", bold=True)
        )
        history_title.pack(anchor="w", padx=10, pady=(10, 5))

        self.history_textbox = ctk.CTkTextbox(
            history_frame,
            font=get_font("small"),
            height=100
        )
        self.history_textbox.pack(fill="x", padx=10, pady=(0, 10))
        self.history_textbox.configure(state="disabled")

        # 히스토리 로드
        self._load_history()

    def _on_collect_click(self):
        """수집 버튼 클릭"""
        if not self.api_key:
            messagebox.showerror("오류", "YouTube API 키가 설정되지 않았습니다.\nsettings.json에 youtube_api_key를 추가해주세요.")
            return

        if self.is_collecting:
            return

        # 파라미터 파싱
        country_selection = self.country_var.get()
        country_code = country_selection.split(" - ")[0]

        try:
            max_results = int(self.count_var.get())
            max_results = min(max(1, max_results), 50)
        except (ValueError, TypeError):
            max_results = 50

        category_selection = self.category_var.get()
        category_id = None
        if category_selection != "전체":
            category_id = category_selection.split(" - ")[0]

        faceless_only = self.faceless_only_var.get()

        # 수집 시작
        self.is_collecting = True
        self.collect_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress_label.configure(text="수집 중...")

        # 백그라운드 스레드에서 실행
        thread = threading.Thread(
            target=self._collect_thread,
            args=(country_code, max_results, category_id, faceless_only),
            daemon=True
        )
        thread.start()

    def _collect_thread(self, country_code: str, max_results: int, category_id: Optional[str], faceless_only: bool):
        """백그라운드 수집 스레드"""
        try:
            # Collector 초기화
            if self.collector is None:
                self.collector = TrendCollector(self.api_key)

            # 수집 실행
            if faceless_only:
                result = self.collector.collect_faceless_friendly(country_code, max_results)
            else:
                result = self.collector.collect_trending(country_code, max_results, category_id)

            self.current_result = result

            # UI 업데이트 (메인 스레드에서)
            self.parent.after(0, lambda: self._on_collect_complete(result))

        except Exception as e:
            self.parent.after(0, lambda: self._on_collect_error(str(e)))

    def _on_collect_complete(self, result: CollectionResult):
        """수집 완료 콜백"""
        self.is_collecting = False
        self.collect_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text=f"완료! {result.total_videos}개 수집")

        # 결과 카운트
        self.result_count_label.configure(text=f"{result.total_videos}개 영상 | {result.country_name}")

        # 결과 표시
        self._display_result(result)

        # 히스토리 갱신
        self._load_history()

        # AI 분석 버튼 활성화
        if AI_GATEKEEPER_AVAILABLE and result.total_videos > 0:
            self.analyze_button.configure(state="normal")

    def _on_collect_error(self, error_msg: str):
        """수집 오류 콜백"""
        self.is_collecting = False
        self.collect_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text="오류 발생")

        messagebox.showerror("수집 오류", f"트렌드 수집 중 오류가 발생했습니다:\n\n{error_msg}")

    def _on_stop_click(self):
        """중지 버튼 클릭"""
        self.is_collecting = False
        self.progress_label.configure(text="중지됨")
        self.collect_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _display_result(self, result: CollectionResult):
        """결과 표시"""
        self.result_textbox.configure(state="normal")
        self.result_textbox.delete("1.0", "end")

        lines = []
        lines.append(f"=== {result.country_name} 트렌드 ({result.collected_at[:19]}) ===\n")
        lines.append(f"총 {result.total_videos}개 영상 수집\n")
        lines.append("-" * 60 + "\n\n")

        for i, video in enumerate(result.videos, 1):
            lines.append(f"{i:2}. [{video.category_name}] {video.title[:60]}")
            if len(video.title) > 60:
                lines.append("...")
            lines.append(f"\n    채널: {video.channel_title}")
            lines.append(f"\n    조회수: {video.view_count:,} | 좋아요: {video.like_count:,}")
            lines.append(f"\n    ID: {video.video_id}")
            lines.append(f"\n    URL: https://youtube.com/watch?v={video.video_id}")
            lines.append("\n\n")

        if result.errors:
            lines.append("-" * 60 + "\n")
            lines.append(f"오류 {len(result.errors)}건:\n")
            for err in result.errors:
                lines.append(f"  - {err}\n")

        self.result_textbox.insert("1.0", "".join(lines))
        self.result_textbox.configure(state="disabled")

    def _load_history(self):
        """히스토리 로드 및 표시"""
        if self.collector is None:
            if self.api_key:
                try:
                    self.collector = TrendCollector(self.api_key)
                except Exception:
                    return
            else:
                return

        history = self.collector.get_collection_history()

        self.history_textbox.configure(state="normal")
        self.history_textbox.delete("1.0", "end")

        if not history:
            self.history_textbox.insert("1.0", "수집 히스토리가 없습니다.")
        else:
            lines = []
            for item in history[:10]:  # 최근 10개
                collected_at = item.get('collected_at', '')[:19]
                lines.append(f"[{item.get('country_code')}] {collected_at} - {item.get('total_videos')}개\n")
            self.history_textbox.insert("1.0", "".join(lines))

        self.history_textbox.configure(state="disabled")

    # ============================================================
    # AI 분석 기능
    # ============================================================

    def _on_analyze_click(self):
        """AI 분석 버튼 클릭"""
        if not AI_GATEKEEPER_AVAILABLE:
            messagebox.showerror("오류", "AI Gatekeeper 모듈을 사용할 수 없습니다.")
            return

        if self.current_result is None or self.current_result.total_videos == 0:
            messagebox.showwarning("경고", "먼저 트렌드를 수집해주세요.")
            return

        if self.is_collecting:
            return

        # 분석 시작
        self.is_collecting = True
        self.collect_button.configure(state="disabled")
        self.analyze_button.configure(state="disabled")
        self.progress_label.configure(text="AI 분석 중...")

        # 백그라운드 스레드에서 실행
        thread = threading.Thread(
            target=self._analyze_thread,
            daemon=True
        )
        thread.start()

    def _analyze_thread(self):
        """백그라운드 AI 분석 스레드"""
        try:
            # Gemini API 키 로드
            gemini_key = self._load_gemini_key()
            if not gemini_key:
                self.parent.after(0, lambda: self._on_analyze_error("Gemini API 키가 없습니다."))
                return

            # AI Gatekeeper 초기화
            gatekeeper = AIGatekeeper(gemini_key)

            # 영상 목록을 dict로 변환
            videos = []
            for v in self.current_result.videos:
                videos.append({
                    'video_id': v.video_id,
                    'title': v.title,
                    'description': v.description,
                    'thumbnail_url': v.thumbnail_url,
                    'thumbnail_high_url': v.thumbnail_high_url,
                    'channel_title': v.channel_title,
                    'category_name': v.category_name,
                    'tags': v.tags
                })

            # 진행 콜백
            def progress_callback(current, total, title):
                self.parent.after(0, lambda: self.progress_label.configure(
                    text=f"분석 중... {current}/{total}"
                ))

            # 분석 실행
            results = gatekeeper.analyze_batch(videos, progress_callback)

            # 통계 계산
            stats = gatekeeper.get_summary_stats(results)

            # UI 업데이트
            self.parent.after(0, lambda: self._on_analyze_complete(results, stats))

        except Exception as e:
            self.parent.after(0, lambda: self._on_analyze_error(str(e)))

    def _load_gemini_key(self) -> Optional[str]:
        """Gemini API 키 로드"""
        # 환경변수
        key = os.environ.get('GEMINI_API_KEY')
        if key:
            return key

        # api_settings.json
        base_dir = Path(__file__).parent.parent
        settings_path = base_dir / "data" / "api_settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    return settings.get('gemini_api_key')
            except (json.JSONDecodeError, OSError):
                pass

        return None

    def _on_analyze_complete(self, results: List, stats: Dict):
        """AI 분석 완료 콜백"""
        self.is_collecting = False
        self.collect_button.configure(state="normal")
        self.analyze_button.configure(state="normal")
        self.progress_label.configure(text=f"분석 완료! KEEP: {stats.get('replicable_count', 0)}개")

        # 분석 결과 저장
        self.analysis_results = results
        self.analysis_stats = stats

        # 결과 표시
        self._display_analysis_result(results, stats)

    def _on_analyze_error(self, error_msg: str):
        """AI 분석 오류 콜백"""
        self.is_collecting = False
        self.collect_button.configure(state="normal")
        self.analyze_button.configure(state="normal")
        self.progress_label.configure(text="분석 오류")

        messagebox.showerror("분석 오류", f"AI 분석 중 오류가 발생했습니다:\n\n{error_msg}")

    def _display_analysis_result(self, results: List, stats: Dict):
        """AI 분석 결과 표시"""
        self.result_textbox.configure(state="normal")
        self.result_textbox.delete("1.0", "end")

        lines = []
        lines.append("=" * 60 + "\n")
        lines.append("AI 분석 결과 (Reverie Filtering Protocol v1.1)\n")
        lines.append("=" * 60 + "\n\n")

        # 요약 통계
        lines.append("[요약 통계]\n")
        lines.append(f"  총 영상: {stats.get('total', 0)}개\n")
        lines.append(f"  REAL (실제 인물): {stats.get('real_count', 0)}개 ({stats.get('real_percent', 0)}%)\n")
        lines.append(f"  FACELESS: {stats.get('faceless_count', 0)}개 ({stats.get('faceless_percent', 0)}%)\n")
        lines.append(f"  제작 가능 (KEEP): {stats.get('replicable_count', 0)}개 ({stats.get('replicable_percent', 0)}%)\n")
        lines.append(f"  제작 불가 (DROP): {stats.get('drop_count', 0)}개\n")
        lines.append(f"  평균 Feasibility: {stats.get('avg_feasibility_score', 0)}/100\n")
        lines.append("\n")

        # 스타일 분포
        style_dist = stats.get('style_distribution', {})
        if style_dist:
            lines.append("[스타일 분포]\n")
            for style, count in sorted(style_dist.items(), key=lambda x: -x[1]):
                lines.append(f"  {style}: {count}개\n")
            lines.append("\n")

        # 난이도 분포
        diff_dist = stats.get('difficulty_distribution', {})
        if diff_dist:
            lines.append("[복제 난이도 분포]\n")
            for diff, count in diff_dist.items():
                lines.append(f"  {diff}: {count}개\n")
            lines.append("\n")

        lines.append("-" * 60 + "\n")
        lines.append("\n[KEEP - 제작 가능한 영상]\n\n")

        # KEEP 영상 목록
        keep_count = 0
        for i, result in enumerate(results):
            if result.can_replicate:
                keep_count += 1
                video = self.current_result.videos[i]
                lines.append(f"{keep_count}. [{result.clone_difficulty}] {video.title[:50]}\n")
                lines.append(f"   Type: {result.content_type} | Style: {result.style_type}\n")
                lines.append(f"   Feasibility: {result.feasibility_score}/100\n")
                if result.replication_tips:
                    lines.append(f"   Tip: {result.replication_tips[:80]}\n")
                lines.append(f"   URL: https://youtube.com/watch?v={video.video_id}\n")
                lines.append("\n")

        if keep_count == 0:
            lines.append("  (제작 가능한 영상이 없습니다)\n\n")

        lines.append("-" * 60 + "\n")
        lines.append("\n[DROP - 제작 불가능한 영상]\n\n")

        # DROP 영상 목록
        drop_count = 0
        for i, result in enumerate(results):
            if not result.can_replicate:
                drop_count += 1
                video = self.current_result.videos[i]
                lines.append(f"{drop_count}. {video.title[:50]}\n")
                lines.append(f"   Type: {result.content_type} | Style: {result.style_type}\n")
                if result.drop_reason:
                    lines.append(f"   Reason: {result.drop_reason[:80]}\n")
                lines.append("\n")

        if drop_count == 0:
            lines.append("  (DROP된 영상이 없습니다)\n")

        self.result_textbox.insert("1.0", "".join(lines))
        self.result_textbox.configure(state="disabled")

        # 결과 카운트 업데이트
        self.result_count_label.configure(
            text=f"KEEP: {stats.get('replicable_count', 0)} | DROP: {stats.get('drop_count', 0)}"
        )

        # 딥 분석 버튼 활성화 (KEEP된 영상이 있을 때)
        if STYLE_ANALYZER_AVAILABLE and stats.get('replicable_count', 0) > 0:
            self.deep_analyze_button.configure(state="normal")

    # ============================================================
    # 딥 분석 기능 (Insight 1.2.0)
    # ============================================================

    def _on_deep_analyze_click(self):
        """딥 분석 버튼 클릭"""
        if not STYLE_ANALYZER_AVAILABLE:
            messagebox.showerror("오류", "StyleAnalyzer 모듈을 사용할 수 없습니다.")
            return

        if not hasattr(self, 'analysis_results') or not self.analysis_results:
            messagebox.showwarning("경고", "먼저 AI 분석을 실행해주세요.")
            return

        # KEEP된 영상 확인
        keep_videos = []
        for i, result in enumerate(self.analysis_results):
            if result.can_replicate:
                keep_videos.append((i, result))

        if not keep_videos:
            messagebox.showwarning("경고", "제작 가능한(KEEP) 영상이 없습니다.")
            return

        # 분석 시작
        self.is_collecting = True
        self.collect_button.configure(state="disabled")
        self.analyze_button.configure(state="disabled")
        self.deep_analyze_button.configure(state="disabled")
        self.progress_label.configure(text="딥 분석 중... (영상 다운로드)")

        # 백그라운드 스레드에서 실행
        thread = threading.Thread(
            target=self._deep_analyze_thread,
            args=(keep_videos,),
            daemon=True
        )
        thread.start()

    def _deep_analyze_thread(self, keep_videos: List):
        """백그라운드 딥 분석 스레드"""
        try:
            gemini_key = self._load_gemini_key()
            if not gemini_key:
                self.parent.after(0, lambda: self._on_deep_analyze_error("Gemini API 키가 없습니다."))
                return

            # StyleAnalyzer 초기화
            analyzer = StyleAnalyzer(gemini_key)

            recipes = []
            total = len(keep_videos)

            for idx, (video_idx, gatekeeper_result) in enumerate(keep_videos):
                video = self.current_result.videos[video_idx]

                # 진행 상태 업데이트
                self.parent.after(0, lambda i=idx, t=total, title=video.title[:30]:
                    self.progress_label.configure(text=f"딥 분석 중... {i+1}/{t} - {title}")
                )

                # 영상 정보 딕셔너리
                video_info = {
                    'video_id': video.video_id,
                    'title': video.title,
                    'description': video.description,
                    'thumbnail_url': video.thumbnail_url,
                    'thumbnail_high_url': video.thumbnail_high_url,
                    'channel_title': video.channel_title,
                    'category_name': video.category_name,
                    'tags': video.tags
                }

                # gatekeeper_result를 dict로 변환
                gatekeeper_dict = {
                    'content_type': gatekeeper_result.content_type,
                    'style_type': gatekeeper_result.style_type,
                    'feasibility_score': gatekeeper_result.feasibility_score,
                    'clone_difficulty': gatekeeper_result.clone_difficulty
                }

                # 클론 레시피 생성
                def progress_cb(stage, vid):
                    stages = {
                        'download': '영상 다운로드',
                        'capture': '프레임 캡처',
                        'color': '색상 분석',
                        'style': '스타일 분석',
                        'tts': 'TTS 가이드 생성'
                    }
                    self.parent.after(0, lambda s=stages.get(stage, stage):
                        self.progress_label.configure(text=f"딥 분석 중... {s}")
                    )

                recipe = analyzer.generate_clone_recipe(
                    video_info,
                    gatekeeper_dict,
                    deep_analysis=True,
                    progress_callback=progress_cb
                )

                recipes.append(recipe)

            # 정리
            analyzer.cleanup()

            # UI 업데이트
            self.parent.after(0, lambda: self._on_deep_analyze_complete(recipes))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.parent.after(0, lambda: self._on_deep_analyze_error(str(e)))

    def _on_deep_analyze_complete(self, recipes: List):
        """딥 분석 완료 콜백"""
        self.is_collecting = False
        self.collect_button.configure(state="normal")
        self.analyze_button.configure(state="normal")
        self.deep_analyze_button.configure(state="normal")
        self.progress_label.configure(text=f"딥 분석 완료! {len(recipes)}개 레시피 생성")

        # 레시피 저장
        self.clone_recipes = recipes

        # 결과 표시
        self._display_deep_analysis_result(recipes)

        # v1.7.0: Factory 버튼만 활성화 (.revpack 생성은 Factory에서)
        if recipes:
            self.factory_button.configure(state="normal")

    def _on_deep_analyze_error(self, error_msg: str):
        """딥 분석 오류 콜백"""
        self.is_collecting = False
        self.collect_button.configure(state="normal")
        self.analyze_button.configure(state="normal")
        self.deep_analyze_button.configure(state="normal")
        self.progress_label.configure(text="딥 분석 오류")

        messagebox.showerror("딥 분석 오류", f"딥 분석 중 오류가 발생했습니다:\n\n{error_msg}")

    def _display_deep_analysis_result(self, recipes: List):
        """딥 분석 결과 표시"""
        self.result_textbox.configure(state="normal")
        self.result_textbox.delete("1.0", "end")

        lines = []
        lines.append("=" * 60 + "\n")
        lines.append("딥 분석 결과 (Reverie Insight v1.2.0)\n")
        lines.append("=" * 60 + "\n\n")

        lines.append(f"총 {len(recipes)}개 클론 레시피 생성됨\n\n")

        for i, recipe in enumerate(recipes, 1):
            lines.append("-" * 60 + "\n")
            lines.append(f"\n[{i}] {recipe.video_title[:50]}\n")
            lines.append(f"    채널: {recipe.channel_title}\n")
            lines.append(f"    스타일: {recipe.style_type} | 난이도: {recipe.clone_difficulty}\n")
            lines.append(f"    Feasibility: {recipe.feasibility_score}/100\n\n")

            # 색상 팔레트
            if recipe.color_palette:
                cp = recipe.color_palette
                lines.append(f"    [색상 분석]\n")
                lines.append(f"    밝기: {cp.brightness} | 채도: {cp.saturation} | 분위기: {cp.mood}\n")
                lines.append(f"    주요 색상: {', '.join(cp.color_names[:3])}\n\n")

            # SD 모델 추천
            if recipe.sd_models:
                lines.append(f"    [SD 모델 추천]\n")
                for j, model in enumerate(recipe.sd_models[:3], 1):
                    lines.append(f"    {j}. {model.model_name}")
                    if model.civitai_url:
                        lines.append(f"\n       Civitai: {model.civitai_url}")
                    lines.append(f"\n       이유: {model.match_reason[:50]}\n")
                lines.append("\n")

            # 프롬프트 템플릿
            if recipe.prompt_template:
                lines.append(f"    [프롬프트 템플릿]\n")
                lines.append(f"    Positive: {recipe.prompt_template[:80]}...\n")
                lines.append(f"    Negative: {recipe.negative_prompt[:50]}...\n\n")

            # TTS 가이드 요약
            if recipe.tts_guide:
                tts = recipe.tts_guide
                lines.append(f"    [TTS 가이드]\n")
                lines.append(f"    목소리: {tts.voice_gender}, {tts.voice_age}, {tts.voice_tone}\n")
                lines.append(f"    필요 감정: {', '.join(tts.required_emotions[:4])}\n")
                lines.append(f"    ElevenLabs 힌트: {tts.elevenlabs_hints[:60]}...\n\n")

            lines.append(f"    YouTube: https://youtube.com/watch?v={recipe.video_id}\n")
            lines.append("\n")

        lines.append("=" * 60 + "\n")
        lines.append("\n[🏭 Factory로 전송] 버튼을 클릭하면 Factory에서 .revpack을 생성할 수 있습니다.\n")

        self.result_textbox.insert("1.0", "".join(lines))
        self.result_textbox.configure(state="disabled")

        # 결과 카운트 업데이트
        self.result_count_label.configure(text=f"클론 레시피: {len(recipes)}개")

    # ============================================================
    # 승인 기능 - .revpack 자동 생성 (Insight 1.4.0)
    # ============================================================

    def _on_approve_click(self):
        """승인 버튼 클릭 - .revpack 자동 생성"""
        if not self.clone_recipes:
            messagebox.showwarning("경고", "먼저 딥 분석을 실행해주세요.")
            return

        if not REVPACK_GENERATOR_AVAILABLE:
            # Revpack 생성기 없으면 기존 방식 (JSON 저장만)
            self._on_approve_click_legacy()
            return

        # 저장 위치 확인
        from tkinter import filedialog

        output_dir = filedialog.askdirectory(
            title=".revpack 저장 위치 선택"
        )

        if not output_dir:
            return

        output_path = Path(output_dir)

        # v63: 팩 암호화 제거 (개인용) — 항상 평문 생성
        encrypt = False

        # .revpack 생성 시작
        self.is_collecting = True
        self.approve_button.configure(state="disabled")
        self.progress_label.configure(text=".revpack 생성 중...")

        thread = threading.Thread(
            target=self._generate_revpack_thread,
            args=(output_path, encrypt),
            daemon=True
        )
        thread.start()

    def _on_approve_click_legacy(self):
        """레거시 승인 (JSON 저장만)"""
        from tkinter import filedialog

        output_dir = filedialog.askdirectory(
            title="클론 레시피 저장 위치 선택"
        )

        if not output_dir:
            return

        output_path = Path(output_dir)

        self.is_collecting = True
        self.approve_button.configure(state="disabled")
        self.progress_label.configure(text="레시피 저장 중...")

        thread = threading.Thread(
            target=self._save_recipes_thread,
            args=(output_path,),
            daemon=True
        )
        thread.start()

    def _generate_revpack_thread(self, output_path: Path, encrypt: bool):
        """.revpack 생성 스레드"""
        try:
            generator = get_revpack_generator()
            generator.output_dir = output_path

            generated_packs = []
            total = len(self.clone_recipes)

            for idx, recipe in enumerate(self.clone_recipes):
                # 진행 상태 업데이트
                self.parent.after(0, lambda i=idx, t=total, title=recipe.video_title[:30]:
                    self.progress_label.configure(text=f".revpack 생성 중... {i+1}/{t} - {title}")
                )

                # .revpack 생성
                success, message, pack_path = generator.generate_revpack(
                    recipe=recipe,
                    output_path=None,  # 자동 생성
                    encrypt=encrypt,
                    require_license=encrypt,
                    include_tts_guide=True,
                )

                if success and pack_path:
                    generated_packs.append(pack_path)

            # 요약 파일 생성
            summary = {
                "generated_at": datetime.now().isoformat(),
                "total_packs": len(generated_packs),
                "encrypted": encrypt,
                "generator_version": "1.4.0",
                "packs": [
                    {
                        "filename": p.name,
                        "video_id": self.clone_recipes[i].video_id,
                        "title": self.clone_recipes[i].video_title,
                        "style": self.clone_recipes[i].style_type,
                        "difficulty": self.clone_recipes[i].clone_difficulty,
                    }
                    for i, p in enumerate(generated_packs)
                ]
            }

            with open(output_path / "revpack_summary.json", 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            self.parent.after(0, lambda: self._on_revpack_complete(output_path, generated_packs))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.parent.after(0, lambda: self._on_revpack_error(str(e)))

    def _on_revpack_complete(self, output_path: Path, packs: List[Path]):
        """.revpack 생성 완료 콜백 - v1.5.0: Studio 연동 옵션 추가"""
        self.is_collecting = False
        self.approve_button.configure(state="normal")
        self.progress_label.configure(text=f".revpack 생성 완료! {len(packs)}개")

        # 결과 메시지
        pack_names = "\n".join([f"  - {p.name}" for p in packs[:5]])
        if len(packs) > 5:
            pack_names += f"\n  ... 외 {len(packs) - 5}개"

        # v1.5.0: Studio 연동 옵션 물어보기
        if packs:
            response = messagebox.askyesnocancel(
                ".revpack 생성 완료",
                f"{len(packs)}개의 .revpack 파일이 생성되었습니다.\n\n"
                f"생성된 파일:\n{pack_names}\n\n"
                f"Studio에서 바로 열어서 영상 제작을 시작하시겠습니까?\n\n"
                f"• 예: 첫 번째 패키지로 Studio 열기\n"
                f"• 아니오: 폴더만 열기\n"
                f"• 취소: 아무것도 하지 않음"
            )

            if response is True:
                # Studio로 열기
                self._open_revpack_in_studio(packs[0])
            elif response is False:
                # 폴더만 열기
                import subprocess
                subprocess.Popen(['explorer', str(output_path)])
            # response is None (취소): 아무것도 안 함
        else:
            messagebox.showinfo(
                ".revpack 생성 완료",
                f"생성된 패키지가 없습니다.\n\n위치: {output_path}"
            )

    def _open_revpack_in_studio(self, revpack_path: Path):
        """v1.5.0: .revpack을 Studio(ScenarioEditor)로 열기"""
        try:
            from insight.revpack_generator import get_revpack_generator

            generator = get_revpack_generator()
            success, msg, revpack_data = generator.load_revpack(revpack_path)

            if not success:
                messagebox.showerror("로드 실패", msg)
                return

            # 토픽 선택 다이얼로그
            topic = self._ask_topic_for_studio(revpack_data)
            if topic is None:
                return

            # plan_data로 변환
            plan_data = generator.revpack_to_plan_data(revpack_data, topic)

            # v57.6.8: 콜백 패턴으로 GUI 호출 (레이어 분리)
            def on_approve(approved_plan):
                """에디터에서 승인됨"""
                messagebox.showinfo(
                    "대본 승인됨",
                    "대본이 승인되었습니다.\n\n"
                    "메인 화면의 [📦 패키지] → [.revpack → Studio 열기]에서\n"
                    "영상 제작을 진행하실 수 있습니다."
                )

            # ScenarioEditor 콜백 사용 (우선)
            if self._on_open_scenario_editor:
                self._on_open_scenario_editor(self.parent, plan_data, on_approve)
            # ScriptPreviewDialog 콜백 사용 (대체)
            elif self._on_open_script_preview:
                self._on_open_script_preview(self.parent, plan_data)
            else:
                # 콜백 미설정 시 안내
                messagebox.showwarning(
                    "Studio 미연결",
                    "ScenarioEditor가 연결되지 않았습니다.\n"
                    "GUI에서 InsightTab 초기화 시 콜백을 설정해주세요."
                )

        except Exception as e:
            messagebox.showerror("Studio 열기 오류", f"오류: {e}")

    def _ask_topic_for_studio(self, revpack_data: dict) -> str:
        """Studio로 열 때 주제 선택 다이얼로그"""
        prompts = revpack_data.get("prompts", {})
        topics_data = prompts.get("topics", {})
        templates = topics_data.get("templates", [])

        if not templates:
            return "기본 주제"

        # 간단한 선택 다이얼로그
        dialog = ctk.CTkToplevel(self.parent)
        dialog.title("주제 선택")
        dialog.geometry("350x200")
        dialog.transient(self.parent)
        dialog.grab_set()

        result = {"topic": templates[0] if templates else "기본 주제"}

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame, text="📝 주제를 선택하세요", font=get_font("medium", bold=True)
        ).pack(pady=(0, 15))

        topic_var = ctk.StringVar(value=templates[0] if templates else "")
        ctk.CTkComboBox(
            frame, values=templates[:5], variable=topic_var, width=300
        ).pack(pady=10)

        def on_confirm():
            result["topic"] = topic_var.get() or templates[0]
            dialog.destroy()

        def on_cancel():
            result["topic"] = None
            dialog.destroy()

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(btn_frame, text="취소", width=80, fg_color="#757575", command=on_cancel).pack(side="left")
        ctk.CTkButton(btn_frame, text="확인", width=80, fg_color="#4CAF50", command=on_confirm).pack(side="right")

        dialog.wait_window()
        return result["topic"]

    def _on_revpack_error(self, error_msg: str):
        """.revpack 생성 오류 콜백"""
        self.is_collecting = False
        self.approve_button.configure(state="normal")
        self.progress_label.configure(text=".revpack 오류")

        messagebox.showerror(
            ".revpack 생성 오류",
            f".revpack 생성 중 오류가 발생했습니다:\n\n{error_msg}"
        )

    # ============================================================
    # Factory 연동 (v1.6.0)
    # ============================================================

    def _send_to_factory(self):
        """v1.6.0: 분석 결과를 Factory 탭으로 전송"""
        if not self.clone_recipes:
            messagebox.showwarning("데이터 없음", "먼저 딥 분석을 수행해주세요.")
            return

        # 레시피 선택 다이얼로그
        if len(self.clone_recipes) > 1:
            recipe = self._select_recipe_for_factory()
            if recipe is None:
                return
        else:
            recipe = self.clone_recipes[0]

        # Factory 탭으로 데이터 전송
        try:
            # 메인 윈도우의 Factory 탭 찾기
            main_window = self._find_main_window()
            if main_window and hasattr(main_window, 'factory_tab_widget'):
                # CloneRecipe → dict 변환
                recipe_data = {
                    "video_id": recipe.video_id,
                    "channel_type": recipe.channel_type,
                    "style_type": recipe.style_type,
                    "color_palette": recipe.color_palette,
                    "sd_models": recipe.sd_models,
                    "tts_guide": recipe.tts_guide,
                    "metadata": {
                        "title": recipe.video_title,
                        "theme": recipe.video_title[:30],
                    }
                }

                # Factory 탭으로 전송
                main_window.factory_tab_widget.load_from_clone_recipe(recipe_data)

                # Factory 탭으로 전환
                if hasattr(main_window, 'tabview'):
                    main_window.tabview.set("🏭 Factory")

                self.progress_label.configure(text="✅ Factory로 전송됨")
            else:
                messagebox.showwarning(
                    "Factory 탭 없음",
                    "Factory 탭을 찾을 수 없습니다.\n\n"
                    "메인 윈도우에서 Factory 탭을 확인해주세요."
                )

        except Exception as e:
            messagebox.showerror("전송 오류", f"Factory로 전송 중 오류:\n\n{e}")

    def _find_main_window(self):
        """메인 윈도우 찾기"""
        widget = self.parent
        while widget:
            if hasattr(widget, 'factory_tab_widget'):
                return widget
            if hasattr(widget, 'master'):
                widget = widget.master
            else:
                break
        return None

    def _select_recipe_for_factory(self):
        """Factory로 보낼 레시피 선택 다이얼로그"""
        dialog = ctk.CTkToplevel(self.parent)
        dialog.title("레시피 선택")
        dialog.geometry("400x300")
        dialog.transient(self.parent)
        dialog.grab_set()

        result = {"recipe": None}

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="🏭 Factory로 보낼 레시피를 선택하세요",
            font=get_font("medium", bold=True)
        ).pack(pady=(0, 15))

        # 레시피 리스트
        recipe_var = ctk.StringVar(value="0")
        scroll_frame = ctk.CTkScrollableFrame(frame, height=150)
        scroll_frame.pack(fill="x", pady=10)

        for i, recipe in enumerate(self.clone_recipes[:10]):
            label = f"{recipe.video_title[:40]}... ({recipe.style_type})"
            ctk.CTkRadioButton(
                scroll_frame,
                text=label,
                variable=recipe_var,
                value=str(i),
                font=get_font("small")
            ).pack(anchor="w", pady=2)

        def on_confirm():
            idx = int(recipe_var.get())
            result["recipe"] = self.clone_recipes[idx]
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(15, 0))

        ctk.CTkButton(btn_frame, text="취소", width=80, fg_color="#757575", command=on_cancel).pack(side="left")
        ctk.CTkButton(btn_frame, text="선택", width=80, fg_color="#9333EA", command=on_confirm).pack(side="right")

        dialog.wait_window()
        return result["recipe"]

    def _save_recipes_thread(self, output_path: Path):
        """레시피 저장 스레드 (레거시)"""
        try:
            gemini_key = self._load_gemini_key()
            analyzer = StyleAnalyzer(gemini_key) if STYLE_ANALYZER_AVAILABLE else None

            saved_count = 0
            for recipe in self.clone_recipes:
                # 레시피 폴더 생성
                recipe_dir = output_path / f"recipe_{recipe.video_id}"
                recipe_dir.mkdir(parents=True, exist_ok=True)

                # JSON 저장
                if analyzer:
                    analyzer.export_recipe_json(recipe, recipe_dir / "clone_recipe.json")

                    # TTS 가이드 마크다운 저장
                    analyzer.export_tts_guide_markdown(recipe, recipe_dir / "tts_guide.md")

                saved_count += 1

                self.parent.after(0, lambda c=saved_count:
                    self.progress_label.configure(text=f"저장 중... {c}/{len(self.clone_recipes)}")
                )

            # 전체 요약 JSON
            summary = {
                "generated_at": datetime.now().isoformat(),
                "total_recipes": len(self.clone_recipes),
                "recipes": [
                    {
                        "video_id": r.video_id,
                        "title": r.video_title,
                        "style": r.style_type,
                        "difficulty": r.clone_difficulty,
                        "folder": f"recipe_{r.video_id}"
                    }
                    for r in self.clone_recipes
                ]
            }

            with open(output_path / "summary.json", 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            self.parent.after(0, lambda: self._on_save_complete(output_path, saved_count))

        except Exception as e:
            self.parent.after(0, lambda: self._on_save_error(str(e)))

    def _on_save_complete(self, output_path: Path, count: int):
        """저장 완료 콜백 (레거시)"""
        self.is_collecting = False
        self.approve_button.configure(state="normal")
        self.progress_label.configure(text=f"저장 완료! {count}개 레시피")

        messagebox.showinfo(
            "저장 완료",
            f"{count}개의 클론 레시피가 저장되었습니다.\n\n"
            f"위치: {output_path}\n\n"
            f"각 폴더에는 다음이 포함됩니다:\n"
            f"- clone_recipe.json (SD 모델, 프롬프트 등)\n"
            f"- tts_guide.md (TTS 녹음 가이드)"
        )

        # 폴더 열기
        import subprocess
        subprocess.Popen(['explorer', str(output_path)])

    def _on_save_error(self, error_msg: str):
        """저장 오류 콜백"""
        self.is_collecting = False
        self.approve_button.configure(state="normal")
        self.progress_label.configure(text="저장 오류")

        messagebox.showerror("저장 오류", f"레시피 저장 중 오류가 발생했습니다:\n\n{error_msg}")


    # ============================================================
    # 채널 분석기 (Insight 1.8.0)
    # ============================================================

    def _open_channel_analyzer(self):
        """채널 분석기 창 열기"""
        if not CHANNEL_ANALYZER_AVAILABLE:
            messagebox.showerror("오류", "ChannelAnalyzer 모듈을 사용할 수 없습니다.")
            return

        # 새 윈도우 생성
        analyzer_window = ctk.CTkToplevel(self.parent)
        analyzer_window.title("Reverie Insight - 채널 분석기")
        analyzer_window.geometry("1100x800")
        analyzer_window.grab_set()  # 모달

        # 채널 분석기 UI 생성
        ChannelAnalyzerWindow(analyzer_window, self)

    # ============================================================
    # 트렌드 리포트 기능 (Insight 1.3.0)
    # ============================================================

    def _open_report_window(self):
        """트렌드 리포트 창 열기"""
        if not TREND_REPORTER_AVAILABLE:
            messagebox.showerror("오류", "TrendReporter 모듈을 사용할 수 없습니다.")
            return

        # 새 윈도우 생성
        report_window = ctk.CTkToplevel(self.parent)
        report_window.title("Reverie Insight - 트렌드 리포트")
        report_window.geometry("1000x800")
        report_window.grab_set()  # 모달

        # 리포트 탭 UI 생성
        ReportWindow(report_window, self)

    def generate_trend_report(self, report_type: str = "weekly") -> Optional['TrendReport']:
        """트렌드 리포트 생성"""
        if not TREND_REPORTER_AVAILABLE:
            return None

        if not self.analysis_results:
            return None

        # 분석된 영상에서 VideoMetadata 업데이트
        videos = []
        for i, result in enumerate(self.analysis_results):
            video = self.current_result.videos[i]
            # 분석 결과를 VideoMetadata에 반영
            video.content_type = result.content_type
            video.style_type = result.style_type
            video.feasibility_score = result.feasibility_score
            video.can_replicate = result.can_replicate
            videos.append(video)

        # 리포터 생성 및 리포트 생성
        gemini_key = self._load_gemini_key()
        reporter = TrendReporter(gemini_key)

        if report_type == "weekly":
            return reporter.generate_weekly_report(videos)
        else:
            return reporter.generate_monthly_report(videos)


class ReportWindow:
    """트렌드 리포트 창"""

    def __init__(self, window, insight_tab: InsightTab):
        self.window = window
        self.insight_tab = insight_tab
        self.current_report: Optional[TrendReport] = None

        self._create_ui()

    def _create_ui(self):
        """리포트 창 UI 생성"""
        # 메인 프레임
        main_frame = ctk.CTkFrame(self.window)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 상단 제어 영역
        control_frame = ctk.CTkFrame(main_frame)
        control_frame.pack(fill="x", pady=(0, 10))

        # 제목
        title_label = ctk.CTkLabel(
            control_frame,
            text="📊 트렌드 리포트 & 경쟁자 분석",
            font=get_font("title", bold=True)
        )
        title_label.pack(side="left", padx=10, pady=10)

        # 리포트 생성 버튼
        generate_btn = ctk.CTkButton(
            control_frame,
            text="주간 리포트 생성",
            font=get_font("normal"),
            width=140,
            command=lambda: self._generate_report("weekly")
        )
        generate_btn.pack(side="right", padx=5, pady=10)

        generate_monthly_btn = ctk.CTkButton(
            control_frame,
            text="월간 리포트 생성",
            font=get_font("normal"),
            width=140,
            fg_color="#6B21A8",
            hover_color="#7C3AED",
            command=lambda: self._generate_report("monthly")
        )
        generate_monthly_btn.pack(side="right", padx=5, pady=10)

        # 진행 상태
        self.progress_label = ctk.CTkLabel(
            control_frame,
            text="",
            font=get_font("small"),
            text_color="gray"
        )
        self.progress_label.pack(side="right", padx=10, pady=10)

        # 탭뷰
        self.tabview = ctk.CTkTabview(main_frame)
        self.tabview.pack(fill="both", expand=True)

        # 탭 생성
        self.tabview.add("시즌 추천")
        self.tabview.add("장르 순위")
        self.tabview.add("황금 구역")
        self.tabview.add("경쟁자 분석")
        self.tabview.add("리포트 전체")

        # 각 탭 UI 생성
        self._create_season_tab(self.tabview.tab("시즌 추천"))
        self._create_genre_tab(self.tabview.tab("장르 순위"))
        self._create_golden_tab(self.tabview.tab("황금 구역"))
        self._create_competitor_tab(self.tabview.tab("경쟁자 분석"))
        self._create_full_report_tab(self.tabview.tab("리포트 전체"))

        # 시즌 추천 자동 로드
        self._load_seasonal_recommendations()

    def _create_season_tab(self, parent):
        """시즌 추천 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.season_text = ctk.CTkTextbox(frame, font=get_font("normal"), height=600)
        self.season_text.pack(fill="both", expand=True)
        self.season_text.configure(state="disabled")

    def _create_genre_tab(self, parent):
        """장르 순위 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.genre_text = ctk.CTkTextbox(frame, font=get_font("normal"), height=600)
        self.genre_text.pack(fill="both", expand=True)
        self.genre_text.configure(state="disabled")
        self.genre_text.configure(state="normal")
        self.genre_text.insert("1.0", "리포트를 생성하면 장르 순위가 표시됩니다.")
        self.genre_text.configure(state="disabled")

    def _create_golden_tab(self, parent):
        """황금 구역 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.golden_text = ctk.CTkTextbox(frame, font=get_font("normal"), height=600)
        self.golden_text.pack(fill="both", expand=True)
        self.golden_text.configure(state="disabled")
        self.golden_text.configure(state="normal")
        self.golden_text.insert("1.0", "리포트를 생성하면 황금 구역 영상이 표시됩니다.\n\n"
                                      "황금 구역 = 조회수 높음 + 복제 쉬움\n"
                                      "이 영상들을 벤치마킹하세요!")
        self.golden_text.configure(state="disabled")

    def _create_competitor_tab(self, parent):
        """경쟁자 분석 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.competitor_text = ctk.CTkTextbox(frame, font=get_font("normal"), height=600)
        self.competitor_text.pack(fill="both", expand=True)
        self.competitor_text.configure(state="disabled")
        self.competitor_text.configure(state="normal")
        self.competitor_text.insert("1.0", "리포트를 생성하면 경쟁 채널 분석이 표시됩니다.\n\n"
                                          "강점, 약점, 틈새 전략을 분석합니다.")
        self.competitor_text.configure(state="disabled")

    def _create_full_report_tab(self, parent):
        """전체 리포트 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.full_report_text = ctk.CTkTextbox(frame, font=get_font("small"), height=600)
        self.full_report_text.pack(fill="both", expand=True)
        self.full_report_text.configure(state="disabled")
        self.full_report_text.configure(state="normal")
        self.full_report_text.insert("1.0", "리포트를 생성하면 전체 요약이 표시됩니다.")
        self.full_report_text.configure(state="disabled")

    def _load_seasonal_recommendations(self):
        """시즌 추천 로드"""
        if not TREND_REPORTER_AVAILABLE:
            return

        gemini_key = self.insight_tab._load_gemini_key()
        reporter = TrendReporter(gemini_key)
        seasonal = reporter.get_seasonal_recommendations()

        lines = []
        lines.append("━" * 50 + "\n")
        lines.append(f"🗓️ 현재: {datetime.now().strftime('%Y년 %m월 %d일')}\n")
        lines.append("━" * 50 + "\n\n")

        lines.append("🎃 현재 시즌 이벤트\n")
        lines.append("-" * 40 + "\n")
        for event in seasonal["current_events"]:
            genres_kr = [GENRE_KR_NAMES.get(g, g) for g in event["genres"][:3]]
            lines.append(f"\n  📌 {event['name_kr']} ({event['name']})\n")
            lines.append(f"     추천 장르: {', '.join(genres_kr)}\n")
        lines.append("\n")

        lines.append("📅 다가오는 이벤트 (30일 내)\n")
        lines.append("-" * 40 + "\n")
        for event in seasonal["upcoming_events"][:8]:
            genres_kr = [GENRE_KR_NAMES.get(g, g) for g in event.get("genres", [])[:2]]
            lines.append(f"  [{event.get('month', '?')}월] {event['name_kr']}: {', '.join(genres_kr)}\n")
        lines.append("\n")

        lines.append("🎯 지금 만들면 좋은 장르\n")
        lines.append("-" * 40 + "\n")
        for genre in seasonal["recommended_genres"][:6]:
            genre_kr = GENRE_KR_NAMES.get(genre, genre)
            lines.append(f"  • {genre_kr}\n")

        lines.append("\n" + "━" * 50 + "\n")
        lines.append("\n💡 TIP: 시즌에 맞는 콘텐츠는 검색 유입이 증가합니다.\n")
        lines.append("   7월 공포특집, 10월 할로윈, 12월 감동 콘텐츠 등")

        self.season_text.configure(state="normal")
        self.season_text.delete("1.0", "end")
        self.season_text.insert("1.0", "".join(lines))
        self.season_text.configure(state="disabled")

    def _generate_report(self, report_type: str):
        """리포트 생성"""
        if not self.insight_tab.analysis_results:
            messagebox.showwarning("경고", "먼저 AI 분석을 실행해주세요.\n\n"
                                          "트렌드 수집 → AI 분석 → 리포트 생성")
            return

        self.progress_label.configure(text="리포트 생성 중...")

        # 백그라운드 스레드에서 생성
        thread = threading.Thread(
            target=self._generate_report_thread,
            args=(report_type,),
            daemon=True
        )
        thread.start()

    def _generate_report_thread(self, report_type: str):
        """리포트 생성 스레드"""
        try:
            report = self.insight_tab.generate_trend_report(report_type)
            self.current_report = report

            # UI 업데이트
            self.window.after(0, lambda: self._on_report_complete(report))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.window.after(0, lambda: self._on_report_error(str(e)))

    def _on_report_complete(self, report: 'TrendReport'):
        """리포트 완료"""
        self.progress_label.configure(text=f"완료! {report.report_type.upper()} 리포트")

        # 각 탭 업데이트
        self._update_genre_tab(report)
        self._update_golden_tab(report)
        self._update_competitor_tab(report)
        self._update_full_report_tab(report)

        messagebox.showinfo("리포트 생성 완료",
                           f"{report.report_type.upper()} 리포트가 생성되었습니다.\n\n"
                           f"분석 영상: {report.total_videos_analyzed}개\n"
                           f"장르: {len(report.genre_rankings)}개\n"
                           f"황금 구역: {len(report.golden_zone_videos)}개\n"
                           f"경쟁 채널: {len(report.competitor_analyses)}개")

    def _on_report_error(self, error_msg: str):
        """리포트 오류"""
        self.progress_label.configure(text="오류 발생")
        messagebox.showerror("리포트 오류", f"리포트 생성 중 오류가 발생했습니다:\n\n{error_msg}")

    def _update_genre_tab(self, report: 'TrendReport'):
        """장르 순위 탭 업데이트"""
        lines = []
        lines.append("━" * 50 + "\n")
        lines.append(f"📈 장르별 순위 ({report.report_type.upper()} 리포트)\n")
        lines.append("━" * 50 + "\n\n")

        for i, genre in enumerate(report.genre_rankings, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            lines.append(f"{medal} {genre.genre_kr} ({genre.genre})\n")
            lines.append(f"   영상 수: {genre.video_count}개\n")
            lines.append(f"   총 조회수: {genre.total_views:,}\n")
            lines.append(f"   평균 조회수: {genre.avg_views:,}\n")
            lines.append(f"   가성비 점수: {genre.feasibility_avg:.1f}/100\n")

            if genre.top_videos:
                lines.append("   TOP 영상:\n")
                for j, vid in enumerate(genre.top_videos[:3], 1):
                    lines.append(f"     {j}. {vid['title'][:40]}... ({vid['views']:,}뷰)\n")
            lines.append("\n")

        self.genre_text.configure(state="normal")
        self.genre_text.delete("1.0", "end")
        self.genre_text.insert("1.0", "".join(lines))
        self.genre_text.configure(state="disabled")

    def _update_golden_tab(self, report: 'TrendReport'):
        """황금 구역 탭 업데이트"""
        lines = []
        lines.append("━" * 50 + "\n")
        lines.append("🏆 황금 구역 (조회수 높음 + 복제 쉬움)\n")
        lines.append("━" * 50 + "\n\n")

        if not report.golden_zone_videos:
            lines.append("황금 구역 영상이 없습니다.\n")
            lines.append("조건: 조회수 10만+ & 가성비 70점+\n")
        else:
            for i, golden in enumerate(report.golden_zone_videos, 1):
                lines.append(f"[{i}] {golden.title[:50]}\n")
                lines.append(f"    채널: {golden.channel_name}\n")
                lines.append(f"    조회수: {golden.view_count:,}\n")
                lines.append(f"    가성비: {golden.feasibility_score}/100\n")
                lines.append(f"    스타일: {golden.style_type}\n")
                lines.append(f"    난이도: {golden.clone_difficulty}\n")
                lines.append(f"    추천 모델: {golden.recommended_sd_model}\n")
                if golden.keywords:
                    lines.append(f"    키워드: {', '.join(golden.keywords[:5])}\n")
                lines.append(f"    URL: https://youtube.com/watch?v={golden.video_id}\n")
                lines.append("\n")

        self.golden_text.configure(state="normal")
        self.golden_text.delete("1.0", "end")
        self.golden_text.insert("1.0", "".join(lines))
        self.golden_text.configure(state="disabled")

    def _update_competitor_tab(self, report: 'TrendReport'):
        """경쟁자 분석 탭 업데이트"""
        lines = []
        lines.append("━" * 50 + "\n")
        lines.append("🎯 경쟁 채널 분석\n")
        lines.append("━" * 50 + "\n\n")

        if not report.competitor_analyses:
            lines.append("분석된 경쟁 채널이 없습니다.\n")
        else:
            for i, comp in enumerate(report.competitor_analyses, 1):
                threat_emoji = "🔴" if comp.threat_level == "HIGH" else "🟡" if comp.threat_level == "MEDIUM" else "🟢"
                genre_kr = GENRE_KR_NAMES.get(comp.main_genre, comp.main_genre)

                lines.append(f"[{i}] {comp.channel_name} {threat_emoji}\n")
                lines.append(f"    위협 수준: {comp.threat_level}\n")
                lines.append(f"    영상 수: {comp.video_count}개\n")
                lines.append(f"    총 조회수: {comp.total_views:,}\n")
                lines.append(f"    평균 조회수: {comp.avg_views:,}\n")
                lines.append(f"    주력 장르: {genre_kr}\n")

                if comp.strengths:
                    lines.append(f"\n    💪 강점:\n")
                    for s in comp.strengths:
                        lines.append(f"       • {s}\n")

                if comp.weaknesses:
                    lines.append(f"\n    😰 약점:\n")
                    for w in comp.weaknesses:
                        lines.append(f"       • {w}\n")

                if comp.niche_opportunities:
                    lines.append(f"\n    🎯 틈새 기회:\n")
                    for n in comp.niche_opportunities:
                        lines.append(f"       • {n}\n")

                lines.append("\n" + "-" * 40 + "\n\n")

        self.competitor_text.configure(state="normal")
        self.competitor_text.delete("1.0", "end")
        self.competitor_text.insert("1.0", "".join(lines))
        self.competitor_text.configure(state="disabled")

    def _update_full_report_tab(self, report: 'TrendReport'):
        """전체 리포트 탭 업데이트"""
        summary = format_report_summary(report)

        lines = []
        lines.append(summary)
        lines.append("\n\n")
        lines.append("=" * 50 + "\n")
        lines.append("키워드 트렌드\n")
        lines.append("=" * 50 + "\n\n")

        for i, kw in enumerate(report.trending_keywords[:15], 1):
            lines.append(f"  {i:2}. {kw['keyword']}: {kw['count']}회\n")

        self.full_report_text.configure(state="normal")
        self.full_report_text.delete("1.0", "end")
        self.full_report_text.insert("1.0", "".join(lines))
        self.full_report_text.configure(state="disabled")


# ============================================================
# 채널 분석기 창 (v1.8.0)
# ============================================================

class ChannelAnalyzerWindow:
    """채널 분석기 창"""

    def __init__(self, window, insight_tab: InsightTab):
        self.window = window
        self.insight_tab = insight_tab
        self.analyzer: Optional[ChannelAnalyzer] = None
        self.current_analysis: Optional[ChannelAnalysis] = None
        self.is_analyzing = False

        self._create_ui()

    def _create_ui(self):
        """UI 생성"""
        # 메인 프레임
        main_frame = ctk.CTkFrame(self.window)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 상단: 입력 영역
        input_frame = ctk.CTkFrame(main_frame)
        input_frame.pack(fill="x", pady=(0, 10))

        # 제목
        title_label = ctk.CTkLabel(
            input_frame,
            text="📺 YouTube 채널 심층 분석",
            font=get_font("title", bold=True)
        )
        title_label.pack(side="left", padx=10, pady=10)

        version_label = ctk.CTkLabel(
            input_frame,
            text="v1.8.0",
            font=get_font("small"),
            text_color="gray"
        )
        version_label.pack(side="left", padx=5, pady=10)

        # 채널 URL 입력
        url_frame = ctk.CTkFrame(main_frame)
        url_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            url_frame,
            text="채널 URL:",
            font=get_font("normal"),
            width=80
        ).pack(side="left", padx=10, pady=10)

        self.url_entry = ctk.CTkEntry(
            url_frame,
            placeholder_text="https://www.youtube.com/@채널명 또는 채널 ID",
            width=500,
            font=get_font("normal")
        )
        self.url_entry.pack(side="left", padx=5, pady=10)

        self.analyze_button = ctk.CTkButton(
            url_frame,
            text="🔍 분석 시작",
            font=get_font("medium", bold=True),
            width=120,
            height=36,
            fg_color="#10B981",
            hover_color="#059669",
            command=self._start_analysis
        )
        self.analyze_button.pack(side="left", padx=10, pady=10)

        # 옵션
        option_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        option_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            option_frame,
            text="분석 영상 수:",
            font=get_font("normal")
        ).pack(side="left", padx=10)

        self.max_videos_var = ctk.StringVar(value="50")
        ctk.CTkEntry(
            option_frame,
            textvariable=self.max_videos_var,
            width=60,
            font=get_font("normal")
        ).pack(side="left", padx=5)

        self.analyze_comments_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            option_frame,
            text="댓글 AI 분석",
            variable=self.analyze_comments_var,
            font=get_font("normal")
        ).pack(side="left", padx=20)

        self.generate_report_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            option_frame,
            text="AI 전략 리포트",
            variable=self.generate_report_var,
            font=get_font("normal")
        ).pack(side="left", padx=10)

        # 진행 상태
        self.progress_label = ctk.CTkLabel(
            option_frame,
            text="",
            font=get_font("normal"),
            text_color="gray"
        )
        self.progress_label.pack(side="right", padx=10)

        # 결과 탭뷰
        self.result_tabview = ctk.CTkTabview(main_frame)
        self.result_tabview.pack(fill="both", expand=True)

        # 탭 생성
        self.result_tabview.add("📊 요약")
        self.result_tabview.add("📈 통계")
        self.result_tabview.add("🎯 패턴")
        self.result_tabview.add("💬 댓글 분석")
        self.result_tabview.add("📝 전략 리포트")

        # 각 탭 UI
        self._create_summary_tab(self.result_tabview.tab("📊 요약"))
        self._create_stats_tab(self.result_tabview.tab("📈 통계"))
        self._create_pattern_tab(self.result_tabview.tab("🎯 패턴"))
        self._create_comments_tab(self.result_tabview.tab("💬 댓글 분석"))
        self._create_report_tab(self.result_tabview.tab("📝 전략 리포트"))

        # 하단: 버튼
        bottom_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        bottom_frame.pack(fill="x", pady=(10, 0))

        self.factory_button = ctk.CTkButton(
            bottom_frame,
            text="🏭 Factory로 전송",
            font=get_font("medium", bold=True),
            width=150,
            height=40,
            fg_color="#9333EA",
            hover_color="#7E22CE",
            command=self._send_to_factory,
            state="disabled"
        )
        self.factory_button.pack(side="right", padx=5)

        self.export_button = ctk.CTkButton(
            bottom_frame,
            text="📁 JSON 내보내기",
            font=get_font("normal"),
            width=130,
            height=40,
            fg_color="#6B7280",
            hover_color="#4B5563",
            command=self._export_json,
            state="disabled"
        )
        self.export_button.pack(side="right", padx=5)

    def _create_summary_tab(self, parent):
        """요약 탭"""
        self.summary_text = ctk.CTkTextbox(parent, font=get_font("normal"))
        self.summary_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.summary_text.configure(state="disabled")
        self._set_placeholder(self.summary_text, "채널 URL을 입력하고 '분석 시작'을 클릭하세요.")

    def _create_stats_tab(self, parent):
        """통계 탭"""
        self.stats_text = ctk.CTkTextbox(parent, font=get_font("normal"))
        self.stats_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.stats_text.configure(state="disabled")
        self._set_placeholder(self.stats_text, "분석 후 통계가 표시됩니다.")

    def _create_pattern_tab(self, parent):
        """패턴 탭"""
        self.pattern_text = ctk.CTkTextbox(parent, font=get_font("normal"))
        self.pattern_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.pattern_text.configure(state="disabled")
        self._set_placeholder(self.pattern_text, "분석 후 업로드/제목 패턴이 표시됩니다.")

    def _create_comments_tab(self, parent):
        """댓글 분석 탭"""
        self.comments_text = ctk.CTkTextbox(parent, font=get_font("normal"))
        self.comments_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.comments_text.configure(state="disabled")
        self._set_placeholder(self.comments_text, "분석 후 댓글 감성 분석 결과가 표시됩니다.")

    def _create_report_tab(self, parent):
        """전략 리포트 탭"""
        self.report_text = ctk.CTkTextbox(parent, font=get_font("normal"))
        self.report_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.report_text.configure(state="disabled")
        self._set_placeholder(self.report_text, "분석 후 AI 전략 리포트가 표시됩니다.")

    def _set_placeholder(self, textbox, text):
        """텍스트박스에 플레이스홀더 설정"""
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")

    def _start_analysis(self):
        """분석 시작"""
        if self.is_analyzing:
            return

        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("입력 필요", "채널 URL 또는 ID를 입력해주세요.")
            return

        # API 키 확인
        youtube_key = self.insight_tab.api_key
        gemini_key = self.insight_tab._load_gemini_key()

        if not youtube_key:
            messagebox.showerror("API 키 없음", "YouTube API 키가 설정되지 않았습니다.")
            return

        # 옵션
        try:
            max_videos = int(self.max_videos_var.get())
            max_videos = min(max(10, max_videos), 200)
        except (ValueError, TypeError):
            max_videos = 50

        analyze_comments = self.analyze_comments_var.get()
        generate_report = self.generate_report_var.get()

        # 분석 시작
        self.is_analyzing = True
        self.analyze_button.configure(state="disabled")
        self.progress_label.configure(text="분석 준비 중...")

        # 백그라운드 스레드
        thread = threading.Thread(
            target=self._analyze_thread,
            args=(url, youtube_key, gemini_key, max_videos, analyze_comments, generate_report),
            daemon=True
        )
        thread.start()

    def _analyze_thread(self, url, youtube_key, gemini_key, max_videos, analyze_comments, generate_report):
        """백그라운드 분석 스레드"""
        try:
            # 분석기 초기화
            self.analyzer = ChannelAnalyzer(youtube_key, gemini_key)

            # 진행 콜백
            def progress_cb(current, total, stage):
                self.window.after(0, lambda: self.progress_label.configure(
                    text=f"{stage}... {current}/{total}"
                ))

            # 분석 실행
            analysis = self.analyzer.analyze_channel(
                url,
                max_videos=max_videos,
                analyze_comments=analyze_comments,
                generate_report=generate_report,
                progress_callback=progress_cb
            )

            if analysis:
                self.current_analysis = analysis
                self.window.after(0, lambda: self._on_analysis_complete(analysis))
            else:
                self.window.after(0, lambda: self._on_analysis_error("채널을 찾을 수 없습니다."))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.window.after(0, lambda: self._on_analysis_error(str(e)))

    def _on_analysis_complete(self, analysis: ChannelAnalysis):
        """분석 완료"""
        self.is_analyzing = False
        self.analyze_button.configure(state="normal")
        self.factory_button.configure(state="normal")
        self.export_button.configure(state="normal")
        self.progress_label.configure(text=f"✅ 분석 완료: {len(analysis.videos)}개 영상")

        # 결과 표시
        self._display_summary(analysis)
        self._display_stats(analysis)
        self._display_pattern(analysis)
        self._display_comments(analysis)
        self._display_report(analysis)

    def _on_analysis_error(self, error_msg):
        """분석 오류"""
        self.is_analyzing = False
        self.analyze_button.configure(state="normal")
        self.progress_label.configure(text="❌ 오류 발생")
        messagebox.showerror("분석 오류", f"채널 분석 중 오류가 발생했습니다:\n\n{error_msg}")

    def _display_summary(self, analysis: ChannelAnalysis):
        """요약 표시"""
        lines = []
        lines.append("=" * 50 + "\n")
        lines.append(f"📺 {analysis.channel_title}\n")
        lines.append("=" * 50 + "\n\n")

        lines.append(f"채널 ID: {analysis.channel_id}\n")
        lines.append(f"구독자: {analysis.subscriber_count:,}명\n")
        lines.append(f"총 조회수: {analysis.total_view_count:,}\n")
        lines.append(f"총 영상: {analysis.total_video_count}개\n")
        lines.append(f"개설일: {analysis.channel_created_at[:10]}\n\n")

        lines.append("-" * 50 + "\n")
        lines.append("📈 주요 지표\n")
        lines.append("-" * 50 + "\n\n")

        lines.append(f"평균 조회수: {analysis.avg_views_per_video:,.0f}\n")
        lines.append(f"평균 좋아요: {analysis.avg_likes_per_video:,.0f}\n")
        lines.append(f"평균 댓글: {analysis.avg_comments_per_video:,.0f}\n")
        lines.append(f"참여율: {analysis.engagement_rate:.2%}\n\n")

        lines.append("-" * 50 + "\n")
        lines.append("🏆 TOP 5 영상 (조회수)\n")
        lines.append("-" * 50 + "\n\n")

        for i, v in enumerate(analysis.top_videos_by_views[:5], 1):
            lines.append(f"{i}. {v.title[:50]}\n")
            lines.append(f"   조회수: {v.view_count:,} | 좋아요: {v.like_count:,}\n\n")

        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "".join(lines))
        self.summary_text.configure(state="disabled")

    def _display_stats(self, analysis: ChannelAnalysis):
        """통계 표시"""
        lines = []
        lines.append("=" * 50 + "\n")
        lines.append("📈 영상 통계 분석\n")
        lines.append("=" * 50 + "\n\n")

        if analysis.videos:
            views = [v.view_count for v in analysis.videos]
            lines.append(f"분석 영상 수: {len(analysis.videos)}개\n\n")

            lines.append("[조회수 분포]\n")
            lines.append(f"  최고: {max(views):,}\n")
            lines.append(f"  최저: {min(views):,}\n")
            lines.append(f"  평균: {sum(views)/len(views):,.0f}\n")
            lines.append(f"  중앙값: {sorted(views)[len(views)//2]:,}\n\n")

            # 영상 길이 분포
            durations = [v.duration_seconds for v in analysis.videos if v.duration_seconds > 0]
            if durations:
                avg_min = sum(durations) / len(durations) / 60
                lines.append(f"[영상 길이]\n")
                lines.append(f"  평균: {avg_min:.1f}분\n")
                lines.append(f"  최장: {max(durations)//60}분 {max(durations)%60}초\n")
                lines.append(f"  최단: {min(durations)//60}분 {min(durations)%60}초\n\n")

            # 성과 분포
            lines.append("[성과 분포]\n")
            high_perf = sum(1 for v in analysis.videos if v.performance_score > 1.5)
            mid_perf = sum(1 for v in analysis.videos if 0.5 <= v.performance_score <= 1.5)
            low_perf = sum(1 for v in analysis.videos if v.performance_score < 0.5)
            lines.append(f"  평균 이상 (1.5x+): {high_perf}개\n")
            lines.append(f"  평균 수준: {mid_perf}개\n")
            lines.append(f"  평균 이하: {low_perf}개\n")

        self.stats_text.configure(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("1.0", "".join(lines))
        self.stats_text.configure(state="disabled")

    def _display_pattern(self, analysis: ChannelAnalysis):
        """패턴 표시"""
        lines = []
        lines.append("=" * 50 + "\n")
        lines.append("🎯 업로드 & 제목 패턴\n")
        lines.append("=" * 50 + "\n\n")

        if analysis.upload_pattern:
            up = analysis.upload_pattern
            lines.append("[업로드 패턴]\n")
            lines.append(f"  주당 평균: {up.avg_videos_per_week}개\n")
            lines.append(f"  최적 요일: {up.best_upload_day}요일\n")
            lines.append(f"  최적 시간: {up.best_upload_hour}시\n")
            lines.append(f"  트렌드: {up.upload_frequency_trend}\n\n")

            lines.append("  [요일별 분포]\n")
            for day, count in sorted(up.upload_day_distribution.items(), key=lambda x: -x[1]):
                bar = "█" * (count // 2)
                lines.append(f"    {day}: {bar} {count}개\n")
            lines.append("\n")

        if analysis.title_pattern:
            tp = analysis.title_pattern
            lines.append("[제목 패턴]\n")
            lines.append(f"  평균 길이: {tp.avg_title_length}자\n")
            lines.append(f"  이모지 사용: {tp.emoji_usage_rate:.0%}\n")
            lines.append(f"  숫자 사용: {tp.number_usage_rate:.0%}\n\n")

            lines.append("  [자주 쓰는 키워드]\n")
            for kw, count in tp.common_keywords[:10]:
                lines.append(f"    • {kw}: {count}회\n")
            lines.append("\n")

            if tp.common_patterns:
                lines.append("  [제목 공식]\n")
                for pattern in tp.common_patterns:
                    lines.append(f"    • {pattern}\n")

        self.pattern_text.configure(state="normal")
        self.pattern_text.delete("1.0", "end")
        self.pattern_text.insert("1.0", "".join(lines))
        self.pattern_text.configure(state="disabled")

    def _display_comments(self, analysis: ChannelAnalysis):
        """댓글 분석 표시"""
        lines = []
        lines.append("=" * 50 + "\n")
        lines.append("💬 댓글 감성 분석 (AI)\n")
        lines.append("=" * 50 + "\n\n")

        if analysis.comment_analysis and analysis.comment_analysis.total_comments_analyzed > 0:
            ca = analysis.comment_analysis
            lines.append(f"분석 댓글: {ca.total_comments_analyzed}개\n\n")

            lines.append("[감성 분석]\n")
            pos_bar = "█" * int(ca.sentiment_positive * 20)
            neg_bar = "█" * int(ca.sentiment_negative * 20)
            neu_bar = "█" * int(ca.sentiment_neutral * 20)
            lines.append(f"  긍정: {pos_bar} {ca.sentiment_positive:.0%}\n")
            lines.append(f"  부정: {neg_bar} {ca.sentiment_negative:.0%}\n")
            lines.append(f"  중립: {neu_bar} {ca.sentiment_neutral:.0%}\n\n")

            if ca.fan_characteristics:
                lines.append(f"[팬층 특성]\n")
                lines.append(f"  {ca.fan_characteristics}\n\n")

            if ca.common_requests:
                lines.append("[시청자 요청]\n")
                for req in ca.common_requests:
                    lines.append(f"  • {req}\n")
                lines.append("\n")

            if ca.common_praise:
                lines.append("[칭찬 포인트]\n")
                for praise in ca.common_praise:
                    lines.append(f"  • {praise}\n")
                lines.append("\n")

            if ca.common_criticism:
                lines.append("[지적 사항]\n")
                for crit in ca.common_criticism:
                    lines.append(f"  • {crit}\n")
        else:
            lines.append("댓글 분석 데이터가 없습니다.\n")
            lines.append("'댓글 AI 분석' 옵션을 활성화하고 다시 분석해주세요.\n")

        self.comments_text.configure(state="normal")
        self.comments_text.delete("1.0", "end")
        self.comments_text.insert("1.0", "".join(lines))
        self.comments_text.configure(state="disabled")

    def _display_report(self, analysis: ChannelAnalysis):
        """전략 리포트 표시"""
        if analysis.ai_strategy_report:
            content = analysis.ai_strategy_report
        else:
            content = "AI 전략 리포트가 없습니다.\n'AI 전략 리포트' 옵션을 활성화하고 다시 분석해주세요."

        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", content)
        self.report_text.configure(state="disabled")

    def _send_to_factory(self):
        """Factory로 전송"""
        if not self.current_analysis:
            return

        try:
            # 채널 클론 데이터 생성
            clone_data = self.analyzer.to_clone_recipe_data(self.current_analysis)

            # 메인 윈도우의 Factory 탭 찾기
            main_window = self.insight_tab._find_main_window()
            if main_window and hasattr(main_window, 'factory_tab_widget'):
                # Factory 탭으로 전송
                main_window.factory_tab_widget.load_from_channel_analysis(clone_data)

                # Factory 탭으로 전환
                if hasattr(main_window, 'tabview'):
                    main_window.tabview.set("🏭 Factory")

                self.progress_label.configure(text="✅ Factory로 전송됨")
                messagebox.showinfo("전송 완료", "채널 분석 데이터가 Factory로 전송되었습니다.")
            else:
                messagebox.showwarning("Factory 없음", "Factory 탭을 찾을 수 없습니다.")

        except Exception as e:
            messagebox.showerror("전송 오류", f"Factory 전송 실패:\n{e}")

    def _export_json(self):
        """JSON 내보내기"""
        if not self.current_analysis:
            return

        from tkinter import filedialog

        filename = filedialog.asksaveasfilename(
            title="분석 결과 저장",
            defaultextension=".json",
            filetypes=[("JSON 파일", "*.json")],
            initialfilename=f"channel_analysis_{self.current_analysis.channel_id}.json"
        )

        if filename:
            if self.analyzer.export_to_json(self.current_analysis, filename):
                messagebox.showinfo("저장 완료", f"분석 결과가 저장되었습니다:\n{filename}")
            else:
                messagebox.showerror("저장 실패", "파일 저장에 실패했습니다.")


# ============================================================
# 테스트용
# ============================================================

def main():
    """독립 실행 테스트"""
    if not CTK_AVAILABLE:
        print("customtkinter가 필요합니다.")
        return

    root = ctk.CTk()
    root.title("Insight Tab Test")
    root.geometry("800x700")

    # v57.6.8: 테스트용 콜백 (실제 GUI 모듈은 테스트에서 로드 생략)
    def test_scenario_editor(parent, plan_data, on_approve):
        print(f"[TEST] ScenarioEditor 호출: plan_data={list(plan_data.keys())}")

    def test_script_preview(parent, plan_data):
        print(f"[TEST] ScriptPreviewDialog 호출: plan_data={list(plan_data.keys())}")

    tab = InsightTab(
        root,
        on_open_scenario_editor=test_scenario_editor,
        on_open_script_preview=test_script_preview
    )

    root.mainloop()


if __name__ == "__main__":
    main()
