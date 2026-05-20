from pathlib import Path


def test_hook_renders_all_wrapped_lines():
    source = Path(__file__).resolve().parents[1] / "remotion-poc" / "src" / "RadioDrama.tsx"
    text = source.read_text(encoding="utf-8")

    assert "const displayLines = lines.map" in text
    assert "index === lines.length - 1" in text
