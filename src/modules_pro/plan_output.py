from typing import Any, Dict, List, Optional, Tuple


def resolve_part_instructions(story_outline: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    """아웃라인을 파트별 집필 지시문으로 변환한다."""
    if not story_outline:
        return (
            "이야기 시작. 배경/인물/초기 갈등 제시. 결말 금지.",
            "사건 본격화. 갈등 폭발. 위기 고조.",
            "반전과 결말. 떡밥 회수.",
        )

    inst1 = story_outline.get("p1_goal", "이야기 시작. 배경/인물/초기 갈등 제시. 결말 금지.")
    inst2 = story_outline.get("p2_goal", "사건 본격화. 갈등 폭발. 위기 고조.")
    inst3 = story_outline.get("p3_goal", "반전과 결말. 떡밥 회수.")
    outline_extras = []
    for key in ["last_line", "last_speaker", "twist_reveal", "catharsis_moment", "open_question"]:
        value = story_outline.get(key)
        if value:
            outline_extras.append(f"- {key}: {value}")
    if outline_extras:
        inst3 = inst3 + "\n[아웃라인 참고]\n" + "\n".join(outline_extras)
    return inst1, inst2, inst3


def build_final_plan(
    *,
    project_name: str,
    category: str,
    mode: str,
    topic: str,
    story_bible: str,
    meta: Dict[str, Any],
    hook: str,
    cold_open: List[Dict[str, Any]],
    script_list: List[Dict[str, Any]],
    visual_scenes: List[Any],
    quality_gate: Dict[str, Any],
    story_outline: Optional[Dict[str, Any]] = None,
    shorts_plan: Optional[Dict[str, Any]] = None,
    motiontoon_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """최종 계획 JSON 구조를 조립한다."""
    final_plan = {
        "project_name": project_name,
        "category": category,
        "mode": mode,
        "topic": topic,
        "story_bible": story_bible,
        "title": meta.get("title", topic),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", ""),
        "thumbnail_text": meta.get("thumbnail_text", "화제의 영상"),
        "thumbnail_title": meta.get("thumbnail_title", ""),
        "hook": hook,
        "cold_open": cold_open,
        "script_list": script_list,
        "visual_scenes": visual_scenes,
        "quality_gate": quality_gate,
    }
    if shorts_plan:
        final_plan["shorts_plan"] = shorts_plan
    if motiontoon_plan:
        final_plan["motiontoon_plan"] = motiontoon_plan
    if story_outline:
        final_plan["story_outline"] = story_outline
        outline_title = story_outline.get("title", "")
        if outline_title and len(outline_title) > 2:
            final_plan["outline_title"] = outline_title
    return final_plan
