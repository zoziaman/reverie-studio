# src/gui/utopia_dashboard.py
"""
v54.7: 유토피아 대시보드

실시간 모니터링 및 통계 대시보드

기능:
1. 실시간 시스템 상태 모니터링
2. 채널 성과 통계
3. 업로드 히스토리
4. 학습 데이터 시각화
5. 알림 및 경고

"유토피아 시스템의 관제탑"
"""
import customtkinter as ctk
from tkinter import messagebox
import threading
from typing import Optional
from datetime import datetime, timedelta


class UtopiaDashboard(ctk.CTkToplevel):
    """유토피아 대시보드 - 실시간 모니터링"""

    def __init__(self, parent, data_dir: str, channel_type: str = "daily_life_toon"):
        super().__init__(parent)

        self.data_dir = data_dir
        self.channel_type = channel_type

        # 서브시스템
        self.utopia_engine = None
        self.upload_scheduler = None
        self.feedback_loop = None
        self.prompt_optimizer = None

        self.title("📊 유토피아 대시보드")
        self.geometry("1100x750")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 1100) // 2
        y = (self.winfo_screenheight() - 750) // 2
        self.geometry(f"1100x750+{x}+{y}")

        # 자동 새로고침
        self._auto_refresh = True
        self._refresh_interval = 30000  # 30초

        self._init_systems()
        self._create_ui()
        self._start_auto_refresh()

    def _init_systems(self):
        """시스템 초기화"""
        try:
            from utils.utopia_engine import get_utopia_engine
            self.utopia_engine = get_utopia_engine(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"UtopiaEngine 초기화 실패: {e}")

        try:
            from utils.upload_scheduler import get_upload_scheduler
            self.upload_scheduler = get_upload_scheduler(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"UploadScheduler 초기화 실패: {e}")

        try:
            from utils.feedback_loop import get_feedback_loop
            self.feedback_loop = get_feedback_loop(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"FeedbackLoop 초기화 실패: {e}")

        try:
            from utils.prompt_optimizer import get_prompt_optimizer
            self.prompt_optimizer = get_prompt_optimizer(self.data_dir, self.channel_type)
        except Exception as e:
            print(f"PromptOptimizer 초기화 실패: {e}")

    def _create_ui(self):
        """UI 구성"""
        # 메인 프레임
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 헤더
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            header_frame,
            text="📊 유토피아 대시보드",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(side="left")

        # 자동 새로고침 토글
        self.auto_refresh_switch = ctk.CTkSwitch(
            header_frame,
            text="자동 새로고침",
            command=self._toggle_auto_refresh
        )
        self.auto_refresh_switch.select()
        self.auto_refresh_switch.pack(side="right", padx=(10, 0))

        # 새로고침 버튼
        ctk.CTkButton(
            header_frame,
            text="🔄 새로고침",
            command=self._refresh_all,
            width=100
        ).pack(side="right")

        # 마지막 업데이트 시간
        self.last_update_label = ctk.CTkLabel(
            header_frame,
            text="마지막 업데이트: -",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.last_update_label.pack(side="right", padx=20)

        # 콘텐츠 영역 (2열)
        content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True)

        # 왼쪽 열
        left_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # 오른쪽 열
        right_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))

        # === 왼쪽: 시스템 상태 ===
        self._build_system_status(left_frame)
        self._build_quick_stats(left_frame)
        self._build_recent_activity(left_frame)

        # === 오른쪽: 성과 및 인사이트 ===
        self._build_performance_summary(right_frame)
        self._build_learning_insights(right_frame)
        self._build_alerts(right_frame)

    # =========================================================
    # 왼쪽 패널
    # =========================================================

    def _build_system_status(self, parent):
        """시스템 상태 패널"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            frame,
            text="🔧 시스템 상태",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 상태 그리드
        status_grid = ctk.CTkFrame(frame, fg_color="transparent")
        status_grid.pack(fill="x", padx=15, pady=(0, 15))

        # 시스템 상태 카드들
        systems = [
            ("🌟 유토피아 엔진", "utopia"),
            ("📤 업로드 스케줄러", "upload"),
            ("🔄 피드백 루프", "feedback"),
            ("🎯 개인화 학습", "personalization"),
        ]

        self.status_labels = {}

        for i, (name, key) in enumerate(systems):
            card = ctk.CTkFrame(status_grid)
            card.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="ew")
            status_grid.grid_columnconfigure(i % 2, weight=1)

            ctk.CTkLabel(
                card,
                text=name,
                font=ctk.CTkFont(size=12)
            ).pack(anchor="w", padx=10, pady=(10, 5))

            self.status_labels[key] = ctk.CTkLabel(
                card,
                text="확인 중...",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray"
            )
            self.status_labels[key].pack(anchor="w", padx=10, pady=(0, 10))

    def _build_quick_stats(self, parent):
        """빠른 통계 패널"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            frame,
            text="📈 오늘의 통계",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 통계 그리드
        stats_grid = ctk.CTkFrame(frame, fg_color="transparent")
        stats_grid.pack(fill="x", padx=15, pady=(0, 15))

        stats = [
            ("🎬 생성", "generated"),
            ("📤 업로드", "uploaded"),
            ("👀 조회수", "views"),
            ("📊 평균 CTR", "avg_ctr"),
        ]

        self.stat_labels = {}

        for i, (name, key) in enumerate(stats):
            card = ctk.CTkFrame(stats_grid)
            card.grid(row=0, column=i, padx=5, pady=5, sticky="ew")
            stats_grid.grid_columnconfigure(i, weight=1)

            ctk.CTkLabel(
                card,
                text=name,
                font=ctk.CTkFont(size=11),
                text_color="gray"
            ).pack(pady=(10, 5))

            self.stat_labels[key] = ctk.CTkLabel(
                card,
                text="0",
                font=ctk.CTkFont(size=20, weight="bold")
            )
            self.stat_labels[key].pack(pady=(0, 10))

    def _build_recent_activity(self, parent):
        """최근 활동 패널"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header,
            text="📝 최근 활동",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")

        # 활동 로그
        self.activity_text = ctk.CTkTextbox(frame, height=200)
        self.activity_text.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    # =========================================================
    # 오른쪽 패널
    # =========================================================

    def _build_performance_summary(self, parent):
        """성과 요약 패널"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            frame,
            text="🏆 성과 요약 (최근 7일)",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 성과 텍스트
        self.performance_text = ctk.CTkTextbox(frame, height=150)
        self.performance_text.pack(fill="x", padx=15, pady=(0, 15))

    def _build_learning_insights(self, parent):
        """학습 인사이트 패널"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            frame,
            text="💡 학습된 인사이트",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 인사이트 내용
        self.insights_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.insights_frame.pack(fill="x", padx=15, pady=(0, 15))

        # 기본 레이블
        self.insights_label = ctk.CTkLabel(
            self.insights_frame,
            text="데이터 수집 중...",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            wraplength=450
        )
        self.insights_label.pack(anchor="w")

    def _build_alerts(self, parent):
        """알림 패널"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header,
            text="⚠️ 알림",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")

        # 알림 목록
        self.alerts_frame = ctk.CTkScrollableFrame(frame, height=150)
        self.alerts_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 기본 메시지
        self.no_alerts_label = ctk.CTkLabel(
            self.alerts_frame,
            text="✅ 현재 알림이 없습니다.",
            font=ctk.CTkFont(size=12),
            text_color="#22c55e"
        )
        self.no_alerts_label.pack(pady=20)

    # =========================================================
    # 데이터 로드
    # =========================================================

    def _refresh_all(self):
        """전체 새로고침 (v54.7.1: 에러 처리 강화)"""
        errors = []

        try:
            self._load_system_status()
        except Exception as e:
            errors.append(f"시스템 상태: {e}")

        try:
            self._load_quick_stats()
        except Exception as e:
            errors.append(f"통계: {e}")

        try:
            self._load_recent_activity()
        except Exception as e:
            errors.append(f"활동 로그: {e}")

        try:
            self._load_performance_summary()
        except Exception as e:
            errors.append(f"성과 요약: {e}")

        try:
            self._load_learning_insights()
        except Exception as e:
            errors.append(f"학습 인사이트: {e}")

        try:
            self._load_alerts()
        except Exception as e:
            errors.append(f"알림: {e}")

        # 에러가 있으면 알림에 표시
        if errors:
            self._show_load_errors(errors)

        self.last_update_label.configure(
            text=f"마지막 업데이트: {datetime.now().strftime('%H:%M:%S')}"
        )

    def _show_load_errors(self, errors: list):
        """데이터 로드 에러 표시"""
        # 기존 알림에 에러 추가
        for error in errors[:3]:  # 최대 3개
            error_frame = ctk.CTkFrame(self.alerts_frame, fg_color="gray20")
            error_frame.pack(fill="x", pady=3)

            ctk.CTkLabel(
                error_frame,
                text=f"⚠️ 로드 실패: {error}",
                font=ctk.CTkFont(size=11),
                text_color="#ef4444",
                wraplength=400
            ).pack(anchor="w", padx=10, pady=8)

    def _load_system_status(self):
        """시스템 상태 로드"""
        # 유토피아 엔진
        if self.utopia_engine:
            if self.utopia_engine.is_running():
                self.status_labels["utopia"].configure(text="✅ 실행 중", text_color="#22c55e")
            else:
                self.status_labels["utopia"].configure(text="⏸️ 중지됨", text_color="gray")
        else:
            self.status_labels["utopia"].configure(text="❌ 미설정", text_color="#ef4444")

        # 업로드 스케줄러
        if self.upload_scheduler:
            if self.upload_scheduler.is_scheduler_running():
                pending = self.upload_scheduler.get_pending_count()
                self.status_labels["upload"].configure(
                    text=f"✅ 실행 중 ({pending}개 대기)",
                    text_color="#22c55e"
                )
            else:
                self.status_labels["upload"].configure(text="⏸️ 중지됨", text_color="gray")
        else:
            self.status_labels["upload"].configure(text="❌ 미설정", text_color="#ef4444")

        # 피드백 루프
        if self.feedback_loop:
            if self.feedback_loop.is_scheduler_running():
                status = self.feedback_loop.get_status()
                tracking = status.get("active_tracking", 0)
                self.status_labels["feedback"].configure(
                    text=f"✅ 추적 중 ({tracking}개)",
                    text_color="#22c55e"
                )
            else:
                self.status_labels["feedback"].configure(text="⏸️ 중지됨", text_color="gray")
        else:
            self.status_labels["feedback"].configure(text="❌ 미설정", text_color="#ef4444")

        # 개인화
        if self.prompt_optimizer:
            status = self.prompt_optimizer.get_learning_status()
            if status.get("has_enough_data"):
                self.status_labels["personalization"].configure(
                    text=f"✅ 학습 완료 ({status.get('total_videos_analyzed', 0)}개)",
                    text_color="#22c55e"
                )
            else:
                self.status_labels["personalization"].configure(
                    text=f"📊 학습 중 ({status.get('total_videos_analyzed', 0)}/10)",
                    text_color="#eab308"
                )
        else:
            self.status_labels["personalization"].configure(text="❌ 미설정", text_color="#ef4444")

    def _load_quick_stats(self):
        """빠른 통계 로드"""
        today_generated = 0
        today_uploaded = 0
        total_views = 0
        avg_ctr = 0

        # 유토피아 엔진에서 오늘 통계
        if self.utopia_engine:
            status = self.utopia_engine.get_status()
            today_generated = status.get("today_generated", 0)
            today_uploaded = status.get("today_uploaded", 0)

        # 피드백 루프에서 성과 데이터
        if self.feedback_loop:
            report = self.feedback_loop.generate_report(days=1)
            avg_ctr = report.get("average_ctr", 0)

        self.stat_labels["generated"].configure(text=str(today_generated))
        self.stat_labels["uploaded"].configure(text=str(today_uploaded))
        self.stat_labels["views"].configure(text="-")  # YouTube API 필요
        self.stat_labels["avg_ctr"].configure(text=f"{avg_ctr:.1f}%")

    def _load_recent_activity(self):
        """최근 활동 로드"""
        self.activity_text.configure(state="normal")
        self.activity_text.delete("1.0", "end")

        logs = []

        # 유토피아 엔진 로그
        if self.utopia_engine:
            logs.extend(self.utopia_engine.get_recent_logs(20))

        # 시간순 정렬
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        if not logs:
            self.activity_text.insert("end", "최근 활동이 없습니다.")
        else:
            for log in logs[:15]:
                timestamp = log.get("timestamp", "")[:19]
                level = log.get("level", "info")
                message = log.get("message", "")

                level_icons = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
                icon = level_icons.get(level, "ℹ️")

                self.activity_text.insert("end", f"[{timestamp}] {icon} {message}\n")

        self.activity_text.configure(state="disabled")

    def _load_performance_summary(self):
        """성과 요약 로드"""
        self.performance_text.configure(state="normal")
        self.performance_text.delete("1.0", "end")

        if self.feedback_loop:
            report_text = self.feedback_loop.get_report_text(days=7)
            self.performance_text.insert("end", report_text)
        else:
            self.performance_text.insert("end", "피드백 루프가 초기화되지 않았습니다.")

        self.performance_text.configure(state="disabled")

    def _load_learning_insights(self):
        """학습 인사이트 로드"""
        insights_text = ""

        if self.prompt_optimizer:
            status = self.prompt_optimizer.get_learning_status()

            if status.get("has_enough_data"):
                # 최적 업로드 시간
                upload_rec = self.prompt_optimizer.get_optimal_upload_time()
                if upload_rec.get("confidence", 0) > 0.5:
                    day_names = ["월", "화", "수", "목", "금", "토", "일"]
                    insights_text += f"⏰ 최적 업로드 시간: {day_names[upload_rec['recommended_day']]}요일 {upload_rec['recommended_hour']}시\n\n"

                # 추천 요약
                summary = self.prompt_optimizer.get_recommendations_summary()
                if summary:
                    insights_text += summary[:300]
            else:
                insights_text = f"📊 데이터 수집 중... ({status.get('total_videos_analyzed', 0)}/10개 영상 분석됨)\n\n"
                insights_text += "더 많은 영상을 업로드하면 개인화된 인사이트를 제공합니다."

        if self.feedback_loop:
            learnings = self.feedback_loop.get_learnings_summary()

            if learnings.get("top_keywords"):
                insights_text += "\n\n🔑 고성과 키워드:\n"
                for kw, ctr in learnings["top_keywords"][:5]:
                    insights_text += f"  • {kw} (CTR {ctr:.1f}%)\n"

        if not insights_text:
            insights_text = "아직 충분한 학습 데이터가 없습니다."

        self.insights_label.configure(text=insights_text)

    def _load_alerts(self):
        """알림 로드"""
        # 기존 알림 삭제
        for widget in self.alerts_frame.winfo_children():
            widget.destroy()

        alerts = []

        # 저성과 영상 확인
        if self.feedback_loop:
            videos = self.feedback_loop.get_tracked_videos()
            for video in videos:
                grade = video.get("current_grade")
                if grade in ["poor", "below"]:
                    alerts.append({
                        "type": "warning",
                        "message": f"⚠️ 저성과: '{video.get('title', '')[:20]}...' - 썸네일 교체 권장",
                    })

        # 업로드 대기열 확인
        if self.upload_scheduler:
            status = self.upload_scheduler.get_status()
            if status.get("failed", 0) > 0:
                alerts.append({
                    "type": "error",
                    "message": f"❌ 업로드 실패: {status['failed']}개 영상",
                })

        # 알림 표시
        if not alerts:
            ctk.CTkLabel(
                self.alerts_frame,
                text="✅ 현재 알림이 없습니다.",
                font=ctk.CTkFont(size=12),
                text_color="#22c55e"
            ).pack(pady=20)
        else:
            for alert in alerts[:10]:
                alert_type = alert.get("type", "info")
                colors = {"error": "#ef4444", "warning": "#eab308", "info": "#3b82f6"}

                alert_frame = ctk.CTkFrame(self.alerts_frame, fg_color="gray20")
                alert_frame.pack(fill="x", pady=3)

                ctk.CTkLabel(
                    alert_frame,
                    text=alert.get("message", ""),
                    font=ctk.CTkFont(size=11),
                    text_color=colors.get(alert_type, "gray"),
                    wraplength=400
                ).pack(anchor="w", padx=10, pady=8)

    # =========================================================
    # 자동 새로고침
    # =========================================================

    def _toggle_auto_refresh(self):
        """자동 새로고침 토글"""
        self._auto_refresh = self.auto_refresh_switch.get()

    def _start_auto_refresh(self):
        """자동 새로고침 시작"""
        self._refresh_all()
        self._schedule_refresh()

    def _schedule_refresh(self):
        """다음 새로고침 예약"""
        if self._auto_refresh:
            self._refresh_all()
        self.after(self._refresh_interval, self._schedule_refresh)

    def destroy(self):
        """창 닫기"""
        self._auto_refresh = False
        super().destroy()


def open_utopia_dashboard(parent, data_dir: str, channel_type: str = "daily_life_toon"):
    """유토피아 대시보드 열기"""
    dashboard = UtopiaDashboard(parent, data_dir, channel_type)
    dashboard.grab_set()
    return dashboard
