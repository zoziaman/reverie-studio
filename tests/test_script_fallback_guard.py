import pytest

from modules_pro import scenario_planner as planner_module
from modules_pro.scenario_planner import FallbackScriptError, ScenarioPlanner


class _DummyWriter:
    def __init__(self, role_name, result):
        self.role_name = role_name
        self._result = result

    def write_part(self, *args, **kwargs):
        return list(self._result)


class _DummyPD:
    def package_content(self, *args, **kwargs):
        return {"title": "title", "description": "desc", "tags": "tag"}


class _DummyVisualDirector:
    def create_scenes(self, *args, **kwargs):
        return []


def _make_planner(fallback_script):
    planner = ScenarioPlanner.__new__(ScenarioPlanner)
    planner.pd = _DummyPD()
    planner.visual_director = _DummyVisualDirector()
    planner.writer1 = _DummyWriter("writer1", fallback_script)
    planner.writer2 = _DummyWriter("writer2", [])
    planner.writer3 = _DummyWriter("writer3", [])
    planner._local_validate = lambda script, outline: ([], False)
    planner._extract_cold_open = lambda script: []
    return planner


def test_execute_plan_rejects_fallback_script(monkeypatch, tmp_path):
    monkeypatch.setattr(planner_module.config, "TEST_MODE", True, raising=False)
    monkeypatch.setattr(planner_module.config, "TEST_TURNS_PER_PART", 2, raising=False)
    monkeypatch.setattr(planner_module.config, "TEST_IMAGE_COUNT", 1, raising=False)
    monkeypatch.setattr(planner_module.config, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(planner_module.progress_callback, "set_total_steps", lambda *args, **kwargs: None)
    monkeypatch.setattr(planner_module.progress_callback, "reset", lambda *args, **kwargs: None)
    monkeypatch.setattr(planner_module.progress_callback, "update", lambda *args, **kwargs: None)

    fallback_script = [
        {"role": "나레이션", "voice_type": "narrator", "text": "fallback", "emotion": "calm", "_is_fallback": True},
        {"role": "남자", "voice_type": "young_man", "text": "fallback2", "emotion": "worried", "_is_fallback": True},
    ]
    planner = _make_planner(fallback_script)

    with pytest.raises(FallbackScriptError, match="writer1|Part 1|fallback"):
        planner._execute_plan_with_bible(
            "horror",
            "horror",
            "테스트 주제",
            "스토리 바이블",
            {"p1_goal": "시작", "p2_goal": "중간", "p3_goal": "끝"},
        )
