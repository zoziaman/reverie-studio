from gui.mixins.production_mixin import ProductionMixin


class _DummyPackage:
    def __init__(self, package_id, channel_type):
        self.package_id = package_id
        self.channel_type = channel_type


class _DummyPM:
    def __init__(self, package):
        self._package = package

    def get_channel(self, channel_id):
        return self._package


class _DummyMixin(ProductionMixin):
    pass


def test_get_channel_mode_recovers_specific_mode_from_legacy_channel_entry(monkeypatch):
    package = _DummyPackage(package_id="senior_life_saguk", channel_type="senior")

    monkeypatch.setattr(
        "utils.package_manager.get_package_manager",
        lambda: _DummyPM(package),
    )

    mixin = _DummyMixin()
    channel, mode = mixin._get_channel_mode_from_package("senior_senior_life_saguk")

    assert channel == "senior"
    assert mode == "life_saguk"
