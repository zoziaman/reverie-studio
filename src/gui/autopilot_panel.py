# src/gui/autopilot_panel.py
"""
v37 - AI 자율주행 모드 패널

기능:
1. 자율주행 ON/OFF 스위치
2. 트렌드 분석 기반 주제 자동 제안
3. 승인 대기 큐 (배지 표시)
4. 자동 제작 스케줄링

Note: on_produce_callback은 향후 자동 제작 기능 구현 시 사용 예정
"""
import customtkinter as ctk
from typing import Dict, Any, List, Callable, Optional
from datetime import datetime
import threading
import json
import os

# 폰트 설정
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    """통일된 폰트 반환"""
    sizes = {"small": 11, "normal": 13, "medium": 14, "large": 16, "title": 20}
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


class ApprovalQueueItem:
    """승인 대기 큐 아이템"""
    def __init__(self, topic: str, channel: str, mode: str, source: str = "auto"):
        self.topic = topic
        self.channel = channel
        self.mode = mode
        self.source = source  # auto, trend, manual
        self.created_at = datetime.now().isoformat()
        self.status = "pending"  # pending, approved, rejected


class AutopilotPanel(ctk.CTkFrame):
    """
    AI 자율주행 모드 패널

    메인 윈도우에 임베드되어 사용
    """

    def __init__(
        self,
        parent,
        on_approve_callback: Optional[Callable] = None,
        on_produce_callback: Optional[Callable] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)

        self.on_approve_callback = on_approve_callback
        self.on_produce_callback = on_produce_callback

        # 상태
        self.is_autopilot_on = False
        self.approval_queue: List[ApprovalQueueItem] = []
        self._trend_thread = None

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        # 헤더
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            header,
            text="🤖 AI 자율주행 모드",
            font=get_font("medium", bold=True)
        ).pack(side="left")

        # 자율주행 스위치
        self.autopilot_switch = ctk.CTkSwitch(
            header,
            text="",
            width=50,
            command=self._toggle_autopilot,
            onvalue=True,
            offvalue=False
        )
        self.autopilot_switch.pack(side="right", padx=5)

        # 상태 라벨
        self.status_label = ctk.CTkLabel(
            header,
            text="OFF",
            font=get_font("small"),
            text_color="#888888"
        )
        self.status_label.pack(side="right", padx=5)

        # 승인 대기 배지
        self.badge_frame = ctk.CTkFrame(self, fg_color="#FF5722", corner_radius=10, height=24)
        self.badge_frame.pack(fill="x", padx=10, pady=5)

        self.badge_label = ctk.CTkLabel(
            self.badge_frame,
            text="🔔 승인 대기: 0개",
            font=get_font("small"),
            text_color="white"
        )
        self.badge_label.pack(pady=5)

        # 트렌드 제안 영역
        self.suggestions_frame = ctk.CTkScrollableFrame(self, height=150)
        self.suggestions_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # 초기 상태
        self._update_badge()
        self._show_empty_state()

    def _toggle_autopilot(self):
        """자율주행 모드 토글"""
        self.is_autopilot_on = self.autopilot_switch.get()

        if self.is_autopilot_on:
            self.status_label.configure(text="ON", text_color="#4CAF50")
            self._start_trend_analysis()
        else:
            self.status_label.configure(text="OFF", text_color="#888888")
            self._stop_trend_analysis()

    def _start_trend_analysis(self):
        """트렌드 분석 시작"""
        # 샘플 트렌드 주제 생성 (실제로는 API 연동)
        def analyze_task():
            # 샘플 트렌드 데이터
            sample_trends = [
                {"topic": "연예인 부모의 은밀한 재산 이전", "channel": "senior", "mode": "makjang", "source": "trend"},
                {"topic": "손주가 발견한 할머니의 숨겨진 과거", "channel": "senior", "mode": "touching", "source": "trend"},
                {"topic": "폐가에서 들려오는 의문의 소리", "channel": "horror", "mode": "horror", "source": "trend"},
            ]

            for trend in sample_trends:
                if not self.is_autopilot_on:
                    break
                item = ApprovalQueueItem(
                    topic=trend["topic"],
                    channel=trend["channel"],
                    mode=trend["mode"],
                    source=trend["source"]
                )
                self.approval_queue.append(item)

            # UI 업데이트 (메인 스레드에서)
            self.after(0, self._refresh_suggestions)
            self.after(0, self._update_badge)

        if self._trend_thread is None or not self._trend_thread.is_alive():
            self._trend_thread = threading.Thread(target=analyze_task, daemon=True)
            self._trend_thread.start()

    def _stop_trend_analysis(self):
        """트렌드 분석 중지"""
        self.is_autopilot_on = False

    def _show_empty_state(self):
        """빈 상태 표시"""
        for widget in self.suggestions_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self.suggestions_frame,
            text="자율주행 모드를 켜면\nAI가 트렌드를 분석하여\n주제를 제안합니다.",
            font=get_font("small"),
            text_color="#888888",
            justify="center"
        ).pack(pady=30)

    def _refresh_suggestions(self):
        """제안 목록 새로고침"""
        for widget in self.suggestions_frame.winfo_children():
            widget.destroy()

        pending_items = [item for item in self.approval_queue if item.status == "pending"]

        if not pending_items:
            self._show_empty_state()
            return

        for i, item in enumerate(pending_items[:5]):  # 최대 5개 표시
            row = ctk.CTkFrame(self.suggestions_frame, fg_color="#333333", corner_radius=8)
            row.pack(fill="x", pady=3)

            # 정보
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(fill="x", padx=10, pady=8)

            source_emoji = "📈" if item.source == "trend" else "🤖"
            channel_text = f"[{item.channel}/{item.mode}]"

            ctk.CTkLabel(
                info_frame,
                text=f"{source_emoji} {channel_text}",
                font=get_font("small"),
                text_color="#4CAF50"
            ).pack(anchor="w")

            ctk.CTkLabel(
                info_frame,
                text=item.topic[:35] + "..." if len(item.topic) > 35 else item.topic,
                font=get_font("small"),
                anchor="w"
            ).pack(anchor="w", pady=(2, 0))

            # 버튼
            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=10, pady=5)

            ctk.CTkButton(
                btn_frame,
                text="✓",
                width=30,
                height=28,
                fg_color="#4CAF50",
                font=get_font("small"),
                command=lambda idx=i: self._approve_item(idx)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                btn_frame,
                text="✕",
                width=30,
                height=28,
                fg_color="#F44336",
                font=get_font("small"),
                command=lambda idx=i: self._reject_item(idx)
            ).pack(side="left", padx=2)

    def _update_badge(self):
        """배지 업데이트"""
        pending_count = len([item for item in self.approval_queue if item.status == "pending"])

        if pending_count > 0:
            self.badge_frame.configure(fg_color="#FF5722")
            self.badge_label.configure(text=f"🔔 승인 대기: {pending_count}개")
        else:
            self.badge_frame.configure(fg_color="#555555")
            self.badge_label.configure(text="✓ 승인 대기 없음")

    def _approve_item(self, index: int):
        """아이템 승인"""
        pending_items = [item for item in self.approval_queue if item.status == "pending"]

        if 0 <= index < len(pending_items):
            item = pending_items[index]
            item.status = "approved"

            # 콜백 호출
            if self.on_approve_callback:
                self.on_approve_callback(item)

            self._refresh_suggestions()
            self._update_badge()

    def _reject_item(self, index: int):
        """아이템 거부"""
        pending_items = [item for item in self.approval_queue if item.status == "pending"]

        if 0 <= index < len(pending_items):
            item = pending_items[index]
            item.status = "rejected"

            self._refresh_suggestions()
            self._update_badge()

    def get_pending_count(self) -> int:
        """승인 대기 수 반환"""
        return len([item for item in self.approval_queue if item.status == "pending"])

    def add_manual_topic(self, topic: str, channel: str, mode: str):
        """수동 주제 추가"""
        item = ApprovalQueueItem(
            topic=topic,
            channel=channel,
            mode=mode,
            source="manual"
        )
        self.approval_queue.append(item)
        self._refresh_suggestions()
        self._update_badge()


class AutopilotDialog(ctk.CTkToplevel):
    """자율주행 모드 설정 다이얼로그"""

    def __init__(self, parent, config: Dict = None, on_save: Callable = None):
        super().__init__(parent)

        self.config = config or {}
        self.on_save = on_save

        self.title("🤖 자율주행 설정")
        self.geometry("500x400")
        self.transient(parent)
        self.grab_set()

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 500) // 2
        y = (self.winfo_screenheight() - 400) // 2
        self.geometry(f"500x400+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        ctk.CTkLabel(
            main_frame,
            text="🤖 자율주행 모드 설정",
            font=get_font("title", bold=True)
        ).pack(pady=(0, 20))

        # 자동 생성 간격
        interval_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        interval_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            interval_frame,
            text="주제 생성 간격:",
            font=get_font("normal"),
            width=120
        ).pack(side="left")

        self.interval_var = ctk.StringVar(value=self.config.get("interval", "30분"))
        interval_combo = ctk.CTkComboBox(
            interval_frame,
            values=["10분", "30분", "1시간", "2시간", "4시간"],
            variable=self.interval_var,
            width=150,
            font=get_font("normal")
        )
        interval_combo.pack(side="left", padx=10)

        # 일일 최대 제작 수
        max_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        max_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            max_frame,
            text="일일 최대 제작:",
            font=get_font("normal"),
            width=120
        ).pack(side="left")

        self.max_daily_var = ctk.StringVar(value=str(self.config.get("max_daily", 10)))
        max_entry = ctk.CTkEntry(
            max_frame,
            textvariable=self.max_daily_var,
            width=80,
            font=get_font("normal")
        )
        max_entry.pack(side="left", padx=10)

        ctk.CTkLabel(
            max_frame,
            text="개",
            font=get_font("normal")
        ).pack(side="left")

        # 자동 승인 옵션
        auto_approve_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        auto_approve_frame.pack(fill="x", pady=10)

        self.auto_approve_var = ctk.BooleanVar(value=self.config.get("auto_approve", False))
        ctk.CTkCheckBox(
            auto_approve_frame,
            text="트렌드 주제 자동 승인",
            variable=self.auto_approve_var,
            font=get_font("normal")
        ).pack(anchor="w")

        ctk.CTkLabel(
            auto_approve_frame,
            text="⚠️ 자동 승인 시 검토 없이 바로 제작이 시작됩니다",
            font=get_font("small"),
            text_color="#FF9800"
        ).pack(anchor="w", padx=25, pady=(2, 0))

        # 채널 선택
        channel_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        channel_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(
            channel_frame,
            text="자동 제작 채널:",
            font=get_font("normal"),
            width=120
        ).pack(side="left")

        self.channel_var = ctk.StringVar(value=self.config.get("channel", "senior"))
        channel_combo = ctk.CTkComboBox(
            channel_frame,
            values=["horror", "senior", "all"],
            variable=self.channel_var,
            width=150,
            font=get_font("normal")
        )
        channel_combo.pack(side="left", padx=10)

        # 버튼
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(30, 0))

        ctk.CTkButton(
            btn_frame,
            text="저장",
            width=100,
            fg_color="#4CAF50",
            font=get_font("normal"),
            command=self._save
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="#757575",
            font=get_font("normal"),
            command=self.destroy
        ).pack(side="right", padx=5)

    def _save(self):
        """설정 저장"""
        config = {
            "interval": self.interval_var.get(),
            "max_daily": int(self.max_daily_var.get()),
            "auto_approve": self.auto_approve_var.get(),
            "channel": self.channel_var.get()
        }

        if self.on_save:
            self.on_save(config)

        self.destroy()
