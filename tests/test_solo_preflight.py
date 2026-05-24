import json
from pathlib import Path

from reverie_solo_preflight import run_solo_preflight, main


ROOT = Path(__file__).resolve().parents[1]


def test_solo_preflight_runs_safe_daily_checks_and_writes_reports(tmp_path):
    report = run_solo_preflight(repo_root=ROOT, output_dir=tmp_path)

    assert report["schema"] == "reverie.local.solo_preflight.v1"
    assert report["overall_status"] in {"ready", "warnings", "needs_setup"}
    assert report["checks"]["solo_status"]["status"] in {"ready", "warnings", "needs_setup"}
    assert report["checks"]["environment_doctor"]["status"] in {"pass", "needs_setup"}
    assert report["checks"]["dry_run"]["status"] == "pass"
    assert report["checks"]["dry_run"]["final_status"] == "needs_human_review"
    assert report["safety"]["calls_external_services"] is False
    assert report["safety"]["starts_local_services"] is False
    assert report["safety"]["creates_media"] is False
    assert Path(report["artifacts"]["dry_run_manifest"]).parts[-2:] == ("dry_run", "run_manifest.json")
    assert (tmp_path / "dry_run" / "run_manifest.json").exists()
    assert "GEMINI_API_KEY=" not in json.dumps(report)


def test_solo_preflight_cli_writes_json_report(tmp_path, capsys):
    out_dir = tmp_path / "preflight"

    exit_code = main(["--repo-root", str(ROOT), "--out", str(out_dir), "--json"])

    assert exit_code == 0
    payload = json.loads((out_dir / "solo_preflight_report.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "reverie.local.solo_preflight.v1"
    printed = capsys.readouterr().out
    assert "reverie.local.solo_preflight.v1" in printed
