from pathlib import Path

from gui import license_generator_gui


def test_license_history_path_uses_runtime_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(license_generator_gui.config, "DATA_DIR", str(tmp_path))

    history_path = Path(license_generator_gui._get_license_history_file())

    assert history_path == tmp_path / "license_history.json"
    assert "src" not in history_path.parts
