# src/gui/auto_optimizer_dialog.py
"""
v54.1 → v57: 자동 최적화 다이얼로그

"유토피아" 시스템의 GUI
- 자동 최적화 상태 모니터링
- 썸네일 교체 필요 영상 관리
- 패턴 학습 결과 확인
- 스케줄러 제어
- v54.3: 개인화된 프롬프트 최적화 추가
- v54.4: 업로드 스케줄러 탭 추가
- v54.5: 피드백 루프 탭 추가
- v54.6: 유토피아 엔진 통합 (완전 자동 모드)
- v54.7: 대시보드 버튼 추가
- v54.8: 멀티채널 지원 (채널 선택 드롭다운, 최대 100개)
- v55: 캐릭터 관리 탭 (이미지 일관성)
- v53: 효과음 설정 탭 (Auto-SFX)
- v56: 멀티채널 스케줄러 탭
- v57: 다국어 지원 (채널별 언어 설정)
"""
import customtkinter as ctk
from tkinter import messagebox
import threading
from typing import Optional
from datetime import datetime

# v57: 다국어 지원
from utils.channel_registry import SUPPORTED_LANGUAGES


class AutoOptimizerDialog(ctk.CTkToplevel):
    """자동 최적화 다이얼로그"""

    def __init__(self, parent, data_dir: str, channel_type: str = "daily_life_toon", channel_id: str = None):
        super().__init__(parent)

        self.parent = parent
        self.data_dir = data_dir
        self.channel_type = channel_type
        self.channel_id = channel_id  # v54.8: 멀티채널 지원
        self.optimizer = None
        self.prompt_optimizer = None  # v54.3: 개인화 프롬프트 최적화
        self.upload_scheduler = None  # v54.4: 업로드 스케줄러
        self.feedback_loop = None  # v54.5: 피드백 루프
        self.utopia_engine = None  # v54.6: 유토피아 엔진

        # v54.8: 채널 레지스트리
        self.channel_registry = None
        self._init_channel_registry()

        self.title("🤖 자동 최적화 시스템 (유토피아)")
        self.geometry("1050x750")  # v54.8: 채널 선택 UI를 위해 크기 확대
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 1050) // 2
        y = (self.winfo_screenheight() - 750) // 2
        self.geometry(f"1050x750+{x}+{y}")

        self._init_optimizer()
        self._create_ui()
        self._load_data()

    def _init_channel_registry(self):
        """v54.8: 채널 레지스트리 초기화"""
        try:
            from utils.channel_registry import get_channel_registry
            self.channel_registry = get_channel_registry(self.data_dir)
        except Exception as e:
            print(f"ChannelRegistry 초기화 실패: {e}")

    def _init_optimizer(self):
        """AutoOptimizer 초기화"""
        try:
            from utils.auto_optimizer import get_auto_optimizer
            self.optimizer = get_auto_optimizer(self.data_dir, self.channel_type)
        except Exception as e:
            messagebox.showerror("오류", f"AutoOptimizer 초기화 실패: {e}")

        # v54.3: PromptOptimizer 초기화
        try:
            from utils.prompt_optimizer import get_prompt_optimizer
            self.prompt_optimizer = get_prompt_optimizer(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"PromptOptimizer 초기화 실패: {e}")

        # v54.4: UploadScheduler 초기화
        try:
            from utils.upload_scheduler import get_upload_scheduler
            self.upload_scheduler = get_upload_scheduler(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"UploadScheduler 초기화 실패: {e}")

        # v54.5: FeedbackLoop 초기화
        try:
            from utils.feedback_loop import get_feedback_loop
            self.feedback_loop = get_feedback_loop(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"FeedbackLoop 초기화 실패: {e}")

        # v54.6/v54.8: UtopiaEngine 초기화 (멀티채널 지원)
        try:
            from utils.utopia_engine import get_utopia_engine
            self.utopia_engine = get_utopia_engine(
                self.data_dir,
                self.channel_type,
                self.channel_id  # v54.8: 멀티채널
            )
            # v54.7.1: 모드 변경 콜백 연결
            self.utopia_engine.on_mode_change = self._on_engine_mode_change
        except Exception as e:
            print(f"UtopiaEngine 초기화 실패: {e}")

    def _create_ui(self):
        """UI 구성"""
        # v54.8: 채널 선택 헤더
        self._create_channel_header()

        # 탭뷰
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        # 탭 추가
        self.tab_status = self.tabview.add("📊 상태")
        self.tab_thumbnails = self.tabview.add("🖼️ 썸네일 관리")
        self.tab_patterns = self.tabview.add("🧠 패턴 학습")
        self.tab_personalization = self.tabview.add("🎯 개인화")  # v54.3
        self.tab_upload = self.tabview.add("📤 업로드")  # v54.4
        self.tab_feedback = self.tabview.add("🔄 피드백")  # v54.5
        self.tab_characters = self.tabview.add("👤 캐릭터")  # v55: 캐릭터 관리
        self.tab_sfx = self.tabview.add("🔊 효과음")  # v53: Auto-SFX
        self.tab_scheduler = self.tabview.add("📅 스케줄러")  # v56: 멀티채널 스케줄러
        self.tab_settings = self.tabview.add("⚙️ 설정")

        # 각 탭 구성
        self._build_status_tab()
        self._build_thumbnails_tab()
        self._build_patterns_tab()
        self._build_personalization_tab()  # v54.3
        self._build_upload_tab()  # v54.4
        self._build_feedback_tab()  # v54.5
        self._build_characters_tab()  # v55: 캐릭터 관리
        self._build_sfx_tab()  # v53: Auto-SFX
        self._build_scheduler_tab()  # v56: 멀티채널 스케줄러
        self._build_settings_tab()

    # =========================================================
    # v54.8: 채널 선택 헤더
    # =========================================================

    def _create_channel_header(self):
        """v54.8: 채널 선택 헤더 UI"""
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(15, 5))

        # 왼쪽: 채널 선택
        left_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            left_frame,
            text="📺 채널:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left", padx=(0, 10))

        # 채널 드롭다운
        self.channel_var = ctk.StringVar(value=self._get_current_channel_display())
        self.channel_dropdown = ctk.CTkComboBox(
            left_frame,
            variable=self.channel_var,
            values=self._get_channel_list(),
            command=self._on_channel_change,
            width=300,
            state="readonly"
        )
        self.channel_dropdown.pack(side="left", padx=(0, 10))

        # 새로고침 버튼
        ctk.CTkButton(
            left_frame,
            text="🔄",
            width=35,
            command=self._refresh_channel_list
        ).pack(side="left", padx=(0, 5))

        # 오른쪽: 채널 관리 버튼들
        right_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_frame.pack(side="right")

        # 채널 추가 버튼
        ctk.CTkButton(
            right_frame,
            text="➕ 채널 추가",
            width=100,
            fg_color="#22c55e",
            hover_color="#16a34a",
            command=self._add_channel_dialog
        ).pack(side="left", padx=(0, 5))

        # 채널 관리 버튼
        ctk.CTkButton(
            right_frame,
            text="⚙️ 채널 관리",
            width=100,
            fg_color="#6366f1",
            hover_color="#4f46e5",
            command=self._manage_channels_dialog
        ).pack(side="left")

        # 채널 통계 라벨
        self.channel_stats_label = ctk.CTkLabel(
            header_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.channel_stats_label.pack(side="right", padx=(10, 0))
        self._update_channel_stats()

    def _get_current_channel_display(self) -> str:
        """현재 채널 표시 문자열"""
        if self.channel_id and self.channel_registry:
            channel = self.channel_registry.get_channel(self.channel_id)
            if channel:
                return f"{channel.display_name} ({channel.channel_id})"
        return f"기본 ({self.channel_type})"

    def _get_channel_list(self) -> list:
        """채널 목록 가져오기"""
        channels = [f"기본 ({self.channel_type})"]  # 레거시 모드

        if self.channel_registry:
            for ch in self.channel_registry.get_all_channels():
                channels.append(f"{ch.display_name} ({ch.channel_id})")

        return channels

    def _refresh_channel_list(self):
        """채널 목록 새로고침"""
        self.channel_dropdown.configure(values=self._get_channel_list())
        self._update_channel_stats()

    def _update_channel_stats(self):
        """채널 통계 업데이트"""
        if self.channel_registry:
            stats = self.channel_registry.get_stats()
            self.channel_stats_label.configure(
                text=f"총 {stats['total_channels']}/100개 채널"
            )

    def _on_channel_change(self, selection: str):
        """채널 변경 시 호출"""
        # 선택된 채널 파싱
        if selection.startswith("기본"):
            new_channel_id = None
        else:
            # "표시이름 (channel_id)" 형식에서 channel_id 추출
            try:
                new_channel_id = selection.split("(")[-1].rstrip(")")
            except Exception:
                new_channel_id = None

        # 채널 변경 확인
        if new_channel_id != self.channel_id:
            if messagebox.askyesno(
                "채널 변경",
                f"'{selection}' 채널로 변경하시겠습니까?\n\n"
                "현재 진행 중인 작업이 있다면 저장 후 변경해주세요."
            ):
                self._switch_channel(new_channel_id)
            else:
                # 원래 선택으로 복원
                self.channel_var.set(self._get_current_channel_display())

    def _switch_channel(self, new_channel_id: str):
        """채널 전환"""
        self.channel_id = new_channel_id

        # 모든 모듈 재초기화
        self._init_optimizer()

        # UI 새로고침
        self._load_data()

        # 제목 업데이트
        if new_channel_id:
            channel = self.channel_registry.get_channel(new_channel_id)
            if channel:
                self.title(f"🤖 유토피아 - {channel.display_name}")
        else:
            self.title("🤖 자동 최적화 시스템 (유토피아)")

        messagebox.showinfo("채널 변경", "채널이 변경되었습니다.")

    def _add_channel_dialog(self):
        """채널 추가 다이얼로그"""
        dialog = ChannelAddDialog(self, self.channel_registry)
        self.wait_window(dialog)

        if dialog.result:
            self._refresh_channel_list()
            messagebox.showinfo(
                "채널 추가",
                f"'{dialog.result.display_name}' 채널이 추가되었습니다.\n"
                f"채널 ID: {dialog.result.channel_id}"
            )

    def _manage_channels_dialog(self):
        """채널 관리 다이얼로그"""
        dialog = ChannelManageDialog(self, self.channel_registry)
        self.wait_window(dialog)
        self._refresh_channel_list()

    # =========================================================
    # 상태 탭
    # =========================================================

    def _build_status_tab(self):
        """상태 탭 구성 - v54.6 유토피아 통합 대시보드"""
        frame = ctk.CTkScrollableFrame(self.tab_status)
        frame.pack(fill="both", expand=True)

        # 헤더
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20))

        ctk.CTkLabel(
            header_frame,
            text="🌟 유토피아 시스템",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")

        # v54.6: 유토피아 엔진 토글 버튼
        self.utopia_engine_btn = ctk.CTkButton(
            header_frame,
            text="🚀 유토피아 시작",
            command=self._toggle_utopia_engine,
            width=150,
            fg_color="#9333ea",
            hover_color="#7c3aed"
        )
        self.utopia_engine_btn.pack(side="right", padx=(10, 0))

        # v54.7: 대시보드 버튼
        ctk.CTkButton(
            header_frame,
            text="📊 대시보드",
            command=self._open_dashboard,
            width=100,
            fg_color="#3b82f6",
            hover_color="#2563eb"
        ).pack(side="right", padx=(10, 0))

        # 새로고침 버튼
        ctk.CTkButton(
            header_frame,
            text="🔄 새로고침",
            command=self._load_data,
            width=100
        ).pack(side="right")

        # v54.6: 유토피아 모드 선택
        mode_frame = ctk.CTkFrame(frame)
        mode_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            mode_frame,
            text="⚙️ 운영 모드:",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=(15, 10), pady=12)

        self.utopia_mode_var = ctk.StringVar(value="semi_auto")
        modes = [("수동", "manual"), ("반자동", "semi_auto"), ("완전 자동", "full_auto")]
        for text, value in modes:
            ctk.CTkRadioButton(
                mode_frame,
                text=text,
                variable=self.utopia_mode_var,
                value=value,
                command=self._change_utopia_mode
            ).pack(side="left", padx=10, pady=12)

        # 유토피아 상태 레이블
        self.utopia_state_label = ctk.CTkLabel(
            mode_frame,
            text="대기 중",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="gray"
        )
        self.utopia_state_label.pack(side="right", padx=15, pady=12)

        # 상태 카드
        self.status_frame = ctk.CTkFrame(frame)
        self.status_frame.pack(fill="x", pady=(0, 20))

        # 유토피아 엔진 상태
        self.engine_card = ctk.CTkFrame(self.status_frame)
        self.engine_card.pack(side="left", padx=10, pady=15)

        ctk.CTkLabel(
            self.engine_card,
            text="🌟",
            font=ctk.CTkFont(size=32)
        ).pack(pady=(15, 5))

        ctk.CTkLabel(
            self.engine_card,
            text="엔진",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack()

        self.engine_status_label = ctk.CTkLabel(
            self.engine_card,
            text="중지됨",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.engine_status_label.pack(pady=(5, 15))

        # 스케줄러 상태
        self.scheduler_card = ctk.CTkFrame(self.status_frame)
        self.scheduler_card.pack(side="left", padx=10, pady=15)

        ctk.CTkLabel(
            self.scheduler_card,
            text="⏰",
            font=ctk.CTkFont(size=32)
        ).pack(pady=(15, 5))

        ctk.CTkLabel(
            self.scheduler_card,
            text="스케줄러",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack()

        self.scheduler_status_label = ctk.CTkLabel(
            self.scheduler_card,
            text="확인 중...",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.scheduler_status_label.pack(pady=(5, 5))

        self.scheduler_btn = ctk.CTkButton(
            self.scheduler_card,
            text="시작",
            command=self._toggle_scheduler,
            width=80
        )
        self.scheduler_btn.pack(pady=(5, 15))

        # 최근 액션 수
        self.actions_card = ctk.CTkFrame(self.status_frame)
        self.actions_card.pack(side="left", padx=10, pady=15)

        ctk.CTkLabel(
            self.actions_card,
            text="📈",
            font=ctk.CTkFont(size=32)
        ).pack(pady=(15, 5))

        ctk.CTkLabel(
            self.actions_card,
            text="총 액션",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack()

        self.actions_count_label = ctk.CTkLabel(
            self.actions_card,
            text="0",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.actions_count_label.pack(pady=(5, 15))

        # 학습 패턴 수
        self.patterns_card = ctk.CTkFrame(self.status_frame)
        self.patterns_card.pack(side="left", padx=10, pady=15)

        ctk.CTkLabel(
            self.patterns_card,
            text="🧠",
            font=ctk.CTkFont(size=32)
        ).pack(pady=(15, 5))

        ctk.CTkLabel(
            self.patterns_card,
            text="학습된 패턴",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack()

        self.patterns_count_label = ctk.CTkLabel(
            self.patterns_card,
            text="0",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.patterns_count_label.pack(pady=(5, 15))

        # 최근 액션 로그
        log_label = ctk.CTkLabel(
            frame,
            text="📝 최근 활동 로그",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        log_label.pack(anchor="w", pady=(10, 10))

        self.log_text = ctk.CTkTextbox(frame, height=200)
        self.log_text.pack(fill="x", pady=(0, 10))

    # =========================================================
    # 썸네일 관리 탭
    # =========================================================

    def _build_thumbnails_tab(self):
        """썸네일 관리 탭"""
        frame = ctk.CTkScrollableFrame(self.tab_thumbnails)
        frame.pack(fill="both", expand=True)

        # 헤더
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20))

        ctk.CTkLabel(
            header_frame,
            text="🖼️ 썸네일 교체 필요 영상",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            header_frame,
            text="🔍 검색",
            command=self._scan_thumbnails,
            width=100
        ).pack(side="right")

        # 설명
        ctk.CTkLabel(
            frame,
            text="CTR이 낮거나 초반 이탈이 많은 영상을 자동으로 감지합니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(anchor="w", pady=(0, 15))

        # 영상 목록 프레임
        self.thumbnails_list_frame = ctk.CTkFrame(frame)
        self.thumbnails_list_frame.pack(fill="both", expand=True)

        # 로딩 표시
        self.thumb_loading_label = ctk.CTkLabel(
            self.thumbnails_list_frame,
            text="🔍 검색 버튼을 눌러 분석을 시작하세요.",
            text_color="gray"
        )
        self.thumb_loading_label.pack(pady=50)

    def _scan_thumbnails(self):
        """썸네일 교체 필요 영상 스캔"""
        self.thumb_loading_label.configure(text="⏳ 영상 분석 중...", text_color="gray")

        def worker():
            try:
                from utils.youtube_analytics import YouTubeAnalytics
                analytics = YouTubeAnalytics(self.data_dir, self.channel_type)

                if not analytics.is_authenticated():
                    self.after(0, lambda: self.thumb_loading_label.configure(
                        text="❌ YouTube 인증이 필요합니다.",
                        text_color="red"
                    ))
                    return

                videos = analytics.get_videos_needing_thumbnail_change()
                self.after(0, lambda: self._show_thumbnail_results(videos))

            except Exception as e:
                self.after(0, lambda: self.thumb_loading_label.configure(
                    text=f"❌ 분석 실패: {str(e)}",
                    text_color="red"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _show_thumbnail_results(self, videos: list):
        """썸네일 분석 결과 표시"""
        # 기존 위젯 삭제
        for widget in self.thumbnails_list_frame.winfo_children():
            widget.destroy()

        if not videos:
            ctk.CTkLabel(
                self.thumbnails_list_frame,
                text="✅ 모든 영상이 양호합니다! 교체가 필요한 영상이 없습니다.",
                font=ctk.CTkFont(size=14),
                text_color="#22c55e"
            ).pack(pady=50)
            return

        # 헤더
        header = ctk.CTkFrame(self.thumbnails_list_frame, fg_color="gray25")
        header.pack(fill="x", pady=(0, 5))

        headers = [("제목", 200), ("업로드", 80), ("조회수", 70), ("시청률", 60), ("문제점", 200), ("액션", 80)]
        for text, width in headers:
            ctk.CTkLabel(header, text=text, font=ctk.CTkFont(size=11, weight="bold"), width=width).pack(side="left", padx=3, pady=8)

        # 영상 목록
        for video in videos:
            row = ctk.CTkFrame(self.thumbnails_list_frame)
            row.pack(fill="x", pady=2)

            # 제목
            title = video.get('title', '')[:25]
            if len(video.get('title', '')) > 25:
                title += "..."
            ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=11), width=200, anchor="w").pack(side="left", padx=3)

            # 업로드 시간
            age = video.get('age_hours', 0)
            if age < 24:
                age_text = f"{int(age)}시간"
            else:
                age_text = f"{int(age/24)}일"
            ctk.CTkLabel(row, text=age_text, font=ctk.CTkFont(size=11), width=80).pack(side="left", padx=3)

            # 조회수
            views = video.get('views', 0)
            ctk.CTkLabel(row, text=f"{views:,}", font=ctk.CTkFont(size=11), width=70).pack(side="left", padx=3)

            # 시청률
            retention = video.get('avg_view_percentage', 0)
            retention_color = "#ef4444" if retention < 30 else "#eab308"
            ctk.CTkLabel(row, text=f"{retention:.1f}%", font=ctk.CTkFont(size=11), width=60, text_color=retention_color).pack(side="left", padx=3)

            # 문제점
            reason = video.get('reason', '')[:40]
            ctk.CTkLabel(row, text=reason, font=ctk.CTkFont(size=10), width=200, anchor="w", text_color="gray").pack(side="left", padx=3)

            # 교체 버튼
            video_id = video['video_id']
            ctk.CTkButton(
                row,
                text="교체",
                width=60,
                height=25,
                fg_color="#ef4444",
                hover_color="#dc2626",
                command=lambda vid=video_id, t=video.get('title', ''): self._change_thumbnail(vid, t)
            ).pack(side="left", padx=3)

    def _change_thumbnail(self, video_id: str, title: str):
        """썸네일 교체 실행"""
        if not messagebox.askyesno("확인", f"'{title}' 영상의 썸네일을 교체하시겠습니까?"):
            return

        def worker():
            try:
                if self.optimizer:
                    result = self.optimizer._execute_thumbnail_change(video_id, title, "수동 교체")

                    if result.get('success'):
                        self.after(0, lambda: messagebox.showinfo("완료", "썸네일이 교체되었습니다!"))
                        self.after(0, self._scan_thumbnails)  # 목록 새로고침
                    else:
                        self.after(0, lambda: messagebox.showerror("실패", result.get('error', '알 수 없는 오류')))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("오류", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # 패턴 학습 탭
    # =========================================================

    def _build_patterns_tab(self):
        """패턴 학습 탭"""
        frame = ctk.CTkScrollableFrame(self.tab_patterns)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="🧠 학습된 패턴",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=(10, 5))

        ctk.CTkLabel(
            frame,
            text="채널 성과 데이터를 분석하여 학습된 패턴입니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(anchor="w", pady=(0, 20))

        # 고성과 키워드
        top_frame = ctk.CTkFrame(frame)
        top_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            top_frame,
            text="🏆 고성과 키워드 (제목에 포함하면 좋음)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.top_keywords_label = ctk.CTkLabel(
            top_frame,
            text="데이터 부족",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            wraplength=700
        )
        self.top_keywords_label.pack(anchor="w", padx=15, pady=(0, 15))

        # 저성과 키워드
        low_frame = ctk.CTkFrame(frame)
        low_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            low_frame,
            text="⚠️ 저성과 키워드 (피해야 할 키워드)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.low_keywords_label = ctk.CTkLabel(
            low_frame,
            text="데이터 부족",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            wraplength=700
        )
        self.low_keywords_label.pack(anchor="w", padx=15, pady=(0, 15))

        # 개선 제안
        suggestions_frame = ctk.CTkFrame(frame)
        suggestions_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            suggestions_frame,
            text="💡 개선 제안",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.suggestions_list_frame = ctk.CTkFrame(suggestions_frame, fg_color="transparent")
        self.suggestions_list_frame.pack(fill="x", padx=15, pady=(0, 15))

        # 패턴 업데이트 버튼
        ctk.CTkButton(
            frame,
            text="🔄 패턴 재학습",
            command=self._update_patterns,
            width=150
        ).pack(pady=20)

    def _update_patterns(self):
        """패턴 업데이트"""
        if not self.optimizer:
            return

        def worker():
            try:
                from utils.youtube_analytics import YouTubeAnalytics
                analytics = YouTubeAnalytics(self.data_dir, self.channel_type)
                self.optimizer._update_patterns(analytics)
                self.after(0, self._load_patterns_data)
                self.after(0, lambda: messagebox.showinfo("완료", "패턴이 업데이트되었습니다!"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("오류", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _load_patterns_data(self):
        """패턴 데이터 로드"""
        if not self.optimizer:
            return

        patterns = self.optimizer.patterns

        # 고성과 키워드
        top_keywords = patterns.get('top_performing_keywords', [])
        if top_keywords:
            self.top_keywords_label.configure(
                text=", ".join(top_keywords[:15]),
                text_color="#22c55e"
            )

        # 저성과 키워드
        low_keywords = patterns.get('low_performing_keywords', [])
        if low_keywords:
            self.low_keywords_label.configure(
                text=", ".join(low_keywords[:15]),
                text_color="#ef4444"
            )

        # 개선 제안
        for widget in self.suggestions_list_frame.winfo_children():
            widget.destroy()

        suggestions = self.optimizer.get_improvement_suggestions()

        if not suggestions:
            ctk.CTkLabel(
                self.suggestions_list_frame,
                text="충분한 데이터가 쌓이면 개선 제안이 표시됩니다.",
                text_color="gray"
            ).pack(anchor="w")
        else:
            for suggestion in suggestions:
                priority = suggestion.get('priority', 'low')
                priority_color = "#ef4444" if priority == "high" else "#eab308" if priority == "medium" else "gray"

                row = ctk.CTkFrame(self.suggestions_list_frame, fg_color="transparent")
                row.pack(fill="x", pady=3)

                ctk.CTkLabel(
                    row,
                    text=f"• {suggestion.get('title', '')}",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=priority_color
                ).pack(anchor="w")

                ctk.CTkLabel(
                    row,
                    text=f"  {suggestion.get('description', '')}",
                    font=ctk.CTkFont(size=11),
                    text_color="gray"
                ).pack(anchor="w")

    # =========================================================
    # 개인화 탭 (v54.3)
    # =========================================================

    def _build_personalization_tab(self):
        """개인화 탭 구성 - v54.3"""
        frame = ctk.CTkScrollableFrame(self.tab_personalization)
        frame.pack(fill="both", expand=True)

        # 헤더
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20))

        ctk.CTkLabel(
            header_frame,
            text="🎯 개인화된 프롬프트 최적화",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # 분석 버튼
        ctk.CTkButton(
            header_frame,
            text="🔄 채널 분석",
            command=self._run_personalization_analysis,
            width=120,
            fg_color="#9333ea",
            hover_color="#7c3aed"
        ).pack(side="right")

        # 설명
        ctk.CTkLabel(
            frame,
            text="채널의 성과 데이터를 분석하여 최적의 프롬프트를 자동으로 추천합니다.\n"
                 "제목, 썸네일, 스크립트, 업로드 시간 등을 개인화된 패턴으로 최적화합니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left"
        ).pack(anchor="w", pady=(0, 20))

        # 학습 상태 카드
        status_card = ctk.CTkFrame(frame)
        status_card.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            status_card,
            text="📊 학습 상태",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.personalization_status_label = ctk.CTkLabel(
            status_card,
            text="분석되지 않음",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.personalization_status_label.pack(anchor="w", padx=15, pady=(0, 15))

        # 제목 최적화 테스트
        title_frame = ctk.CTkFrame(frame)
        title_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            title_frame,
            text="📝 제목 최적화 테스트",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        input_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        input_frame.pack(fill="x", padx=15, pady=(0, 10))

        self.test_title_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="제목을 입력하세요...",
            width=400
        )
        self.test_title_entry.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            input_frame,
            text="분석",
            command=self._analyze_title,
            width=80
        ).pack(side="left")

        # 제목 분석 결과
        self.title_result_frame = ctk.CTkFrame(title_frame, fg_color="gray20")
        self.title_result_frame.pack(fill="x", padx=15, pady=(0, 15))

        self.title_score_label = ctk.CTkLabel(
            self.title_result_frame,
            text="예상 점수: -",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.title_score_label.pack(anchor="w", padx=10, pady=(10, 5))

        self.title_suggestions_label = ctk.CTkLabel(
            self.title_result_frame,
            text="제목을 입력하고 분석 버튼을 누르세요.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=600,
            justify="left"
        )
        self.title_suggestions_label.pack(anchor="w", padx=10, pady=(0, 10))

        # 추천 요약
        summary_frame = ctk.CTkFrame(frame)
        summary_frame.pack(fill="x", pady=(0, 15))

        summary_header = ctk.CTkFrame(summary_frame, fg_color="transparent")
        summary_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            summary_header,
            text="💡 최적화 추천 요약",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            summary_header,
            text="📋 복사",
            command=self._copy_recommendations,
            width=70,
            height=25,
            fg_color="gray40"
        ).pack(side="right")

        self.recommendations_text = ctk.CTkTextbox(summary_frame, height=200)
        self.recommendations_text.pack(fill="x", padx=15, pady=(0, 15))

        # 업로드 시간 추천
        upload_frame = ctk.CTkFrame(frame)
        upload_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            upload_frame,
            text="⏰ 최적 업로드 시간",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.upload_time_label = ctk.CTkLabel(
            upload_frame,
            text="분석 필요",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.upload_time_label.pack(anchor="w", padx=15, pady=(0, 15))

    def _run_personalization_analysis(self):
        """개인화 분석 실행"""
        if not self.prompt_optimizer:
            messagebox.showerror("오류", "PromptOptimizer가 초기화되지 않았습니다.")
            return

        self.personalization_status_label.configure(
            text="⏳ 채널 분석 중... (YouTube API에서 데이터를 가져오는 중)",
            text_color="#eab308"
        )

        def worker():
            try:
                result = self.prompt_optimizer.collect_and_analyze()

                if result.get("success"):
                    # 성공
                    self.after(0, lambda: self._load_personalization_data())
                    self.after(0, lambda: messagebox.showinfo(
                        "분석 완료",
                        f"✅ 채널 분석 완료!\n\n"
                        f"• 분석된 영상: {result.get('videos_analyzed', 0)}개\n"
                        f"• 발견된 패턴: {sum(result.get('patterns_found', {}).values())}개\n\n"
                        f"이제 제목 최적화 테스트와 추천 요약을 확인할 수 있습니다."
                    ))
                else:
                    # 실패
                    errors = result.get("errors", ["알 수 없는 오류"])
                    self.after(0, lambda: self.personalization_status_label.configure(
                        text=f"❌ 분석 실패: {errors[0]}",
                        text_color="#ef4444"
                    ))
                    self.after(0, lambda: messagebox.showerror("분석 실패", "\n".join(errors)))

            except Exception as e:
                self.after(0, lambda: self.personalization_status_label.configure(
                    text=f"❌ 오류: {str(e)}",
                    text_color="#ef4444"
                ))
                self.after(0, lambda: messagebox.showerror("오류", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _load_personalization_data(self):
        """개인화 데이터 로드"""
        if not self.prompt_optimizer:
            return

        # 학습 상태
        status = self.prompt_optimizer.get_learning_status()

        # v54.3.1: 채널 정보 표시
        channel_info = ""
        if status.get("is_personalized") and status.get("channel_name"):
            channel_info = f"📺 {status.get('channel_name')} | "
        elif status.get("channel_id"):
            channel_info = f"📺 {status.get('channel_id')[:8]}... | "

        if status.get("has_enough_data"):
            self.personalization_status_label.configure(
                text=f"✅ {channel_info}학습 완료 | 분석된 영상: {status.get('total_videos_analyzed', 0)}개 | "
                     f"마지막 업데이트: {status.get('last_updated', '없음')[:10] if status.get('last_updated') else '없음'}",
                text_color="#22c55e"
            )
        else:
            personalized_note = " (개인화됨)" if status.get("is_personalized") else " (공용 패턴)"
            self.personalization_status_label.configure(
                text=f"⚠️ {channel_info}데이터 부족: {status.get('total_videos_analyzed', 0)}/10개 영상 필요{personalized_note}",
                text_color="#eab308"
            )

        # 추천 요약
        summary = self.prompt_optimizer.get_recommendations_summary()
        self.recommendations_text.configure(state="normal")
        self.recommendations_text.delete("1.0", "end")
        self.recommendations_text.insert("1.0", summary)
        self.recommendations_text.configure(state="disabled")

        # 업로드 시간
        upload_rec = self.prompt_optimizer.get_optimal_upload_time()
        day_names = ["월", "화", "수", "목", "금", "토", "일"]

        if upload_rec.get("confidence", 0) > 0.5:
            self.upload_time_label.configure(
                text=f"📅 {day_names[upload_rec.get('recommended_day', 5)]}요일 "
                     f"🕐 {upload_rec.get('recommended_hour', 18)}시 "
                     f"(신뢰도: {upload_rec.get('confidence', 0)*100:.0f}%)\n"
                     f"💬 {upload_rec.get('reason', '')}",
                text_color="#22c55e"
            )
        else:
            self.upload_time_label.configure(
                text=f"기본 추천: {day_names[upload_rec.get('recommended_day', 5)]}요일 "
                     f"{upload_rec.get('recommended_hour', 18)}시 (데이터 부족으로 신뢰도 낮음)",
                text_color="gray"
            )

    def _analyze_title(self):
        """제목 분석"""
        if not self.prompt_optimizer:
            messagebox.showwarning("경고", "먼저 '채널 분석'을 실행해주세요.")
            return

        title = self.test_title_entry.get().strip()
        if not title:
            messagebox.showwarning("경고", "제목을 입력해주세요.")
            return

        result = self.prompt_optimizer.optimize_title(title)

        # 점수 표시
        score = result.get("score", 50)
        if score >= 70:
            color = "#22c55e"
            emoji = "🏆"
        elif score >= 50:
            color = "#eab308"
            emoji = "📊"
        else:
            color = "#ef4444"
            emoji = "⚠️"

        self.title_score_label.configure(
            text=f"{emoji} 예상 성과 점수: {score:.0f}/100",
            text_color=color
        )

        # 제안 표시
        suggestions = result.get("suggestions", [])
        keywords_added = result.get("keywords_added", [])
        keywords_avoided = result.get("keywords_avoided", [])

        suggestion_text = ""
        if keywords_added:
            suggestion_text += f"✅ 고성과 키워드 포함: {', '.join(keywords_added)}\n"
        if keywords_avoided:
            suggestion_text += f"⚠️ 저성과 키워드 발견: {', '.join(keywords_avoided)}\n"
        if suggestions:
            suggestion_text += "💡 제안:\n" + "\n".join(f"  • {s}" for s in suggestions)

        if not suggestion_text:
            suggestion_text = "분석 가능한 패턴이 부족합니다. 더 많은 채널 데이터가 필요합니다."

        self.title_suggestions_label.configure(
            text=suggestion_text,
            text_color="white"
        )

    def _copy_recommendations(self):
        """추천 요약 복사"""
        text = self.recommendations_text.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("복사 완료", "추천 요약이 클립보드에 복사되었습니다.")

    # =========================================================
    # 업로드 탭 (v54.4)
    # =========================================================

    def _build_upload_tab(self):
        """업로드 스케줄러 탭 구성 - v54.4"""
        frame = ctk.CTkScrollableFrame(self.tab_upload)
        frame.pack(fill="both", expand=True)

        # 헤더
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20))

        ctk.CTkLabel(
            header_frame,
            text="📤 업로드 스케줄러",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # 새로고침 버튼
        ctk.CTkButton(
            header_frame,
            text="🔄 새로고침",
            command=self._refresh_upload_queue,
            width=100
        ).pack(side="right", padx=(10, 0))

        # 스케줄러 토글 버튼
        self.upload_scheduler_btn = ctk.CTkButton(
            header_frame,
            text="▶️ 스케줄러 시작",
            command=self._toggle_upload_scheduler,
            width=130,
            fg_color="#22c55e",
            hover_color="#16a34a"
        )
        self.upload_scheduler_btn.pack(side="right")

        # 설명
        ctk.CTkLabel(
            frame,
            text="제작 완료된 영상을 대기열에 추가하고, 최적의 시간에 자동으로 YouTube에 업로드합니다.\n"
                 "개인화된 패턴을 학습하여 가장 효과적인 업로드 시간을 자동으로 예약합니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left"
        ).pack(anchor="w", pady=(0, 20))

        # 상태 카드들
        status_row = ctk.CTkFrame(frame, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 20))

        # 스케줄러 상태
        scheduler_card = ctk.CTkFrame(status_row)
        scheduler_card.pack(side="left", padx=(0, 10), pady=5)

        ctk.CTkLabel(scheduler_card, text="⏰", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(scheduler_card, text="스케줄러", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.upload_scheduler_status = ctk.CTkLabel(
            scheduler_card, text="중지됨", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.upload_scheduler_status.pack(pady=(5, 15))

        # 대기 중
        pending_card = ctk.CTkFrame(status_row)
        pending_card.pack(side="left", padx=10, pady=5)

        ctk.CTkLabel(pending_card, text="📋", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(pending_card, text="대기 중", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.upload_pending_count = ctk.CTkLabel(
            pending_card, text="0", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.upload_pending_count.pack(pady=(5, 15))

        # 다음 예약
        next_card = ctk.CTkFrame(status_row)
        next_card.pack(side="left", padx=10, pady=5)

        ctk.CTkLabel(next_card, text="📅", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(next_card, text="다음 예약", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.upload_next_scheduled = ctk.CTkLabel(
            next_card, text="없음", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.upload_next_scheduled.pack(pady=(5, 15))

        # 오늘 업로드
        today_card = ctk.CTkFrame(status_row)
        today_card.pack(side="left", padx=10, pady=5)

        ctk.CTkLabel(today_card, text="📊", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(today_card, text="오늘 업로드", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.upload_today_count = ctk.CTkLabel(
            today_card, text="0/5", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.upload_today_count.pack(pady=(5, 15))

        # 대기열 목록
        queue_label = ctk.CTkLabel(
            frame,
            text="📋 업로드 대기열",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        queue_label.pack(anchor="w", pady=(10, 10))

        # 대기열 프레임
        self.upload_queue_frame = ctk.CTkFrame(frame)
        self.upload_queue_frame.pack(fill="both", expand=True, pady=(0, 15))

        # 빈 상태 표시
        self.upload_queue_empty_label = ctk.CTkLabel(
            self.upload_queue_frame,
            text="대기열이 비어있습니다.\n영상 제작 후 '업로드 예약' 버튼으로 추가하세요.",
            text_color="gray",
            font=ctk.CTkFont(size=13)
        )
        self.upload_queue_empty_label.pack(pady=50)

        # 업로드 설정 섹션
        settings_frame = ctk.CTkFrame(frame)
        settings_frame.pack(fill="x", pady=(10, 10))

        ctk.CTkLabel(
            settings_frame,
            text="⚙️ 업로드 설정",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 설정 그리드
        settings_grid = ctk.CTkFrame(settings_frame, fg_color="transparent")
        settings_grid.pack(fill="x", padx=15, pady=(0, 15))

        # 일일 업로드 제한
        row1 = ctk.CTkFrame(settings_grid, fg_color="transparent")
        row1.pack(fill="x", pady=3)
        ctk.CTkLabel(row1, text="일일 업로드 제한:", width=150, anchor="w").pack(side="left")
        self.upload_daily_limit_entry = ctk.CTkEntry(row1, width=60)
        self.upload_daily_limit_entry.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(row1, text="개", text_color="gray").pack(side="left")

        # 업로드 간격
        row2 = ctk.CTkFrame(settings_grid, fg_color="transparent")
        row2.pack(fill="x", pady=3)
        ctk.CTkLabel(row2, text="업로드 간 최소 간격:", width=150, anchor="w").pack(side="left")
        self.upload_gap_entry = ctk.CTkEntry(row2, width=60)
        self.upload_gap_entry.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(row2, text="시간", text_color="gray").pack(side="left")

        # 선호 업로드 시간
        row3 = ctk.CTkFrame(settings_grid, fg_color="transparent")
        row3.pack(fill="x", pady=3)
        ctk.CTkLabel(row3, text="선호 업로드 시간:", width=150, anchor="w").pack(side="left")
        self.upload_preferred_hours_entry = ctk.CTkEntry(row3, width=120, placeholder_text="예: 18,19,20")
        self.upload_preferred_hours_entry.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(row3, text="시 (쉼표 구분)", text_color="gray").pack(side="left")

        # 저장 버튼
        ctk.CTkButton(
            settings_frame,
            text="💾 설정 저장",
            command=self._save_upload_settings,
            width=120,
            fg_color="#3b82f6",
            hover_color="#2563eb"
        ).pack(pady=(0, 15))

    def _refresh_upload_queue(self):
        """업로드 대기열 새로고침"""
        if not self.upload_scheduler:
            return

        status = self.upload_scheduler.get_status()
        queue = self.upload_scheduler.get_queue()

        # 상태 업데이트
        if status.get("scheduler_running"):
            self.upload_scheduler_status.configure(text="실행 중", text_color="#22c55e")
            self.upload_scheduler_btn.configure(
                text="⏹️ 스케줄러 중지",
                fg_color="#ef4444",
                hover_color="#dc2626"
            )
        else:
            self.upload_scheduler_status.configure(text="중지됨", text_color="gray")
            self.upload_scheduler_btn.configure(
                text="▶️ 스케줄러 시작",
                fg_color="#22c55e",
                hover_color="#16a34a"
            )

        # 카운트 업데이트
        pending = status.get("pending", 0) + status.get("scheduled", 0)
        self.upload_pending_count.configure(text=str(pending))
        self.upload_next_scheduled.configure(text=status.get("next_scheduled_display", "없음"))
        self.upload_today_count.configure(
            text=f"{status.get('today_uploaded', 0)}/{status.get('daily_limit', 5)}"
        )

        # 대기열 목록 업데이트
        for widget in self.upload_queue_frame.winfo_children():
            widget.destroy()

        # 활성 항목만 필터링 (완료/취소 제외)
        active_items = [
            item for item in queue
            if item.get("status") in ["pending", "scheduled", "uploading"]
        ]

        if not active_items:
            self.upload_queue_empty_label = ctk.CTkLabel(
                self.upload_queue_frame,
                text="대기열이 비어있습니다.\n영상 제작 후 '업로드 예약' 버튼으로 추가하세요.",
                text_color="gray",
                font=ctk.CTkFont(size=13)
            )
            self.upload_queue_empty_label.pack(pady=50)
            return

        # 헤더
        header = ctk.CTkFrame(self.upload_queue_frame, fg_color="gray25")
        header.pack(fill="x", pady=(0, 5))

        headers = [("제목", 200), ("상태", 80), ("예약 시간", 100), ("액션", 120)]
        for text, width in headers:
            ctk.CTkLabel(
                header, text=text,
                font=ctk.CTkFont(size=11, weight="bold"),
                width=width
            ).pack(side="left", padx=3, pady=8)

        # 항목들
        for item in active_items:
            row = ctk.CTkFrame(self.upload_queue_frame)
            row.pack(fill="x", pady=2)

            # 제목
            title = item.get("title", "")[:25]
            if len(item.get("title", "")) > 25:
                title += "..."
            ctk.CTkLabel(
                row, text=title,
                font=ctk.CTkFont(size=11),
                width=200, anchor="w"
            ).pack(side="left", padx=3)

            # 상태
            status_text = item.get("status", "unknown")
            status_colors = {
                "pending": ("대기", "gray"),
                "scheduled": ("예약됨", "#3b82f6"),
                "uploading": ("업로드 중", "#eab308"),
            }
            text, color = status_colors.get(status_text, ("알 수 없음", "gray"))
            ctk.CTkLabel(
                row, text=text,
                font=ctk.CTkFont(size=11),
                width=80, text_color=color
            ).pack(side="left", padx=3)

            # 예약 시간
            scheduled_time = item.get("scheduled_time", "")
            if scheduled_time:
                try:
                    dt = datetime.fromisoformat(scheduled_time)
                    time_text = dt.strftime("%m/%d %H:%M")
                except Exception:
                    time_text = "-"
            else:
                time_text = "즉시"
            ctk.CTkLabel(
                row, text=time_text,
                font=ctk.CTkFont(size=11),
                width=100
            ).pack(side="left", padx=3)

            # 액션 버튼들
            action_frame = ctk.CTkFrame(row, fg_color="transparent")
            action_frame.pack(side="left", padx=3)

            item_id = item["id"]

            # 즉시 업로드 버튼
            if item.get("status") != "uploading":
                ctk.CTkButton(
                    action_frame,
                    text="⬆️",
                    width=30, height=25,
                    fg_color="#22c55e",
                    hover_color="#16a34a",
                    command=lambda iid=item_id: self._upload_now(iid)
                ).pack(side="left", padx=2)

            # 취소 버튼
            if item.get("status") != "uploading":
                ctk.CTkButton(
                    action_frame,
                    text="❌",
                    width=30, height=25,
                    fg_color="#ef4444",
                    hover_color="#dc2626",
                    command=lambda iid=item_id: self._cancel_upload(iid)
                ).pack(side="left", padx=2)

        # 설정 값 로드
        self._load_upload_settings()

    def _toggle_upload_scheduler(self):
        """업로드 스케줄러 토글"""
        if not self.upload_scheduler:
            messagebox.showerror("오류", "UploadScheduler가 초기화되지 않았습니다.")
            return

        if self.upload_scheduler.is_scheduler_running():
            self.upload_scheduler.stop_scheduler()
            messagebox.showinfo("스케줄러", "업로드 스케줄러가 중지되었습니다.")
        else:
            self.upload_scheduler.start_scheduler()
            messagebox.showinfo(
                "스케줄러",
                "업로드 스케줄러가 시작되었습니다!\n"
                f"매 {self.upload_scheduler.config.get('check_interval_minutes', 5)}분마다 예약을 확인합니다."
            )

        self._refresh_upload_queue()

    def _upload_now(self, item_id: str):
        """즉시 업로드"""
        if not self.upload_scheduler:
            return

        if not messagebox.askyesno("확인", "이 영상을 지금 바로 업로드하시겠습니까?"):
            return

        def worker():
            try:
                result = self.upload_scheduler.upload_now(item_id)
                if result:
                    self.after(0, lambda: messagebox.showinfo("완료", "업로드가 완료되었습니다!"))
                else:
                    self.after(0, lambda: messagebox.showerror("실패", "업로드에 실패했습니다."))
                self.after(0, self._refresh_upload_queue)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("오류", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_upload(self, item_id: str):
        """업로드 취소"""
        if not self.upload_scheduler:
            return

        if not messagebox.askyesno("확인", "이 업로드 예약을 취소하시겠습니까?"):
            return

        if self.upload_scheduler.remove_from_queue(item_id):
            messagebox.showinfo("완료", "업로드가 취소되었습니다.")
        else:
            messagebox.showerror("실패", "취소할 항목을 찾을 수 없습니다.")

        self._refresh_upload_queue()

    def _load_upload_settings(self):
        """업로드 설정 로드"""
        if not self.upload_scheduler:
            return

        config = self.upload_scheduler.get_config()

        # 일일 제한
        self.upload_daily_limit_entry.delete(0, "end")
        self.upload_daily_limit_entry.insert(0, str(config.get("daily_upload_limit", 5)))

        # 간격
        self.upload_gap_entry.delete(0, "end")
        self.upload_gap_entry.insert(0, str(config.get("min_gap_hours", 4)))

        # 선호 시간
        preferred_hours = config.get("preferred_hours", [18, 19, 20])
        self.upload_preferred_hours_entry.delete(0, "end")
        self.upload_preferred_hours_entry.insert(0, ",".join(map(str, preferred_hours)))

    def _save_upload_settings(self):
        """업로드 설정 저장"""
        if not self.upload_scheduler:
            return

        try:
            # 일일 제한
            daily_limit = int(self.upload_daily_limit_entry.get())
            if daily_limit < 1 or daily_limit > 50:
                raise ValueError("일일 제한은 1-50 사이여야 합니다.")

            # 간격
            gap_hours = int(self.upload_gap_entry.get())
            if gap_hours < 0 or gap_hours > 24:
                raise ValueError("간격은 0-24 사이여야 합니다.")

            # 선호 시간
            hours_str = self.upload_preferred_hours_entry.get()
            preferred_hours = [int(h.strip()) for h in hours_str.split(",") if h.strip()]
            for h in preferred_hours:
                if h < 0 or h > 23:
                    raise ValueError("시간은 0-23 사이여야 합니다.")

            # 설정 업데이트
            new_config = {
                "daily_upload_limit": daily_limit,
                "min_gap_hours": gap_hours,
                "preferred_hours": preferred_hours,
            }

            self.upload_scheduler.update_config(new_config)
            messagebox.showinfo("저장 완료", "업로드 설정이 저장되었습니다.")

        except ValueError as e:
            messagebox.showerror("입력 오류", str(e))
        except Exception as e:
            messagebox.showerror("오류", str(e))

    # =========================================================
    # 피드백 탭 (v54.5)
    # =========================================================

    def _build_feedback_tab(self):
        """피드백 루프 탭 구성 - v54.5"""
        frame = ctk.CTkScrollableFrame(self.tab_feedback)
        frame.pack(fill="both", expand=True)

        # 헤더
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20))

        ctk.CTkLabel(
            header_frame,
            text="🔄 피드백 루프 시스템",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # 새로고침 버튼
        ctk.CTkButton(
            header_frame,
            text="🔄 새로고침",
            command=self._refresh_feedback_data,
            width=100
        ).pack(side="right", padx=(10, 0))

        # 스케줄러 토글 버튼
        self.feedback_scheduler_btn = ctk.CTkButton(
            header_frame,
            text="▶️ 추적 시작",
            command=self._toggle_feedback_scheduler,
            width=120,
            fg_color="#8b5cf6",
            hover_color="#7c3aed"
        )
        self.feedback_scheduler_btn.pack(side="right")

        # 설명
        ctk.CTkLabel(
            frame,
            text="업로드된 영상의 성과를 자동으로 추적하고 학습합니다.\n"
                 "24시간, 48시간, 7일 단위로 CTR, 시청률 등을 분석하여 패턴을 학습합니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left"
        ).pack(anchor="w", pady=(0, 20))

        # 상태 카드들
        status_row = ctk.CTkFrame(frame, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 20))

        # 스케줄러 상태
        scheduler_card = ctk.CTkFrame(status_row)
        scheduler_card.pack(side="left", padx=(0, 10), pady=5)

        ctk.CTkLabel(scheduler_card, text="🔄", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(scheduler_card, text="추적 상태", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.feedback_scheduler_status = ctk.CTkLabel(
            scheduler_card, text="중지됨", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.feedback_scheduler_status.pack(pady=(5, 15))

        # 추적 중인 영상
        tracking_card = ctk.CTkFrame(status_row)
        tracking_card.pack(side="left", padx=10, pady=5)

        ctk.CTkLabel(tracking_card, text="📹", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(tracking_card, text="추적 중", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.feedback_tracking_count = ctk.CTkLabel(
            tracking_card, text="0", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.feedback_tracking_count.pack(pady=(5, 15))

        # 분석 완료
        analyzed_card = ctk.CTkFrame(status_row)
        analyzed_card.pack(side="left", padx=10, pady=5)

        ctk.CTkLabel(analyzed_card, text="📊", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(analyzed_card, text="분석 완료", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.feedback_analyzed_count = ctk.CTkLabel(
            analyzed_card, text="0", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.feedback_analyzed_count.pack(pady=(5, 15))

        # 학습된 패턴
        patterns_card = ctk.CTkFrame(status_row)
        patterns_card.pack(side="left", padx=10, pady=5)

        ctk.CTkLabel(patterns_card, text="🧠", font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(patterns_card, text="학습 패턴", font=ctk.CTkFont(size=11), text_color="gray").pack()
        self.feedback_patterns_count = ctk.CTkLabel(
            patterns_card, text="0", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.feedback_patterns_count.pack(pady=(5, 15))

        # 추적 중인 영상 목록
        videos_label = ctk.CTkLabel(
            frame,
            text="📹 추적 중인 영상",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        videos_label.pack(anchor="w", pady=(10, 10))

        self.feedback_videos_frame = ctk.CTkFrame(frame)
        self.feedback_videos_frame.pack(fill="both", expand=True, pady=(0, 15))

        # 빈 상태
        self.feedback_empty_label = ctk.CTkLabel(
            self.feedback_videos_frame,
            text="추적 중인 영상이 없습니다.\n영상 업로드 후 자동으로 추적이 시작됩니다.",
            text_color="gray",
            font=ctk.CTkFont(size=13)
        )
        self.feedback_empty_label.pack(pady=50)

        # 리포트 섹션
        report_frame = ctk.CTkFrame(frame)
        report_frame.pack(fill="x", pady=(10, 10))

        report_header = ctk.CTkFrame(report_frame, fg_color="transparent")
        report_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            report_header,
            text="📈 성과 리포트",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            report_header,
            text="📋 복사",
            command=self._copy_feedback_report,
            width=70,
            height=25,
            fg_color="gray40"
        ).pack(side="right")

        self.feedback_report_text = ctk.CTkTextbox(report_frame, height=200)
        self.feedback_report_text.pack(fill="x", padx=15, pady=(0, 15))

        # 학습 인사이트
        insights_frame = ctk.CTkFrame(frame)
        insights_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            insights_frame,
            text="💡 학습된 인사이트",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.feedback_insights_label = ctk.CTkLabel(
            insights_frame,
            text="아직 충분한 데이터가 쌓이지 않았습니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            wraplength=700
        )
        self.feedback_insights_label.pack(anchor="w", padx=15, pady=(0, 15))

    def _refresh_feedback_data(self):
        """피드백 데이터 새로고침"""
        if not self.feedback_loop:
            return

        status = self.feedback_loop.get_status()

        # 상태 카드 업데이트
        if status.get("scheduler_running"):
            self.feedback_scheduler_status.configure(text="실행 중", text_color="#22c55e")
            self.feedback_scheduler_btn.configure(
                text="⏹️ 추적 중지",
                fg_color="#ef4444",
                hover_color="#dc2626"
            )
        else:
            self.feedback_scheduler_status.configure(text="중지됨", text_color="gray")
            self.feedback_scheduler_btn.configure(
                text="▶️ 추적 시작",
                fg_color="#8b5cf6",
                hover_color="#7c3aed"
            )

        self.feedback_tracking_count.configure(text=str(status.get("active_tracking", 0)))
        self.feedback_analyzed_count.configure(text=str(status.get("total_analyzed", 0)))

        total_patterns = status.get("successful_patterns_count", 0) + status.get("failed_patterns_count", 0)
        self.feedback_patterns_count.configure(text=str(total_patterns))

        # 추적 중인 영상 목록
        videos = self.feedback_loop.get_tracked_videos(active_only=True)

        for widget in self.feedback_videos_frame.winfo_children():
            widget.destroy()

        if not videos:
            self.feedback_empty_label = ctk.CTkLabel(
                self.feedback_videos_frame,
                text="추적 중인 영상이 없습니다.\n영상 업로드 후 자동으로 추적이 시작됩니다.",
                text_color="gray",
                font=ctk.CTkFont(size=13)
            )
            self.feedback_empty_label.pack(pady=50)
        else:
            # 헤더
            header = ctk.CTkFrame(self.feedback_videos_frame, fg_color="gray25")
            header.pack(fill="x", pady=(0, 5))

            headers = [("제목", 180), ("업로드", 80), ("등급", 70), ("CTR", 60), ("상태", 100)]
            for text, width in headers:
                ctk.CTkLabel(
                    header, text=text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    width=width
                ).pack(side="left", padx=3, pady=8)

            # 영상 목록 (최대 10개)
            for video in videos[:10]:
                row = ctk.CTkFrame(self.feedback_videos_frame)
                row.pack(fill="x", pady=2)

                # 제목
                title = video.get("title", "")[:22]
                if len(video.get("title", "")) > 22:
                    title += "..."
                ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=11), width=180, anchor="w").pack(side="left", padx=3)

                # 업로드 시간
                try:
                    upload_time = datetime.fromisoformat(video["upload_time"])
                    hours_ago = (datetime.now() - upload_time).total_seconds() / 3600
                    if hours_ago < 24:
                        time_text = f"{int(hours_ago)}시간 전"
                    else:
                        time_text = f"{int(hours_ago/24)}일 전"
                except Exception:
                    time_text = "-"
                ctk.CTkLabel(row, text=time_text, font=ctk.CTkFont(size=11), width=80).pack(side="left", padx=3)

                # 등급
                grade = video.get("current_grade", "-")
                grade_colors = {
                    "excellent": ("#22c55e", "우수"),
                    "good": ("#3b82f6", "양호"),
                    "average": ("#eab308", "보통"),
                    "below": ("#f97316", "미흡"),
                    "poor": ("#ef4444", "부진"),
                }
                color, text = grade_colors.get(grade, ("gray", grade or "-"))
                ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=11), width=70, text_color=color).pack(side="left", padx=3)

                # CTR
                milestones = video.get("milestones", {})
                ctr = milestones.get("24", {}).get("ctr", milestones.get("6", {}).get("ctr", 0))
                ctk.CTkLabel(row, text=f"{ctr:.1f}%", font=ctk.CTkFont(size=11), width=60).pack(side="left", padx=3)

                # 마일스톤 상태
                completed_milestones = len(milestones)
                ctk.CTkLabel(
                    row,
                    text=f"{completed_milestones}/5 마일스톤",
                    font=ctk.CTkFont(size=11),
                    width=100,
                    text_color="gray"
                ).pack(side="left", padx=3)

        # 리포트 텍스트
        report_text = self.feedback_loop.get_report_text(days=7)
        self.feedback_report_text.configure(state="normal")
        self.feedback_report_text.delete("1.0", "end")
        self.feedback_report_text.insert("1.0", report_text)
        self.feedback_report_text.configure(state="disabled")

        # 학습 인사이트
        learnings = self.feedback_loop.get_learnings_summary()

        insights_text = ""
        if learnings.get("best_upload_times"):
            insights_text += "최적 업로드 시간:\n"
            for t in learnings["best_upload_times"][:3]:
                insights_text += f"  • {t}\n"

        if learnings.get("top_keywords"):
            insights_text += "\n고성과 키워드:\n"
            for kw, ctr in learnings["top_keywords"][:5]:
                insights_text += f"  • {kw} (평균 CTR {ctr:.1f}%)\n"

        if not insights_text:
            insights_text = "아직 충분한 데이터가 쌓이지 않았습니다.\n영상을 업로드하면 자동으로 학습합니다."

        self.feedback_insights_label.configure(text=insights_text)

    def _toggle_feedback_scheduler(self):
        """피드백 스케줄러 토글"""
        if not self.feedback_loop:
            messagebox.showerror("오류", "FeedbackLoop가 초기화되지 않았습니다.")
            return

        if self.feedback_loop.is_scheduler_running():
            self.feedback_loop.stop_scheduler()
            messagebox.showinfo("피드백 루프", "성과 추적이 중지되었습니다.")
        else:
            self.feedback_loop.start_scheduler(check_interval_minutes=30)
            messagebox.showinfo(
                "피드백 루프",
                "성과 추적이 시작되었습니다!\n"
                "30분마다 업로드된 영상의 성과를 자동으로 분석합니다."
            )

        self._refresh_feedback_data()

    def _copy_feedback_report(self):
        """피드백 리포트 복사"""
        text = self.feedback_report_text.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("복사 완료", "성과 리포트가 클립보드에 복사되었습니다.")

    # =========================================================
    # v55: 캐릭터 관리 탭
    # =========================================================

    def _build_characters_tab(self):
        """v55: 캐릭터 관리 탭 (이미지 일관성)"""
        frame = ctk.CTkScrollableFrame(self.tab_characters)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 헤더
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            header_frame,
            text="👤 캐릭터 관리",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # 새 캐릭터 추가 버튼
        ctk.CTkButton(
            header_frame,
            text="➕ 새 캐릭터",
            width=120,
            fg_color="#22c55e",
            hover_color="#16a34a",
            command=self._add_character_dialog
        ).pack(side="right")

        # IP-Adapter 상태
        status_frame = ctk.CTkFrame(frame)
        status_frame.pack(fill="x", pady=(0, 15))

        self.ip_adapter_status_label = ctk.CTkLabel(
            status_frame,
            text="IP-Adapter 상태: 확인 중...",
            font=ctk.CTkFont(size=12)
        )
        self.ip_adapter_status_label.pack(side="left", padx=15, pady=10)

        ctk.CTkButton(
            status_frame,
            text="🔄 확인",
            width=70,
            command=self._check_ip_adapter_status
        ).pack(side="right", padx=15, pady=10)

        # 캐릭터 목록
        list_label = ctk.CTkLabel(
            frame,
            text="📋 캐릭터 목록",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        list_label.pack(anchor="w", pady=(10, 5))

        # 캐릭터 리스트 프레임
        self.character_list_frame = ctk.CTkFrame(frame)
        self.character_list_frame.pack(fill="both", expand=True)

        # 캐릭터 로드
        self._load_characters()

        # 사용 안내
        info_text = (
            "💡 캐릭터 일관성 기능 사용법:\n"
            "1. '새 캐릭터' 버튼으로 캐릭터 생성\n"
            "2. 참조 이미지 추가 (얼굴 또는 전신)\n"
            "3. 영상 생성 시 캐릭터 선택하면 동일 캐릭터 유지\n\n"
            "※ IP-Adapter가 SD WebUI에 설치되어 있어야 합니다."
        )
        ctk.CTkLabel(
            frame,
            text=info_text,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left"
        ).pack(anchor="w", pady=(20, 0))

    def _check_ip_adapter_status(self):
        """IP-Adapter 상태 확인"""
        try:
            from core.ip_adapter_bridge import get_ip_adapter_bridge
            bridge = get_ip_adapter_bridge()
            available, msg = bridge.check_availability()

            if available:
                models = bridge.get_available_models()
                self.ip_adapter_status_label.configure(
                    text=f"✅ IP-Adapter 사용 가능 ({len(models)}개 모델)",
                    text_color="green"
                )
            else:
                self.ip_adapter_status_label.configure(
                    text=f"❌ {msg}",
                    text_color="red"
                )
        except Exception as e:
            self.ip_adapter_status_label.configure(
                text=f"⚠️ 확인 실패: {e}",
                text_color="orange"
            )

    def _load_characters(self):
        """캐릭터 목록 로드"""
        # 기존 위젯 제거
        for widget in self.character_list_frame.winfo_children():
            widget.destroy()

        try:
            from core.character_manager import get_character_manager
            manager = get_character_manager(self.data_dir, self.channel_type)
            characters = manager.get_all_characters()

            if not characters:
                ctk.CTkLabel(
                    self.character_list_frame,
                    text="등록된 캐릭터가 없습니다.\n'새 캐릭터' 버튼으로 추가하세요.",
                    text_color="gray"
                ).pack(pady=30)
                return

            for char in characters:
                self._create_character_row(char)

        except Exception as e:
            ctk.CTkLabel(
                self.character_list_frame,
                text=f"캐릭터 로드 실패: {e}",
                text_color="red"
            ).pack(pady=30)

    def _create_character_row(self, character):
        """캐릭터 행 생성"""
        row = ctk.CTkFrame(self.character_list_frame)
        row.pack(fill="x", pady=5, padx=5)

        # 왼쪽: 캐릭터 정보
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=10, pady=8)

        ctk.CTkLabel(
            info_frame,
            text=f"👤 {character.name}",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w")

        ref_count = len(character.reference_images)
        detail = f"ID: {character.character_id} | 참조 이미지: {ref_count}개 | 사용: {character.use_count}회"
        ctk.CTkLabel(
            info_frame,
            text=detail,
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w")

        if character.base_prompt:
            prompt_preview = character.base_prompt[:50] + "..." if len(character.base_prompt) > 50 else character.base_prompt
            ctk.CTkLabel(
                info_frame,
                text=f"프롬프트: {prompt_preview}",
                font=ctk.CTkFont(size=10),
                text_color="gray"
            ).pack(anchor="w")

        # 오른쪽: 버튼들
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=10, pady=8)

        # 이미지 추가 버튼
        ctk.CTkButton(
            btn_frame,
            text="🖼️ 이미지",
            width=80,
            height=28,
            command=lambda c=character: self._add_reference_image(c.character_id)
        ).pack(side="left", padx=2)

        # 편집 버튼
        ctk.CTkButton(
            btn_frame,
            text="✏️",
            width=40,
            height=28,
            command=lambda c=character: self._edit_character(c.character_id)
        ).pack(side="left", padx=2)

        # 삭제 버튼
        ctk.CTkButton(
            btn_frame,
            text="🗑️",
            width=40,
            height=28,
            fg_color="red",
            hover_color="darkred",
            command=lambda c=character: self._delete_character(c.character_id)
        ).pack(side="left", padx=2)

    def _add_character_dialog(self):
        """새 캐릭터 추가 다이얼로그"""
        dialog = CharacterAddDialog(self, self.data_dir, self.channel_type)
        self.wait_window(dialog)
        if dialog.result:
            self._load_characters()

    def _add_reference_image(self, character_id: str):
        """참조 이미지 추가"""
        from tkinter import filedialog

        file_path = filedialog.askopenfilename(
            title="참조 이미지 선택",
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.webp")]
        )

        if file_path:
            try:
                from core.character_manager import get_character_manager
                manager = get_character_manager(self.data_dir, self.channel_type)
                result = manager.add_reference_image(character_id, file_path)

                if result:
                    messagebox.showinfo("성공", f"참조 이미지가 추가되었습니다.\n파일: {result}")
                    self._load_characters()
                else:
                    messagebox.showerror("오류", "이미지 추가에 실패했습니다.")
            except Exception as e:
                messagebox.showerror("오류", f"이미지 추가 실패: {e}")

    def _edit_character(self, character_id: str):
        """캐릭터 편집"""
        try:
            from core.character_manager import get_character_manager
            manager = get_character_manager(self.data_dir, self.channel_type)
            character = manager.get_character(character_id)

            if character:
                dialog = CharacterEditDialog(self, manager, character)
                self.wait_window(dialog)
                self._load_characters()
        except Exception as e:
            messagebox.showerror("오류", f"캐릭터 편집 실패: {e}")

    def _delete_character(self, character_id: str):
        """캐릭터 삭제"""
        result = messagebox.askyesno(
            "캐릭터 삭제",
            f"캐릭터 '{character_id}'를 삭제하시겠습니까?\n참조 이미지도 함께 삭제됩니다."
        )

        if result:
            try:
                from core.character_manager import get_character_manager
                manager = get_character_manager(self.data_dir, self.channel_type)
                manager.delete_character(character_id, delete_files=True)
                messagebox.showinfo("성공", "캐릭터가 삭제되었습니다.")
                self._load_characters()
            except Exception as e:
                messagebox.showerror("오류", f"캐릭터 삭제 실패: {e}")

    # =========================================================
    # v53: 효과음 탭 (Auto-SFX)
    # =========================================================

    def _build_sfx_tab(self):
        """v53: 효과음 설정 탭"""
        frame = ctk.CTkScrollableFrame(self.tab_sfx)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="🔊 Auto-SFX 효과음 설정",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=(10, 20))

        # 효과음 활성화
        enable_frame = ctk.CTkFrame(frame)
        enable_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            enable_frame,
            text="자동 효과음 삽입",
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=15, pady=15)

        self.sfx_enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            enable_frame,
            text="",
            variable=self.sfx_enabled_var
        ).pack(side="right", padx=15, pady=15)

        # 효과음 밀도
        density_frame = ctk.CTkFrame(frame)
        density_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            density_frame,
            text="효과음 밀도",
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=15, pady=15)

        self.sfx_density_var = ctk.StringVar(value="medium")
        density_menu = ctk.CTkSegmentedButton(
            density_frame,
            values=["low", "medium", "high"],
            variable=self.sfx_density_var
        )
        density_menu.pack(side="right", padx=15, pady=15)

        # 마스터 볼륨
        volume_frame = ctk.CTkFrame(frame)
        volume_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            volume_frame,
            text="효과음 볼륨",
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=15, pady=15)

        vol_inner = ctk.CTkFrame(volume_frame, fg_color="transparent")
        vol_inner.pack(side="right", padx=15, pady=15)

        self.sfx_volume_slider = ctk.CTkSlider(vol_inner, from_=0, to=2, number_of_steps=20, width=150)
        self.sfx_volume_slider.set(1.0)
        self.sfx_volume_slider.pack(side="left", padx=(0, 10))

        self.sfx_volume_label = ctk.CTkLabel(vol_inner, text="100%")
        self.sfx_volume_label.pack(side="left")
        self.sfx_volume_slider.configure(
            command=lambda v: self.sfx_volume_label.configure(text=f"{int(v*100)}%")
        )

        # 배경음 덕킹
        ducking_frame = ctk.CTkFrame(frame)
        ducking_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            ducking_frame,
            text="배경음 덕킹 (효과음 나올 때 배경음 줄이기)",
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=15, pady=15)

        self.ducking_enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            ducking_frame,
            text="",
            variable=self.ducking_enabled_var
        ).pack(side="right", padx=15, pady=15)

        # 효과음 라이브러리 상태
        lib_frame = ctk.CTkFrame(frame)
        lib_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            lib_frame,
            text="📁 효과음 라이브러리",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.sfx_stats_label = ctk.CTkLabel(lib_frame, text="로딩 중...", text_color="gray")
        self.sfx_stats_label.pack(anchor="w", padx=15, pady=(0, 10))

        # 스캔 버튼
        ctk.CTkButton(
            lib_frame,
            text="🔄 효과음 폴더 스캔",
            command=self._scan_sfx_library,
            width=150
        ).pack(anchor="w", padx=15, pady=(0, 15))

        # 효과음 목록
        list_frame = ctk.CTkFrame(frame)
        list_frame.pack(fill="both", expand=True, pady=(0, 15))

        ctk.CTkLabel(
            list_frame,
            text="등록된 효과음",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.sfx_list_frame = ctk.CTkScrollableFrame(list_frame, height=200)
        self.sfx_list_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 효과음 목록 로드
        self._load_sfx_library()

        # 안내
        ctk.CTkLabel(
            frame,
            text="💡 효과음 추가: assets/sfx/ 폴더에 파일을 넣고 '스캔' 버튼 클릭",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w", pady=(10, 0))

    def _load_sfx_library(self):
        """효과음 라이브러리 로드"""
        # 기존 위젯 제거
        for widget in self.sfx_list_frame.winfo_children():
            widget.destroy()

        try:
            from core.sfx_manager import get_sfx_manager
            manager = get_sfx_manager("assets/sfx")
            stats = manager.get_stats()

            # 통계 업데이트
            self.sfx_stats_label.configure(
                text=f"총 {stats['total_sfx']}개 효과음 | {stats['total_tags']}개 태그"
            )

            # 카테고리별 표시
            all_sfx = manager.get_all_sfx()
            categories = {}
            for sfx in all_sfx:
                cat = sfx.category.split('\\')[0].split('/')[0]
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(sfx)

            for cat, sfx_list in categories.items():
                # 카테고리 헤더
                ctk.CTkLabel(
                    self.sfx_list_frame,
                    text=f"📂 {cat} ({len(sfx_list)}개)",
                    font=ctk.CTkFont(weight="bold")
                ).pack(anchor="w", pady=(10, 5))

                # 효과음 목록 (최대 5개씩)
                for sfx in sfx_list[:5]:
                    tags_str = ", ".join(sfx.tags[:3]) if sfx.tags else "태그 없음"
                    ctk.CTkLabel(
                        self.sfx_list_frame,
                        text=f"  • {sfx.filename} [{tags_str}]",
                        text_color="gray"
                    ).pack(anchor="w")

                if len(sfx_list) > 5:
                    ctk.CTkLabel(
                        self.sfx_list_frame,
                        text=f"  ... 외 {len(sfx_list) - 5}개",
                        text_color="gray"
                    ).pack(anchor="w")

        except Exception as e:
            self.sfx_stats_label.configure(text=f"로드 실패: {e}")

    def _scan_sfx_library(self):
        """효과음 폴더 스캔"""
        try:
            from core.sfx_manager import get_sfx_manager
            manager = get_sfx_manager("assets/sfx")
            new_count = manager.scan_directory()

            if new_count > 0:
                messagebox.showinfo("스캔 완료", f"새로운 효과음 {new_count}개가 등록되었습니다.")
            else:
                messagebox.showinfo("스캔 완료", "새로운 효과음이 없습니다.")

            self._load_sfx_library()

        except Exception as e:
            messagebox.showerror("오류", f"스캔 실패: {e}")

    # =========================================================
    # v56: 멀티채널 스케줄러 탭
    # =========================================================

    def _build_scheduler_tab(self):
        """v56: 멀티채널 스케줄러 탭"""
        frame = ctk.CTkScrollableFrame(self.tab_scheduler)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="📅 멀티채널 스케줄러",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=(10, 20))

        # 스케줄러 상태
        status_frame = ctk.CTkFrame(frame)
        status_frame.pack(fill="x", pady=(0, 15))

        status_inner = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_inner.pack(fill="x", padx=15, pady=15)

        ctk.CTkLabel(
            status_inner,
            text="스케줄러 상태:",
            font=ctk.CTkFont(size=14)
        ).pack(side="left")

        self.scheduler_state_label = ctk.CTkLabel(
            status_inner,
            text="중지됨",
            text_color="gray",
            font=ctk.CTkFont(weight="bold")
        )
        self.scheduler_state_label.pack(side="left", padx=10)

        self.scheduler_toggle_btn = ctk.CTkButton(
            status_inner,
            text="▶️ 시작",
            width=100,
            command=self._toggle_scheduler
        )
        self.scheduler_toggle_btn.pack(side="right")

        # 통계 카드
        stats_frame = ctk.CTkFrame(frame)
        stats_frame.pack(fill="x", pady=(0, 15))

        stats_inner = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_inner.pack(fill="x", padx=15, pady=15)

        # 대기 작업
        stat1 = ctk.CTkFrame(stats_inner)
        stat1.pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkLabel(stat1, text="대기 작업", text_color="gray").pack()
        self.pending_tasks_label = ctk.CTkLabel(stat1, text="0", font=ctk.CTkFont(size=24, weight="bold"))
        self.pending_tasks_label.pack()

        # 실행 중
        stat2 = ctk.CTkFrame(stats_inner)
        stat2.pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkLabel(stat2, text="실행 중", text_color="gray").pack()
        self.running_tasks_label = ctk.CTkLabel(stat2, text="0", font=ctk.CTkFont(size=24, weight="bold"))
        self.running_tasks_label.pack()

        # 오늘 생성
        stat3 = ctk.CTkFrame(stats_inner)
        stat3.pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkLabel(stat3, text="오늘 생성", text_color="gray").pack()
        self.today_videos_label = ctk.CTkLabel(stat3, text="0", font=ctk.CTkFont(size=24, weight="bold"))
        self.today_videos_label.pack()

        # 활성 채널
        stat4 = ctk.CTkFrame(stats_inner)
        stat4.pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkLabel(stat4, text="활성 채널", text_color="gray").pack()
        self.active_channels_label = ctk.CTkLabel(stat4, text="0", font=ctk.CTkFont(size=24, weight="bold"))
        self.active_channels_label.pack()

        # 설정
        settings_frame = ctk.CTkFrame(frame)
        settings_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            settings_frame,
            text="⚙️ 스케줄러 설정",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 동시 실행 제한
        concurrent_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        concurrent_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(concurrent_frame, text="동시 실행 작업 수:").pack(side="left")
        self.concurrent_entry = ctk.CTkEntry(concurrent_frame, width=60)
        self.concurrent_entry.insert(0, "2")
        self.concurrent_entry.pack(side="right")

        # 일일 생성 제한
        daily_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        daily_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(daily_frame, text="일일 총 생성 제한:").pack(side="left")
        self.daily_limit_entry = ctk.CTkEntry(daily_frame, width=60)
        self.daily_limit_entry.insert(0, "50")
        self.daily_limit_entry.pack(side="right")

        # 자동 우선순위
        auto_priority_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        auto_priority_frame.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(auto_priority_frame, text="성과 기반 자동 우선순위 조절:").pack(side="left")
        self.auto_priority_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(auto_priority_frame, text="", variable=self.auto_priority_var).pack(side="right")

        # 채널 목록
        channels_frame = ctk.CTkFrame(frame)
        channels_frame.pack(fill="both", expand=True, pady=(0, 15))

        ch_header = ctk.CTkFrame(channels_frame, fg_color="transparent")
        ch_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            ch_header,
            text="📺 채널별 상태",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            ch_header,
            text="🔄 새로고침",
            width=100,
            command=self._refresh_scheduler_data
        ).pack(side="right")

        self.scheduler_channels_frame = ctk.CTkScrollableFrame(channels_frame, height=200)
        self.scheduler_channels_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 데이터 로드
        self._refresh_scheduler_data()

    def _toggle_scheduler(self):
        """스케줄러 토글"""
        try:
            from utils.channel_scheduler import get_channel_scheduler
            scheduler = get_channel_scheduler(self.data_dir)
            status = scheduler.get_status()

            if status['state'] == 'running':
                scheduler.stop()
                messagebox.showinfo("스케줄러", "멀티채널 스케줄러가 중지되었습니다.")
            else:
                scheduler.start()
                messagebox.showinfo("스케줄러", "멀티채널 스케줄러가 시작되었습니다!")

            self._refresh_scheduler_data()

        except Exception as e:
            messagebox.showerror("오류", f"스케줄러 제어 실패: {e}")

    def _refresh_scheduler_data(self):
        """스케줄러 데이터 새로고침"""
        try:
            from utils.channel_scheduler import get_channel_scheduler
            scheduler = get_channel_scheduler(self.data_dir)
            status = scheduler.get_status()

            # 상태 업데이트
            state = status['state']
            if state == 'running':
                self.scheduler_state_label.configure(text="실행 중", text_color="green")
                self.scheduler_toggle_btn.configure(text="⏹️ 중지", fg_color="red", hover_color="darkred")
            elif state == 'paused':
                self.scheduler_state_label.configure(text="일시 정지", text_color="orange")
                self.scheduler_toggle_btn.configure(text="▶️ 재개", fg_color="green")
            else:
                self.scheduler_state_label.configure(text="중지됨", text_color="gray")
                self.scheduler_toggle_btn.configure(text="▶️ 시작", fg_color="green", hover_color="darkgreen")

            # 통계 업데이트
            self.pending_tasks_label.configure(text=str(status['pending_tasks']))
            self.running_tasks_label.configure(text=str(status['running_tasks']))
            self.today_videos_label.configure(text=str(status['stats'].get('videos_generated_today', 0)))
            self.active_channels_label.configure(text=str(status['active_channels']))

            # 채널 목록 로드
            self._load_scheduler_channels(scheduler)

        except Exception as e:
            self.scheduler_state_label.configure(text=f"오류: {e}", text_color="red")

    def _load_scheduler_channels(self, scheduler):
        """스케줄러 채널 목록 로드"""
        # 기존 위젯 제거
        for widget in self.scheduler_channels_frame.winfo_children():
            widget.destroy()

        channels = scheduler.get_all_channel_status()

        if not channels:
            ctk.CTkLabel(
                self.scheduler_channels_frame,
                text="등록된 채널이 없습니다.",
                text_color="gray"
            ).pack(pady=20)
            return

        # 우선순위 순 정렬
        channels = sorted(channels, key=lambda x: x['priority'], reverse=True)

        for ch in channels:
            row = ctk.CTkFrame(self.scheduler_channels_frame)
            row.pack(fill="x", pady=3)

            # 상태 아이콘
            status_icon = "🟢" if ch['is_active'] else "⚫"

            # 채널 정보
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=8)

            ctk.CTkLabel(
                info,
                text=f"{status_icon} {ch['display_name']}",
                font=ctk.CTkFont(weight="bold")
            ).pack(anchor="w")

            detail = f"우선순위: {ch['priority']} | 오늘: {ch['videos_today']}/{ch['daily_limit']} | 대기: {ch['pending_tasks']}"
            ctk.CTkLabel(info, text=detail, text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w")

            # 우선순위 조절
            priority_frame = ctk.CTkFrame(row, fg_color="transparent")
            priority_frame.pack(side="right", padx=10, pady=8)

            ctk.CTkButton(
                priority_frame,
                text="▲",
                width=30,
                height=25,
                command=lambda cid=ch['channel_id']: self._change_channel_priority(cid, 10)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                priority_frame,
                text="▼",
                width=30,
                height=25,
                command=lambda cid=ch['channel_id']: self._change_channel_priority(cid, -10)
            ).pack(side="left", padx=2)

    def _change_channel_priority(self, channel_id: str, delta: int):
        """채널 우선순위 변경"""
        try:
            from utils.channel_scheduler import get_channel_scheduler
            scheduler = get_channel_scheduler(self.data_dir)
            status = scheduler.get_channel_status(channel_id)

            if status:
                new_priority = max(0, min(100, status['priority'] + delta))
                scheduler.set_channel_priority(channel_id, new_priority)
                self._refresh_scheduler_data()

        except Exception as e:
            messagebox.showerror("오류", f"우선순위 변경 실패: {e}")

    # =========================================================
    # 설정 탭
    # =========================================================

    def _build_settings_tab(self):
        """설정 탭"""
        frame = ctk.CTkScrollableFrame(self.tab_settings)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="⚙️ 자동 최적화 설정",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=(10, 20))

        # 활성화 토글
        enable_frame = ctk.CTkFrame(frame)
        enable_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            enable_frame,
            text="자동 최적화 활성화",
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=15, pady=15)

        self.enable_switch = ctk.CTkSwitch(
            enable_frame,
            text="",
            command=self._toggle_enabled
        )
        self.enable_switch.pack(side="right", padx=15, pady=15)

        # 체크 간격
        interval_frame = ctk.CTkFrame(frame)
        interval_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            interval_frame,
            text="체크 간격 (시간)",
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=15, pady=15)

        self.interval_entry = ctk.CTkEntry(interval_frame, width=80)
        self.interval_entry.pack(side="right", padx=15, pady=15)

        # 썸네일 교체 설정
        thumb_section = ctk.CTkFrame(frame)
        thumb_section.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            thumb_section,
            text="🖼️ 썸네일 교체 설정",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 최소 업로드 시간
        min_age_frame = ctk.CTkFrame(thumb_section, fg_color="transparent")
        min_age_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(min_age_frame, text="최소 업로드 시간 (시간):").pack(side="left")
        self.min_age_entry = ctk.CTkEntry(min_age_frame, width=80)
        self.min_age_entry.pack(side="right")

        # 최대 교체 횟수
        max_changes_frame = ctk.CTkFrame(thumb_section, fg_color="transparent")
        max_changes_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(max_changes_frame, text="영상당 최대 교체 횟수:").pack(side="left")
        self.max_changes_entry = ctk.CTkEntry(max_changes_frame, width=80)
        self.max_changes_entry.pack(side="right")

        ctk.CTkLabel(thumb_section, text="").pack(pady=5)

        # 저장 버튼
        ctk.CTkButton(
            frame,
            text="💾 설정 저장",
            command=self._save_settings,
            width=150,
            fg_color="green",
            hover_color="darkgreen"
        ).pack(pady=20)

    def _load_settings_data(self):
        """설정 데이터 로드"""
        if not self.optimizer:
            return

        config = self.optimizer.get_config()

        # 활성화 상태
        if config.get('enabled', True):
            self.enable_switch.select()
        else:
            self.enable_switch.deselect()

        # 체크 간격
        self.interval_entry.delete(0, 'end')
        self.interval_entry.insert(0, str(config.get('check_interval_hours', 6)))

        # 썸네일 설정
        thumb_config = config.get('thumbnail_change', {})

        self.min_age_entry.delete(0, 'end')
        self.min_age_entry.insert(0, str(thumb_config.get('min_age_hours', 24)))

        self.max_changes_entry.delete(0, 'end')
        self.max_changes_entry.insert(0, str(thumb_config.get('max_changes_per_video', 3)))

    def _save_settings(self):
        """설정 저장"""
        if not self.optimizer:
            return

        try:
            new_config = {
                'enabled': self.enable_switch.get(),
                'check_interval_hours': int(self.interval_entry.get()),
                'thumbnail_change': {
                    'min_age_hours': int(self.min_age_entry.get()),
                    'max_changes_per_video': int(self.max_changes_entry.get()),
                }
            }

            self.optimizer.update_config(new_config)
            messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")

        except ValueError as e:
            messagebox.showerror("오류", "숫자를 정확히 입력해주세요.")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _toggle_enabled(self):
        """활성화 토글"""
        if self.optimizer:
            self.optimizer.set_enabled(self.enable_switch.get())

    # =========================================================
    # 공통 기능
    # =========================================================

    def _load_data(self):
        """데이터 로드"""
        # v54.6: 유토피아 엔진 상태 로드
        if self.utopia_engine:
            utopia_status = self.utopia_engine.get_status()

            if utopia_status.get("running"):
                self.engine_status_label.configure(text="실행 중", text_color="#22c55e")
                self.utopia_engine_btn.configure(
                    text="⏹️ 유토피아 중지",
                    fg_color="#ef4444",
                    hover_color="#dc2626"
                )
            else:
                self.engine_status_label.configure(text="중지됨", text_color="gray")
                self.utopia_engine_btn.configure(
                    text="🚀 유토피아 시작",
                    fg_color="#9333ea",
                    hover_color="#7c3aed"
                )

            # 모드 동기화
            current_mode = utopia_status.get("mode", "semi_auto")
            self.utopia_mode_var.set(current_mode)

            # 상태 표시
            state = utopia_status.get("current_state", "idle")
            state_names = {
                "idle": ("대기 중", "gray"),
                "generating": ("생성 중...", "#3b82f6"),
                "reviewing": ("검토 대기", "#eab308"),
                "uploading": ("업로드 중...", "#22c55e"),
                "monitoring": ("모니터링 중", "#8b5cf6"),
                "optimizing": ("최적화 중", "#ec4899"),
                "error": ("오류 발생", "#ef4444"),
            }
            text, color = state_names.get(state, ("알 수 없음", "gray"))
            self.utopia_state_label.configure(text=text, text_color=color)

        if not self.optimizer:
            return

        status = self.optimizer.get_status()

        # 스케줄러 상태
        if status.get('scheduler_running'):
            self.scheduler_status_label.configure(text="실행 중", text_color="#22c55e")
            self.scheduler_btn.configure(text="중지", fg_color="#ef4444", hover_color="#dc2626")
        else:
            self.scheduler_status_label.configure(text="중지됨", text_color="gray")
            self.scheduler_btn.configure(text="시작", fg_color="#22c55e", hover_color="#16a34a")

        # 액션 수
        self.actions_count_label.configure(text=str(status.get('total_actions', 0)))

        # 패턴 수
        patterns = status.get('patterns_learned', {})
        total_patterns = patterns.get('top_keywords', 0) + patterns.get('low_keywords', 0)
        self.patterns_count_label.configure(text=str(total_patterns))

        # 최근 로그
        recent_actions = status.get('recent_actions', [])
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")

        for action in reversed(recent_actions):
            timestamp = action.get('timestamp', '')[:19]
            action_type = action.get('action_type', '')
            video_id = action.get('video_id', '')
            details = action.get('details', {})

            log_line = f"[{timestamp}] {action_type}: {details.get('title', video_id)}\n"
            self.log_text.insert("end", log_line)

        if not recent_actions:
            self.log_text.insert("end", "아직 활동 기록이 없습니다.\n")

        self.log_text.configure(state="disabled")

        # 패턴 데이터 로드
        self._load_patterns_data()

        # 설정 데이터 로드
        self._load_settings_data()

        # v54.3: 개인화 데이터 로드
        self._load_personalization_data()

        # v54.4: 업로드 대기열 로드
        self._refresh_upload_queue()

        # v54.5: 피드백 데이터 로드
        self._refresh_feedback_data()

    def _toggle_scheduler(self):
        """스케줄러 토글"""
        if not self.optimizer:
            return

        status = self.optimizer.get_status()

        if status.get('scheduler_running'):
            self.optimizer.stop_scheduler()
            messagebox.showinfo("스케줄러", "자동 최적화 스케줄러가 중지되었습니다.")
        else:
            self.optimizer.start_scheduler()
            messagebox.showinfo("스케줄러", "자동 최적화 스케줄러가 시작되었습니다!\n"
                                         f"매 {self.optimizer.config.get('check_interval_hours', 6)}시간마다 자동으로 최적화를 실행합니다.")

        self._load_data()

    def _toggle_utopia_engine(self):
        """유토피아 엔진 토글 - v54.6"""
        if not self.utopia_engine:
            messagebox.showerror("오류", "UtopiaEngine이 초기화되지 않았습니다.")
            return

        if self.utopia_engine.is_running():
            self.utopia_engine.stop()
            messagebox.showinfo("유토피아", "유토피아 시스템이 중지되었습니다.")
        else:
            self.utopia_engine.start()
            mode = self.utopia_mode_var.get()
            mode_names = {"manual": "수동", "semi_auto": "반자동", "full_auto": "완전 자동"}
            messagebox.showinfo(
                "유토피아",
                f"유토피아 시스템이 시작되었습니다!\n\n"
                f"모드: {mode_names.get(mode, mode)}\n\n"
                f"• 업로드 스케줄러 자동 시작\n"
                f"• 피드백 루프 자동 시작\n"
                f"• 자동 최적화 활성화"
            )

        self._load_data()

    def _change_utopia_mode(self):
        """유토피아 모드 변경 - v54.6"""
        if not self.utopia_engine:
            return

        mode = self.utopia_mode_var.get()
        from utils.utopia_engine import UtopiaMode
        self.utopia_engine.set_mode(UtopiaMode(mode))

    def _on_engine_mode_change(self, mode):
        """엔진에서 모드가 변경되었을 때 UI 동기화 - v54.7.1"""
        try:
            # UI 스레드에서 실행되도록 after 사용
            self.after(0, lambda: self.utopia_mode_var.set(mode.value))
        except Exception:
            pass  # 창이 닫힌 경우 무시

    def _open_dashboard(self):
        """대시보드 열기 - v54.7"""
        try:
            from gui.utopia_dashboard import open_utopia_dashboard
            open_utopia_dashboard(self, self.data_dir, self.channel_type)
        except Exception as e:
            messagebox.showerror("오류", f"대시보드를 열 수 없습니다: {e}")

    def _run_optimization(self):
        """즉시 최적화 실행"""
        if not self.optimizer:
            messagebox.showerror("오류", "AutoOptimizer가 초기화되지 않았습니다.")
            return

        # 로그에 시작 표시
        self.log_text.configure(state="normal")
        self.log_text.insert("1.0", f"[{datetime.now().strftime('%H:%M:%S')}] 최적화 실행 중...\n")
        self.log_text.configure(state="disabled")

        def worker():
            try:
                result = self.optimizer.run_optimization_cycle()

                # 결과 메시지
                msg = f"최적화 완료!\n\n"
                msg += f"• 분석된 영상: {result.get('analyzed', 0)}개\n"
                msg += f"• 썸네일 교체: {result.get('thumbnails_changed', 0)}개\n"
                msg += f"• 패턴 업데이트: {'예' if result.get('patterns_updated') else '아니오'}\n"

                if result.get('errors'):
                    msg += f"\n⚠️ 오류:\n"
                    for err in result.get('errors', [])[:3]:
                        msg += f"• {err}\n"

                self.after(0, lambda: messagebox.showinfo("최적화 결과", msg))
                self.after(0, self._load_data)

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("오류", str(e)))

        threading.Thread(target=worker, daemon=True).start()


# ========== v54.8: 채널 관리 다이얼로그 ==========

class ChannelAddDialog(ctk.CTkToplevel):
    """채널 추가 다이얼로그 - v54.8, v57: 다국어 지원"""

    def __init__(self, parent, registry):
        super().__init__(parent)
        self.registry = registry
        self.result = None

        self.title("새 채널 추가")
        self.geometry("450x480")  # v57: 언어 선택 필드를 위해 높이 증가
        self.resizable(False, False)

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        self._create_widgets()
        self._center_window()

    def _center_window(self):
        """창 중앙 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 450) // 2
        y = (self.winfo_screenheight() - 480) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        """위젯 생성"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="새 채널 등록",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(0, 20))

        # 채널 이름
        ctk.CTkLabel(main_frame, text="채널 이름 *").pack(anchor="w")
        self.name_entry = ctk.CTkEntry(main_frame, width=400, placeholder_text="예: 공포 이야기 1번 채널")
        self.name_entry.pack(pady=(0, 15))

        # 채널 타입
        ctk.CTkLabel(main_frame, text="채널 타입 *").pack(anchor="w")
        self.type_dropdown = ctk.CTkComboBox(
            main_frame,
            values=["horror", "emotional", "romance", "mystery", "comedy", "drama", "other"],
            width=400
        )
        self.type_dropdown.set("horror")
        self.type_dropdown.pack(pady=(0, 15))

        # YouTube 채널 ID (선택)
        ctk.CTkLabel(main_frame, text="YouTube 채널 ID (선택)").pack(anchor="w")
        self.youtube_id_entry = ctk.CTkEntry(main_frame, width=400, placeholder_text="예: UC...")
        self.youtube_id_entry.pack(pady=(0, 15))

        # v57: 타겟 언어 선택
        ctk.CTkLabel(main_frame, text="타겟 언어 (v57)").pack(anchor="w")
        # SUPPORTED_LANGUAGES: {"ko": "한국어", "en": "English", ...}
        lang_display_values = [f"{code} - {name}" for code, name in SUPPORTED_LANGUAGES.items()]
        self.language_dropdown = ctk.CTkComboBox(
            main_frame,
            values=lang_display_values,
            width=400
        )
        self.language_dropdown.set("ko - 한국어")  # 기본값: 한국어
        self.language_dropdown.pack(pady=(0, 15))

        # 우선순위
        ctk.CTkLabel(main_frame, text="우선순위 (0-100)").pack(anchor="w")
        self.priority_slider = ctk.CTkSlider(main_frame, from_=0, to=100, number_of_steps=100, width=400)
        self.priority_slider.set(50)
        self.priority_slider.pack(pady=(0, 5))
        self.priority_label = ctk.CTkLabel(main_frame, text="50")
        self.priority_label.pack()
        self.priority_slider.configure(command=lambda v: self.priority_label.configure(text=str(int(v))))

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="gray",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="등록",
            width=100,
            command=self._on_submit
        ).pack(side="right")

    def _on_submit(self):
        """등록 버튼 클릭"""
        name = self.name_entry.get().strip()
        channel_type = self.type_dropdown.get()
        youtube_id = self.youtube_id_entry.get().strip() or None
        priority = int(self.priority_slider.get())

        # v57: 타겟 언어 추출 (예: "ko - 한국어" -> "ko")
        lang_selection = self.language_dropdown.get()
        target_language = lang_selection.split(" - ")[0] if " - " in lang_selection else "ko"

        if not name:
            messagebox.showerror("오류", "채널 이름을 입력해주세요.", parent=self)
            return

        # 채널 등록
        try:
            channel = self.registry.register_channel(
                channel_type=channel_type,
                display_name=name,
                youtube_channel_id=youtube_id,
                priority=priority,
                target_language=target_language  # v57: 다국어 지원
            )

            if channel:
                self.result = channel
                messagebox.showinfo("성공", f"채널이 등록되었습니다.\nID: {channel.channel_id}", parent=self)
                self.destroy()
            else:
                messagebox.showerror("오류", "채널 등록에 실패했습니다.\n최대 채널 수(100개)를 초과했을 수 있습니다.", parent=self)

        except Exception as e:
            messagebox.showerror("오류", f"채널 등록 실패: {e}", parent=self)


class ChannelManageDialog(ctk.CTkToplevel):
    """채널 관리 다이얼로그 - v54.8"""

    def __init__(self, parent, registry, on_channel_change=None):
        super().__init__(parent)
        self.registry = registry
        self.on_channel_change = on_channel_change

        self.title("채널 관리")
        self.geometry("600x500")
        self.resizable(True, True)

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        self._create_widgets()
        self._load_channels()
        self._center_window()

    def _center_window(self):
        """창 중앙 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 600) // 2
        y = (self.winfo_screenheight() - 500) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        """위젯 생성"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목 + 통계
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            header_frame,
            text="채널 관리",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        self.stats_label = ctk.CTkLabel(header_frame, text="", text_color="gray")
        self.stats_label.pack(side="right")

        # 채널 목록 (스크롤)
        self.scroll_frame = ctk.CTkScrollableFrame(main_frame, height=350)
        self.scroll_frame.pack(fill="both", expand=True, pady=(0, 15))

        # 하단 버튼
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="닫기",
            width=100,
            command=self.destroy
        ).pack(side="right")

    def _load_channels(self):
        """채널 목록 로드"""
        # 기존 위젯 제거
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        channels = self.registry.get_all_channels()
        stats = self.registry.get_stats()

        self.stats_label.configure(text=f"{stats['total_channels']}/{stats['max_channels']} 채널")

        if not channels:
            ctk.CTkLabel(
                self.scroll_frame,
                text="등록된 채널이 없습니다.",
                text_color="gray"
            ).pack(pady=50)
            return

        # 우선순위 순 정렬
        channels_sorted = sorted(channels, key=lambda c: c.priority, reverse=True)

        for channel in channels_sorted:
            self._create_channel_row(channel)

    def _create_channel_row(self, channel):
        """채널 행 생성"""
        row_frame = ctk.CTkFrame(self.scroll_frame)
        row_frame.pack(fill="x", pady=5, padx=5)

        # 왼쪽: 채널 정보
        info_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=10, pady=10)

        # 채널 이름 + 상태
        name_color = "white" if channel.is_active else "gray"
        status_text = "🟢" if channel.is_active else "⚫"

        ctk.CTkLabel(
            info_frame,
            text=f"{status_text} {channel.display_name}",
            font=ctk.CTkFont(weight="bold"),
            text_color=name_color
        ).pack(anchor="w")

        # 상세 정보 (v57: 언어 정보 추가)
        # 채널의 타겟 언어 가져오기
        target_lang = getattr(channel, 'target_language', 'ko')
        lang_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        detail_text = f"ID: {channel.channel_id} | 타입: {channel.channel_type} | 언어: {lang_name} | 우선순위: {channel.priority}"
        if channel.youtube_channel_id:
            detail_text += f" | YouTube: {channel.youtube_channel_id[:20]}..."

        ctk.CTkLabel(
            info_frame,
            text=detail_text,
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w")

        # 통계
        stats_text = f"영상: {channel.total_videos}개 | 조회수: {channel.total_views:,}"
        ctk.CTkLabel(
            info_frame,
            text=stats_text,
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w")

        # 오른쪽: 버튼
        btn_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        btn_frame.pack(side="right", padx=10, pady=10)

        # v57: 언어 변경 버튼
        ctk.CTkButton(
            btn_frame,
            text="🌐",
            width=40,
            height=28,
            fg_color="#3498db",
            hover_color="#2980b9",
            command=lambda c=channel: self._change_language(c)
        ).pack(side="left", padx=5)

        # 활성화/비활성화 토글
        toggle_text = "비활성화" if channel.is_active else "활성화"
        toggle_color = "orange" if channel.is_active else "green"

        ctk.CTkButton(
            btn_frame,
            text=toggle_text,
            width=80,
            height=28,
            fg_color=toggle_color,
            command=lambda c=channel: self._toggle_active(c)
        ).pack(side="left", padx=5)

        # 삭제 버튼
        ctk.CTkButton(
            btn_frame,
            text="삭제",
            width=60,
            height=28,
            fg_color="red",
            hover_color="darkred",
            command=lambda c=channel: self._delete_channel(c)
        ).pack(side="left", padx=5)

    def _toggle_active(self, channel):
        """채널 활성화/비활성화 토글"""
        new_state = not channel.is_active
        self.registry.set_channel_active(channel.channel_id, new_state)
        self._load_channels()

        if self.on_channel_change:
            self.on_channel_change()

    def _delete_channel(self, channel):
        """채널 삭제"""
        result = messagebox.askyesnocancel(
            "채널 삭제",
            f"'{channel.display_name}' 채널을 삭제하시겠습니까?\n\n"
            f"• '예': 채널과 데이터 모두 삭제\n"
            f"• '아니오': 채널만 삭제 (데이터 유지)\n"
            f"• '취소': 삭제 취소",
            parent=self
        )

        if result is None:  # 취소
            return

        delete_data = result  # True면 데이터도 삭제

        try:
            self.registry.unregister_channel(channel.channel_id, delete_data=delete_data)
            messagebox.showinfo("성공", f"채널이 삭제되었습니다.", parent=self)
            self._load_channels()

            if self.on_channel_change:
                self.on_channel_change()

        except Exception as e:
            messagebox.showerror("오류", f"채널 삭제 실패: {e}", parent=self)

    def _change_language(self, channel):
        """v57: 채널 언어 변경 다이얼로그"""
        # 현재 언어
        current_lang = getattr(channel, 'target_language', 'ko')
        current_lang_name = SUPPORTED_LANGUAGES.get(current_lang, current_lang)

        # 언어 선택 다이얼로그
        dialog = LanguageSelectDialog(self, current_lang)
        self.wait_window(dialog)

        if dialog.result and dialog.result != current_lang:
            try:
                self.registry.set_channel_language(channel.channel_id, dialog.result)
                new_lang_name = SUPPORTED_LANGUAGES.get(dialog.result, dialog.result)
                messagebox.showinfo(
                    "언어 변경 완료",
                    f"'{channel.display_name}' 채널의 언어가\n{current_lang_name} → {new_lang_name}로 변경되었습니다.",
                    parent=self
                )
                self._load_channels()

                if self.on_channel_change:
                    self.on_channel_change()
            except Exception as e:
                messagebox.showerror("오류", f"언어 변경 실패: {e}", parent=self)


class LanguageSelectDialog(ctk.CTkToplevel):
    """v57: 언어 선택 다이얼로그"""

    def __init__(self, parent, current_language: str = "ko"):
        super().__init__(parent)
        self.result = None
        self.current_language = current_language

        self.title("언어 선택")
        self.geometry("300x200")
        self.resizable(False, False)

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        self._create_widgets()
        self._center_window()

    def _center_window(self):
        """창 중앙 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 300) // 2
        y = (self.winfo_screenheight() - 200) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        """위젯 생성"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="🌐 타겟 언어 선택",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(0, 15))

        # 언어 선택 드롭다운
        lang_display_values = [f"{code} - {name}" for code, name in SUPPORTED_LANGUAGES.items()]
        self.language_dropdown = ctk.CTkComboBox(
            main_frame,
            values=lang_display_values,
            width=250
        )
        # 현재 언어 선택
        current_display = f"{self.current_language} - {SUPPORTED_LANGUAGES.get(self.current_language, self.current_language)}"
        self.language_dropdown.set(current_display)
        self.language_dropdown.pack(pady=(0, 20))

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=80,
            fg_color="gray",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="적용",
            width=80,
            command=self._on_submit
        ).pack(side="right")

    def _on_submit(self):
        """적용 버튼 클릭"""
        lang_selection = self.language_dropdown.get()
        self.result = lang_selection.split(" - ")[0] if " - " in lang_selection else "ko"
        self.destroy()


# ========== v55: 캐릭터 관리 다이얼로그 ==========

class CharacterAddDialog(ctk.CTkToplevel):
    """캐릭터 추가 다이얼로그 - v55"""

    def __init__(self, parent, data_dir: str, channel_type: str):
        super().__init__(parent)
        self.data_dir = data_dir
        self.channel_type = channel_type
        self.result = None

        self.title("새 캐릭터 추가")
        self.geometry("500x550")
        self.resizable(False, False)

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        self._create_widgets()
        self._center_window()

    def _center_window(self):
        """창 중앙 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 500) // 2
        y = (self.winfo_screenheight() - 550) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        """위젯 생성"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="👤 새 캐릭터 등록",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(0, 20))

        # 캐릭터 이름
        ctk.CTkLabel(main_frame, text="캐릭터 이름 *").pack(anchor="w")
        self.name_entry = ctk.CTkEntry(main_frame, width=450, placeholder_text="예: 처녀귀신, 도깨비 할아버지")
        self.name_entry.pack(pady=(0, 15))

        # 설명
        ctk.CTkLabel(main_frame, text="설명").pack(anchor="w")
        self.desc_entry = ctk.CTkEntry(main_frame, width=450, placeholder_text="캐릭터에 대한 간단한 설명")
        self.desc_entry.pack(pady=(0, 15))

        # 기본 프롬프트
        ctk.CTkLabel(main_frame, text="기본 프롬프트 (외형 묘사)").pack(anchor="w")
        self.prompt_text = ctk.CTkTextbox(main_frame, width=450, height=100)
        self.prompt_text.pack(pady=(0, 15))
        self.prompt_text.insert("1.0", "korean ghost woman, long black hair, white hanbok, pale skin")

        # IP-Adapter 설정
        settings_frame = ctk.CTkFrame(main_frame)
        settings_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            settings_frame,
            text="🔧 IP-Adapter 설정",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 가중치
        weight_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        weight_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(weight_frame, text="가중치 (0.0 ~ 1.0):").pack(side="left")
        self.weight_slider = ctk.CTkSlider(weight_frame, from_=0, to=1, number_of_steps=20, width=200)
        self.weight_slider.set(0.7)
        self.weight_slider.pack(side="left", padx=10)
        self.weight_label = ctk.CTkLabel(weight_frame, text="0.70")
        self.weight_label.pack(side="left")
        self.weight_slider.configure(command=lambda v: self.weight_label.configure(text=f"{v:.2f}"))

        # 얼굴만 참조 여부
        face_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        face_frame.pack(fill="x", padx=15, pady=(5, 15))

        ctk.CTkLabel(face_frame, text="참조 방식:").pack(side="left")
        self.face_only_var = ctk.StringVar(value="face")
        ctk.CTkRadioButton(
            face_frame,
            text="얼굴만",
            variable=self.face_only_var,
            value="face"
        ).pack(side="left", padx=(10, 5))
        ctk.CTkRadioButton(
            face_frame,
            text="전체 스타일",
            variable=self.face_only_var,
            value="full"
        ).pack(side="left", padx=5)

        # 안내 문구
        ctk.CTkLabel(
            main_frame,
            text="💡 참조 이미지는 캐릭터 생성 후 추가할 수 있습니다.",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(anchor="w", pady=(0, 15))

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="gray",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="등록",
            width=100,
            command=self._on_submit
        ).pack(side="right")

    def _on_submit(self):
        """등록 버튼 클릭"""
        name = self.name_entry.get().strip()
        description = self.desc_entry.get().strip()
        base_prompt = self.prompt_text.get("1.0", "end").strip()
        ip_weight = self.weight_slider.get()
        face_only = self.face_only_var.get() == "face"

        if not name:
            messagebox.showerror("오류", "캐릭터 이름을 입력해주세요.", parent=self)
            return

        try:
            from core.character_manager import get_character_manager
            manager = get_character_manager(self.data_dir, self.channel_type)

            character = manager.create_character(
                name=name,
                description=description,
                base_prompt=base_prompt,
                ip_weight=ip_weight,
                face_only=face_only
            )

            if character:
                self.result = character
                messagebox.showinfo(
                    "성공",
                    f"캐릭터가 등록되었습니다!\n\nID: {character.character_id}\n이름: {character.name}\n\n"
                    f"이제 '🖼️ 이미지' 버튼으로 참조 이미지를 추가하세요.",
                    parent=self
                )
                self.destroy()
            else:
                messagebox.showerror("오류", "캐릭터 등록에 실패했습니다.", parent=self)

        except Exception as e:
            messagebox.showerror("오류", f"캐릭터 등록 실패: {e}", parent=self)


class CharacterEditDialog(ctk.CTkToplevel):
    """캐릭터 편집 다이얼로그 - v55"""

    def __init__(self, parent, manager, character):
        super().__init__(parent)
        self.manager = manager
        self.character = character

        self.title(f"캐릭터 편집: {character.name}")
        self.geometry("550x650")
        self.resizable(False, False)

        # 모달 설정
        self.transient(parent)
        self.grab_set()

        self._create_widgets()
        self._load_data()
        self._center_window()

    def _center_window(self):
        """창 중앙 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 550) // 2
        y = (self.winfo_screenheight() - 650) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        """위젯 생성"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text=f"✏️ 캐릭터 편집",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(0, 10))

        # ID 표시 (수정 불가)
        id_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        id_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(id_frame, text=f"ID: {self.character.character_id}", text_color="gray").pack(anchor="w")

        # 캐릭터 이름
        ctk.CTkLabel(main_frame, text="캐릭터 이름").pack(anchor="w")
        self.name_entry = ctk.CTkEntry(main_frame, width=500)
        self.name_entry.pack(pady=(0, 15))

        # 설명
        ctk.CTkLabel(main_frame, text="설명").pack(anchor="w")
        self.desc_entry = ctk.CTkEntry(main_frame, width=500)
        self.desc_entry.pack(pady=(0, 15))

        # 기본 프롬프트
        ctk.CTkLabel(main_frame, text="기본 프롬프트 (외형 묘사)").pack(anchor="w")
        self.prompt_text = ctk.CTkTextbox(main_frame, width=500, height=80)
        self.prompt_text.pack(pady=(0, 15))

        # IP-Adapter 설정
        settings_frame = ctk.CTkFrame(main_frame)
        settings_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            settings_frame,
            text="🔧 IP-Adapter 설정",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 가중치
        weight_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        weight_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(weight_frame, text="가중치:").pack(side="left")
        self.weight_slider = ctk.CTkSlider(weight_frame, from_=0, to=1, number_of_steps=20, width=200)
        self.weight_slider.pack(side="left", padx=10)
        self.weight_label = ctk.CTkLabel(weight_frame, text="0.70")
        self.weight_label.pack(side="left")
        self.weight_slider.configure(command=lambda v: self.weight_label.configure(text=f"{v:.2f}"))

        # 얼굴만 참조 여부
        face_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        face_frame.pack(fill="x", padx=15, pady=(5, 15))

        ctk.CTkLabel(face_frame, text="참조 방식:").pack(side="left")
        self.face_only_var = ctk.StringVar(value="face")
        ctk.CTkRadioButton(
            face_frame,
            text="얼굴만",
            variable=self.face_only_var,
            value="face"
        ).pack(side="left", padx=(10, 5))
        ctk.CTkRadioButton(
            face_frame,
            text="전체 스타일",
            variable=self.face_only_var,
            value="full"
        ).pack(side="left", padx=5)

        # 참조 이미지 목록
        ref_frame = ctk.CTkFrame(main_frame)
        ref_frame.pack(fill="x", pady=(0, 15))

        ref_header = ctk.CTkFrame(ref_frame, fg_color="transparent")
        ref_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            ref_header,
            text="🖼️ 참조 이미지",
            font=ctk.CTkFont(weight="bold")
        ).pack(side="left")

        self.ref_count_label = ctk.CTkLabel(ref_header, text="", text_color="gray")
        self.ref_count_label.pack(side="right")

        # 이미지 목록 프레임
        self.ref_list_frame = ctk.CTkFrame(ref_frame, fg_color="transparent")
        self.ref_list_frame.pack(fill="x", padx=15, pady=(0, 15))

        # 통계
        stats_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 15))

        stats_text = f"📊 사용 횟수: {self.character.use_count}회 | 생성: {self.character.created_at[:10]}"
        ctk.CTkLabel(stats_frame, text=stats_text, text_color="gray").pack(anchor="w")

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="gray",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="저장",
            width=100,
            command=self._on_save
        ).pack(side="right")

    def _load_data(self):
        """데이터 로드"""
        self.name_entry.insert(0, self.character.name)
        self.desc_entry.insert(0, self.character.description)
        self.prompt_text.insert("1.0", self.character.base_prompt)
        self.weight_slider.set(self.character.ip_weight)
        self.weight_label.configure(text=f"{self.character.ip_weight:.2f}")
        self.face_only_var.set("face" if self.character.face_only else "full")

        # 참조 이미지 목록
        self._load_reference_images()

    def _load_reference_images(self):
        """참조 이미지 목록 로드"""
        # 기존 위젯 제거
        for widget in self.ref_list_frame.winfo_children():
            widget.destroy()

        ref_images = self.character.reference_images
        self.ref_count_label.configure(text=f"{len(ref_images)}개")

        if not ref_images:
            ctk.CTkLabel(
                self.ref_list_frame,
                text="참조 이미지가 없습니다.",
                text_color="gray"
            ).pack(pady=10)
            return

        for idx, filename in enumerate(ref_images):
            row = ctk.CTkFrame(self.ref_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # 주 이미지 표시
            is_primary = filename == self.character.primary_image
            prefix = "⭐ " if is_primary else "   "

            ctk.CTkLabel(row, text=f"{prefix}{filename}").pack(side="left")

            # 삭제 버튼
            ctk.CTkButton(
                row,
                text="❌",
                width=30,
                height=24,
                fg_color="transparent",
                hover_color="red",
                command=lambda f=filename: self._remove_reference(f)
            ).pack(side="right")

            # 주 이미지 설정 버튼
            if not is_primary:
                ctk.CTkButton(
                    row,
                    text="⭐",
                    width=30,
                    height=24,
                    fg_color="transparent",
                    hover_color="gold",
                    command=lambda f=filename: self._set_primary(f)
                ).pack(side="right")

    def _remove_reference(self, filename: str):
        """참조 이미지 제거"""
        result = messagebox.askyesno(
            "이미지 삭제",
            f"'{filename}'을(를) 삭제하시겠습니까?",
            parent=self
        )

        if result:
            self.manager.remove_reference_image(self.character.character_id, filename)
            # 캐릭터 데이터 새로고침
            self.character = self.manager.get_character(self.character.character_id)
            self._load_reference_images()

    def _set_primary(self, filename: str):
        """주 이미지 설정"""
        self.manager.update_character(self.character.character_id, primary_image=filename)
        # 캐릭터 데이터 새로고침
        self.character = self.manager.get_character(self.character.character_id)
        self._load_reference_images()

    def _on_save(self):
        """저장 버튼 클릭"""
        name = self.name_entry.get().strip()
        description = self.desc_entry.get().strip()
        base_prompt = self.prompt_text.get("1.0", "end").strip()
        ip_weight = self.weight_slider.get()
        face_only = self.face_only_var.get() == "face"

        if not name:
            messagebox.showerror("오류", "캐릭터 이름을 입력해주세요.", parent=self)
            return

        try:
            self.manager.update_character(
                self.character.character_id,
                name=name,
                description=description,
                base_prompt=base_prompt,
                ip_weight=ip_weight,
                face_only=face_only
            )

            messagebox.showinfo("성공", "캐릭터 정보가 저장되었습니다.", parent=self)
            self.destroy()

        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}", parent=self)
