from pathlib import Path

from utils.commercial_readiness import (
    CommercialReadinessReport,
    generate_commercial_readiness_report,
    report_to_dict,
    render_markdown_report,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_report_flags_release_blockers_in_stale_project(tmp_path):
    _write(tmp_path / "pyproject.toml", '[project]\nname = "reverie-studio"\nversion = "63.0"\n')
    _write(tmp_path / "installer_setup.iss", 'AppVersion=32.0\nSource: "C:\\ReverieStudio\\Reverie_Studio.exe"\n')
    _write(tmp_path / "tools" / "build_nuitka.py", 'f.write("v62.23\\n")\n')
    _write(tmp_path / "docs" / "ROADMAP_v65.md", "> 현재 버전: v62.41\n")
    _write(tmp_path / "src" / "gui" / "mixins" / "production_mixin.py", "def _run_production_preflight():\n    pass\n")
    _write(tmp_path / "src" / "data" / "logs" / "reverie.log", "runtime log")
    _write(tmp_path / "src" / "data" / "scripts" / "sample.json", "{}")
    _write(tmp_path / "src" / "data" / "license_history.json", "{}")
    _write(tmp_path / "src" / "config" / "pack_crypto.py", "b'ReverieStudio_PackEncryption_v57'\n")
    _write(tmp_path / ".env", "SECRET=not-read-by-test\n")

    report = generate_commercial_readiness_report(tmp_path)

    assert isinstance(report, CommercialReadinessReport)
    failed_ids = {check.id for check in report.checks if check.status == "fail"}
    assert "root_readme" in failed_ids
    assert "project_metadata" in failed_ids
    assert "installer_version" in failed_ids
    assert "build_version" in failed_ids
    assert "source_runtime_artifacts" in failed_ids
    assert "source_sensitive_state" in failed_ids
    assert "hardcoded_legacy_secret" in failed_ids
    assert "docs_version_alignment" in failed_ids
    assert "gui_readiness_integration" in failed_ids
    assert report.score < 70


def test_report_accepts_clean_distribution_basics(tmp_path):
    _write(
        tmp_path / "README.md",
        "# Reverie Studio\n\nCommercial production guide.\n\n" + "Setup details.\n" * 40,
    )
    _write(
        tmp_path / "pyproject.toml",
        "\n".join(
            [
                "[project]",
                'name = "reverie-studio"',
                'version = "63.0"',
                'description = "AI video production studio"',
                'readme = "README.md"',
                'requires-python = ">=3.10"',
                'authors = [{ name = "Reverie Studio" }]',
                'dependencies = ["requests"]',
            ]
        ),
    )
    _write(
        tmp_path / ".gitignore",
        ".env\nsrc/data/logs/\nsrc/data/scripts/\nsrc/data/thumbnails/\n"
        "data/license_history.json\nsrc/data/license_history.json\n"
        "config/youtube_credentials.json\n**/service_account*.json\n",
    )
    _write(tmp_path / "installer_setup.iss", 'AppVersion=63.0\nSource: "release\\ReverieStudio.exe"\n')
    _write(tmp_path / "tools" / "build_nuitka.py", 'APP_VERSION = "63.0"\n')
    _write(tmp_path / "docs" / "ROADMAP_v65.md", "> 현재 버전: v63.0\n상용화 점수 95/100\n")
    _write(
        tmp_path / "src" / "gui" / "mixins" / "production_mixin.py",
        "from utils.commercial_readiness import generate_commercial_readiness_report\n"
        "def _run_production_preflight():\n"
        "    report = generate_commercial_readiness_report()\n"
        "    print('상용화 점검')\n"
        "    return report.fail_count\n",
    )
    _write(tmp_path / "src" / "config" / "pack_crypto.py", "PACK_KEY_ENV = 'REVERIE_PACK_PASSWORD'\n")
    _write(tmp_path / "src" / "utils" / "youtube_policy_guard.py", "def ok():\n    return True\n")
    _write(tmp_path / "tests" / "test_smoke.py", "def test_smoke():\n    assert True\n")

    report = generate_commercial_readiness_report(tmp_path)

    by_id = {check.id: check for check in report.checks}
    assert by_id["root_readme"].status == "pass"
    assert by_id["project_metadata"].status == "pass"
    assert by_id["installer_version"].status == "pass"
    assert by_id["build_version"].status == "pass"
    assert by_id["source_runtime_artifacts"].status == "pass"
    assert by_id["source_sensitive_state"].status == "pass"
    assert by_id["hardcoded_legacy_secret"].status == "pass"
    assert by_id["docs_version_alignment"].status == "pass"
    assert by_id["gui_readiness_integration"].status == "pass"
    assert report.score >= 85


def test_markdown_report_is_actionable(tmp_path):
    _write(tmp_path / "pyproject.toml", '[project]\nname = "reverie-studio"\nversion = "63.0"\n')

    report = generate_commercial_readiness_report(tmp_path)
    markdown = render_markdown_report(report)

    assert "Commercial Readiness Report" in markdown
    assert "Score:" in markdown
    assert "root_readme" in markdown
    assert "Recommended Next Actions" in markdown


def test_report_can_be_serialized_for_ci_or_gui(tmp_path):
    _write(tmp_path / "pyproject.toml", '[project]\nname = "reverie-studio"\nversion = "63.0"\n')

    payload = report_to_dict(generate_commercial_readiness_report(tmp_path))

    assert payload["score"] < 100
    assert isinstance(payload["checks"], tuple) or isinstance(payload["checks"], list)
    assert payload["checks"][0]["id"]
