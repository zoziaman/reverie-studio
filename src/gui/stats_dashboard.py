# src/gui/stats_dashboard.py
"""
v37 - 생산 통계 대시보드 (차트 시각화 포함)

기능:
1. 통계 요약 카드
2. 수익 그래프 (CTkinter Canvas 기반)
3. 채널별 성과 차트
4. 일별 트렌드 시각화
5. AI 자율주행 모드 상태 표시
"""
import customtkinter as ctk
from tkinter import Canvas
from typing import Dict, Any, List
import math
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 폰트 설정
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    """통일된 폰트 반환"""
    sizes = {"small": 11, "normal": 13, "medium": 14, "large": 16, "title": 20, "header": 28}
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


class SimpleBarChart(ctk.CTkFrame):
    """간단한 막대 차트 (CTkinter Canvas 기반)"""

    def __init__(self, parent, data: List[Dict], title: str = "", width: int = 400, height: int = 200, **kwargs):
        super().__init__(parent, **kwargs)

        self.data = data
        self.chart_width = width
        self.chart_height = height

        # 제목
        if title:
            ctk.CTkLabel(self, text=title, font=get_font("medium", bold=True)).pack(pady=(5, 10))

        # 캔버스
        self.canvas = Canvas(
            self,
            width=width,
            height=height,
            bg="#2B2B2B",
            highlightthickness=0
        )
        self.canvas.pack(padx=10, pady=5)

        self._draw_chart()

    def _draw_chart(self):
        """차트 그리기"""
        if not self.data:
            self.canvas.create_text(
                self.chart_width // 2, self.chart_height // 2,
                text="데이터 없음", fill="#888888", font=(FONT_FAMILY, 12)
            )
            return

        # 여백
        margin_left = 50
        margin_right = 20
        margin_top = 20
        margin_bottom = 40

        chart_w = self.chart_width - margin_left - margin_right
        chart_h = self.chart_height - margin_top - margin_bottom

        # 최대값 계산
        max_val = max((d.get('value', 0) for d in self.data), default=1)
        if max_val == 0:
            max_val = 1

        # 막대 그리기
        bar_count = len(self.data)
        bar_width = max(chart_w // bar_count - 10, 20)
        gap = (chart_w - bar_width * bar_count) // (bar_count + 1)

        colors = ["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4", "#8BC34A"]

        for i, item in enumerate(self.data):
            value = item.get('value', 0)
            label = item.get('label', '')
            color = item.get('color', colors[i % len(colors)])

            bar_height = int((value / max_val) * chart_h)
            x1 = margin_left + gap + i * (bar_width + gap)
            y1 = margin_top + chart_h - bar_height
            x2 = x1 + bar_width
            y2 = margin_top + chart_h

            # 막대
            self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="")

            # 값 표시
            self.canvas.create_text(
                (x1 + x2) // 2, y1 - 10,
                text=str(value), fill="white", font=(FONT_FAMILY, 10)
            )

            # 라벨
            self.canvas.create_text(
                (x1 + x2) // 2, y2 + 15,
                text=label[:6], fill="#AAAAAA", font=(FONT_FAMILY, 9)
            )

        # Y축 눈금
        for i in range(5):
            y = margin_top + int(chart_h * i / 4)
            val = int(max_val * (4 - i) / 4)
            self.canvas.create_text(
                margin_left - 10, y,
                text=str(val), fill="#888888", font=(FONT_FAMILY, 9), anchor="e"
            )
            self.canvas.create_line(margin_left, y, margin_left + chart_w, y, fill="#444444", dash=(2, 2))


class SimpleLineChart(ctk.CTkFrame):
    """간단한 라인 차트"""

    def __init__(self, parent, data: List[Dict], title: str = "", width: int = 500, height: int = 200, **kwargs):
        super().__init__(parent, **kwargs)

        self.data = data
        self.chart_width = width
        self.chart_height = height

        # 제목
        if title:
            ctk.CTkLabel(self, text=title, font=get_font("medium", bold=True)).pack(pady=(5, 10))

        # 캔버스
        self.canvas = Canvas(
            self,
            width=width,
            height=height,
            bg="#2B2B2B",
            highlightthickness=0
        )
        self.canvas.pack(padx=10, pady=5)

        self._draw_chart()

    def _draw_chart(self):
        """차트 그리기"""
        if not self.data or len(self.data) < 2:
            self.canvas.create_text(
                self.chart_width // 2, self.chart_height // 2,
                text="데이터 부족", fill="#888888", font=(FONT_FAMILY, 12)
            )
            return

        # 여백
        margin_left = 50
        margin_right = 20
        margin_top = 20
        margin_bottom = 40

        chart_w = self.chart_width - margin_left - margin_right
        chart_h = self.chart_height - margin_top - margin_bottom

        # 최대값 계산
        max_val = max((d.get('value', 0) for d in self.data), default=1)
        if max_val == 0:
            max_val = 1

        # 포인트 계산
        points = []
        step = chart_w / (len(self.data) - 1) if len(self.data) > 1 else chart_w

        for i, item in enumerate(self.data):
            value = item.get('value', 0)
            x = margin_left + i * step
            y = margin_top + chart_h - (value / max_val * chart_h)
            points.append((x, y))

        # 영역 채우기 (그라데이션 효과)
        if len(points) > 1:
            fill_points = points + [(points[-1][0], margin_top + chart_h), (points[0][0], margin_top + chart_h)]
            # Tkinter Canvas는 8자리 색상 미지원 - 반투명 효과 대신 연한 색상 사용
            self.canvas.create_polygon(fill_points, fill="#A5D6A7", outline="")

        # 선 그리기
        for i in range(len(points) - 1):
            self.canvas.create_line(
                points[i][0], points[i][1],
                points[i + 1][0], points[i + 1][1],
                fill="#4CAF50", width=2
            )

        # 포인트 그리기
        for i, (x, y) in enumerate(points):
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#4CAF50", outline="white")

            # 라벨
            label = self.data[i].get('label', '')[:5]
            self.canvas.create_text(
                x, margin_top + chart_h + 15,
                text=label, fill="#AAAAAA", font=(FONT_FAMILY, 8)
            )

        # Y축 눈금
        for i in range(5):
            y = margin_top + int(chart_h * i / 4)
            val = int(max_val * (4 - i) / 4)
            self.canvas.create_text(
                margin_left - 10, y,
                text=str(val), fill="#888888", font=(FONT_FAMILY, 9), anchor="e"
            )


class SimplePieChart(ctk.CTkFrame):
    """간단한 파이 차트"""

    def __init__(self, parent, data: List[Dict], title: str = "", size: int = 150, **kwargs):
        super().__init__(parent, **kwargs)

        self.data = data
        self.size = size

        # 제목
        if title:
            ctk.CTkLabel(self, text=title, font=get_font("medium", bold=True)).pack(pady=(5, 10))

        # 캔버스
        self.canvas = Canvas(
            self,
            width=size + 120,
            height=size + 20,
            bg="#2B2B2B",
            highlightthickness=0
        )
        self.canvas.pack(padx=10, pady=5)

        self._draw_chart()

    def _draw_chart(self):
        """차트 그리기"""
        if not self.data:
            return

        total = sum(d.get('value', 0) for d in self.data)
        if total == 0:
            return

        colors = ["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4"]
        start_angle = 90

        cx, cy = self.size // 2 + 10, self.size // 2 + 10
        radius = self.size // 2 - 10

        for i, item in enumerate(self.data):
            value = item.get('value', 0)
            label = item.get('label', '')
            color = colors[i % len(colors)]

            extent = (value / total) * 360

            # 파이 조각
            self.canvas.create_arc(
                cx - radius, cy - radius,
                cx + radius, cy + radius,
                start=start_angle, extent=-extent,
                fill=color, outline="#2B2B2B", width=2
            )

            start_angle -= extent

        # 범례
        legend_x = self.size + 20
        for i, item in enumerate(self.data):
            y = 20 + i * 25
            color = colors[i % len(colors)]
            label = item.get('label', '')
            value = item.get('value', 0)
            pct = (value / total * 100) if total > 0 else 0

            self.canvas.create_rectangle(legend_x, y, legend_x + 12, y + 12, fill=color, outline="")
            self.canvas.create_text(
                legend_x + 20, y + 6,
                text=f"{label}: {value} ({pct:.0f}%)",
                fill="white", font=(FONT_FAMILY, 9), anchor="w"
            )


class StatsDashboard(ctk.CTkToplevel):
    """v37 생산 통계 대시보드 - 차트 시각화 포함"""

    def __init__(self, parent, stats_manager):
        super().__init__(parent)

        self.stats_manager = stats_manager

        self.title("📊 생산 통계 대시보드")
        self.geometry("1100x800")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 1100) // 2
        y = (self.winfo_screenheight() - 800) // 2
        self.geometry(f"1100x800+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        # 메인 스크롤 프레임
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 헤더
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header,
            text="📊 생산 통계 대시보드",
            font=get_font("header", bold=True)
        ).pack(side="left")

        # 새로고침 버튼
        ctk.CTkButton(
            header,
            text="🔄 새로고침",
            width=100,
            font=get_font("normal"),
            command=self._refresh_dashboard
        ).pack(side="right")

        # ===== Row 1: 요약 카드들 =====
        summary_frame = ctk.CTkFrame(main_frame)
        summary_frame.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            summary_frame,
            text="📈 통계 요약",
            font=get_font("large", bold=True)
        ).pack(anchor="w", padx=15, pady=(15, 10))

        cards_row = ctk.CTkFrame(summary_frame, fg_color="transparent")
        cards_row.pack(fill="x", padx=15, pady=(0, 15))

        # 통계 카드들 (데이터 검증 포함)
        try:
            today = self.stats_manager.get_today_stats() or {"success": 0, "duration_minutes": 0}
            week = self.stats_manager.get_week_stats() or {"success": 0, "duration_minutes": 0}
            month = self.stats_manager.get_month_stats() or {"success": 0, "duration_minutes": 0}
            total = self.stats_manager.get_total_stats() or {"success": 0, "total_duration_minutes": 0}
        except Exception as e:
            logger.warning(f"[StatsDashboard] 통계 로드 실패: {e}")
            today = {"success": 0, "duration_minutes": 0}
            week = {"success": 0, "duration_minutes": 0}
            month = {"success": 0, "duration_minutes": 0}
            total = {"success": 0, "total_duration_minutes": 0}

        self._create_summary_card(cards_row, "오늘", today["success"], today.get("duration_minutes", 0), "#4CAF50")
        self._create_summary_card(cards_row, "이번 주", week["success"], week.get("duration_minutes", 0), "#2196F3")
        self._create_summary_card(cards_row, "이번 달", month["success"], month.get("duration_minutes", 0), "#FF9800")
        self._create_summary_card(cards_row, "전체", total["success"], total.get("total_duration_minutes", 0), "#9C27B0")

        # 예상 수익 카드 (가상 데이터)
        estimated_revenue = total["success"] * 15000  # 영상당 약 15,000원 예상
        self._create_revenue_card(cards_row, "예상 수익", estimated_revenue)

        # ===== Row 2: 차트 영역 =====
        charts_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        charts_row.pack(fill="x", pady=(0, 20))

        # 일별 트렌드 라인 차트
        trend_frame = ctk.CTkFrame(charts_row)
        trend_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        try:
            trend_data = self.stats_manager.get_daily_trend(7) or []
            line_data = [
                {"label": d.get("date", "")[-5:], "value": d.get("success", 0)}
                for d in trend_data if isinstance(d, dict)
            ]
        except Exception as e:
            logger.warning(f"[StatsDashboard] 트렌드 데이터 로드 실패: {e}")
            line_data = []

        SimpleLineChart(
            trend_frame,
            data=line_data,
            title="📅 최근 7일 제작 트렌드",
            width=500,
            height=200
        ).pack(padx=10, pady=10)

        # 채널별 통계 막대 차트
        channel_frame = ctk.CTkFrame(charts_row)
        channel_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))

        try:
            channel_stats = self.stats_manager.get_channel_stats() or {}
        except Exception as e:
            logger.warning(f"[StatsDashboard] 채널 통계 로드 실패: {e}")
            channel_stats = {}

        channel_names = {
            "daily_life_toon": "일상 영상툰",
            "mystery_toon": "미스터리 영상툰",
            "senior": "영상툰"
        }

        bar_data = [
            {"label": channel_names.get(k, k), "value": v.get("success", 0) if isinstance(v, dict) else 0}
            for k, v in channel_stats.items()
        ]

        SimpleBarChart(
            channel_frame,
            data=bar_data if bar_data else [{"label": "없음", "value": 0}],
            title="📺 채널별 제작 현황",
            width=400,
            height=200
        ).pack(padx=10, pady=10)

        # ===== Row 3: 성공률 & 파이차트 =====
        row3 = ctk.CTkFrame(main_frame, fg_color="transparent")
        row3.pack(fill="x", pady=(0, 20))

        # 성공률 게이지
        rate_frame = ctk.CTkFrame(row3)
        rate_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        success_rate = self.stats_manager.get_success_rate()
        self._create_gauge(rate_frame, "성공률", success_rate)

        # 상태별 파이 차트
        pie_frame = ctk.CTkFrame(row3)
        pie_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))

        total_success = total.get("success", 0)
        total_failed = total.get("failed", 0)

        pie_data = [
            {"label": "성공", "value": total_success},
            {"label": "실패", "value": total_failed}
        ]

        SimplePieChart(
            pie_frame,
            data=pie_data,
            title="📊 성공/실패 비율",
            size=150
        ).pack(padx=10, pady=10)

        # ===== Row 4: 최근 프로젝트 =====
        recent_frame = ctk.CTkFrame(main_frame)
        recent_frame.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            recent_frame,
            text="🕐 최근 프로젝트",
            font=get_font("large", bold=True)
        ).pack(anchor="w", padx=15, pady=(15, 10))

        recent_projects = self.stats_manager.get_recent_projects(10)

        if recent_projects:
            for project in recent_projects:
                row = ctk.CTkFrame(recent_frame, fg_color="#333333", corner_radius=8)
                row.pack(fill="x", padx=15, pady=3)

                status_emoji = "✅" if project.get("success") else "❌"
                channel = project.get("channel", "")
                mode = project.get("mode", "")
                duration = project.get("duration_minutes", 0)
                created = project.get("created_at", "")[:16].replace("T", " ")
                topic = project.get("topic", "제목 없음")[:40]

                ctk.CTkLabel(
                    row,
                    text=f"{status_emoji} [{channel}/{mode}] {topic}... ({duration:.1f}분) - {created}",
                    font=get_font("small"),
                    anchor="w"
                ).pack(anchor="w", padx=10, pady=8)
        else:
            ctk.CTkLabel(
                recent_frame,
                text="아직 제작 기록이 없습니다.",
                font=get_font("normal"),
                text_color="#888888"
            ).pack(pady=20)

        # 닫기 버튼
        ctk.CTkButton(
            main_frame,
            text="닫기",
            command=self.destroy,
            width=120,
            font=get_font("normal")
        ).pack(pady=20)

    def _create_summary_card(self, parent, title: str, count: int, duration: float, color: str):
        """통계 요약 카드"""
        card = ctk.CTkFrame(parent, fg_color="#333333", corner_radius=12)
        card.pack(side="left", padx=8, pady=5, expand=True, fill="both")

        ctk.CTkLabel(
            card,
            text=title,
            font=get_font("small"),
            text_color="#AAAAAA"
        ).pack(pady=(12, 2))

        ctk.CTkLabel(
            card,
            text=f"{count}개",
            font=get_font("title", bold=True),
            text_color=color
        ).pack()

        hours = int(duration // 60)
        mins = int(duration % 60)
        duration_text = f"{hours}h {mins}m" if hours > 0 else f"{mins}분"

        ctk.CTkLabel(
            card,
            text=f"소요: {duration_text}",
            font=get_font("small"),
            text_color="#666666"
        ).pack(pady=(2, 12))

    def _create_revenue_card(self, parent, title: str, amount: int):
        """수익 카드"""
        card = ctk.CTkFrame(parent, fg_color="#1E3A1E", corner_radius=12)
        card.pack(side="left", padx=8, pady=5, expand=True, fill="both")

        ctk.CTkLabel(
            card,
            text=f"💰 {title}",
            font=get_font("small"),
            text_color="#88CC88"
        ).pack(pady=(12, 2))

        formatted = f"₩{amount:,}"
        ctk.CTkLabel(
            card,
            text=formatted,
            font=get_font("title", bold=True),
            text_color="#4CAF50"
        ).pack()

        ctk.CTkLabel(
            card,
            text="영상당 ₩15,000 기준",
            font=get_font("small"),
            text_color="#556655"
        ).pack(pady=(2, 12))

    def _create_gauge(self, parent, title: str, value: float):
        """게이지 위젯"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(padx=15, pady=15)

        ctk.CTkLabel(
            frame,
            text=f"✅ {title}",
            font=get_font("medium", bold=True)
        ).pack(pady=(5, 10))

        # 게이지 값
        ctk.CTkLabel(
            frame,
            text=f"{value:.1f}%",
            font=ctk.CTkFont(family=FONT_FAMILY, size=36, weight="bold"),
            text_color="#4CAF50" if value >= 80 else "#FF9800" if value >= 50 else "#F44336"
        ).pack()

        # 프로그레스 바
        progress = ctk.CTkProgressBar(frame, width=200, height=12)
        progress.set(value / 100)
        progress.pack(pady=(10, 5))

        status = "우수" if value >= 80 else "양호" if value >= 50 else "개선 필요"
        ctk.CTkLabel(
            frame,
            text=status,
            font=get_font("small"),
            text_color="#888888"
        ).pack()

    def _refresh_dashboard(self):
        """대시보드 새로고침"""
        self.destroy()
        StatsDashboard(self.master, self.stats_manager)
