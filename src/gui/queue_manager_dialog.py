# src/gui/queue_manager_dialog.py
"""
배치 큐 관리 다이얼로그
"""
import customtkinter as ctk
from tkinter import messagebox
from typing import Callable, Optional


class QueueManagerDialog(ctk.CTkToplevel):
    """배치 큐 관리 다이얼로그"""

    def __init__(self, parent, queue_manager, on_start_callback: Callable = None):
        super().__init__(parent)

        self.queue_manager = queue_manager
        self.on_start_callback = on_start_callback

        self.title("📋 배치 큐 관리")
        self.geometry("800x600")
        self.transient(parent)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 800) // 2
        y = (self.winfo_screenheight() - 600) // 2
        self.geometry(f"800x600+{x}+{y}")

        self._create_ui()
        self._refresh_queue()

    def _create_ui(self):
        """UI 구성"""
        # 상단 제목
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            title_frame,
            text="📋 배치 큐 관리",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")

        # 큐 요약
        self.summary_label = ctk.CTkLabel(
            title_frame,
            text="",
            font=ctk.CTkFont(size=12)
        )
        self.summary_label.pack(side="right")

        # 큐 목록
        list_frame = ctk.CTkFrame(self)
        list_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 스크롤 가능한 프레임
        self.queue_scroll = ctk.CTkScrollableFrame(list_frame)
        self.queue_scroll.pack(fill="both", expand=True)

        # 하단 버튼
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=20, pady=15)

        # 왼쪽 버튼들
        left_buttons = ctk.CTkFrame(button_frame, fg_color="transparent")
        left_buttons.pack(side="left")

        ctk.CTkButton(
            left_buttons,
            text="🔄 새로고침",
            command=self._refresh_queue,
            width=100
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            left_buttons,
            text="🗑️ 완료된 항목 정리",
            command=self._clear_completed,
            width=140,
            fg_color="gray",
            hover_color="darkgray"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            left_buttons,
            text="⛔ 대기 중 모두 취소",
            command=self._cancel_all,
            width=140,
            fg_color="red",
            hover_color="darkred"
        ).pack(side="left", padx=5)

        # 오른쪽 버튼들
        right_buttons = ctk.CTkFrame(button_frame, fg_color="transparent")
        right_buttons.pack(side="right")

        ctk.CTkButton(
            right_buttons,
            text="▶️ 큐 실행",
            command=self._start_queue,
            width=120,
            fg_color="green",
            hover_color="darkgreen"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            right_buttons,
            text="닫기",
            command=self.destroy,
            width=80
        ).pack(side="left", padx=5)

    def _refresh_queue(self):
        """큐 목록 새로고침"""
        # 기존 항목 삭제
        for widget in self.queue_scroll.winfo_children():
            widget.destroy()

        jobs = self.queue_manager.get_all_jobs()
        summary = self.queue_manager.get_queue_summary()

        # 요약 업데이트
        self.summary_label.configure(
            text=f"대기: {summary['pending']} | 진행: {summary['running']} | 완료: {summary['completed']} | 실패: {summary['failed']}"
        )

        if not jobs:
            ctk.CTkLabel(
                self.queue_scroll,
                text="큐가 비어 있습니다.",
                font=ctk.CTkFont(size=14),
                text_color="gray"
            ).pack(pady=50)
            return

        # 작업 목록 표시
        for i, job in enumerate(jobs):
            self._create_job_row(job, i)

    def _create_job_row(self, job: dict, index: int):
        """작업 행 생성"""
        status = job.get("status", "pending")
        status_colors = {
            "pending": ("⏳", "orange"),
            "running": ("🔄", "blue"),
            "completed": ("✅", "green"),
            "failed": ("❌", "red"),
            "cancelled": ("⛔", "gray")
        }

        emoji, color = status_colors.get(status, ("❓", "gray"))

        row = ctk.CTkFrame(self.queue_scroll)
        row.pack(fill="x", pady=2, padx=5)

        # 상태 아이콘
        ctk.CTkLabel(
            row,
            text=emoji,
            width=30,
            font=ctk.CTkFont(size=16)
        ).pack(side="left", padx=5)

        # 작업 정보 - v58.3: pack_id 표시
        pack_id = job.get("pack_id", "")
        channel = job.get("channel", "")
        mode = job.get("mode", "")
        topic = job.get("manual_topic", "") or "자동 생성"
        job_id = job.get("id", "")

        # 팩 ID가 있으면 팩 이름 표시, 없으면 channel/mode
        display_name = pack_id if pack_id else f"{channel}/{mode}"
        retry_count = job.get("retry_count", 0)
        retry_suffix = f" (retry {retry_count})" if retry_count else ""
        info_text = f"[{display_name}] {topic[:25]}...{retry_suffix}"
        if status == "failed" and job.get("error"):
            info_text += f" | {str(job.get('error'))[:40]}"

        ctk.CTkLabel(
            row,
            text=info_text,
            font=ctk.CTkFont(size=12),
            anchor="w",
            width=350
        ).pack(side="left", padx=10)

        # 작업 ID
        ctk.CTkLabel(
            row,
            text=f"#{job_id}",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            width=80
        ).pack(side="left")

        # 버튼들 (대기 중인 작업만)
        if status == "pending":
            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=5)

            # 위로 이동
            ctk.CTkButton(
                btn_frame,
                text="⬆️",
                width=30,
                command=lambda jid=job_id: self._move_up(jid)
            ).pack(side="left", padx=2)

            # 아래로 이동
            ctk.CTkButton(
                btn_frame,
                text="⬇️",
                width=30,
                command=lambda jid=job_id: self._move_down(jid)
            ).pack(side="left", padx=2)

            # 취소
            ctk.CTkButton(
                btn_frame,
                text="❌",
                width=30,
                fg_color="red",
                hover_color="darkred",
                command=lambda jid=job_id: self._cancel_job(jid)
            ).pack(side="left", padx=2)

        elif status == "failed":
            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=5)

            ctk.CTkButton(
                btn_frame,
                text="재시도",
                width=70,
                fg_color="#1D4ED8",
                hover_color="#1E40AF",
                command=lambda jid=job_id: self._retry_job(jid)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                btn_frame,
                text="삭제",
                width=50,
                fg_color="gray",
                command=lambda jid=job_id: self._remove_job(jid)
            ).pack(side="left", padx=2)

        elif status in ["completed", "cancelled"]:
            # 삭제
            ctk.CTkButton(
                row,
                text="🗑️",
                width=30,
                fg_color="gray",
                command=lambda jid=job_id: self._remove_job(jid)
            ).pack(side="right", padx=5)

    def _move_up(self, job_id: str):
        """작업 위로 이동"""
        self.queue_manager.move_job_up(job_id)
        self._refresh_queue()

    def _move_down(self, job_id: str):
        """작업 아래로 이동"""
        self.queue_manager.move_job_down(job_id)
        self._refresh_queue()

    def _cancel_job(self, job_id: str):
        """작업 취소"""
        if messagebox.askyesno("확인", "이 작업을 취소하시겠습니까?"):
            self.queue_manager.cancel_job(job_id)
            self._refresh_queue()

    def _remove_job(self, job_id: str):
        """작업 삭제"""
        self.queue_manager.remove_job(job_id)
        self._refresh_queue()

    def _retry_job(self, job_id: str):
        """Retry a failed job from the queue manager."""
        new_job_id = self.queue_manager.retry_job(job_id)
        if not new_job_id:
            messagebox.showerror("오류", "재시도할 실패 작업을 찾지 못했습니다.")
            return

        self._refresh_queue()
        summary = self.queue_manager.get_queue_summary()
        if summary.get("running", 0) == 0 and self.on_start_callback:
            self.destroy()
            self.on_start_callback()
            return

        messagebox.showinfo("재시도 등록", f"재시도 작업을 대기열에 추가했습니다.\n작업 ID: {new_job_id}")

    def _clear_completed(self):
        """완료된 작업 정리"""
        self.queue_manager.clear_completed()
        self._refresh_queue()
        messagebox.showinfo("완료", "완료/실패/취소된 작업이 정리되었습니다.")

    def _cancel_all(self):
        """모든 대기 중인 작업 취소"""
        if messagebox.askyesno("확인", "대기 중인 모든 작업을 취소하시겠습니까?"):
            self.queue_manager.cancel_all_pending()
            self._refresh_queue()

    def _start_queue(self):
        """큐 실행 시작"""
        pending = self.queue_manager.get_pending_jobs()
        if not pending:
            messagebox.showinfo("알림", "실행할 작업이 없습니다.")
            return

        if messagebox.askyesno("확인", f"{len(pending)}개의 작업을 실행하시겠습니까?"):
            self.destroy()
            if self.on_start_callback:
                self.on_start_callback()
