from gui.mixins.server_mixin import probe_http_endpoints, safe_after
from gui.mixins.settings_mixin import SettingsMixin


class _DummyVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _DummySettings(SettingsMixin):
    def __init__(self, channel_id):
        self.channel_var = _DummyVar(channel_id)

    def _safe_get_var(self, attr_name: str, default=None):
        if attr_name == "channel_var":
            return self.channel_var.get()
        return default

    def _get_channel_mode_from_package(self, channel_id: str):
        if channel_id == "senior_scam_alert":
            return ("senior", "scam_alert")
        return ("horror", "horror")


class _DummyWidget:
    def __init__(self, exists=True, shutting_down=False, raises=False):
        self._exists = exists
        self._is_shutting_down = shutting_down
        self._raises = raises
        self.scheduled = []

    def winfo_exists(self):
        return self._exists

    def after(self, delay, callback):
        if self._raises:
            raise RuntimeError("main thread is not in main loop")
        self.scheduled.append((delay, callback))


def test_probe_http_endpoints_accepts_secondary_success(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, status_code):
            self.status_code = status_code

    def _fake_get(url, timeout):
        calls.append(url)
        if url.endswith("/"):
            return _Resp(404)
        if url.endswith("/docs"):
            return _Resp(200)
        return _Resp(500)

    monkeypatch.setattr("requests.get", _fake_get)

    assert probe_http_endpoints("http://127.0.0.1:9880", ["/", "/docs"], timeout=3) is True
    assert calls == [
        "http://127.0.0.1:9880/",
        "http://127.0.0.1:9880/docs",
    ]


def test_safe_after_skips_shutdown_or_tk_teardown():
    shutting_down = _DummyWidget(shutting_down=True)
    destroyed = _DummyWidget(exists=False)
    broken = _DummyWidget(raises=True)

    assert safe_after(shutting_down, lambda: None) is False
    assert safe_after(destroyed, lambda: None) is False
    assert safe_after(broken, lambda: None) is False


def test_safe_after_schedules_when_widget_alive():
    widget = _DummyWidget()

    assert safe_after(widget, lambda: None, delay=25) is True
    assert len(widget.scheduled) == 1
    assert widget.scheduled[0][0] == 25


def test_resolve_auto_optimizer_target_uses_selected_pack():
    mixin = _DummySettings("senior_scam_alert")

    channel_type, channel_id = mixin._resolve_auto_optimizer_target()

    assert channel_type == "senior"
    assert channel_id == "senior_scam_alert"
