from facades.config_facade import ConfigFacade


def test_config_facade_returns_default_style_without_settings_manager():
    facade = ConfigFacade()
    facade._settings_manager_unavailable = True

    style = facade.get_channel_style("senior")

    assert style == {"bgm_volume": 0.18, "subtitle_size": 42, "speaker_size": 32}


def test_config_facade_returns_copy_of_default_style():
    style = ConfigFacade._default_channel_style("unknown")
    style["bgm_volume"] = 99

    fresh = ConfigFacade._default_channel_style("unknown")

    assert fresh == {"bgm_volume": 0.15, "subtitle_size": 36, "speaker_size": 28}


def test_config_facade_uses_existing_settings_manager_when_available():
    class DummySettingsManager:
        def get_channel_style(self, channel: str):
            assert channel == "horror"
            return {"bgm_volume": 0.33, "subtitle_size": 41, "speaker_size": 30}

    facade = ConfigFacade()
    facade._settings_manager = DummySettingsManager()

    style = facade.get_channel_style("horror")

    assert style == {"bgm_volume": 0.33, "subtitle_size": 41, "speaker_size": 30}
