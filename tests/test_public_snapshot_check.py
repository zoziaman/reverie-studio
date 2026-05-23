import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_snapshot_check():
    spec = importlib.util.spec_from_file_location(
        "public_snapshot_check",
        ROOT / "scripts" / "public_snapshot_check.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_example_is_allowed_but_real_env_files_are_blocked():
    snapshot_check = _load_snapshot_check()

    assert snapshot_check._is_blocked_path(Path(".env.example")) is None
    assert snapshot_check._is_blocked_path(Path(".env")) == "blocked filename: .env"
    assert snapshot_check._is_blocked_path(Path(".env.local")) == "blocked filename pattern: .env.local"
    assert snapshot_check._is_blocked_path(Path(".env.production.local")) == (
        "blocked filename pattern: .env.production.local"
    )


def test_credential_token_and_oauth_filenames_are_blocked():
    snapshot_check = _load_snapshot_check()

    assert snapshot_check._is_blocked_path(Path("config/youtube_token.json")) == (
        "blocked filename pattern: youtube_token.json"
    )
    assert snapshot_check._is_blocked_path(Path("config/client_secret_123.json")) == (
        "blocked filename pattern: client_secret_123.json"
    )
    assert snapshot_check._is_blocked_path(Path("config/firebase-service-account.json")) == (
        "blocked filename pattern: firebase-service-account.json"
    )
