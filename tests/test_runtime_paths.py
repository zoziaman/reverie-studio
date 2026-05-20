import os

from config.path_utils import normalize_runtime_base_dir
from config.settings_v2 import ReverieSettings


def test_normalize_runtime_base_dir_collapses_nested_bundle(tmp_path):
    source_root = tmp_path / "ReverieStudio"
    nested_bundle = source_root / "ReverieStudio"

    for path in (
        source_root / "src",
        source_root / "assets",
        source_root / "data",
        nested_bundle / "assets",
        nested_bundle / "data",
        nested_bundle / "output",
    ):
        path.mkdir(parents=True, exist_ok=True)

    resolved = normalize_runtime_base_dir(
        str(nested_bundle),
        source_root=str(source_root),
        is_binary_runtime=False,
    )

    assert resolved == os.path.normpath(str(source_root.resolve()))


def test_normalize_runtime_base_dir_keeps_binary_runtime_bundle(tmp_path):
    source_root = tmp_path / "ReverieStudio"
    nested_bundle = source_root / "ReverieStudio"

    for path in (
        source_root / "src",
        source_root / "assets",
        source_root / "data",
        nested_bundle / "assets",
        nested_bundle / "data",
        nested_bundle / "output",
    ):
        path.mkdir(parents=True, exist_ok=True)

    resolved = normalize_runtime_base_dir(
        str(nested_bundle),
        source_root=str(source_root),
        is_binary_runtime=True,
    )

    assert resolved == os.path.normpath(str(nested_bundle.resolve()))


def test_settings_derive_normalized_project_paths(tmp_path):
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    settings = ReverieSettings(BASE_DIR=str(base_dir))

    expected_root = os.path.normpath(str(base_dir.resolve()))
    assert settings.BASE_DIR == expected_root
    assert settings.PROJECT_ROOT == expected_root
    assert settings.DATA_DIR == os.path.join(expected_root, "data")
    assert settings.ASSETS_DIR == os.path.join(expected_root, "assets")
    assert settings.OUTPUT_DIR == os.path.join(expected_root, "output")
    assert settings.EXPORTS_DIR == os.path.join(expected_root, "data", "exports")
    assert settings.LOGS_DIR == os.path.join(expected_root, "data", "logs")
    assert settings.SCRIPTS_DIR == os.path.join(expected_root, "data", "scripts")
    assert settings.THUMBNAILS_DIR == os.path.join(expected_root, "data", "thumbnails")
    assert settings.TEMP_AUDIO_DIR == os.path.join(expected_root, "data", "temp_audio")
    assert settings.TEMP_IMAGES_DIR == os.path.join(expected_root, "data", "temp_images")
    assert settings.V50_CLIPS_DIR == os.path.join(expected_root, "output", "clips")
    assert settings.V50_TEMP_DIR == os.path.join(expected_root, "output", "temp")
