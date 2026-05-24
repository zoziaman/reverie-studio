import json
from pathlib import Path

from reverie_solo_handoff import build_solo_handoff_report, main


ROOT = Path(__file__).resolve().parents[1]


def test_solo_handoff_report_collects_safe_session_context(tmp_path):
    report = build_solo_handoff_report(repo_root=ROOT, output_dir=tmp_path)

    assert report["schema"] == "reverie.local.solo_handoff.v1"
    assert report["repo_root"] == str(ROOT)
    assert report["checks"]["solo_status"]["status"] in {"ready", "warnings", "needs_setup"}
    assert report["checks"]["preflight"]["status"] in {"ready", "warnings", "needs_setup"}
    assert report["git"]["branch"]
    assert isinstance(report["git"]["status_short"], list)
    assert report["artifacts"]["markdown"].endswith("solo_handoff.md")
    assert (tmp_path / "solo_handoff.md").exists()
    assert "GEMINI_API_KEY=" not in json.dumps(report)


def test_solo_handoff_cli_writes_json_and_markdown(tmp_path, capsys):
    exit_code = main(["--repo-root", str(ROOT), "--out", str(tmp_path), "--json"])

    assert exit_code in {0, 1}
    payload = json.loads((tmp_path / "solo_handoff_report.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "solo_handoff.md").read_text(encoding="utf-8")
    printed = capsys.readouterr().out

    assert payload["schema"] == "reverie.local.solo_handoff.v1"
    assert "# Reverie Solo Handoff" in markdown
    assert "reverie.local.solo_handoff.v1" in printed
