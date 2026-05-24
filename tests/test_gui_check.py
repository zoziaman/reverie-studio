import json
from pathlib import Path

from reverie_gui_check import build_gui_check_report, main


ROOT = Path(__file__).resolve().parents[1]


def test_gui_check_imports_runtime_entrypoints_without_opening_windows(tmp_path):
    report = build_gui_check_report(repo_root=ROOT, output_dir=tmp_path)

    assert report["schema"] == "reverie.local.gui_check.v1"
    assert report["repo_root"] == str(ROOT)
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["main_gui_file"]["status"] == "pass"
    assert checks["import_main_gui"]["status"] == "pass"
    assert checks["import_main_window"]["status"] == "pass"
    assert checks["gui_launchers"]["status"] == "pass"
    assert report["safety"]["opens_windows"] is False
    assert report["safety"]["calls_external_services"] is False
    assert report["safety"]["prints_secret_values"] is False
    assert "GEMINI_API_KEY=" not in json.dumps(report)
    assert (tmp_path / "gui_check_report.json").exists()


def test_gui_check_cli_writes_json_report(tmp_path, capsys):
    exit_code = main(["--repo-root", str(ROOT), "--out", str(tmp_path), "--json"])

    assert exit_code == 0
    payload = json.loads((tmp_path / "gui_check_report.json").read_text(encoding="utf-8"))
    printed = capsys.readouterr().out

    assert payload["schema"] == "reverie.local.gui_check.v1"
    assert payload["overall_status"] == "ready"
    assert "reverie.local.gui_check.v1" in printed
