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


def test_content_scan_detects_slack_tokens(tmp_path):
    snapshot_check = _load_snapshot_check()
    secret_file = tmp_path / "notes.txt"
    token = "xox" + "b-" + "123456789012-abcdefghijklmnopqrst"
    secret_file.write_text(
        f"SLACK_BOT_TOKEN={token}\n",
        encoding="utf-8",
    )

    findings = snapshot_check._scan_contents(tmp_path, [Path("notes.txt")])

    assert findings == ["notes.txt: content pattern matched: slack_token"]


def test_content_scan_detects_aws_and_stripe_keys(tmp_path):
    snapshot_check = _load_snapshot_check()
    secret_file = tmp_path / "cloud_keys.txt"
    aws_key = "AK" + "IA" + "1234567890ABCDEF"
    stripe_key = "sk_" + "live_" + "abcdefghijklmnopqrstuvwx"
    secret_file.write_text(
        f"AWS_ACCESS_KEY_ID={aws_key}\nSTRIPE_SECRET_KEY={stripe_key}\n",
        encoding="utf-8",
    )

    findings = snapshot_check._scan_contents(tmp_path, [Path("cloud_keys.txt")])

    assert findings == [
        "cloud_keys.txt: content pattern matched: aws_access_key",
        "cloud_keys.txt: content pattern matched: stripe_live_key",
    ]


def test_content_scan_detects_huggingface_and_npm_tokens(tmp_path):
    snapshot_check = _load_snapshot_check()
    secret_file = tmp_path / "package_tokens.txt"
    hf_token = "hf" + "_" + "abcdefghijklmnopqrstuvwx123456"
    npm_token = "npm" + "_" + "abcdefghijklmnopqrstuvwx123456"
    secret_file.write_text(
        f"HUGGINGFACE_TOKEN={hf_token}\nNPM_TOKEN={npm_token}\n",
        encoding="utf-8",
    )

    findings = snapshot_check._scan_contents(tmp_path, [Path("package_tokens.txt")])

    assert findings == [
        "package_tokens.txt: content pattern matched: huggingface_token",
        "package_tokens.txt: content pattern matched: npm_token",
    ]


def test_content_scan_detects_discord_and_telegram_webhooks(tmp_path):
    snapshot_check = _load_snapshot_check()
    secret_file = tmp_path / "webhooks.txt"
    discord_webhook = (
        "https://discord"
        ".com/api/webhooks/123456789012345678/"
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    )
    telegram_webhook = (
        "https://api.telegram"
        ".org/bot123456789:"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwx/sendMessage"
    )
    secret_file.write_text(
        f"DISCORD_WEBHOOK={discord_webhook}\nTELEGRAM_WEBHOOK={telegram_webhook}\n",
        encoding="utf-8",
    )

    findings = snapshot_check._scan_contents(tmp_path, [Path("webhooks.txt")])

    assert findings == [
        "webhooks.txt: content pattern matched: discord_webhook",
        "webhooks.txt: content pattern matched: telegram_bot_token",
    ]


def test_build_json_report_redacts_raw_findings():
    snapshot_check = _load_snapshot_check()
    findings = [
        "config/client_secret_alice.json: blocked filename pattern: client_secret_alice.json",
        "notes.txt: content pattern matched: slack_token",
    ]

    report = snapshot_check.build_json_report(findings)

    assert report["schema"] == "reverie.public_snapshot_check.v1"
    assert report["status"] == "fail"
    assert report["finding_count"] == 2
    assert report["finding_types"] == {
        "blocked filename pattern": 1,
        "content pattern matched": 1,
    }
    assert report["finding_fingerprints"][0]["fingerprint"]
    assert "findings" not in report
    assert "client_secret_alice.json" not in str(report)
