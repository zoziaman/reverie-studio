# src/gui/youtube_analytics_dialog.py
"""
YouTube 분석 다이얼로그 (v54 Enhanced)
- 기존: 조회수, 좋아요, 댓글
- [v54 신규] 시청 지속률 분석
- [v54 신규] 트래픽 소스 분석
- [v54 신규] Gemini AI 심층 분석
- [v54 신규] 자동 개선 제안
"""
import customtkinter as ctk
from tkinter import messagebox
import threading
import json
from typing import Optional
from datetime import datetime


class YouTubeAnalyticsDialog(ctk.CTkToplevel):
    """YouTube 분석 다이얼로그"""

    def __init__(self, parent, analytics_manager):
        super().__init__(parent)

        self.analytics = analytics_manager

        self.title("📊 YouTube 분석")
        self.geometry("800x650")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 800) // 2
        y = (self.winfo_screenheight() - 650) // 2
        self.geometry(f"800x650+{x}+{y}")

        self._create_ui()

        # 데이터 로드
        self._load_data()

    def _create_ui(self):
        """UI 구성"""
        # 메인 스크롤 프레임
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        title_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            title_frame,
            text="📊 YouTube 채널 분석",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            title_frame,
            text="🔄 새로고침",
            command=self._load_data,
            width=100
        ).pack(side="right")

        # 로딩 표시
        self.loading_label = ctk.CTkLabel(
            main_frame,
            text="⏳ 데이터를 불러오는 중...",
            font=ctk.CTkFont(size=14),
            text_color="gray"
        )
        self.loading_label.pack(pady=20)

        # 채널 정보 프레임
        self.channel_frame = ctk.CTkFrame(main_frame)
        self.channel_frame.pack(fill="x", pady=(0, 15))
        self.channel_frame.pack_forget()  # 초기에 숨김

        # 최근 영상 프레임
        self.videos_frame = ctk.CTkFrame(main_frame)
        self.videos_frame.pack(fill="x", pady=(0, 15))
        self.videos_frame.pack_forget()  # 초기에 숨김

        # 성과 요약 프레임
        self.summary_frame = ctk.CTkFrame(main_frame)
        self.summary_frame.pack(fill="x", pady=(0, 15))
        self.summary_frame.pack_forget()  # 초기에 숨김

        # 닫기 버튼
        ctk.CTkButton(
            main_frame,
            text="닫기",
            command=self.destroy,
            width=100
        ).pack(pady=10)

    def _load_data(self):
        """데이터 로드"""
        if not self.analytics.is_authenticated():
            self.loading_label.configure(
                text="❌ YouTube 인증이 필요합니다.\n시스템 탭에서 YouTube 인증을 완료해주세요.",
                text_color="red"
            )
            return

        self.loading_label.configure(text="⏳ 데이터를 불러오는 중...", text_color="gray")

        # 백그라운드에서 로드
        threading.Thread(target=self._load_data_worker, daemon=True).start()

    def _load_data_worker(self):
        """데이터 로드 워커"""
        try:
            # 채널 정보
            channel_stats = self.analytics.get_channel_stats()

            # 최근 영상
            recent_videos = self.analytics.get_recent_videos(10)

            # UI 업데이트 (메인 스레드에서)
            self.after(0, lambda: self._update_ui(channel_stats, recent_videos))

        except Exception as e:
            self.after(0, lambda: self.loading_label.configure(
                text=f"❌ 데이터 로드 실패: {str(e)}",
                text_color="red"
            ))

    def _update_ui(self, channel_stats: Optional[dict], recent_videos: list):
        """UI 업데이트"""
        self.loading_label.pack_forget()

        if not channel_stats:
            self.loading_label.configure(
                text="❌ 채널 정보를 가져올 수 없습니다.",
                text_color="red"
            )
            self.loading_label.pack()
            return

        # === 채널 정보 표시 ===
        self.channel_frame.pack(fill="x", pady=(0, 15))

        # 기존 위젯 삭제
        for widget in self.channel_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self.channel_frame,
            text="📺 채널 정보",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        info_frame = ctk.CTkFrame(self.channel_frame, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(0, 15))

        # 채널명
        ctk.CTkLabel(
            info_frame,
            text=f"📌 채널명: {channel_stats['title']}",
            font=ctk.CTkFont(size=14)
        ).pack(anchor="w", pady=2)

        # 구독자
        subs = self.analytics.format_number(channel_stats['subscriber_count'])
        ctk.CTkLabel(
            info_frame,
            text=f"👥 구독자: {subs}명",
            font=ctk.CTkFont(size=14)
        ).pack(anchor="w", pady=2)

        # 총 조회수
        views = self.analytics.format_number(channel_stats['view_count'])
        ctk.CTkLabel(
            info_frame,
            text=f"👁️ 총 조회수: {views}회",
            font=ctk.CTkFont(size=14)
        ).pack(anchor="w", pady=2)

        # 영상 수
        ctk.CTkLabel(
            info_frame,
            text=f"🎬 영상 수: {channel_stats['video_count']}개",
            font=ctk.CTkFont(size=14)
        ).pack(anchor="w", pady=2)

        # === 최근 영상 표시 ===
        if recent_videos:
            self.videos_frame.pack(fill="x", pady=(0, 15))

            for widget in self.videos_frame.winfo_children():
                widget.destroy()

            ctk.CTkLabel(
                self.videos_frame,
                text="🕐 최근 업로드 영상",
                font=ctk.CTkFont(size=16, weight="bold")
            ).pack(anchor="w", padx=15, pady=(15, 10))

            for video in recent_videos[:10]:
                self._create_video_row(video)

            # 성과 요약
            if len(recent_videos) >= 3:
                self._show_performance_summary(recent_videos)

    def _create_video_row(self, video: dict):
        """영상 행 생성"""
        row = ctk.CTkFrame(self.videos_frame, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=3)

        # 제목
        title = video.get('title', '')[:40]
        if len(video.get('title', '')) > 40:
            title += "..."

        ctk.CTkLabel(
            row,
            text=title,
            font=ctk.CTkFont(size=12),
            anchor="w",
            width=280
        ).pack(side="left")

        # 조회수
        views = self.analytics.format_number(video.get('view_count', 0))
        ctk.CTkLabel(
            row,
            text=f"👁️ {views}",
            font=ctk.CTkFont(size=11),
            width=80
        ).pack(side="left")

        # 좋아요
        likes = self.analytics.format_number(video.get('like_count', 0))
        ctk.CTkLabel(
            row,
            text=f"❤️ {likes}",
            font=ctk.CTkFont(size=11),
            width=70
        ).pack(side="left")

        # 댓글
        comments = video.get('comment_count', 0)
        ctk.CTkLabel(
            row,
            text=f"💬 {comments}",
            font=ctk.CTkFont(size=11),
            width=60
        ).pack(side="left")

        # 길이
        duration = self.analytics.format_duration(video.get('duration', 'PT0S'))
        ctk.CTkLabel(
            row,
            text=f"⏱️ {duration}",
            font=ctk.CTkFont(size=11),
            width=70
        ).pack(side="left")

    def _show_performance_summary(self, videos: list):
        """성과 요약 표시"""
        self.summary_frame.pack(fill="x", pady=(0, 15))

        for widget in self.summary_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self.summary_frame,
            text="📈 최근 영상 성과 요약",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 총계 계산
        total_views = sum(v.get('view_count', 0) for v in videos)
        total_likes = sum(v.get('like_count', 0) for v in videos)
        avg_views = total_views / len(videos) if videos else 0

        engagement = (total_likes / total_views * 100) if total_views > 0 else 0

        summary_info = ctk.CTkFrame(self.summary_frame, fg_color="transparent")
        summary_info.pack(fill="x", padx=15, pady=(0, 15))

        ctk.CTkLabel(
            summary_info,
            text=f"📊 최근 {len(videos)}개 영상 기준",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(anchor="w")

        ctk.CTkLabel(
            summary_info,
            text=f"👁️ 총 조회수: {self.analytics.format_number(total_views)}회",
            font=ctk.CTkFont(size=13)
        ).pack(anchor="w", pady=2)

        ctk.CTkLabel(
            summary_info,
            text=f"📈 평균 조회수: {self.analytics.format_number(int(avg_views))}회/영상",
            font=ctk.CTkFont(size=13)
        ).pack(anchor="w", pady=2)

        ctk.CTkLabel(
            summary_info,
            text=f"💕 참여율: {engagement:.2f}% (좋아요/조회수)",
            font=ctk.CTkFont(size=13)
        ).pack(anchor="w", pady=2)

        # v54: AI 심층 분석 버튼
        ai_btn_frame = ctk.CTkFrame(self.summary_frame, fg_color="transparent")
        ai_btn_frame.pack(fill="x", padx=15, pady=(10, 15))

        ctk.CTkButton(
            ai_btn_frame,
            text="🤖 AI 심층 분석",
            command=lambda: self._run_ai_analysis(videos),
            width=150,
            fg_color="#9333ea",
            hover_color="#7c3aed"
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            ai_btn_frame,
            text="📊 상세 리포트",
            command=lambda: self._show_detailed_report(videos),
            width=150
        ).pack(side="left")

    # =========================================================
    # v54: AI 심층 분석
    # =========================================================

    def _run_ai_analysis(self, videos: list):
        """v54: Gemini AI 심층 분석 실행"""
        # 분석 중 표시
        self.loading_label.configure(text="🤖 AI가 채널을 분석 중...", text_color="#9333ea")
        self.loading_label.pack()

        def worker():
            try:
                # 종합 리포트 생성
                video_ids = [v['video_id'] for v in videos]
                report = self.analytics.get_comprehensive_report(video_ids=video_ids, days=28)

                # Gemini 분석
                ai_analysis = self.analytics.analyze_with_gemini(report)

                # UI 업데이트
                self.after(0, lambda: self._show_ai_analysis_result(ai_analysis, report))

            except Exception as e:
                self.after(0, lambda: self._show_error(f"AI 분석 실패: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_ai_analysis_result(self, ai_analysis: str, report: dict):
        """AI 분석 결과 표시"""
        self.loading_label.pack_forget()

        # 새 창으로 표시
        result_window = ctk.CTkToplevel(self)
        result_window.title("🤖 AI 채널 분석 결과")
        result_window.geometry("900x700")
        result_window.transient(self)

        # 중앙 배치
        result_window.update_idletasks()
        x = (result_window.winfo_screenwidth() - 900) // 2
        y = (result_window.winfo_screenheight() - 700) // 2
        result_window.geometry(f"900x700+{x}+{y}")

        # 스크롤 가능한 텍스트 영역
        main_frame = ctk.CTkScrollableFrame(result_window)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="🤖 AI 채널 분석 리포트",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            main_frame,
            text=f"분석 기간: {report.get('period', {}).get('start', '')} ~ {report.get('period', {}).get('end', '')}",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(anchor="w", pady=(0, 15))

        # 자동 인사이트
        if report.get('insights'):
            insights_frame = ctk.CTkFrame(main_frame)
            insights_frame.pack(fill="x", pady=(0, 15))

            ctk.CTkLabel(
                insights_frame,
                text="⚡ 자동 감지된 문제점",
                font=ctk.CTkFont(size=14, weight="bold")
            ).pack(anchor="w", padx=15, pady=(15, 10))

            for insight in report.get('insights', []):
                ctk.CTkLabel(
                    insights_frame,
                    text=insight,
                    font=ctk.CTkFont(size=12),
                    wraplength=800,
                    justify="left"
                ).pack(anchor="w", padx=15, pady=2)

            ctk.CTkLabel(insights_frame, text="").pack(pady=5)  # 여백

        # AI 분석 결과
        if ai_analysis:
            ai_frame = ctk.CTkFrame(main_frame)
            ai_frame.pack(fill="x", pady=(0, 15))

            ctk.CTkLabel(
                ai_frame,
                text="🧠 Gemini AI 심층 분석",
                font=ctk.CTkFont(size=14, weight="bold")
            ).pack(anchor="w", padx=15, pady=(15, 10))

            # 분석 내용 (텍스트박스)
            analysis_text = ctk.CTkTextbox(ai_frame, height=350, wrap="word")
            analysis_text.pack(fill="x", padx=15, pady=(0, 15))
            analysis_text.insert("1.0", ai_analysis)
            analysis_text.configure(state="disabled")
        else:
            ctk.CTkLabel(
                main_frame,
                text="❌ AI 분석 결과를 가져오지 못했습니다.",
                text_color="red"
            ).pack(pady=10)

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)

        ctk.CTkButton(
            btn_frame,
            text="📄 리포트 저장",
            command=lambda: self._save_report(report, ai_analysis),
            width=120
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_frame,
            text="닫기",
            command=result_window.destroy,
            width=100
        ).pack(side="right")

    def _save_report(self, report: dict, ai_analysis: str = None):
        """리포트 저장"""
        try:
            if ai_analysis:
                report['ai_analysis'] = ai_analysis

            filepath = self.analytics.save_report(report)
            messagebox.showinfo("저장 완료", f"리포트가 저장되었습니다.\n{filepath}")
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))

    # =========================================================
    # v54: 상세 리포트
    # =========================================================

    def _show_detailed_report(self, videos: list):
        """v54: 상세 성과 리포트"""
        self.loading_label.configure(text="📊 상세 데이터 수집 중...", text_color="gray")
        self.loading_label.pack()

        def worker():
            try:
                video_ids = [v['video_id'] for v in videos]
                report = self.analytics.get_comprehensive_report(video_ids=video_ids, days=28)
                self.after(0, lambda: self._show_detailed_report_window(report))
            except Exception as e:
                self.after(0, lambda: self._show_error(f"리포트 생성 실패: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_detailed_report_window(self, report: dict):
        """상세 리포트 창"""
        self.loading_label.pack_forget()

        # 새 창
        detail_window = ctk.CTkToplevel(self)
        detail_window.title("📊 상세 성과 리포트")
        detail_window.geometry("950x750")
        detail_window.transient(self)

        # 중앙 배치
        detail_window.update_idletasks()
        x = (detail_window.winfo_screenwidth() - 950) // 2
        y = (detail_window.winfo_screenheight() - 750) // 2
        detail_window.geometry(f"950x750+{x}+{y}")

        # 탭뷰
        tabview = ctk.CTkTabview(detail_window)
        tabview.pack(fill="both", expand=True, padx=20, pady=20)

        # 탭 추가
        tab_overview = tabview.add("📈 개요")
        tab_videos = tabview.add("🎬 영상별 성과")
        tab_traffic = tabview.add("🚦 트래픽 소스")
        tab_insights = tabview.add("💡 인사이트")

        # === 개요 탭 ===
        self._build_overview_tab(tab_overview, report)

        # === 영상별 성과 탭 ===
        self._build_videos_tab(tab_videos, report)

        # === 트래픽 소스 탭 ===
        self._build_traffic_tab(tab_traffic, report)

        # === 인사이트 탭 ===
        self._build_insights_tab(tab_insights, report)

    def _build_overview_tab(self, parent, report: dict):
        """개요 탭 구성"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True)

        channel = report.get('channel_stats', {})
        period = report.get('period', {})

        ctk.CTkLabel(
            frame,
            text=f"📺 {channel.get('title', '채널')} 성과 리포트",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=(10, 5))

        ctk.CTkLabel(
            frame,
            text=f"기간: {period.get('start', '')} ~ {period.get('end', '')} ({period.get('days', 28)}일)",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(anchor="w", pady=(0, 20))

        # 주요 지표 카드
        metrics_frame = ctk.CTkFrame(frame)
        metrics_frame.pack(fill="x", pady=10)

        # 구독자
        self._create_metric_card(metrics_frame, "👥", "구독자",
                                  self.analytics.format_number(channel.get('subscriber_count', 0)))

        # 총 조회수
        self._create_metric_card(metrics_frame, "👁️", "총 조회수",
                                  self.analytics.format_number(channel.get('view_count', 0)))

        # 분석 영상 수
        self._create_metric_card(metrics_frame, "🎬", "분석 영상",
                                  f"{report.get('video_count', 0)}개")

        # Top 3
        top_frame = ctk.CTkFrame(frame)
        top_frame.pack(fill="x", pady=15)

        ctk.CTkLabel(
            top_frame,
            text="🏆 성과 TOP 3",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        for i, video in enumerate(report.get('top_performers', []), 1):
            ctk.CTkLabel(
                top_frame,
                text=f"{i}. {video.get('title', '')[:50]} - 조회수 {video.get('views', 0):,}",
                font=ctk.CTkFont(size=12)
            ).pack(anchor="w", padx=15, pady=2)

        ctk.CTkLabel(top_frame, text="").pack(pady=5)

    def _create_metric_card(self, parent, icon: str, label: str, value: str):
        """지표 카드 생성"""
        card = ctk.CTkFrame(parent, width=150)
        card.pack(side="left", padx=10, pady=10)
        card.pack_propagate(False)

        ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=28)).pack(pady=(15, 5))
        ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=11), text_color="gray").pack()
        ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(5, 15))

    def _build_videos_tab(self, parent, report: dict):
        """영상별 성과 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True)

        # 헤더
        header = ctk.CTkFrame(frame, fg_color="gray25")
        header.pack(fill="x", pady=(0, 5))

        headers = [("제목", 250), ("조회수", 80), ("시청률", 80), ("시청시간", 80), ("상태", 100)]
        for text, width in headers:
            ctk.CTkLabel(header, text=text, font=ctk.CTkFont(size=11, weight="bold"), width=width).pack(side="left", padx=5, pady=8)

        # 데이터
        for video in report.get('video_performances', []):
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # 제목
            title = video.get('title', '')[:35]
            if len(video.get('title', '')) > 35:
                title += "..."
            ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=11), width=250, anchor="w").pack(side="left", padx=5)

            # 조회수
            views = self.analytics.format_number(video.get('views', 0))
            ctk.CTkLabel(row, text=views, font=ctk.CTkFont(size=11), width=80).pack(side="left", padx=5)

            # 시청률
            retention = video.get('avg_view_percentage', 0)
            retention_color = "#22c55e" if retention >= 50 else "#eab308" if retention >= 30 else "#ef4444"
            ctk.CTkLabel(row, text=f"{retention:.1f}%", font=ctk.CTkFont(size=11), width=80, text_color=retention_color).pack(side="left", padx=5)

            # 평균 시청시간
            duration = video.get('avg_view_duration', 0)
            ctk.CTkLabel(row, text=f"{int(duration)}초", font=ctk.CTkFont(size=11), width=80).pack(side="left", padx=5)

            # 상태
            status = "⚠️ 초반이탈" if video.get('early_drop_warning') else "✅ 양호"
            ctk.CTkLabel(row, text=status, font=ctk.CTkFont(size=11), width=100).pack(side="left", padx=5)

    def _build_traffic_tab(self, parent, report: dict):
        """트래픽 소스 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="🚦 트래픽 소스 분석",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(10, 15))

        traffic_sources = report.get('traffic_sources', [])

        if not traffic_sources:
            ctk.CTkLabel(frame, text="트래픽 데이터가 없습니다.", text_color="gray").pack(pady=20)
            return

        # 트래픽 소스별 표시
        source_names = {
            'SUGGESTED': '🎯 추천 영상',
            'SEARCH': '🔍 검색',
            'BROWSE': '🏠 홈/구독',
            'EXT_URL': '🔗 외부 링크',
            'NOTIFICATION': '🔔 알림',
            'PLAYLIST': '📋 재생목록',
            'OTHER': '📦 기타'
        }

        for source in traffic_sources:
            source_frame = ctk.CTkFrame(frame)
            source_frame.pack(fill="x", pady=5)

            source_name = source_names.get(source['source'], source['source'])
            percentage = source.get('percentage', 0)

            # 라벨
            ctk.CTkLabel(
                source_frame,
                text=source_name,
                font=ctk.CTkFont(size=12),
                width=150
            ).pack(side="left", padx=15, pady=10)

            # 프로그레스 바
            progress = ctk.CTkProgressBar(source_frame, width=300)
            progress.pack(side="left", padx=10)
            progress.set(percentage / 100)

            # 퍼센트
            ctk.CTkLabel(
                source_frame,
                text=f"{percentage}%",
                font=ctk.CTkFont(size=12, weight="bold"),
                width=60
            ).pack(side="left")

            # 조회수
            views = self.analytics.format_number(source.get('views', 0))
            ctk.CTkLabel(
                source_frame,
                text=f"({views}회)",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            ).pack(side="left", padx=10)

    def _build_insights_tab(self, parent, report: dict):
        """인사이트 탭"""
        frame = ctk.CTkScrollableFrame(parent)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="💡 자동 분석 인사이트",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(10, 15))

        insights = report.get('insights', [])

        if not insights:
            ctk.CTkLabel(frame, text="인사이트가 없습니다.", text_color="gray").pack(pady=20)
            return

        for insight in insights:
            insight_frame = ctk.CTkFrame(frame)
            insight_frame.pack(fill="x", pady=5)

            ctk.CTkLabel(
                insight_frame,
                text=insight,
                font=ctk.CTkFont(size=13),
                wraplength=700,
                justify="left"
            ).pack(anchor="w", padx=15, pady=12)

        # AI 분석 버튼
        ctk.CTkButton(
            frame,
            text="🤖 더 자세한 AI 분석 받기",
            command=lambda: self._run_ai_analysis(report.get('video_performances', [])),
            fg_color="#9333ea",
            hover_color="#7c3aed"
        ).pack(pady=20)

    def _show_error(self, message: str):
        """에러 표시"""
        self.loading_label.configure(text=f"❌ {message}", text_color="red")
        self.loading_label.pack()
