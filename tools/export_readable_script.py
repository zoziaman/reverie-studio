import argparse
import json
from pathlib import Path


def build_markdown(data: dict, source_path: Path) -> str:
    project_name = data.get("project_name", source_path.stem)
    category = data.get("category", "")
    mode = data.get("mode", "")
    topic = data.get("topic", "")
    quality_score = data.get("quality_gate", {}).get("score", "")
    script_list = data.get("script_list", [])
    cold_open = data.get("cold_open", [])

    lines = [
        f"# {project_name}",
        "",
        f"- Source JSON: `{source_path.name}`",
        f"- Category: `{category}`",
        f"- Mode: `{mode}`",
        f"- Quality Score: `{quality_score}`",
        f"- Turns: `{len(script_list)}`",
    ]

    if topic:
        lines.extend(["", "## Topic", "", topic])

    if cold_open:
        lines.extend(["", "## Cold Open", ""])
        for idx, turn in enumerate(cold_open, 1):
            role = turn.get("role", "")
            emotion = turn.get("emotion", "")
            text = turn.get("text", "")
            lines.append(f"{idx}. [{role} / {emotion}] {text}")

    lines.extend(["", "## Script", ""])
    for idx, turn in enumerate(script_list, 1):
        role = turn.get("role", "")
        voice_type = turn.get("voice_type", "")
        emotion = turn.get("emotion", "")
        sfx_tag = turn.get("sfx_tag", "")
        text = turn.get("text", "")

        meta_parts = [part for part in [role, voice_type, emotion] if part]
        meta = " / ".join(meta_parts)
        if sfx_tag:
            meta = f"{meta} / sfx:{sfx_tag}" if meta else f"sfx:{sfx_tag}"
        lines.append(f"{idx:02d}. [{meta}] {text}")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Reverie script JSON to a readable Markdown file.")
    parser.add_argument("json_path", help="Path to the Reverie script JSON file")
    parser.add_argument(
        "--output",
        help="Optional output path. Defaults to <json_path>.readable.md",
    )
    args = parser.parse_args()

    source_path = Path(args.json_path).resolve()
    output_path = Path(args.output).resolve() if args.output else source_path.with_suffix(".readable.md")

    with source_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    markdown = build_markdown(data, source_path)
    output_path.write_text(markdown, encoding="utf-8-sig")

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
