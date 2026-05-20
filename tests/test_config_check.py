"""Safe config smoke tests.

These tests must not read user-local gui_settings.json files or mutate the
global config at import time. They verify the public default surface only.
"""

from config.settings import config


def test_config_tts_engine_is_supported():
    assert getattr(config, "TTS_ENGINE", "sovits") in {"sovits", "supertonic"}
