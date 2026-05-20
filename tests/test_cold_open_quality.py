from modules_pro import scenario_planner as planner_module
from modules_pro.scenario_planner import ScenarioPlanner


class _DummyPD:
    def __init__(self, hook_text=""):
        self.hook_text = hook_text

    def create_powerful_hook(self, topic, category, mode=""):
        return self.hook_text


def test_weak_hook_filter_rejects_generic_openings():
    assert planner_module._is_weak_hook_candidate("이야기가 시작됩니다", topic="폐병원 괴담")
    assert planner_module._is_weak_hook_candidate("그날 밤 모든 것이 시작됐다", topic="폐병원 괴담")
    assert not planner_module._is_weak_hook_candidate("문 열지 마, 거기 있어", topic="폐병원 괴담")


def test_extract_cold_open_prefers_dramatic_dialogue_from_full_script(monkeypatch):
    monkeypatch.setattr(planner_module, "PACK_CONFIG_AVAILABLE", False, raising=False)

    planner = ScenarioPlanner.__new__(ScenarioPlanner)
    script = [
        {"role": "나레이션", "text": "평범한 밤이었다.", "emotion": "calm"},
        {"role": "민수", "text": "진짜 아무도 없는 거지?", "emotion": "worried"},
        {"role": "지연", "text": "괜히 왔나 봐.", "emotion": "worried"},
        {"role": "나레이션", "text": "복도 끝 문이 흔들렸다.", "emotion": "calm"},
        {"role": "민수", "text": "방금 들었어?", "emotion": "scared"},
        {"role": "지연", "text": "장난치지 마.", "emotion": "angry"},
        {"role": "민수", "text": "문 열지 마, 거기 있어!", "emotion": "desperate"},
        {"role": "지연", "text": "뒤에 누가 서 있어.", "emotion": "scared"},
        {"role": "나레이션", "text": "비명은 그제야 터졌다.", "emotion": "calm"},
        {"role": "민수", "text": "우린 여기 오면 안 됐어.", "emotion": "sad"},
    ]

    cold_open = planner._extract_cold_open(script, topic="폐병원 괴담")

    dramatic_turns = [turn for turn in cold_open if not turn.get("_is_bridge")]
    assert dramatic_turns
    assert dramatic_turns[0]["text"] == "문 열지 마, 거기 있어!"
    assert cold_open[-1]["_is_bridge"] is True


def test_select_hook_text_prefers_cold_open_line_over_topic():
    planner = ScenarioPlanner.__new__(ScenarioPlanner)
    planner.pd = _DummyPD("이야기가 시작됩니다")

    cold_open = [
        {"role": "민수", "character": "민수", "text": "문 열지 마, 거기 있어!", "emotion": "desperate"},
        {"role": "나레이션", "character": "narrator", "text": "모든 것은 며칠 전으로 거슬러 올라갑니다.", "emotion": "calm", "_is_bridge": True},
    ]
    script = [
        {"role": "민수", "text": "괜찮아.", "emotion": "calm"},
        {"role": "민수", "text": "문 열지 마, 거기 있어!", "emotion": "desperate"},
    ]

    hook_text = planner._select_hook_text("폐병원 괴담", "horror", "horror", cold_open, script)

    assert hook_text == "문 열지 마, 거기 있어!"


def test_resolve_cold_open_bridge_generates_sentence_instead_of_prompt(monkeypatch):
    class _DummyModel:
        def generate_content(self, prompt, timeout=None, generation_config=None, **kwargs):
            del prompt, timeout, generation_config, kwargs

            class _Response:
                text = "진실은 그날부터 비틀렸다."

            return _Response()

    planner = ScenarioPlanner.__new__(ScenarioPlanner)
    planner.model = _DummyModel()

    monkeypatch.setattr(planner_module, "PACK_CONFIG_AVAILABLE", True, raising=False)
    monkeypatch.setattr(
        planner_module,
        "get_prompt",
        lambda key: (
            "Write ONE short Korean bridge sentence spoken by the narrator immediately after a dramatic cold open.\n\n"
            "Rules:\n- 10-24 Korean characters preferred\n\n"
            "Output: ONE Korean sentence only."
            if key == "cold_open_bridge" else ""
        ),
        raising=False,
    )

    bridge = planner._resolve_cold_open_bridge_text(
        "봉인된 편지의 진실",
        [{"character": "순이", "text": "그 편지는 내가 숨겼어."}],
    )

    assert bridge == "진실은 그날부터 비틀렸다."
