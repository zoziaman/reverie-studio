from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_silent_launcher_uses_project_root_gui_entrypoint():
    launcher = (ROOT / "run_reverie_silent.bat").read_text(encoding="utf-8").lower()

    assert 'cd /d "%~dp0"' in launcher
    assert "cd src\\gui" not in launcher
    assert 'pythonw "%~dp0src\\main_gui.py"' in launcher
