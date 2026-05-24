from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_solo_use_runbook():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/SOLO_USE_RUNBOOK.md" in readme


def test_solo_use_runbook_pins_personal_entrypoints():
    runbook = (ROOT / "docs" / "SOLO_USE_RUNBOOK.md").read_text(encoding="utf-8")

    required = [
        "run_reverie.bat",
        "run_reverie_silent.bat",
        "run_reverie_doctor.bat",
        "run_reverie_solo_status.bat",
        "run_reverie_setup_env.bat",
        "run_reverie_demo_dry_run.bat",
        "run_reverie_videotoon_smoke.bat",
        "python src\\reverie_env_bootstrap.py --json",
        "python src\\reverie_solo_status.py --json",
        "python src\\reverie_doctor.py --json",
        "python src\\reverie_demo.py --backend-profile local_dry_run",
        "python -m utils.videotoon_smoke local",
        "python -m utils.videotoon_smoke stage-remotion",
        "python -m pytest -q",
        ".env.example",
        ".env",
        "PYTHONPATH=src",
    ]
    for phrase in required:
        assert phrase in runbook
