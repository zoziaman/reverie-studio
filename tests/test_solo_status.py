import json
from pathlib import Path

from reverie_solo_status import build_solo_status_report, main


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_repo(root: Path, *, include_env: bool = True) -> Path:
    _write(root / ".env.example", "GEMINI_API_KEY=\nSD_URL=http://127.0.0.1:7860\n")
    if include_env:
        _write(
            root / ".env",
            "\n".join(
                [
                    "GEMINI_API_KEY=super-secret-value",
                    "SD_URL=http://127.0.0.1:7860",
                    "SOVITS_URL=http://127.0.0.1:9880",
                    "COMFYUI_URL=http://127.0.0.1:8188",
                    "TTS_ENGINE=sovits",
                    "VIDEOTOON_WORKSPACE_ROOT=C:\\local\\videotoon",
                    "",
                ]
            ),
        )
    _write(root / "config" / ".gitkeep")
    _write(root / "data" / ".gitkeep")
    _write(root / "assets" / "packs" / "demo" / "manifest.json", "{}\n")
    _write(root / "examples" / "public_demo_pack.json", "{}\n")
    _write(root / "src" / "main_gui.py", "print('gui')\n")
    _write(root / "src" / "reverie_doctor.py", "print('doctor')\n")
    _write(root / "src" / "reverie_demo.py", "print('demo')\n")
    _write(root / "remotion-poc" / "package.json", "{}\n")
    for name in [
        "run_reverie.bat",
        "run_reverie_silent.bat",
        "run_reverie_doctor.bat",
        "run_reverie_solo_status.bat",
        "run_reverie_setup_env.bat",
        "run_reverie_demo_dry_run.bat",
        "run_reverie_videotoon_smoke.bat",
    ]:
        _write(root / name, "@echo off\n")
    return root


def test_solo_status_reports_personal_readiness_without_secret_values(tmp_path):
    repo = _minimal_repo(tmp_path)

    report = build_solo_status_report(repo)

    assert report["schema"] == "reverie.local.solo_status.v1"
    assert report["overall_status"] == "ready"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["local_env_file"]["status"] == "pass"
    assert checks["personal_launchers"]["status"] == "pass"
    assert report["counts"]["pack_directory_count"] == 1
    assert report["safety"]["reads_env_values"] is False
    assert report["safety"]["prints_secret_values"] is False
    assert "super-secret-value" not in json.dumps(report)


def test_solo_status_warns_when_env_file_is_missing(tmp_path):
    repo = _minimal_repo(tmp_path, include_env=False)

    report = build_solo_status_report(repo)

    assert report["overall_status"] == "warnings"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["local_env_file"]["status"] == "warning"
    assert "run_reverie_setup_env.bat" in checks["local_env_file"]["next_action"]
    assert "Run run_reverie_setup_env.bat to create .env from .env.example" in report["next_actions"]


def test_solo_status_cli_writes_json_report(tmp_path, capsys):
    repo = _minimal_repo(tmp_path / "repo")
    out = tmp_path / "solo_status.json"

    exit_code = main(["--repo-root", str(repo), "--json", "--out", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "reverie.local.solo_status.v1"
    printed = capsys.readouterr().out
    assert "reverie.local.solo_status.v1" in printed
