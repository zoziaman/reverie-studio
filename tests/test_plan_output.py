from modules_pro.plan_output import build_final_plan, resolve_part_instructions


def test_resolve_part_instructions_uses_outline_metadata():
    inst1, inst2, inst3 = resolve_part_instructions(
        {
            "p1_goal": "opening",
            "p2_goal": "middle",
            "p3_goal": "ending",
            "last_line": "The truth is already in the room.",
            "open_question": "Who hid it first?",
        }
    )

    assert inst1 == "opening"
    assert inst2 == "middle"
    assert "ending" in inst3
    assert "last_line" in inst3
    assert "open_question" in inst3


def test_build_final_plan_includes_optional_outline_title():
    plan = build_final_plan(
        project_name="proj",
        category="horror",
        mode="horror",
        topic="topic",
        story_bible="story bible",
        meta={"title": "title"},
        hook="hook",
        cold_open=[],
        script_list=[],
        visual_scenes=[],
        quality_gate={"passed": True},
        story_outline={"title": "Outline Title", "p1_goal": "opening"},
    )

    assert plan["project_name"] == "proj"
    assert plan["quality_gate"]["passed"] is True
    assert plan["story_outline"]["title"] == "Outline Title"
    assert plan["outline_title"] == "Outline Title"


def test_build_final_plan_includes_shorts_and_motiontoon_when_present():
    plan = build_final_plan(
        project_name="proj",
        category="senior",
        mode="touching",
        topic="topic",
        story_bible="story bible",
        meta={"title": "title"},
        hook="hook",
        cold_open=[],
        script_list=[],
        visual_scenes=[],
        quality_gate={"passed": True},
        shorts_plan={"enabled": True, "title": "Short title #Shorts"},
        motiontoon_plan={"enabled": True, "mode": "screen_space", "scenes": [{"scene_type": "reveal"}]},
    )

    assert plan["shorts_plan"]["enabled"] is True
    assert plan["shorts_plan"]["title"].endswith("#Shorts")
    assert plan["motiontoon_plan"]["enabled"] is True
    assert plan["motiontoon_plan"]["scenes"][0]["scene_type"] == "reveal"
