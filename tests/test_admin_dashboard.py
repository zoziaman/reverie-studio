import time
import os
import sys
import tkinter
import tkinter.messagebox as messagebox

import pytest

from utils.channel_registry import ChannelInfo


class FakeChannelRegistry:
    def __init__(self):
        self.channels = {
            "alpha_001": ChannelInfo(
                channel_id="alpha_001",
                channel_type="scam",
                display_name="Alpha Channel",
                is_active=True,
                priority=80,
                daily_video_limit=3,
                today_video_count=1,
                total_videos=12,
                total_views=3456,
            ),
            "beta_001": ChannelInfo(
                channel_id="beta_001",
                channel_type="saguk",
                display_name="Beta Channel",
                is_active=False,
                priority=50,
                daily_video_limit=2,
                today_video_count=0,
                total_videos=5,
                total_views=987,
            ),
        }

    def get_all_channels(self):
        return list(self.channels.values())

    def set_channel_active(self, channel_id, is_active):
        self.channels[channel_id].is_active = is_active
        return True

    def update_channel(self, channel_id, **kwargs):
        channel = self.channels[channel_id]
        for key, value in kwargs.items():
            setattr(channel, key, value)
        return True


class FakeProductionStats:
    def get_daily_trend(self, days=7):
        return [
            {"date": "2026-03-16", "success": 1, "failed": 0},
            {"date": "2026-03-17", "success": 2, "failed": 1},
            {"date": "2026-03-18", "success": 3, "failed": 0},
            {"date": "2026-03-19", "success": 1, "failed": 0},
            {"date": "2026-03-20", "success": 4, "failed": 1},
            {"date": "2026-03-21", "success": 2, "failed": 0},
            {"date": "2026-03-22", "success": 5, "failed": 0},
        ]

    def get_recent_projects(self, limit=8):
        return []

    def get_total_stats(self):
        return {"success": 18, "failed": 2}

    def get_today_stats(self):
        return {"success": 5, "failed": 0}

    def get_success_rate(self):
        return 90.0


class FakeFirebaseValidator:
    def __init__(self):
        self.licenses = {
            "AAA-BBB-CCC-P-ZZZ": {
                "license_key": "AAA-BBB-CCC-P-ZZZ",
                "user_id": "alpha@example.com",
                "license_type": "P",
                "owned_packs": ["horror_pack", "senior_touching_pack"],
                "is_active": True,
                "hardware_id": "ABCDEF1234567890",
                "memo": "alpha memo",
                "expire_date": "2026-04-01",
            },
            "DDD-EEE-FFF-P-ZZZ": {
                "license_key": "DDD-EEE-FFF-P-ZZZ",
                "user_id": "beta@example.com",
                "license_type": "P",
                "owned_packs": ["senior_makjang_pack"],
                "is_active": False,
                "hardware_id": "1234567890ABCDEF",
                "memo": "beta memo",
                "expire_date": "2026-05-01",
            },
        }

    def is_available(self):
        return True

    def get_all_licenses(self):
        return list(self.licenses.values())

    def get_all_package_stats(self):
        return [
            {"pack_id": "horror_pack", "total_count": 1, "active_count": 1},
            {"pack_id": "senior_touching_pack", "total_count": 1, "active_count": 1},
            {"pack_id": "senior_makjang_pack", "total_count": 1, "active_count": 0},
        ]

    def deactivate_license(self, license_key):
        self.licenses[license_key]["is_active"] = False
        return True, "deactivated"

    def activate_license(self, license_key):
        self.licenses[license_key]["is_active"] = True
        return True, "activated"

    def update_license(self, license_key, **kwargs):
        self.licenses[license_key].update(kwargs)
        return True, "updated"

    def extend_license(self, license_key, additional_days):
        self.licenses[license_key]["expire_date"] = f"2026-06-{additional_days:02d}"
        return True, "extended"

    def delete_license(self, license_key):
        self.licenses.pop(license_key, None)
        return True, "deleted"

    def add_package_to_license(self, license_key, pack_id):
        packs = self.licenses[license_key].setdefault("owned_packs", [])
        if pack_id not in packs:
            packs.append(pack_id)
        return True, "added"

    def remove_package_from_license(self, license_key, pack_id):
        packs = self.licenses[license_key].setdefault("owned_packs", [])
        if pack_id in packs:
            packs.remove(pack_id)
        return True, "removed"

    def get_package_distribution(self, pack_id):
        licenses = []
        active_count = 0
        for info in self.licenses.values():
            if pack_id in info.get("owned_packs", []):
                licenses.append(
                    {
                        "license_key": info["license_key"],
                        "user_id": info["user_id"],
                        "is_active": info["is_active"],
                        "expire_date": info["expire_date"],
                        "memo": info.get("memo", ""),
                    }
                )
                if info["is_active"]:
                    active_count += 1
        return {
            "pack_id": pack_id,
            "total_count": len(licenses),
            "active_count": active_count,
            "licenses": licenses,
        }


def _spin(root, seconds=0.6):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update_idletasks()
        root.update()
        time.sleep(0.02)


def _patch_messageboxes(monkeypatch):
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: "ok")
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: "ok")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)


def _patch_tcl_env(monkeypatch):
    base = os.path.join(sys.base_prefix, "tcl")
    monkeypatch.setenv("TCL_LIBRARY", os.path.join(base, "tcl8.6"))
    monkeypatch.setenv("TK_LIBRARY", os.path.join(base, "tk8.6"))


def test_admin_dashboard_renders_live_snapshot(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import customtkinter as ctk
    from gui.admin_dashboard import AdminDashboard

    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tcl/Tk unavailable in test environment: {exc}")
    root.withdraw()
    dashboard = None
    try:
        dashboard = AdminDashboard(
            root,
            license_info={"org_name": "Test Org"},
            services={
                "channel_registry": FakeChannelRegistry(),
                "production_stats": FakeProductionStats(),
                "firebase_validator": FakeFirebaseValidator(),
            },
        )
        _spin(root)

        assert "마지막 갱신" in dashboard.status_label.cget("text")
        assert len(dashboard.channels_body.winfo_children()) > 0
        assert len(dashboard.accounts_body.winfo_children()) > 1
    finally:
        if dashboard is not None:
            dashboard.destroy()
        root.destroy()


def test_admin_dashboard_actions_mutate_real_services(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import customtkinter as ctk
    from gui.admin_dashboard import AdminDashboard

    channel_registry = FakeChannelRegistry()
    firebase_validator = FakeFirebaseValidator()

    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tcl/Tk unavailable in test environment: {exc}")
    root.withdraw()
    dashboard = None
    try:
        dashboard = AdminDashboard(
            root,
            services={
                "channel_registry": channel_registry,
                "production_stats": FakeProductionStats(),
                "firebase_validator": firebase_validator,
            },
        )
        _spin(root)

        dashboard._pause_channel({"channel_id": "alpha_001", "display_name": "Alpha Channel"})
        assert channel_registry.channels["alpha_001"].is_active is False

        dashboard._activate_account(firebase_validator.licenses["DDD-EEE-FFF-P-ZZZ"])
        _spin(root)
        assert firebase_validator.licenses["DDD-EEE-FFF-P-ZZZ"]["is_active"] is True
    finally:
        if dashboard is not None:
            dashboard.destroy()
        root.destroy()


def test_admin_dashboard_edit_paths_update_services(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import customtkinter as ctk
    from gui.admin_dashboard import AdminDashboard

    channel_registry = FakeChannelRegistry()
    firebase_validator = FakeFirebaseValidator()

    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tcl/Tk unavailable in test environment: {exc}")
    root.withdraw()
    dashboard = None
    try:
        dashboard = AdminDashboard(
            root,
            services={
                "channel_registry": channel_registry,
                "production_stats": FakeProductionStats(),
                "firebase_validator": firebase_validator,
            },
        )
        _spin(root)

        ok, _message = dashboard._update_license_record(
            firebase_validator.licenses["AAA-BBB-CCC-P-ZZZ"],
            user_id="updated@example.com",
            memo="patched memo",
            hardware_id="FFEEDDCCBBAA",
            owned_packs=["senior_makjang_pack"],
        )
        assert ok is True
        assert firebase_validator.licenses["AAA-BBB-CCC-P-ZZZ"]["user_id"] == "updated@example.com"
        assert firebase_validator.licenses["AAA-BBB-CCC-P-ZZZ"]["memo"] == "patched memo"
        assert firebase_validator.licenses["AAA-BBB-CCC-P-ZZZ"]["owned_packs"] == ["senior_makjang_pack"]

        assert channel_registry.update_channel(
            "alpha_001",
            display_name="Alpha Prime",
            priority=90,
            daily_video_limit=5,
            target_language="en",
        )
        assert channel_registry.channels["alpha_001"].display_name == "Alpha Prime"
        assert channel_registry.channels["alpha_001"].priority == 90
        assert channel_registry.channels["alpha_001"].daily_video_limit == 5
        assert channel_registry.channels["alpha_001"].target_language == "en"
    finally:
        if dashboard is not None:
            dashboard.destroy()
        root.destroy()


def test_update_license_record_sends_owned_packs_in_single_update(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import customtkinter as ctk
    from gui.admin_dashboard import AdminDashboard

    class RecordingFirebaseValidator(FakeFirebaseValidator):
        def __init__(self):
            super().__init__()
            self.update_calls = []

        def update_license(self, license_key, **kwargs):
            self.update_calls.append((license_key, dict(kwargs)))
            return super().update_license(license_key, **kwargs)

        def add_package_to_license(self, license_key, pack_id):
            raise AssertionError("incremental package updates should not be used")

        def remove_package_from_license(self, license_key, pack_id):
            raise AssertionError("incremental package updates should not be used")

    firebase_validator = RecordingFirebaseValidator()

    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tcl/Tk unavailable in test environment: {exc}")
    root.withdraw()
    dashboard = None
    try:
        dashboard = AdminDashboard(
            root,
            services={
                "channel_registry": FakeChannelRegistry(),
                "production_stats": FakeProductionStats(),
                "firebase_validator": firebase_validator,
            },
        )
        _spin(root)

        ok, _message = dashboard._update_license_record(
            firebase_validator.licenses["AAA-BBB-CCC-P-ZZZ"],
            user_id="updated@example.com",
            memo="patched memo",
            hardware_id="FFEEDDCCBBAA",
            owned_packs=["senior_makjang_pack", "senior_makjang_pack"],
        )

        assert ok is True
        assert firebase_validator.update_calls
        _license_key, kwargs = firebase_validator.update_calls[-1]
        assert kwargs["owned_packs"] == ["senior_makjang_pack"]
    finally:
        if dashboard is not None:
            dashboard.destroy()
        root.destroy()
