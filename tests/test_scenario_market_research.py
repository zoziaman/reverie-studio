from types import ModuleType, SimpleNamespace
import sys


fake_qwen_adapter = ModuleType("modules_pro.tts_qwen3_adapter")
fake_qwen_adapter.normalize_emotion = lambda emotion: emotion
sys.modules.setdefault("modules_pro.tts_qwen3_adapter", fake_qwen_adapter)

from modules_pro import scenario_planner as sp


class FakeModel:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def generate_content(self, prompt, generation_config=None, timeout=None):
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.text)


def _fake_bundle():
    return SimpleNamespace(
        context=(
            "[Market Research Context]\n"
            "- source: 정책브리핑\n"
            "- trend: 오픈뱅킹 안심차단과 가족 알림 사각지대\n"
            "- story angle: 가족이 뒤늦게 등록 알림을 확인한다\n"
        ),
        cards=[SimpleNamespace(id="open-banking")],
        quality_score=91,
        warnings=[],
    )


def test_chief_producer_topic_prompt_includes_market_research(monkeypatch):
    active_pack = SimpleNamespace(
        is_loaded=True,
        pack_name="사기 경보 드라마 채널",
        pack_id="senior_scam_alert",
    )
    model = FakeModel("오픈뱅킹 등록 알림을 놓친 가족의 사기 경보 드라마")
    producer = sp.ChiefProducer(model, SimpleNamespace(get_bans_for_senior=lambda: ""))

    monkeypatch.setattr(sp, "PACK_CONFIG_AVAILABLE", True)
    monkeypatch.setattr(sp, "ACTIVE_PACK", active_pack)
    monkeypatch.setattr(sp, "get_topic_templates", lambda: ["문자 하나로 돈을 잃는 이야기"])
    monkeypatch.setattr(sp, "get_prompt", lambda name, *args: "brand guide")
    monkeypatch.setattr(sp, "build_market_research_context", lambda **kwargs: _fake_bundle())

    topic = producer.create_topic("senior", "scam_alert")

    assert "오픈뱅킹 등록 알림" in topic
    assert "[Market Research Context]" in model.prompts[0]
    assert "그대로 복사하지 말고" in model.prompts[0]


def test_story_blueprint_prompt_and_bible_include_market_research(monkeypatch):
    response = {
        "bible": {
            "setting": "평일 아침 아파트 거실",
            "characters": [
                {"name": "순자", "voice_type": "grandma", "desc": "알림을 늦게 확인한 피해자"}
            ],
            "conflicts": ["가족은 늦은 알림을 두고 서로를 탓한다"],
            "tone": "예방 목적의 현실 드라마",
        },
        "outline": {
            "title": "늦게 울린 알림",
            "twist_type": "오해 반전",
            "p1_goal": "알림 확인",
        },
    }
    model = FakeModel(__import__("json").dumps(response, ensure_ascii=False))
    planner = object.__new__(sp.ScenarioPlanner)
    planner.model = model
    planner.memory = SimpleNamespace(is_similar=lambda text: False)

    active_pack = SimpleNamespace(is_loaded=True, pack_id="senior_scam_alert")
    monkeypatch.setattr(sp, "PACK_CONFIG_AVAILABLE", True)
    monkeypatch.setattr(sp, "ACTIVE_PACK", active_pack)
    monkeypatch.setattr(sp, "get_prompt", lambda name: "BLUEPRINT {{topic}} {{ban_line}}" if name == "story_blueprint" else "")
    monkeypatch.setattr(sp, "get_scenario_pools", lambda: None)
    monkeypatch.setattr(sp, "build_market_research_context", lambda **kwargs: _fake_bundle())

    bible, outline = planner._build_story_blueprint("오픈뱅킹 알림", "senior", "scam_alert")

    assert "[Market Research Context]" in model.prompts[0]
    assert "[Market Research Context]" in bible
    assert outline["title"] == "늦게 울린 알림"
