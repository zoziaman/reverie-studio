from types import SimpleNamespace

import pipeline.orchestrator as orchestrator


def _make_factory(channel: str = "senior", cfg: dict | None = None):
    factory = orchestrator.MediaFactory.__new__(orchestrator.MediaFactory)
    factory.channel = channel
    factory.cfg = cfg or {}
    return factory


def test_get_bgm_folder_uses_current_channel_when_pack_requests_channel_bgm_true(tmp_path, monkeypatch):
    bgm_dir = tmp_path / "bgm" / "senior" / "touching"
    bgm_dir.mkdir(parents=True)

    monkeypatch.setattr(orchestrator.config, "ASSETS_DIR", str(tmp_path))
    monkeypatch.setattr(orchestrator, "PACK_CONFIG_AVAILABLE", True)
    monkeypatch.setattr(
        orchestrator,
        "ACTIVE_PACK",
        SimpleNamespace(
            is_loaded=True,
            assets=SimpleNamespace(use_channel_bgm=True),
        ),
    )

    factory = _make_factory(
        cfg={
            "bgm_touching": "fallback-touching",
            "bgm_makjang": "fallback-makjang",
        }
    )

    assert factory._get_bgm_folder("touching") == str(bgm_dir)


def test_get_bgm_folder_falls_back_cleanly_on_invalid_pack_channel(monkeypatch, caplog):
    monkeypatch.setattr(orchestrator, "PACK_CONFIG_AVAILABLE", True)
    monkeypatch.setattr(
        orchestrator,
        "ACTIVE_PACK",
        SimpleNamespace(
            is_loaded=True,
            assets=SimpleNamespace(use_channel_bgm="bogus"),
        ),
    )

    factory = _make_factory(
        cfg={
            "bgm_touching": "fallback-touching",
            "bgm_makjang": "fallback-makjang",
        }
    )

    with caplog.at_level("WARNING"):
        result = factory._get_bgm_folder("touching")

    assert result == "fallback-touching"
    assert "유효하지 않은 use_channel_bgm 값" in caplog.text
    assert "⚠️" not in caplog.text
