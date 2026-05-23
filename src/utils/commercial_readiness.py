"""Commercial release-readiness checks for Reverie Studio.

The checks in this module are intentionally local and deterministic. They do
not call SD, TTS, YouTube, Firebase, or any external service; their job is to
catch packaging, security, and product-readiness blockers before a paid build
or a customer-facing demo.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tomllib
from typing import Iterable, Literal


Status = Literal["pass", "warn", "fail"]
Severity = Literal["P0", "P1", "P2", "P3"]

REQUIRED_PYPROJECT_FIELDS = (
    "description",
    "readme",
    "requires-python",
    "authors",
    "dependencies",
)

RUNTIME_ARTIFACT_DIRS = (
    Path("src/data/logs"),
    Path("src/data/scripts"),
    Path("src/data/thumbnails"),
    Path("src/data/outputs"),
    Path("src/data/temp"),
    Path("src/data/temp_audio"),
    Path("src/data/temp_images"),
    Path("src/data/failed_images"),
)

SENSITIVE_GITIGNORE_PATTERNS = (
    ".env",
    "src/data/logs/",
    "src/data/scripts/",
    "src/data/thumbnails/",
    "data/license_history.json",
    "src/data/license_history.json",
    "config/youtube_credentials.json",
    "**/service_account*.json",
)

SENSITIVE_SOURCE_STATE_FILES = (
    Path("src/data/license_history.json"),
    Path("src/data/license.dat"),
    Path("src/data/license_cache.json"),
    Path("src/data/api_settings.json"),
    Path("src/data/gui_settings.json"),
)

STALE_VERSION_RE = re.compile(r"\bv(?:5\d|6[0-2])(?:\.\d+)?\b")
INNO_APP_VERSION_RE = re.compile(r"^\s*AppVersion\s*=\s*([^\s]+)\s*$", re.MULTILINE)
INNO_SOURCE_RE = re.compile(r'^\s*Source:\s*"([^"]+)"', re.MULTILINE)


@dataclass(frozen=True)
class ReadinessCheck:
    id: str
    title: str
    status: Status
    severity: Severity
    detail: str
    remediation: str
    penalty: int

    @property
    def ok(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True)
class CommercialReadinessReport:
    root: str
    generated_at: str
    score: int
    checks: tuple[ReadinessCheck, ...]

    @property
    def fail_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "fail")

    @property
    def warn_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "warn")

    @property
    def pass_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "pass")


def generate_commercial_readiness_report(root: str | Path | None = None) -> CommercialReadinessReport:
    project_root = Path(root) if root is not None else _default_project_root()
    project_root = project_root.resolve()

    pyproject = _read_pyproject(project_root)
    project_version = str(pyproject.get("version", "")).strip()

    checks = (
        _check_root_readme(project_root),
        _check_project_metadata(project_root, pyproject),
        _check_installer_version(project_root, project_version),
        _check_build_versions(project_root),
        _check_source_runtime_artifacts(project_root),
        _check_sensitive_source_state(project_root),
        _check_hardcoded_legacy_secret(project_root),
        _check_env_files(project_root),
        _check_gitignore_sensitive_patterns(project_root),
        _check_youtube_policy_guard(project_root),
        _check_gui_readiness_integration(project_root),
        _check_docs_version_alignment(project_root, project_version),
        _check_tests_present(project_root),
        _check_pycache_artifacts(project_root),
    )
    score = max(0, 100 - sum(check.penalty for check in checks if check.status != "pass"))

    return CommercialReadinessReport(
        root=str(project_root),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        score=score,
        checks=checks,
    )


def render_markdown_report(report: CommercialReadinessReport) -> str:
    lines = [
        "# Commercial Readiness Report",
        "",
        f"- Root: `{report.root}`",
        f"- Generated: `{report.generated_at}`",
        f"- Score: **{report.score}/100**",
        f"- Summary: {report.pass_count} pass, {report.warn_count} warn, {report.fail_count} fail",
        "",
        "## Checks",
        "",
        "| ID | Status | Severity | Detail |",
        "| --- | --- | --- | --- |",
    ]

    for check in report.checks:
        lines.append(
            f"| `{check.id}` | `{check.status}` | `{check.severity}` | "
            f"{_escape_table(check.detail)} |"
        )

    actions = [
        check
        for check in report.checks
        if check.status in {"fail", "warn"}
    ]
    lines.extend(["", "## Recommended Next Actions", ""])
    if not actions:
        lines.append("- No blocking local packaging or readiness issues detected by this checker.")
    else:
        for check in sorted(actions, key=_action_sort_key):
            lines.append(f"- `{check.id}` ({check.severity}): {check.remediation}")

    lines.append("")
    return "\n".join(lines)


def report_to_dict(report: CommercialReadinessReport) -> dict:
    return asdict(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Reverie Studio commercial readiness report.")
    parser.add_argument("--root", default=".", help="Project root to inspect.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", help="Optional output file path.")
    parser.add_argument(
        "--fail-under",
        type=int,
        default=0,
        help="Exit with code 2 when the readiness score is below this value.",
    )
    args = parser.parse_args(argv)

    report = generate_commercial_readiness_report(args.root)
    if args.format == "json":
        rendered = json.dumps(report_to_dict(report), ensure_ascii=False, indent=2)
    else:
        rendered = render_markdown_report(report)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)

    return 2 if report.score < args.fail_under else 0


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _read_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
    except Exception:
        return {}


def _check_root_readme(root: Path) -> ReadinessCheck:
    readme = root / "README.md"
    if not readme.is_file():
        return _fail(
            "root_readme",
            "Root README",
            "P0",
            "README.md is missing.",
            "Create a customer-facing README with install, prerequisites, first-run, troubleshooting, and support notes.",
            12,
        )
    text = _read_text(readme).strip()
    if len(text) < 400:
        return _warn(
            "root_readme",
            "Root README",
            "P1",
            f"README.md exists but is too thin ({len(text)} chars).",
            "Expand README.md so a paying user can install and operate the product without private chat history.",
            6,
        )
    return _pass("root_readme", "Root README", "P0", "README.md exists and has customer-facing substance.")


def _check_project_metadata(root: Path, pyproject: dict) -> ReadinessCheck:
    if not (root / "pyproject.toml").is_file():
        return _fail(
            "project_metadata",
            "Project metadata",
            "P0",
            "pyproject.toml is missing.",
            "Add pyproject.toml with complete commercial package metadata.",
            12,
        )
    if not pyproject:
        return _fail(
            "project_metadata",
            "Project metadata",
            "P0",
            "pyproject.toml could not be parsed or has no [project] table.",
            "Fix pyproject.toml syntax and define [project] metadata.",
            12,
        )

    missing = [field for field in REQUIRED_PYPROJECT_FIELDS if not pyproject.get(field)]
    if missing:
        return _fail(
            "project_metadata",
            "Project metadata",
            "P1",
            f"Missing project metadata fields: {', '.join(missing)}.",
            "Fill description, readme, requires-python, authors, and dependency metadata.",
            10,
        )
    return _pass("project_metadata", "Project metadata", "P1", "pyproject.toml has commercial package metadata.")


def _check_installer_version(root: Path, project_version: str) -> ReadinessCheck:
    installer = root / "installer_setup.iss"
    if not installer.is_file():
        return _warn(
            "installer_version",
            "Installer version",
            "P1",
            "installer_setup.iss is missing.",
            "Either remove stale installer references or add a maintained installer definition.",
            4,
        )

    text = _read_text(installer)
    version_match = INNO_APP_VERSION_RE.search(text)
    if not version_match:
        return _fail(
            "installer_version",
            "Installer version",
            "P1",
            "installer_setup.iss has no AppVersion.",
            "Set AppVersion to the current project version.",
            8,
        )

    app_version = version_match.group(1).strip()
    if project_version and app_version != project_version:
        return _fail(
            "installer_version",
            "Installer version",
            "P1",
            f"installer_setup.iss AppVersion={app_version}, pyproject version={project_version}.",
            "Update installer_setup.iss AppVersion whenever pyproject.toml version changes.",
            8,
        )

    stale_sources = [
        source
        for source in INNO_SOURCE_RE.findall(text)
        if "C:\\ReverieStudio" in source or "Reverie_Studio.exe" in source
    ]
    if stale_sources:
        return _fail(
            "installer_version",
            "Installer version",
            "P1",
            "installer_setup.iss references stale absolute/local executable paths.",
            "Point the installer at maintained release artifacts, not a deleted local exe path.",
            8,
        )
    return _pass("installer_version", "Installer version", "P1", "Installer version and source paths are not stale.")


def _check_build_versions(root: Path) -> ReadinessCheck:
    build_files = [root / "tools" / "build_nuitka.py", root / "tools" / "build_release.py"]
    stale_hits: list[str] = []
    for path in build_files:
        if not path.is_file():
            continue
        for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
            code = line.split("#", 1)[0]
            if not code.strip():
                continue
            if STALE_VERSION_RE.search(code):
                stale_hits.append(f"{path.relative_to(root)}:{line_number}")
                if len(stale_hits) >= 5:
                    break

    if stale_hits:
        return _fail(
            "build_version",
            "Build version consistency",
            "P1",
            "Build scripts contain stale v62-or-older version literals: " + ", ".join(stale_hits),
            "Use one project version source for generated VERSION files and release labels.",
            8,
        )
    return _pass("build_version", "Build version consistency", "P1", "Build scripts do not contain stale v62-or-older release literals.")


def _check_source_runtime_artifacts(root: Path) -> ReadinessCheck:
    files = _collect_files(root, RUNTIME_ARTIFACT_DIRS)
    if files:
        shown = ", ".join(str(path.relative_to(root)) for path in files[:5])
        suffix = "" if len(files) <= 5 else f" and {len(files) - 5} more"
        return _fail(
            "source_runtime_artifacts",
            "Runtime artifacts inside src",
            "P0",
            f"Runtime/generated files are inside src: {shown}{suffix}.",
            "Move generated logs, scripts, thumbnails, audio, and images out of src/ and keep them excluded from builds.",
            12,
        )
    return _pass("source_runtime_artifacts", "Runtime artifacts inside src", "P0", "No runtime/generated files found inside src/data artifact directories.")


def _check_sensitive_source_state(root: Path) -> ReadinessCheck:
    present = [path for path in SENSITIVE_SOURCE_STATE_FILES if (root / path).is_file()]
    if present:
        shown = ", ".join(str(path) for path in present)
        return _fail(
            "source_sensitive_state",
            "Sensitive local state inside src",
            "P0",
            f"Sensitive local state files are inside the source tree: {shown}.",
            "Move license history, GUI settings, API settings, and caches to runtime data/ and keep them out of shipped source.",
            12,
        )
    return _pass(
        "source_sensitive_state",
        "Sensitive local state inside src",
        "P0",
        "No sensitive local state files found inside src/data.",
    )


def _check_hardcoded_legacy_secret(root: Path) -> ReadinessCheck:
    crypto = root / "src" / "config" / "pack_crypto.py"
    text = _read_text(crypto)
    if "ReverieStudio_PackEncryption" in text or "_LEGACY_PACK_ENCRYPTION_PASSWORD = b" in text:
        return _fail(
            "hardcoded_legacy_secret",
            "Hardcoded legacy secret",
            "P0",
            "pack_crypto.py contains a legacy encryption password literal.",
            "Move legacy migration keys outside the shipped app or require an external migration-only secret.",
            12,
        )
    return _pass("hardcoded_legacy_secret", "Hardcoded legacy secret", "P0", "No legacy pack encryption password literal detected.")


def _check_env_files(root: Path) -> ReadinessCheck:
    env_files = [path.name for path in root.glob(".env*") if path.is_file() and not path.name.endswith(".example")]
    if env_files:
        return _warn(
            "local_env_files",
            "Local environment files",
            "P1",
            f"Local env files exist: {', '.join(sorted(env_files))}.",
            "Keep local env files out of release archives and rotate any key that may have been exposed.",
            5,
        )
    return _pass("local_env_files", "Local environment files", "P1", "No local .env files detected at project root.")


def _check_gitignore_sensitive_patterns(root: Path) -> ReadinessCheck:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return _warn(
            "gitignore_sensitive",
            "Sensitive gitignore patterns",
            "P1",
            ".gitignore is missing.",
            "Add .gitignore rules for credentials, tokens, generated content, and release outputs.",
            5,
        )
    text = _read_text(gitignore)
    missing = [pattern for pattern in SENSITIVE_GITIGNORE_PATTERNS if pattern not in text]
    if missing:
        return _warn(
            "gitignore_sensitive",
            "Sensitive gitignore patterns",
            "P1",
            f"Missing sensitive/generated ignore patterns: {', '.join(missing)}.",
            "Extend .gitignore so credentials and generated customer content cannot be committed by accident.",
            5,
        )
    return _pass("gitignore_sensitive", "Sensitive gitignore patterns", "P1", ".gitignore covers key sensitive/generated paths.")


def _check_youtube_policy_guard(root: Path) -> ReadinessCheck:
    guard = root / "src" / "utils" / "youtube_policy_guard.py"
    uploader = root / "src" / "utils" / "youtube_uploader.py"
    if not guard.is_file():
        return _warn(
            "youtube_policy_guard",
            "YouTube policy guard",
            "P1",
            "youtube_policy_guard.py is missing.",
            "Keep upload metadata policy checks in the upload path before selling YouTube automation.",
            6,
        )
    text = _read_text(guard) + "\n" + _read_text(uploader)
    required_terms = ("contains_synthetic_media", "verified_true_story", "privacy")
    missing = [term for term in required_terms if term not in text]
    if missing:
        return _warn(
            "youtube_policy_guard",
            "YouTube policy guard",
            "P1",
            f"YouTube policy guard exists but is missing expected terms: {', '.join(missing)}.",
            "Ensure upload metadata handling includes synthetic-media disclosure, true-story controls, and privacy gates.",
            4,
        )
    return _pass("youtube_policy_guard", "YouTube policy guard", "P1", "YouTube policy guard is present with expected upload-safety controls.")


def _check_gui_readiness_integration(root: Path) -> ReadinessCheck:
    production_mixin = root / "src" / "gui" / "mixins" / "production_mixin.py"
    text = _read_text(production_mixin)
    required_terms = ("generate_commercial_readiness_report", "fail_count", "상용화")
    missing = [term for term in required_terms if term not in text]
    if missing:
        return _fail(
            "gui_readiness_integration",
            "GUI commercial preflight",
            "P1",
            f"Production GUI preflight is missing commercial readiness integration: {', '.join(missing)}.",
            "Surface commercial readiness score/failures in production preflight before long-running generation starts.",
            8,
        )
    return _pass(
        "gui_readiness_integration",
        "GUI commercial preflight",
        "P1",
        "Production GUI preflight exposes commercial readiness failures before generation starts.",
    )


def _check_docs_version_alignment(root: Path, project_version: str) -> ReadinessCheck:
    roadmap = root / "docs" / "ROADMAP_v65.md"
    if not roadmap.is_file():
        return _warn(
            "docs_version_alignment",
            "Roadmap version alignment",
            "P2",
            "docs/ROADMAP_v65.md is missing.",
            "Keep a current roadmap that distinguishes shipped, validated, and planned work.",
            4,
        )
    text = _read_text(roadmap)
    expected_markers = (
        f"Current version: v{project_version}",
        f"현재 버전: v{project_version}",
    ) if project_version else ()
    if expected_markers and not any(marker in text for marker in expected_markers):
        return _fail(
            "docs_version_alignment",
            "Roadmap version alignment",
            "P1",
            f"ROADMAP_v65.md does not match pyproject version {project_version}.",
            "Update roadmap current-version and fixed/remaining issue sections after hardening work.",
            8,
        )
    if "코덱스 작업 중" in text:
        return _warn(
            "docs_version_alignment",
            "Roadmap version alignment",
            "P2",
            "ROADMAP_v65.md still contains stale '코덱스 작업 중' status text.",
            "Replace stale work-in-progress labels with verified pass/fail status.",
            4,
        )
    return _pass(
        "docs_version_alignment",
        "Roadmap version alignment",
        "P1",
        "Roadmap current version is aligned with project metadata.",
    )


def _check_tests_present(root: Path) -> ReadinessCheck:
    tests_dir = root / "tests"
    test_files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
    if len(test_files) < 10:
        return _warn(
            "tests_present",
            "Automated tests",
            "P2",
            f"Only {len(test_files)} pytest files detected.",
            "Keep behavior covered with targeted tests before release builds.",
            4,
        )
    return _pass("tests_present", "Automated tests", "P2", f"{len(test_files)} pytest files detected.")


def _check_pycache_artifacts(root: Path) -> ReadinessCheck:
    pycache_dirs = list((root / "src").rglob("__pycache__")) if (root / "src").is_dir() else []
    if len(pycache_dirs) > 10:
        shown = ", ".join(str(path.relative_to(root)) for path in pycache_dirs[:5])
        return _warn(
            "pycache_artifacts",
            "Python cache artifacts",
            "P3",
            f"__pycache__ directories exist under src: {shown}.",
            "Clean Python cache directories before packaging or add them to release sanitizer output checks.",
            2,
        )
    if pycache_dirs:
        return _pass(
            "pycache_artifacts",
            "Python cache artifacts",
            "P3",
            f"Only {len(pycache_dirs)} small __pycache__ directory entries found; not a commercial blocker.",
        )
    return _pass("pycache_artifacts", "Python cache artifacts", "P3", "No __pycache__ directories found under src.")


def _collect_files(root: Path, dirs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for rel_dir in dirs:
        full_dir = root / rel_dir
        if not full_dir.is_dir():
            continue
        files.extend(path for path in full_dir.rglob("*") if path.is_file())
    return sorted(files)


def _pass(check_id: str, title: str, severity: Severity, detail: str) -> ReadinessCheck:
    return ReadinessCheck(check_id, title, "pass", severity, detail, "", 0)


def _warn(
    check_id: str,
    title: str,
    severity: Severity,
    detail: str,
    remediation: str,
    penalty: int,
) -> ReadinessCheck:
    return ReadinessCheck(check_id, title, "warn", severity, detail, remediation, penalty)


def _fail(
    check_id: str,
    title: str,
    severity: Severity,
    detail: str,
    remediation: str,
    penalty: int,
) -> ReadinessCheck:
    return ReadinessCheck(check_id, title, "fail", severity, detail, remediation, penalty)


def _action_sort_key(check: ReadinessCheck) -> tuple[int, int, str]:
    severity_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    status_rank = {"fail": 0, "warn": 1, "pass": 2}
    return (status_rank[check.status], severity_rank[check.severity], check.id)


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
