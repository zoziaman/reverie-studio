"""
실데이터 기반 운영 패널.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from tkinter import Canvas, messagebox
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

from config.settings import config
from utils.channel_registry import ChannelInfo, SUPPORTED_LANGUAGES, get_channel_registry
from utils.production_stats import ProductionStats

try:
    from utils.firebase_license import FirebaseLicenseValidator
except ImportError:  # pragma: no cover
    FirebaseLicenseValidator = None


FONT_FAMILY = "Malgun Gothic"


def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    sizes = {
        "small": 11,
        "normal": 13,
        "medium": 14,
        "large": 16,
        "title": 20,
        "header": 28,
    }
    try:
        return ctk.CTkFont(
            family=FONT_FAMILY,
            size=sizes.get(size, 13),
            weight="bold" if bold else "normal",
        )
    except RuntimeError:
        return (FONT_FAMILY, sizes.get(size, 13), "bold" if bold else "normal")


class AdminDashboard(ctk.CTkToplevel):
    """실운영 데이터에 연결되는 관리자 패널."""

    def __init__(
        self,
        parent,
        license_info: Optional[Dict[str, Any]] = None,
        services: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.license_info = license_info or {}
        self.services = services or {}
        self.data_dir = getattr(config, "DATA_DIR", os.path.join(os.getcwd(), "data"))

        self.channel_registry = self.services.get("channel_registry") or get_channel_registry(self.data_dir)
        self.production_stats = self.services.get("production_stats") or ProductionStats(self.data_dir)
        self.firebase_validator = self.services.get("firebase_validator") or self._build_firebase_validator()

        self.title("레베리 운영 패널")
        self.geometry("1360x920")
        self.minsize(1180, 800)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._snapshot: Dict[str, Any] = {}

        self._center_window()
        self._create_ui()
        self._refresh_data_async()

    def _build_firebase_validator(self):
        if FirebaseLicenseValidator is None:
            return None
        try:
            validator = FirebaseLicenseValidator()
            return validator if validator.is_available() else None
        except Exception:
            return None

    def _center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 1360) // 2
        y = (self.winfo_screenheight() - 920) // 2
        self.geometry(f"1360x920+{x}+{y}")

    def _safe_after(self, delay_ms: int, callback: Callable[[], None]):
        try:
            if self.winfo_exists():
                self.after(delay_ms, callback)
        except Exception:
            return None
        return None

    def _start_job(
        self,
        name: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Optional[Callable[[Exception], None]] = None,
        busy_text: Optional[str] = None,
    ):
        current = self._jobs.get(name)
        if current and not current.get("done", False):
            return

        if busy_text:
            self.status_label.configure(text=busy_text, text_color="orange")

        state: Dict[str, Any] = {"done": False, "result": None, "error": None}
        self._jobs[name] = state

        def worker():
            try:
                state["result"] = task()
            except Exception as exc:  # pragma: no cover
                state["error"] = exc
            finally:
                state["done"] = True

        threading.Thread(target=worker, daemon=True).start()
        self._safe_after(50, lambda: self._poll_job(name, on_success, on_error))

    def _poll_job(
        self,
        name: str,
        on_success: Callable[[Any], None],
        on_error: Optional[Callable[[Exception], None]],
    ):
        state = self._jobs.get(name)
        if not state:
            return
        if not state.get("done", False):
            self._safe_after(50, lambda: self._poll_job(name, on_success, on_error))
            return

        self._jobs.pop(name, None)
        if state.get("error") is not None:
            self.status_label.configure(text=f"오류: {state['error']}", text_color="red")
            if on_error is not None:
                on_error(state["error"])
            return

        on_success(state.get("result"))

    def _create_ui(self):
        root = ctk.CTkFrame(self)
        root.pack(fill="both", expand=True, padx=18, pady=18)

        self._create_header(root)

        self.summary_frame = ctk.CTkFrame(root)
        self.summary_frame.pack(fill="x", pady=(0, 18))

        self.trend_frame = ctk.CTkFrame(root)
        self.trend_frame.pack(fill="x", pady=(0, 18))
        self.trend_canvas = Canvas(
            self.trend_frame,
            width=1250,
            height=220,
            bg="#202020",
            highlightthickness=0,
        )
        self.trend_canvas.pack(padx=16, pady=(10, 16))

        self.packages_section = ctk.CTkFrame(root)
        self.packages_section.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(
            self.packages_section,
            text="패키지 배포 현황",
            font=get_font("large", bold=True),
        ).pack(anchor="w", padx=16, pady=(16, 10))
        self.packages_body = ctk.CTkFrame(self.packages_section, fg_color="transparent")
        self.packages_body.pack(fill="x", padx=16, pady=(0, 16))

        self.channels_section = ctk.CTkFrame(root)
        self.channels_section.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(
            self.channels_section,
            text="채널 운영",
            font=get_font("large", bold=True),
        ).pack(anchor="w", padx=16, pady=(16, 10))
        self.channels_body = ctk.CTkFrame(self.channels_section, fg_color="transparent")
        self.channels_body.pack(fill="x", padx=16, pady=(0, 16))

        self.accounts_section = ctk.CTkFrame(root)
        self.accounts_section.pack(fill="both", expand=True)
        ctk.CTkLabel(
            self.accounts_section,
            text="라이센스 계정",
            font=get_font("large", bold=True),
        ).pack(anchor="w", padx=16, pady=(16, 10))
        self.accounts_body = ctk.CTkFrame(self.accounts_section, fg_color="transparent")
        self.accounts_body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _create_header(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(0, 18))

        ctk.CTkLabel(
            header,
            text="레베리 운영 패널",
            font=get_font("header", bold=True),
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="새로고침",
            width=110,
            font=get_font("normal"),
            command=self._refresh_data_async,
        ).pack(side="right", padx=(0, 12))

        meta = ctk.CTkFrame(header, fg_color="transparent")
        meta.pack(side="right")

        org_name = self.license_info.get("org_name", os.environ.get("COMPUTERNAME", "Reverie"))
        ctk.CTkLabel(
            meta,
            text=org_name,
            font=get_font("medium", bold=True),
            text_color="#4CAF50",
        ).pack(anchor="e")

        self.status_label = ctk.CTkLabel(
            meta,
            text="데이터를 불러오는 중입니다.",
            font=get_font("small"),
            text_color="#AAAAAA",
        )
        self.status_label.pack(anchor="e", pady=(4, 0))

    def _refresh_data_async(self):
        self._start_job(
            "dashboard_refresh",
            self._collect_snapshot,
            self._apply_snapshot,
            busy_text="운영 데이터를 불러오는 중입니다...",
        )

    def _collect_snapshot(self) -> Dict[str, Any]:
        channels = [self._serialize_channel(channel) for channel in self.channel_registry.get_all_channels()]
        channels.sort(key=lambda item: (-item["is_active"], -item["priority"], item["display_name"]))

        licenses: List[Dict[str, Any]] = []
        package_stats: List[Dict[str, Any]] = []
        if self.firebase_validator and self.firebase_validator.is_available():
            licenses = self.firebase_validator.get_all_licenses()
            package_stats = self.firebase_validator.get_all_package_stats()

        snapshot = {
            "channels": channels,
            "licenses": licenses,
            "package_stats": package_stats,
            "trend": self.production_stats.get_daily_trend(7),
            "recent_projects": self.production_stats.get_recent_projects(8),
            "total_stats": self.production_stats.get_total_stats(),
            "today_stats": self.production_stats.get_today_stats(),
            "success_rate": self.production_stats.get_success_rate(),
        }
        snapshot["summary"] = self._build_summary(snapshot)
        return snapshot

    def _serialize_channel(self, channel: ChannelInfo) -> Dict[str, Any]:
        return {
            "channel_id": channel.channel_id,
            "display_name": channel.display_name,
            "channel_type": channel.channel_type,
            "is_active": bool(channel.is_active),
            "priority": channel.priority,
            "daily_video_limit": channel.daily_video_limit,
            "today_video_count": channel.today_video_count,
            "total_videos": channel.total_videos,
            "total_views": channel.total_views,
            "target_language": channel.target_language,
            "updated_at": channel.updated_at,
        }

    @staticmethod
    def _build_summary(snapshot: Dict[str, Any]) -> List[Dict[str, str]]:
        channels = snapshot.get("channels", [])
        licenses = snapshot.get("licenses", [])
        total_stats = snapshot.get("total_stats", {})

        active_channels = sum(1 for channel in channels if channel.get("is_active"))
        active_licenses = sum(1 for license_info in licenses if license_info.get("is_active"))
        total_success = total_stats.get("success", 0)
        total_failed = total_stats.get("failed", 0)

        return [
            {"title": "활성 채널", "value": f"{active_channels}/{len(channels)}"},
            {"title": "활성 라이센스", "value": f"{active_licenses}/{len(licenses)}"},
            {"title": "누적 성공", "value": f"{total_success:,}"},
            {"title": "누적 실패", "value": f"{total_failed:,}"},
            {"title": "성공률", "value": f"{snapshot.get('success_rate', 0.0):.1f}%"},
            {"title": "등록 팩 수", "value": f"{len(snapshot.get('package_stats', []))}"},
        ]

    def _apply_snapshot(self, snapshot: Dict[str, Any]):
        self._snapshot = snapshot
        self._render_summary(snapshot["summary"])
        self._render_trend(snapshot["trend"])
        self._render_package_stats(snapshot["package_stats"])
        self._render_channels(snapshot["channels"])
        self._render_accounts(snapshot["licenses"])
        self.status_label.configure(
            text=(
                f"마지막 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                f"채널 {len(snapshot['channels'])}개 | 라이센스 {len(snapshot['licenses'])}개"
            ),
            text_color="#AAAAAA",
        )

    def _render_summary(self, cards: List[Dict[str, str]]):
        for child in self.summary_frame.winfo_children():
            child.destroy()

        row = ctk.CTkFrame(self.summary_frame, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=16)

        for card in cards:
            panel = ctk.CTkFrame(row, fg_color="#303030", corner_radius=12)
            panel.pack(side="left", fill="both", expand=True, padx=6)
            ctk.CTkLabel(
                panel,
                text=card["title"],
                font=get_font("small"),
                text_color="#A0A0A0",
            ).pack(pady=(14, 6))
            ctk.CTkLabel(
                panel,
                text=card["value"],
                font=get_font("title", bold=True),
                text_color="#FFFFFF",
            ).pack(pady=(0, 14))

    def _render_trend(self, trend: List[Dict[str, Any]]):
        self.trend_canvas.delete("all")
        if not trend:
            self.trend_canvas.create_text(
                620,
                110,
                text="최근 생산 통계가 없습니다.",
                fill="#A0A0A0",
                font=(FONT_FAMILY, 14),
            )
            return

        width = 1250
        height = 220
        margin_left = 70
        margin_right = 30
        margin_top = 24
        margin_bottom = 45
        chart_w = width - margin_left - margin_right
        chart_h = height - margin_top - margin_bottom
        max_value = max((item.get("success", 0) for item in trend), default=0) or 1
        bar_width = max(30, chart_w // max(len(trend), 1) - 20)

        self.trend_canvas.create_text(
            24,
            20,
            text="최근 7일 성공 생산 추이",
            fill="#FFFFFF",
            anchor="nw",
            font=(FONT_FAMILY, 13, "bold"),
        )

        for index, item in enumerate(trend):
            success = item.get("success", 0)
            failed = item.get("failed", 0)
            x1 = margin_left + 10 + index * (bar_width + 20)
            x2 = x1 + bar_width
            bar_height = int((success / max_value) * chart_h)
            y1 = margin_top + chart_h - bar_height
            y2 = margin_top + chart_h

            self.trend_canvas.create_rectangle(x1, y1, x2, y2, fill="#4CAF50", outline="")
            self.trend_canvas.create_text(
                (x1 + x2) // 2,
                y1 - 10,
                text=str(success),
                fill="#FFFFFF",
                font=(FONT_FAMILY, 10),
            )
            self.trend_canvas.create_text(
                (x1 + x2) // 2,
                y2 + 14,
                text=item.get("date", "")[5:],
                fill="#B0B0B0",
                font=(FONT_FAMILY, 9),
            )
            if failed:
                self.trend_canvas.create_text(
                    (x1 + x2) // 2,
                    y2 + 30,
                    text=f"실패 {failed}",
                    fill="#D06060",
                    font=(FONT_FAMILY, 8),
                )

        for step in range(5):
            y = margin_top + int(chart_h * step / 4)
            value = int(max_value * (4 - step) / 4)
            self.trend_canvas.create_text(
                margin_left - 8,
                y,
                text=str(value),
                fill="#909090",
                anchor="e",
                font=(FONT_FAMILY, 9),
            )

    def _render_package_stats(self, stats: List[Dict[str, Any]]):
        for child in self.packages_body.winfo_children():
            child.destroy()

        if not self.firebase_validator:
            ctk.CTkLabel(
                self.packages_body,
                text="Firebase 연결이 없어 패키지 배포 현황을 표시할 수 없습니다.",
                text_color="orange",
                font=get_font("normal"),
            ).pack(pady=20)
            return

        if not stats:
            ctk.CTkLabel(
                self.packages_body,
                text="등록된 패키지 통계가 없습니다.",
                text_color="gray",
                font=get_font("normal"),
            ).pack(pady=20)
            return

        row = None
        for index, package_stat in enumerate(sorted(stats, key=lambda item: item.get("total_count", 0), reverse=True)):
            if index % 4 == 0:
                row = ctk.CTkFrame(self.packages_body, fg_color="transparent")
                row.pack(fill="x", pady=6)
            self._create_package_card(row, package_stat)

    def _create_package_card(self, parent, package_stat: Dict[str, Any]):
        card = ctk.CTkFrame(parent, fg_color="#303030", corner_radius=12, width=290, height=140)
        card.pack(side="left", fill="both", expand=True, padx=6)
        card.pack_propagate(False)

        pack_id = package_stat.get("pack_id", "-")
        active_count = int(package_stat.get("active_count", 0))
        total_count = int(package_stat.get("total_count", 0))

        ctk.CTkLabel(
            card,
            text=pack_id,
            font=get_font("medium", bold=True),
        ).pack(anchor="w", padx=14, pady=(14, 6))

        ctk.CTkLabel(
            card,
            text=f"활성 {active_count} / 전체 {total_count}",
            font=get_font("normal"),
            text_color="#D0D0D0",
        ).pack(anchor="w", padx=14)

        ctk.CTkButton(
            card,
            text="배포 상세",
            width=110,
            height=30,
            fg_color="#1565C0",
            font=get_font("small"),
            command=lambda pid=pack_id: self._show_package_detail(pid),
        ).pack(anchor="w", padx=14, pady=(12, 0))

    def _render_channels(self, channels: List[Dict[str, Any]]):
        for child in self.channels_body.winfo_children():
            child.destroy()

        if not channels:
            ctk.CTkLabel(
                self.channels_body,
                text="등록된 채널이 없습니다.",
                text_color="gray",
                font=get_font("normal"),
            ).pack(pady=20)
            return

        row = None
        for index, channel in enumerate(channels):
            if index % 3 == 0:
                row = ctk.CTkFrame(self.channels_body, fg_color="transparent")
                row.pack(fill="x", pady=6)
            self._create_channel_card(row, channel)

    def _create_channel_card(self, parent, channel: Dict[str, Any]):
        card = ctk.CTkFrame(parent, fg_color="#303030", corner_radius=12, width=390, height=215)
        card.pack(side="left", fill="both", expand=True, padx=6)
        card.pack_propagate(False)

        badge_color = "#2E7D32" if channel["is_active"] else "#C62828"
        badge_text = "활성" if channel["is_active"] else "일시정지"
        ctk.CTkLabel(
            card,
            text=badge_text,
            fg_color=badge_color,
            corner_radius=8,
            width=88,
            font=get_font("small", bold=True),
        ).pack(anchor="ne", padx=12, pady=(12, 0))

        ctk.CTkLabel(
            card,
            text=channel["display_name"],
            font=get_font("medium", bold=True),
        ).pack(anchor="w", padx=14, pady=(4, 2))

        lang_label = SUPPORTED_LANGUAGES.get(channel["target_language"], channel["target_language"])
        ctk.CTkLabel(
            card,
            text=f"{channel['channel_type']} | {lang_label}",
            font=get_font("small"),
            text_color="#A0A0A0",
        ).pack(anchor="w", padx=14)

        details = [
            f"우선순위: {channel['priority']}",
            f"일일 쿼터: {channel['today_video_count']}/{channel['daily_video_limit']}",
            f"누적 영상: {channel['total_videos']}",
            f"누적 조회수: {channel['total_views']:,}",
        ]
        for line in details:
            ctk.CTkLabel(
                card,
                text=line,
                font=get_font("small"),
                text_color="#D0D0D0",
            ).pack(anchor="w", padx=14, pady=1)

        action_row = ctk.CTkFrame(card, fg_color="transparent")
        action_row.pack(fill="x", padx=12, pady=(10, 12))

        toggle_label = "일시정지" if channel["is_active"] else "활성화"
        toggle_color = "#C62828" if channel["is_active"] else "#2E7D32"
        toggle_action = self._pause_channel if channel["is_active"] else self._activate_channel
        ctk.CTkButton(
            action_row,
            text=toggle_label,
            width=84,
            fg_color=toggle_color,
            font=get_font("small"),
            command=lambda data=channel: toggle_action(data),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            action_row,
            text="설정",
            width=70,
            fg_color="#6A1B9A",
            font=get_font("small"),
            command=lambda data=channel: self._edit_channel(data),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            action_row,
            text="상세",
            width=70,
            fg_color="#1565C0",
            font=get_font("small"),
            command=lambda data=channel: self._show_channel_detail(data),
        ).pack(side="left")

    def _render_accounts(self, licenses: List[Dict[str, Any]]):
        for child in self.accounts_body.winfo_children():
            child.destroy()

        if not self.firebase_validator:
            ctk.CTkLabel(
                self.accounts_body,
                text="Firebase 연결이 없어 라이센스 계정을 표시할 수 없습니다.",
                text_color="orange",
                font=get_font("normal"),
            ).pack(pady=20)
            return

        if not licenses:
            ctk.CTkLabel(
                self.accounts_body,
                text="등록된 라이센스가 없습니다.",
                text_color="gray",
                font=get_font("normal"),
            ).pack(pady=20)
            return

        header = ctk.CTkFrame(self.accounts_body, fg_color="#383838")
        header.pack(fill="x", pady=(0, 4))
        columns = [
            ("사용자", 190),
            ("라이센스 키", 230),
            ("보유 팩", 240),
            ("만료일", 110),
            ("상태", 80),
            ("작업", 270),
        ]
        for title, width in columns:
            ctk.CTkLabel(
                header,
                text=title,
                width=width,
                anchor="w",
                font=get_font("small", bold=True),
            ).pack(side="left", padx=8, pady=8)

        sorted_licenses = sorted(
            licenses,
            key=lambda item: (
                not item.get("is_active", False),
                item.get("user_id", ""),
            ),
        )
        for index, license_data in enumerate(sorted_licenses):
            self._create_account_row(license_data, index)

    def _create_account_row(self, license_data: Dict[str, Any], index: int):
        row_color = "#2B2B2B" if index % 2 == 0 else "#333333"
        row = ctk.CTkFrame(self.accounts_body, fg_color=row_color, corner_radius=8)
        row.pack(fill="x", pady=2)

        license_key = license_data.get("license_key", "")
        user_id = license_data.get("user_id", "")
        packs = license_data.get("owned_packs", [])
        pack_text = ", ".join(packs[:3]) if packs else license_data.get("license_type", "-")
        if len(packs) > 3:
            pack_text += f" +{len(packs) - 3}"

        expire_date = license_data.get("expire_date")
        if hasattr(expire_date, "strftime"):
            expire_text = expire_date.strftime("%Y-%m-%d")
        else:
            expire_text = str(expire_date)[:10] if expire_date else "-"

        is_active = bool(license_data.get("is_active"))
        status_text = "활성" if is_active else "중지"
        status_color = "#2E7D32" if is_active else "#C62828"

        values = [
            (user_id[:24], 190),
            (license_key[:28], 230),
            (pack_text, 240),
            (expire_text, 110),
        ]
        for text, width in values:
            ctk.CTkLabel(
                row,
                text=text,
                width=width,
                anchor="w",
                font=get_font("small"),
            ).pack(side="left", padx=8, pady=10)

        ctk.CTkLabel(
            row,
            text=status_text,
            width=80,
            anchor="w",
            font=get_font("small", bold=True),
            text_color=status_color,
        ).pack(side="left", padx=8)

        actions = ctk.CTkFrame(row, fg_color="transparent", width=270)
        actions.pack(side="left", padx=8)

        toggle_action = self._suspend_account if is_active else self._activate_account
        toggle_label = "비활성" if is_active else "활성"
        toggle_color = "#C62828" if is_active else "#2E7D32"
        ctk.CTkButton(
            actions,
            text=toggle_label,
            width=62,
            height=28,
            fg_color=toggle_color,
            font=get_font("small"),
            command=lambda data=license_data: toggle_action(data),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="수정",
            width=54,
            height=28,
            fg_color="#6A1B9A",
            font=get_font("small"),
            command=lambda data=license_data: self._edit_account(data),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="연장",
            width=54,
            height=28,
            fg_color="#2E7D32",
            font=get_font("small"),
            command=lambda data=license_data: self._extend_account(data),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="삭제",
            width=54,
            height=28,
            fg_color="#8B0000",
            font=get_font("small"),
            command=lambda data=license_data: self._delete_account(data),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="상세",
            width=54,
            height=28,
            fg_color="#1565C0",
            font=get_font("small"),
            command=lambda data=license_data: self._show_account_detail(data),
        ).pack(side="left")

    def _create_modal(self, title: str, size: str = "520x420") -> ctk.CTkToplevel:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry(size)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        x = self.winfo_rootx() + max((self.winfo_width() - dialog.winfo_width()) // 2, 40)
        y = self.winfo_rooty() + max((self.winfo_height() - dialog.winfo_height()) // 2, 40)
        dialog.geometry(f"{size}+{x}+{y}")
        return dialog

    def _show_package_detail(self, pack_id: str):
        if not self.firebase_validator:
            messagebox.showerror("오류", "Firebase 연결이 없습니다.")
            return

        self._start_job(
            f"package_detail_{pack_id}",
            lambda: self.firebase_validator.get_package_distribution(pack_id),
            on_success=lambda result: self._show_package_detail_result(pack_id, result),
            on_error=lambda exc: messagebox.showerror("오류", f"패키지 상세 조회 실패: {exc}"),
            busy_text=f"{pack_id} 배포 현황을 조회하는 중입니다...",
        )

    def _show_package_detail_result(self, pack_id: str, distribution: Dict[str, Any]):
        licenses = distribution.get("licenses", [])
        if not licenses:
            messagebox.showinfo("패키지 배포 상세", f"{pack_id} 패키지를 가진 라이센스가 없습니다.")
            return

        lines = [
            f"패키지 ID: {pack_id}",
            f"전체: {distribution.get('total_count', 0)}개",
            f"활성: {distribution.get('active_count', 0)}개",
            "",
            "[라이센스 목록]",
        ]
        for license_info in licenses[:20]:
            expire_date = license_info.get("expire_date")
            if hasattr(expire_date, "strftime"):
                expire_text = expire_date.strftime("%Y-%m-%d")
            else:
                expire_text = str(expire_date)[:10] if expire_date else "-"
            lines.append(
                f"- {license_info.get('user_id', '-')}"
                f" | {'활성' if license_info.get('is_active') else '중지'}"
                f" | 만료 {expire_text}"
            )
        if len(licenses) > 20:
            lines.append(f"... 외 {len(licenses) - 20}건")
        messagebox.showinfo("패키지 배포 상세", "\n".join(lines))

    def _pause_channel(self, channel: Dict[str, Any]):
        if not messagebox.askyesno("채널 일시정지", f"{channel['display_name']} 채널을 일시정지할까요?"):
            return

        ok = self.channel_registry.set_channel_active(channel["channel_id"], False)
        if ok:
            self.status_label.configure(text="채널을 일시정지했습니다.", text_color="green")
            self._refresh_data_async()
        else:
            messagebox.showerror("오류", "채널 상태를 변경하지 못했습니다.")

    def _activate_channel(self, channel: Dict[str, Any]):
        ok = self.channel_registry.set_channel_active(channel["channel_id"], True)
        if ok:
            self.status_label.configure(text="채널을 활성화했습니다.", text_color="green")
            self._refresh_data_async()
        else:
            messagebox.showerror("오류", "채널 상태를 변경하지 못했습니다.")

    def _show_channel_detail(self, channel: Dict[str, Any]):
        lang_label = SUPPORTED_LANGUAGES.get(channel["target_language"], channel["target_language"])
        info = (
            f"채널 ID: {channel['channel_id']}\n"
            f"이름: {channel['display_name']}\n"
            f"타입: {channel['channel_type']}\n"
            f"언어: {lang_label}\n"
            f"상태: {'활성' if channel['is_active'] else '일시정지'}\n"
            f"우선순위: {channel['priority']}\n"
            f"일일 쿼터: {channel['today_video_count']}/{channel['daily_video_limit']}\n"
            f"누적 생산: {channel['total_videos']}\n"
            f"누적 조회: {channel['total_views']:,}\n"
            f"업데이트: {channel['updated_at']}"
        )
        messagebox.showinfo("채널 상세", info)

    def _edit_channel(self, channel: Dict[str, Any]):
        dialog = self._create_modal("채널 설정 수정", "420x330")
        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(frame, text=channel["display_name"], font=get_font("large", bold=True)).pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(frame, text="표시 이름", font=get_font("small")).pack(anchor="w")
        name_entry = ctk.CTkEntry(frame)
        name_entry.pack(fill="x", pady=(0, 10))
        name_entry.insert(0, channel["display_name"])

        ctk.CTkLabel(frame, text="우선순위", font=get_font("small")).pack(anchor="w")
        priority_entry = ctk.CTkEntry(frame)
        priority_entry.pack(fill="x", pady=(0, 10))
        priority_entry.insert(0, str(channel["priority"]))

        ctk.CTkLabel(frame, text="일일 쿼터", font=get_font("small")).pack(anchor="w")
        daily_entry = ctk.CTkEntry(frame)
        daily_entry.pack(fill="x", pady=(0, 10))
        daily_entry.insert(0, str(channel["daily_video_limit"]))

        ctk.CTkLabel(frame, text="대상 언어", font=get_font("small")).pack(anchor="w")
        language_var = ctk.StringVar(value=channel["target_language"])
        language_combo = ctk.CTkComboBox(
            frame,
            values=list(SUPPORTED_LANGUAGES.keys()),
            variable=language_var,
        )
        language_combo.pack(fill="x", pady=(0, 10))

        status_label = ctk.CTkLabel(frame, text="", font=get_font("small"))
        status_label.pack(anchor="w", pady=(4, 0))

        def save():
            try:
                priority = int(priority_entry.get().strip())
                daily_limit = int(daily_entry.get().strip())
            except ValueError:
                status_label.configure(text="우선순위와 일일 쿼터는 숫자로 입력해야 합니다.", text_color="red")
                return

            language = language_var.get().strip()
            if language not in SUPPORTED_LANGUAGES:
                status_label.configure(text="지원하지 않는 언어 코드입니다.", text_color="red")
                return

            ok = self.channel_registry.update_channel(
                channel["channel_id"],
                display_name=name_entry.get().strip() or channel["display_name"],
                priority=priority,
                daily_video_limit=daily_limit,
                target_language=language,
            )
            if not ok:
                status_label.configure(text="채널 설정 저장에 실패했습니다.", text_color="red")
                return

            self.status_label.configure(text="채널 설정을 저장했습니다.", text_color="green")
            dialog.destroy()
            self._refresh_data_async()

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.pack(fill="x", pady=(16, 0))
        ctk.CTkButton(button_row, text="저장", font=get_font("normal"), command=save).pack(side="left")
        ctk.CTkButton(
            button_row,
            text="취소",
            font=get_font("normal"),
            fg_color="#555555",
            command=dialog.destroy,
        ).pack(side="left", padx=(8, 0))

    def _replace_owned_packs(self, license_key: str, current_packs: List[str], new_packs: List[str]) -> Tuple[bool, str]:
        if not self.firebase_validator:
            return False, "Firebase 연결이 없습니다."
        normalized_packs = self._normalize_owned_packs(new_packs)
        return self.firebase_validator.update_license(license_key, owned_packs=normalized_packs)

    @staticmethod
    def _normalize_owned_packs(packs: List[str]) -> List[str]:
        normalized: List[str] = []
        for pack_id in packs or []:
            value = str(pack_id).strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _update_license_record(
        self,
        account: Dict[str, Any],
        user_id: str,
        memo: str,
        hardware_id: str,
        owned_packs: List[str],
    ) -> Tuple[bool, str]:
        if not self.firebase_validator:
            return False, "Firebase 연결이 없습니다."

        license_key = account["license_key"]
        success, message = self.firebase_validator.update_license(
            license_key,
            user_id=user_id,
            memo=memo,
            hardware_id=hardware_id,
            owned_packs=self._normalize_owned_packs(owned_packs),
        )
        if not success:
            return False, message

        return True, "라이센스 정보를 수정했습니다."

    def _edit_account(self, account: Dict[str, Any]):
        dialog = self._create_modal("라이센스 수정", "520x430")
        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            frame,
            text=account.get("license_key", "-"),
            font=get_font("large", bold=True),
        ).pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(frame, text="사용자 ID", font=get_font("small")).pack(anchor="w")
        user_entry = ctk.CTkEntry(frame)
        user_entry.pack(fill="x", pady=(0, 10))
        user_entry.insert(0, account.get("user_id", ""))

        ctk.CTkLabel(frame, text="하드웨어 ID", font=get_font("small")).pack(anchor="w")
        hardware_entry = ctk.CTkEntry(frame)
        hardware_entry.pack(fill="x", pady=(0, 10))
        hardware_entry.insert(0, account.get("hardware_id", ""))

        ctk.CTkLabel(frame, text="보유 팩 (쉼표 구분)", font=get_font("small")).pack(anchor="w")
        packs_entry = ctk.CTkEntry(frame)
        packs_entry.pack(fill="x", pady=(0, 10))
        packs_entry.insert(0, ", ".join(account.get("owned_packs", [])))

        ctk.CTkLabel(frame, text="관리자 메모", font=get_font("small")).pack(anchor="w")
        memo_text = ctk.CTkTextbox(frame, height=120)
        memo_text.pack(fill="both", expand=True, pady=(0, 10))
        memo_text.insert("1.0", account.get("memo", ""))

        status_label = ctk.CTkLabel(frame, text="", font=get_font("small"))
        status_label.pack(anchor="w", pady=(4, 0))

        def save():
            owned_packs = [item.strip() for item in packs_entry.get().split(",") if item.strip()]
            self._start_job(
                f"license_edit_{account['license_key']}",
                lambda: self._update_license_record(
                    account,
                    user_entry.get().strip(),
                    memo_text.get("1.0", "end").strip(),
                    hardware_entry.get().strip(),
                    owned_packs,
                ),
                on_success=lambda result: self._after_modal_license_action(dialog, result),
                on_error=lambda exc: status_label.configure(text=f"저장 실패: {exc}", text_color="red"),
                busy_text="라이센스 정보를 저장하는 중입니다...",
            )

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.pack(fill="x", pady=(12, 0))
        ctk.CTkButton(button_row, text="저장", font=get_font("normal"), command=save).pack(side="left")
        ctk.CTkButton(
            button_row,
            text="취소",
            font=get_font("normal"),
            fg_color="#555555",
            command=dialog.destroy,
        ).pack(side="left", padx=(8, 0))

    def _after_modal_license_action(self, dialog, result: Tuple[bool, str]):
        success, message = result
        self.status_label.configure(text=message, text_color="green" if success else "red")
        if success:
            dialog.destroy()
            self._refresh_data_async()

    def _extend_account(self, account: Dict[str, Any]):
        dialog = self._create_modal("라이센스 연장", "360x220")
        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            frame,
            text=account.get("user_id", "-"),
            font=get_font("large", bold=True),
        ).pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(frame, text="추가 일수", font=get_font("small")).pack(anchor="w")
        days_entry = ctk.CTkEntry(frame)
        days_entry.pack(fill="x", pady=(0, 10))
        days_entry.insert(0, "30")

        status_label = ctk.CTkLabel(frame, text="", font=get_font("small"))
        status_label.pack(anchor="w", pady=(4, 0))

        def save():
            try:
                days = int(days_entry.get().strip())
            except ValueError:
                status_label.configure(text="연장 일수는 숫자로 입력해야 합니다.", text_color="red")
                return
            if days <= 0:
                status_label.configure(text="연장 일수는 1일 이상이어야 합니다.", text_color="red")
                return

            self._start_job(
                f"license_extend_{account['license_key']}",
                lambda: self.firebase_validator.extend_license(account["license_key"], days),
                on_success=lambda result: self._after_modal_license_action(dialog, result),
                on_error=lambda exc: status_label.configure(text=f"연장 실패: {exc}", text_color="red"),
                busy_text="라이센스를 연장하는 중입니다...",
            )

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.pack(fill="x", pady=(16, 0))
        ctk.CTkButton(button_row, text="연장", font=get_font("normal"), command=save).pack(side="left")
        ctk.CTkButton(
            button_row,
            text="취소",
            font=get_font("normal"),
            fg_color="#555555",
            command=dialog.destroy,
        ).pack(side="left", padx=(8, 0))

    def _delete_account(self, account: Dict[str, Any]):
        if not self.firebase_validator:
            messagebox.showerror("오류", "Firebase 연결이 없습니다.")
            return
        if not messagebox.askyesno(
            "라이센스 삭제",
            f"{account.get('user_id', '-')}\n{account.get('license_key', '-')}\n이 라이센스를 삭제할까요?",
        ):
            return

        self._start_job(
            f"license_delete_{account['license_key']}",
            lambda: self.firebase_validator.delete_license(account["license_key"]),
            on_success=self._after_license_action,
            on_error=lambda exc: self.status_label.configure(text=f"삭제 실패: {exc}", text_color="red"),
            busy_text="라이센스를 삭제하는 중입니다...",
        )

    def _suspend_account(self, account: Dict[str, Any]):
        if not self.firebase_validator:
            messagebox.showerror("오류", "Firebase 연결이 없습니다.")
            return
        if not messagebox.askyesno("라이센스 비활성", f"{account.get('user_id', '')} 라이센스를 비활성화할까요?"):
            return

        self._start_job(
            f"license_off_{account['license_key']}",
            lambda: self.firebase_validator.deactivate_license(account["license_key"]),
            on_success=self._after_license_action,
            busy_text="라이센스를 비활성화하는 중입니다...",
        )

    def _activate_account(self, account: Dict[str, Any]):
        if not self.firebase_validator:
            messagebox.showerror("오류", "Firebase 연결이 없습니다.")
            return

        self._start_job(
            f"license_on_{account['license_key']}",
            lambda: self.firebase_validator.activate_license(account["license_key"]),
            on_success=self._after_license_action,
            busy_text="라이센스를 활성화하는 중입니다...",
        )

    def _after_license_action(self, result: Tuple[bool, str]):
        success, message = result
        self.status_label.configure(text=message, text_color="green" if success else "red")
        if success:
            self._refresh_data_async()

    def _show_account_detail(self, account: Dict[str, Any]):
        packs = account.get("owned_packs", [])
        pack_text = "\n".join(f"- {pack}" for pack in packs) if packs else "(없음)"
        expire_date = account.get("expire_date")
        if hasattr(expire_date, "strftime"):
            expire_text = expire_date.strftime("%Y-%m-%d %H:%M")
        else:
            expire_text = str(expire_date) if expire_date else "-"

        memo = account.get("memo") or "-"
        info = (
            f"사용자 ID: {account.get('user_id', '-')}\n"
            f"라이센스 키: {account.get('license_key', '-')}\n"
            f"타입: {account.get('license_type', '-')}\n"
            f"만료: {expire_text}\n"
            f"활성: {'예' if account.get('is_active', False) else '아니오'}\n"
            f"하드웨어 ID: {account.get('hardware_id', '-')}\n"
            f"메모: {memo}\n\n"
            f"보유 팩:\n{pack_text}"
        )
        messagebox.showinfo("라이센스 상세", info)
