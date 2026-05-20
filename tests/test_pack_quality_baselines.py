from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_text(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _read_json(rel_path: str) -> dict:
    with (ROOT / rel_path).open(encoding="utf-8") as handle:
        return json.load(handle)


def test_new_story_packs_have_quality_prompt_baselines() -> None:
    baselines = {
        "assets/packs/senior_scam_alert/prompts/writer_system.txt": 40,
        "assets/packs/senior_scam_alert/prompts/story_bible.txt": 25,
        "assets/packs/senior_scam_alert/prompts/craft_rules.txt": 40,
        "assets/packs/senior_life_saguk/prompts/writer_system.txt": 40,
        "assets/packs/senior_life_saguk/prompts/story_bible.txt": 25,
        "assets/packs/senior_life_saguk/prompts/craft_rules.txt": 40,
    }

    for rel_path, min_lines in baselines.items():
        text = _read_text(rel_path)
        assert len(text.splitlines()) >= min_lines, f"{rel_path} is too thin for production quality"


def test_all_senior_story_packs_define_motiontoon_and_shorts() -> None:
    for rel_path in (
        "assets/packs/senior_touching/settings.json",
        "assets/packs/senior_makjang/settings.json",
        "assets/packs/senior_scam_alert/settings.json",
        "assets/packs/senior_life_saguk/settings.json",
    ):
        data = _read_json(rel_path)
        assert data.get("motiontoon", {}).get("enabled") is True
        assert data.get("shorts", {}).get("enabled") is True
        assert data.get("shorts", {}).get("upload_with_main") is True
