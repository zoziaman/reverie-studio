import json
from pathlib import Path

from reverie_env_bootstrap import bootstrap_env_file, main


def test_env_bootstrap_creates_env_from_template_without_secret_values(tmp_path):
    template = tmp_path / ".env.example"
    template.write_text("GEMINI_API_KEY=\nSD_URL=http://127.0.0.1:7860\n", encoding="utf-8")

    report = bootstrap_env_file(tmp_path)

    assert report["schema"] == "reverie.local.env_bootstrap.v1"
    assert report["status"] == "created"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == template.read_text(encoding="utf-8")
    assert report["safety"]["overwrites_existing_env"] is False
    assert report["safety"]["prints_secret_values"] is False
    assert "GEMINI_API_KEY=" not in json.dumps(report)


def test_env_bootstrap_does_not_overwrite_existing_env_without_force(tmp_path):
    (tmp_path / ".env.example").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    existing = tmp_path / ".env"
    existing.write_text("GEMINI_API_KEY=keep-me\n", encoding="utf-8")

    report = bootstrap_env_file(tmp_path)

    assert report["status"] == "exists"
    assert existing.read_text(encoding="utf-8") == "GEMINI_API_KEY=keep-me\n"
    assert "already exists" in report["message"]


def test_env_bootstrap_reports_missing_template(tmp_path):
    report = bootstrap_env_file(tmp_path)

    assert report["status"] == "missing_template"
    assert report["exit_code"] == 1
    assert "Restore .env.example" in report["next_action"]


def test_env_bootstrap_cli_writes_report(tmp_path, capsys):
    (tmp_path / ".env.example").write_text("TEST_MODE=true\n", encoding="utf-8")
    out = tmp_path / "env_bootstrap_report.json"

    exit_code = main(["--repo-root", str(tmp_path), "--json", "--out", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "created"
    printed = capsys.readouterr().out
    assert "reverie.local.env_bootstrap.v1" in printed
