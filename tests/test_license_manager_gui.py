import os
import sys
import time

import tkinter
import tkinter.messagebox as messagebox
import pytest


def _patch_messageboxes(monkeypatch):
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: "ok")
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: "ok")
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: "ok")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)


def _patch_admin_env(monkeypatch):
    monkeypatch.setenv("REVERIE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("REVERIE_ADMIN_ENABLED", "1")
    monkeypatch.setenv("REVERIE_ADMIN_SKIP_PROMPT", "1")


def _patch_tcl_env(monkeypatch):
    base = os.path.join(sys.base_prefix, "tcl")
    monkeypatch.setenv("TCL_LIBRARY", os.path.join(base, "tcl8.6"))
    monkeypatch.setenv("TK_LIBRARY", os.path.join(base, "tk8.6"))


def _create_license_app_or_skip(lg):
    try:
        return lg.LicenseManagerGUI()
    except (tkinter.TclError, RuntimeError) as exc:
        pytest.skip(f"Tk unavailable in test environment: {exc}")


def test_license_generator_decodes_pack_based_type(monkeypatch):
    monkeypatch.setenv("REVERIE_SECRET_KEY", "test-secret-key")
    from utils.license_generator import LicenseGenerator

    generator = LicenseGenerator()
    key = generator.generate(
        user_id="tester@example.com",
        hardware_id="1234567890ABCDEF",
        duration_days=30,
        license_type="P",
    )

    decoded = generator.decode_license(key)

    assert decoded["type_code"] == "P"
    assert decoded["type_desc"] == "Pack-based"


def test_license_manager_verify_displays_pack_based_label(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_admin_env(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import gui.license_generator_gui as lg

    monkeypatch.setattr(lg, "FIREBASE_AVAILABLE", False)

    app = _create_license_app_or_skip(lg)
    try:
        if not app.pack_vars:
            pytest.skip("no public packs are available in this sanitized snapshot")
        app.user_id_entry.delete(0, "end")
        app.user_id_entry.insert(0, "tester@example.com")
        app.hw_id_entry.delete(0, "end")
        app.hw_id_entry.insert(0, "1234567890ABCDEF")

        for _pack_id, var in app.pack_vars.items():
            var.set(False)
        next(iter(app.pack_vars.values())).set(True)

        app._generate_license()
        license_key = app.license_key_entry.get().strip()

        app.verify_key_entry.delete(0, "end")
        app.verify_key_entry.insert(0, license_key)
        app.verify_hw_entry.delete(0, "end")
        app.verify_hw_entry.insert(0, "1234567890ABCDEF")

        app._verify_license()
        result_text = app.verify_result_text.get("1.0", "end")

        assert "팩 기반" in result_text
    finally:
        app.destroy()


def test_generate_prompts_with_ai_runs_in_background(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_admin_env(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import gui.license_generator_gui as lg

    monkeypatch.setattr(lg, "FIREBASE_AVAILABLE", False)

    app = _create_license_app_or_skip(lg)
    try:
        app.pkg_concept_entry.delete(0, "end")
        app.pkg_concept_entry.insert(0, "현대 사기 경보 드라마")

        def fake_run_ai_prompt_generation(concept):
            time.sleep(0.25)
            return {
                "package_id": "scam_alert_pack",
                "display_name": "사기 경보 채널 팩",
                "description": "보이스피싱 경고 드라마용 팩",
                "pd_system_prompt": f"{concept} PD",
                "writer_system_prompt": f"{concept} Writer",
                "sd_positive": "clean motiontoon",
                "sd_negative": "blurry",
                "topic_templates": ["A", "B", "C"],
                "banned_keywords": ["X", "Y"],
            }

        monkeypatch.setattr(app, "_run_ai_prompt_generation", fake_run_ai_prompt_generation)

        started = time.perf_counter()
        app._generate_prompts_with_ai()
        elapsed = time.perf_counter() - started

        assert elapsed < 0.12

        deadline = time.time() + 3.0
        while time.time() < deadline and app.pkg_id_entry.get().strip() != "scam_alert_pack":
            app.update_idletasks()
            app.update()
            time.sleep(0.05)

        assert app.pkg_id_entry.get().strip() == "scam_alert_pack"
        assert "생성했습니다" in app.pkg_status_label.cget("text")
    finally:
        app.destroy()


def test_license_generator_requires_secret(monkeypatch):
    monkeypatch.delenv("REVERIE_SECRET_KEY", raising=False)

    from utils.license_generator import LicenseGenerator

    with pytest.raises(RuntimeError):
        LicenseGenerator()


def test_license_manager_requires_admin_enable_flag(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_tcl_env(monkeypatch)
    monkeypatch.setenv("REVERIE_SECRET_KEY", "test-secret-key")
    monkeypatch.delenv("REVERIE_ADMIN_ENABLED", raising=False)
    monkeypatch.setenv("REVERIE_ADMIN_SKIP_PROMPT", "1")

    import gui.license_generator_gui as lg

    with pytest.raises(PermissionError):
        try:
            app = lg.LicenseManagerGUI()
        except tkinter.TclError as exc:
            pytest.skip(f"Tcl/Tk unavailable in test environment: {exc}")
        app.destroy()


def test_firebase_refresh_error_keeps_previous_rows(monkeypatch):
    _patch_messageboxes(monkeypatch)
    _patch_admin_env(monkeypatch)
    _patch_tcl_env(monkeypatch)

    import gui.license_generator_gui as lg

    class FakeFirebaseValidator:
        def is_available(self):
            return True

        def get_all_licenses(self):
            raise RuntimeError("firebase offline")

    monkeypatch.setattr(lg, "FIREBASE_AVAILABLE", False)

    app = _create_license_app_or_skip(lg)
    try:
        app.firebase_validator = FakeFirebaseValidator()
        app._create_firebase_row = lambda license_data, index: tkinter.Label(
            app.firebase_items_frame,
            text=license_data["license_key"],
        ).pack()

        lg._lg_apply_firebase_list(
            app,
            [
                {"license_key": "AAA-BBB-CCC-P-ZZZ"},
            ]
        )
        initial_count = len(app.firebase_items_frame.winfo_children())
        assert initial_count > 0

        def fake_start_async_job(job_name, task, on_success, on_error, busy_callback=None):
            if busy_callback:
                busy_callback()
            on_error(RuntimeError("firebase offline"))

        monkeypatch.setattr(app, "_start_async_job", fake_start_async_job)

        app._refresh_firebase_list()
        app.update_idletasks()
        app.update()

        assert len(app.firebase_items_frame.winfo_children()) == initial_count
        assert "로드 실패" in app.fb_status_label.cget("text")
    finally:
        app.destroy()
