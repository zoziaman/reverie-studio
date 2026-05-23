"""Public-safe MediaFactory TTS smoke tests."""

from config.settings import config


def test_mediafactory_tts_import_does_not_require_user_gui_settings():
    from modules_pro.media_factory import MediaFactory

    assert MediaFactory is not None


def test_config_tts_engine_default_is_supported():
    assert getattr(config, "TTS_ENGINE", "sovits") in {"sovits", "supertonic"}
