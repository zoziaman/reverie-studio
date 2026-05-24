from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _launcher_text(name):
    return (ROOT / name).read_text(encoding="utf-8").lower()


def test_visible_launcher_uses_project_root_gui_entrypoint():
    launcher = _launcher_text("run_reverie.bat")

    assert 'cd /d "%~dp0"' in launcher
    assert 'python "%~dp0src\\main_gui.py"' in launcher
    assert "pause" in launcher


def test_silent_launcher_uses_project_root_gui_entrypoint():
    launcher = _launcher_text("run_reverie_silent.bat")

    assert 'cd /d "%~dp0"' in launcher
    assert "cd src\\gui" not in launcher
    assert 'pythonw "%~dp0src\\main_gui.py"' in launcher


def test_doctor_launcher_runs_direct_script():
    launcher = _launcher_text("run_reverie_doctor.bat")

    assert 'cd /d "%~dp0"' in launcher
    assert 'python "%~dp0src\\reverie_doctor.py" --json' in launcher
    assert "pause" in launcher


def test_solo_status_launcher_runs_direct_script():
    launcher = _launcher_text("run_reverie_solo_status.bat")

    assert 'cd /d "%~dp0"' in launcher
    assert 'python "%~dp0src\\reverie_solo_status.py" --json' in launcher
    assert "pause" in launcher


def test_dry_run_launcher_writes_temp_report():
    launcher = _launcher_text("run_reverie_demo_dry_run.bat")

    assert 'cd /d "%~dp0"' in launcher
    assert (
        'python "%~dp0src\\reverie_demo.py" --backend-profile local_dry_run '
        '--out "%temp%\\reverie-solo-demo"'
    ) in launcher
    assert "pause" in launcher


def test_videotoon_smoke_launcher_runs_local_bundle_and_remotion_stage():
    launcher = _launcher_text("run_reverie_videotoon_smoke.bat")

    assert 'cd /d "%~dp0"' in launcher
    assert 'set "pythonpath=%~dp0src"' in launcher
    assert 'set "smoke_out=%temp%\\reverie-videotoon-smoke"' in launcher
    assert (
        'python -m utils.videotoon_smoke local --source-repo-root "%~dp0." '
        '--output-dir "%smoke_out%" --duration-seconds 10'
    ) in launcher
    assert (
        'python -m utils.videotoon_smoke stage-remotion '
        '"%smoke_out%\\smoke_manifest.json" --remotion-project "%~dp0remotion-poc"'
    ) in launcher
    assert "pause" in launcher
