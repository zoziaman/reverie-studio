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
        "run_reverie_demo_dry_run.bat",
        "python src\\reverie_doctor.py --json",
        "python src\\reverie_demo.py --backend-profile local_dry_run",
        "python -m pytest -q",
        ".env.example",
        ".env",
        "PYTHONPATH=src",
    ]
    for phrase in required:
        assert phrase in runbook
