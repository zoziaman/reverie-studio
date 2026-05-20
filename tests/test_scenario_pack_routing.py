from types import SimpleNamespace

from modules_pro.scenario_planner import ScenarioPlanner


def test_ensure_active_pack_routes_specific_senior_mode(monkeypatch):
    planner = object.__new__(ScenarioPlanner)
    active_pack = SimpleNamespace(pack_id="horror_v59", channel_type="horror")
    calls = []

    def fake_load_pack_by_id(pack_id):
        calls.append(pack_id)
        if pack_id == "senior_scam_alert":
            active_pack.pack_id = "senior_scam_alert"
            active_pack.channel_type = "senior_scam_alert"
            return True
        return False

    monkeypatch.setattr("modules_pro.scenario_planner.PACK_CONFIG_AVAILABLE", True)
    monkeypatch.setattr("modules_pro.scenario_planner.ACTIVE_PACK", active_pack)
    monkeypatch.setattr("modules_pro.scenario_planner.load_pack_by_id", fake_load_pack_by_id)
    monkeypatch.setattr("modules_pro.scenario_planner.load_default_pack", lambda genre: True)

    planner._ensure_active_pack("senior", "scam_alert")

    assert calls == ["senior_scam_alert"]
    assert active_pack.pack_id == "senior_scam_alert"


def test_ensure_active_pack_skips_reload_when_matching(monkeypatch):
    planner = object.__new__(ScenarioPlanner)
    active_pack = SimpleNamespace(pack_id="senior_life_saguk", channel_type="senior_life_saguk")

    monkeypatch.setattr("modules_pro.scenario_planner.PACK_CONFIG_AVAILABLE", True)
    monkeypatch.setattr("modules_pro.scenario_planner.ACTIVE_PACK", active_pack)
    monkeypatch.setattr(
        "modules_pro.scenario_planner.load_pack_by_id",
        lambda pack_id: (_ for _ in ()).throw(AssertionError("should not reload matching pack")),
    )
    monkeypatch.setattr("modules_pro.scenario_planner.load_default_pack", lambda genre: True)

    planner._ensure_active_pack("senior", "life_saguk")
