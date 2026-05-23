"""One-command public verification for the Reverie Studio snapshot.

The verifier is intentionally public-safe: it does not read credentials, start
local services, call cloud APIs, or create generated media. It writes reports
outside the repository by default.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from reverie_demo import DEFAULT_PACK_PATH, run_demo
from reverie_doctor import build_environment_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_CHECK_PATH = REPO_ROOT / "scripts" / "public_snapshot_check.py"
PUBLIC_EXPORT_PATH = REPO_ROOT / "scripts" / "public_export.py"
SNAPSHOT_CHECK_SCHEMA = "reverie.public_snapshot_check.v1"
HISTORY_FILENAME_CHECK_SCHEMA = "reverie.public_history_filename_check.v1"
DEFAULT_VERIFY_OUT = Path(tempfile.gettempdir()) / "reverie-public-verify"
FUNCTIONS_DIR = REPO_ROOT / "functions"
FUNCTIONS_AUDIT_DIRECT_DEPENDENCIES = ("firebase-admin", "firebase-functions")

PUBLISH_REVIEW_ITEMS = (
    {
        "id": "existing_git_history",
        "status": "review_required",
        "evidence": "run public_verify with --with-history-scan for historical filename evidence.",
        "required_before_public_existing_repo": (
            "Scan or replace private history before converting an existing private repository to public."
        ),
    },
    {
        "id": "firebase_functions_dependency_audit",
        "status": "review_required",
        "evidence": (
            "run public_verify with --with-functions-audit for current npm audit evidence."
        ),
        "required_before_public_existing_repo": (
            "Keep Firebase Functions optional/non-production, or review and test the breaking dependency path."
        ),
    },
)


def _load_public_snapshot_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("public_snapshot_check", SNAPSHOT_CHECK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SNAPSHOT_CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_public_export() -> ModuleType:
    spec = importlib.util.spec_from_file_location("public_export", PUBLIC_EXPORT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {PUBLIC_EXPORT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _report_artifact_path(path: Path, output_root: Path) -> str:
    try:
        return path.resolve().relative_to(output_root.resolve()).as_posix()
    except ValueError:
        return "<artifact_outside_output>"


def _tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _run_pytest(pytest_args: list[str], timeout_seconds: int) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", *pytest_args]
    report_command = ["python", "-m", "pytest", *pytest_args]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "status": "pass" if completed.returncode == 0 else "fail",
            "command": report_command,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout or ""),
            "stderr_tail": _tail(completed.stderr or ""),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "command": report_command,
            "returncode": None,
            "stdout_tail": _tail(exc.stdout or ""),
            "stderr_tail": _tail(exc.stderr or ""),
            "timeout_seconds": timeout_seconds,
        }


def _run_python_compile(timeout_seconds: int = 60) -> dict[str, Any]:
    command = [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"]
    report_command = ["python", "-m", "compileall", "-q", "src", "scripts", "tests"]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "status": "pass" if completed.returncode == 0 else "fail",
            "command": report_command,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout or ""),
            "stderr_tail": _tail(completed.stderr or ""),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "command": report_command,
            "returncode": None,
            "stdout_tail": _tail(exc.stdout or ""),
            "stderr_tail": _tail(exc.stderr or ""),
            "timeout_seconds": timeout_seconds,
        }


def _run_workspace_state() -> dict[str, Any]:
    command = ["git", "status", "--porcelain=v1", "--untracked-files=normal"]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    changed_paths = [line for line in completed.stdout.splitlines() if line.strip()]
    status_counts: dict[str, int] = {}
    fingerprints = []
    for line in changed_paths:
        status_code = line[:2].strip() or line[:2]
        status_counts[status_code] = status_counts.get(status_code, 0) + 1
        fingerprints.append({
            "status": status_code,
            "fingerprint": hashlib.sha256(line.encode("utf-8")).hexdigest()[:16],
        })
    if completed.returncode != 0:
        return {
            "status": "error",
            "command": command,
            "returncode": completed.returncode,
            "dirty_count": len(changed_paths),
            "status_counts": status_counts,
            "changed_path_fingerprints": fingerprints[:50],
            "truncated_changed_path_fingerprints": max(0, len(fingerprints) - 50),
            "stderr_tail": _tail(completed.stderr or ""),
        }
    return {
        "status": "review_required" if changed_paths else "pass",
        "command": command,
        "returncode": completed.returncode,
        "dirty_count": len(changed_paths),
        "status_counts": status_counts,
        "changed_path_fingerprints": fingerprints[:50],
        "truncated_changed_path_fingerprints": max(0, len(fingerprints) - 50),
    }


def _snapshot_finding_reason(finding: str) -> str:
    _, separator, detail = finding.partition(": ")
    if not separator:
        return "unknown"
    reason, _, _ = detail.partition(": ")
    return reason or "unknown"


def _summarize_snapshot_findings(findings: list[str]) -> dict[str, Any]:
    finding_types: dict[str, int] = {}
    fingerprints = []
    for finding in findings:
        reason = _snapshot_finding_reason(finding)
        finding_types[reason] = finding_types.get(reason, 0) + 1
        fingerprints.append({
            "reason": reason,
            "fingerprint": hashlib.sha256(finding.encode("utf-8")).hexdigest()[:16],
        })
    return {
        "schema": SNAPSHOT_CHECK_SCHEMA,
        "status": "fail" if findings else "pass",
        "finding_count": len(findings),
        "finding_types": finding_types,
        "finding_fingerprints": fingerprints[:50],
        "truncated_finding_fingerprints": max(0, len(fingerprints) - 50),
    }


def _build_snapshot_report(snapshot_check: Any, findings: list[str]) -> dict[str, Any]:
    build_json_report = getattr(snapshot_check, "build_json_report", None)
    if callable(build_json_report):
        report = dict(build_json_report(findings))
        report.setdefault("schema", SNAPSHOT_CHECK_SCHEMA)
        report.setdefault("status", "fail" if findings else "pass")
        return report
    return _summarize_snapshot_findings(findings)


def _build_history_filename_report(snapshot_check: Any, findings: list[str]) -> dict[str, Any]:
    report = _build_snapshot_report(snapshot_check, findings)
    report["schema"] = HISTORY_FILENAME_CHECK_SCHEMA
    return report


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _functions_audit_status(vulnerabilities: dict[str, Any]) -> str:
    if _safe_int(vulnerabilities.get("critical")) or _safe_int(vulnerabilities.get("high")):
        return "blocked"
    if _safe_int(vulnerabilities.get("total")):
        return "review_required"
    return "pass"


def _functions_audit_evidence(functions_audit_report: dict[str, Any]) -> str:
    counts = functions_audit_report.get("vulnerabilities") or {}
    fix_advice = functions_audit_report.get("fix_advice") or {}
    force_targets = fix_advice.get("force_fix_targets") or []
    dependency_versions = _format_functions_dependency_versions(
        functions_audit_report.get("direct_dependency_versions") or {}
    )
    return (
        "functions npm audit status={status}, total={total}, moderate={moderate}, "
        "high={high}, critical={critical}, direct_fix_count={direct_fix_count}, "
        "force_fix_required={force_fix_required}, force_fix_targets={force_fix_targets}, "
        "direct_dependency_versions={direct_dependency_versions}"
    ).format(
        status=functions_audit_report.get("status", "unknown"),
        total=_safe_int(counts.get("total")),
        moderate=_safe_int(counts.get("moderate")),
        high=_safe_int(counts.get("high")),
        critical=_safe_int(counts.get("critical")),
        direct_fix_count=_safe_int(fix_advice.get("direct_fix_count")),
        force_fix_required=str(bool(fix_advice.get("force_fix_required"))).lower(),
        force_fix_targets="|".join(str(target) for target in force_targets),
        direct_dependency_versions=dependency_versions or "not_available",
    )


def _functions_audit_fix_advice(payload: dict[str, Any]) -> dict[str, Any]:
    direct_fix_count = 0
    force_fix_targets = set()
    for vulnerability in (payload.get("vulnerabilities") or {}).values():
        fix_available = vulnerability.get("fixAvailable")
        if fix_available is True:
            direct_fix_count += 1
            continue
        if not isinstance(fix_available, dict):
            continue
        name = fix_available.get("name")
        version = fix_available.get("version")
        if name and version and fix_available.get("isSemVerMajor"):
            force_fix_targets.add(f"{name}@{version}")

    return {
        "direct_fix_count": direct_fix_count,
        "force_fix_required": bool(force_fix_targets),
        "force_fix_targets": sorted(force_fix_targets),
    }


def _functions_direct_dependency_versions() -> dict[str, dict[str, str]]:
    lock_path = FUNCTIONS_DIR / "package-lock.json"
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    packages = payload.get("packages") or {}
    root_package = packages.get("") or {}
    declared_dependencies = root_package.get("dependencies") or {}
    versions: dict[str, dict[str, str]] = {}
    for name in FUNCTIONS_AUDIT_DIRECT_DEPENDENCIES:
        declared = declared_dependencies.get(name)
        installed = (packages.get(f"node_modules/{name}") or {}).get("version")
        if declared or installed:
            versions[name] = {
                "declared": str(declared or "not_declared"),
                "installed": str(installed or "not_installed"),
            }
    return versions


def _format_functions_dependency_versions(versions: dict[str, dict[str, str]]) -> str:
    parts = []
    for name in FUNCTIONS_AUDIT_DIRECT_DEPENDENCIES:
        entry = versions.get(name)
        if not entry:
            continue
        parts.append(f"{name}:{entry.get('declared', 'unknown')}->{entry.get('installed', 'unknown')}")
    return "|".join(parts)


def _format_functions_dependency_versions_summary(versions: dict[str, dict[str, str]]) -> str:
    parts = []
    for name in FUNCTIONS_AUDIT_DIRECT_DEPENDENCIES:
        entry = versions.get(name)
        if not entry:
            continue
        parts.append(f"{name} {entry.get('declared', 'unknown')} -> {entry.get('installed', 'unknown')}")
    return ", ".join(parts)


def _run_functions_audit(timeout_seconds: int) -> dict[str, Any]:
    if not (FUNCTIONS_DIR / "package-lock.json").exists():
        return {
            "status": "not_available",
            "detail": "functions/package-lock.json is missing",
        }
    npm_executable = shutil.which("npm")
    if not npm_executable:
        return {
            "status": "not_available",
            "detail": "npm is not available on PATH",
        }

    command = [
        npm_executable,
        "--prefix",
        str(FUNCTIONS_DIR),
        "audit",
        "--package-lock-only",
        "--omit=dev",
        "--json",
    ]
    report_command = [
        "npm",
        "--prefix",
        "functions",
        "audit",
        "--package-lock-only",
        "--omit=dev",
        "--json",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "command": report_command,
            "returncode": None,
            "stdout_tail": _tail(exc.stdout or ""),
            "stderr_tail": _tail(exc.stderr or ""),
            "timeout_seconds": timeout_seconds,
        }

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "status": "error",
            "command": report_command,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout or ""),
            "stderr_tail": _tail(completed.stderr or ""),
            "detail": "npm audit did not return JSON",
        }

    counts = payload.get("metadata", {}).get("vulnerabilities", {})
    vulnerabilities = {
        "info": _safe_int(counts.get("info")),
        "low": _safe_int(counts.get("low")),
        "moderate": _safe_int(counts.get("moderate")),
        "high": _safe_int(counts.get("high")),
        "critical": _safe_int(counts.get("critical")),
        "total": _safe_int(counts.get("total")),
    }
    names = sorted((payload.get("vulnerabilities") or {}).keys())
    return {
        "status": _functions_audit_status(vulnerabilities),
        "command": report_command,
        "returncode": completed.returncode,
        "vulnerabilities": vulnerabilities,
        "vulnerability_names": names[:25],
        "truncated_vulnerability_names": max(0, len(names) - 25),
        "fix_advice": _functions_audit_fix_advice(payload),
        "direct_dependency_versions": _functions_direct_dependency_versions(),
    }


def _functions_syntax_evidence(functions_syntax_report: dict[str, Any] | None) -> str:
    if not functions_syntax_report:
        return "run with --with-functions-syntax after npm --prefix functions ci."
    status = functions_syntax_report.get("status", "unknown")
    if status == "pass":
        return "functions/index.js loaded with node"
    return "functions syntax status={status}".format(status=status)


def _run_functions_syntax_check(timeout_seconds: int) -> dict[str, Any]:
    if not (FUNCTIONS_DIR / "index.js").exists():
        return {
            "status": "not_available",
            "detail": "functions/index.js is missing",
        }
    if not (FUNCTIONS_DIR / "node_modules" / "firebase-functions").exists():
        return {
            "status": "not_available",
            "detail": "run npm --prefix functions ci before --with-functions-syntax",
        }
    node_executable = shutil.which("node")
    if not node_executable:
        return {
            "status": "not_available",
            "detail": "node is not available on PATH",
        }

    command = [node_executable, "-e", "require('./functions/index.js')"]
    report_command = ["node", "-e", "require('./functions/index.js')"]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "command": report_command,
            "returncode": None,
            "timeout_seconds": timeout_seconds,
            "detail": "functions module load timed out",
        }

    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "command": report_command,
        "returncode": completed.returncode,
        "detail": "functions module loaded" if completed.returncode == 0 else "functions module did not load",
    }


def _public_export_evidence(public_export_report: dict[str, Any] | None) -> str:
    if not public_export_report:
        return "run with --with-public-export to create and verify a history-free source archive."
    if public_export_report.get("status") != "pass":
        return "public export status={status}".format(
            status=public_export_report.get("status", "unknown"),
        )
    manifest = public_export_report.get("manifest") or {}
    verify_report = public_export_report.get("verify") or {}
    release_guidance = manifest.get("release_guidance") or {}
    return (
        "public export archive_file_count={archive_file_count}, "
        "git_history_included={git_history_included}, "
        "distribution_path={distribution_path}, verify_status={verify_status}"
    ).format(
        archive_file_count=_safe_int(manifest.get("archive_file_count")),
        git_history_included=str(bool(manifest.get("git_history_included"))).lower(),
        distribution_path=release_guidance.get("distribution_path", "unknown"),
        verify_status=verify_report.get("status", "unknown"),
    )


def _public_export_error_detail(exc: Exception) -> str:
    detail = str(exc)
    public_safe_fragments = (
        "outside the repository",
        "public snapshot check failed",
        "workspace is not clean",
        "archive integrity check failed",
    )
    if any(fragment in detail for fragment in public_safe_fragments):
        return detail
    return "public export failed before verification"


def _run_public_export(output_dir: Path, *, allow_repo_output: bool) -> dict[str, Any]:
    try:
        public_export = _load_public_export()
        export_out = output_dir / "public_export"
        manifest = public_export.create_public_export(
            export_out,
            allow_repo_output=allow_repo_output,
        )
        verify_report = public_export.verify_public_export(export_out)
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "fail",
            "error_type": type(exc).__name__,
            "detail": _public_export_error_detail(exc),
        }
    except subprocess.CalledProcessError as exc:
        return {
            "status": "fail",
            "error_type": type(exc).__name__,
            "detail": "git archive command failed",
            "returncode": exc.returncode,
        }

    return {
        "status": "pass" if verify_report.get("status") == "pass" else "fail",
        "archive_path": _report_artifact_path(export_out / public_export.ARCHIVE_NAME, output_dir),
        "manifest_path": _report_artifact_path(export_out / public_export.MANIFEST_NAME, output_dir),
        "manifest": {
            "schema": manifest.get("schema"),
            "source_commit": manifest.get("source_commit"),
            "source_tree": manifest.get("source_tree"),
            "tracked_file_count": manifest.get("tracked_file_count"),
            "archive_file_count": manifest.get("archive_file_count"),
            "archive_sha256": manifest.get("archive_sha256"),
            "archive_integrity": manifest.get("archive_integrity"),
            "release_guidance": manifest.get("release_guidance"),
            "git_history_included": manifest.get("git_history_included"),
            "workspace_state": manifest.get("workspace_state"),
            "public_snapshot": manifest.get("public_snapshot"),
        },
        "verify": verify_report,
    }


def _history_filename_evidence(history_filename_report: dict[str, Any] | None) -> str:
    if not history_filename_report:
        return "run public_verify with --with-history-scan for historical filename evidence."
    return "history filename scan finding_count={finding_count}".format(
        finding_count=_safe_int(history_filename_report.get("finding_count")),
    )


def _review_items(
    functions_audit_report: dict[str, Any] | None,
    history_filename_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    items = [dict(item) for item in PUBLISH_REVIEW_ITEMS]
    for item in items:
        if item["id"] == "existing_git_history":
            item["status"] = (
                "blocked"
                if history_filename_report and history_filename_report.get("status") != "pass"
                else "review_required"
            )
            item["evidence"] = _history_filename_evidence(history_filename_report)
        if item["id"] == "firebase_functions_dependency_audit":
            if functions_audit_report:
                item["status"] = functions_audit_report.get("status", "review_required")
                item["evidence"] = _functions_audit_evidence(functions_audit_report)
    return items


def _release_options(
    *,
    snapshot_findings: list[str],
    history_filename_report: dict[str, Any] | None,
    public_export_report: dict[str, Any] | None,
) -> list[dict[str, str]]:
    export_status = public_export_report.get("status") if public_export_report else "not_run"
    if snapshot_findings:
        history_free_status = "blocked"
    elif export_status == "pass":
        history_free_status = "available"
    elif export_status == "not_run":
        history_free_status = "run_required"
    else:
        history_free_status = str(export_status or "unknown")

    history_scan_status = history_filename_report.get("status") if history_filename_report else "not_run"
    existing_repo_status = "blocked" if history_scan_status == "fail" else "review_required"

    return [
        {
            "id": "history_free_export",
            "status": history_free_status,
            "action": (
                "Use the history-free public export for public distribution; it omits git history "
                "and is generated by running public_verify with --with-public-export."
            ),
        },
        {
            "id": "existing_repo_history",
            "status": existing_repo_status,
            "action": (
                "Do not make the existing repository public until the history scan passes, "
                "or publish from a fresh repository created from the history-free export."
            ),
        },
    ]


def _release_option_status(
    release_options: list[dict[str, str]],
    option_id: str,
) -> str:
    for option in release_options:
        if option.get("id") == option_id:
            return option.get("status", "unknown")
    return "unknown"


def _publish_recommendation(
    *,
    failures: list[str],
    release_options: list[dict[str, str]],
) -> str:
    history_free_status = _release_option_status(release_options, "history_free_export")
    existing_history_status = _release_option_status(release_options, "existing_repo_history")
    if failures:
        if history_free_status == "available" and existing_history_status == "blocked":
            return (
                "Use the history-free public export for public distribution. "
                "Do not publish the existing repository history until the history scan passes."
            )
        return "Do not publish until blocking failures are fixed."
    return (
        "Tracked files passed public safety checks. Publish only as a clean export/branch "
        "unless git history is reviewed; keep Firebase Functions optional until its "
        "dependency audit is reviewed."
    )


def _summary_next_actions(report: dict[str, Any]) -> list[str]:
    publish_gate = report.get("publish_gate", {})
    release_options = publish_gate.get("release_options") or []
    history_free_status = _release_option_status(release_options, "history_free_export")
    existing_history_status = _release_option_status(release_options, "existing_repo_history")
    actions: list[str] = []
    if history_free_status == "available" and existing_history_status == "blocked":
        actions.extend([
            "Use the history-free public export or create a fresh public repository from it.",
            "Do not publish the existing repository history until the history scan passes.",
        ])
    else:
        if report.get("overall_status") == "fail":
            actions.append("If `overall_status` is `fail`, fix blocking failures before publishing.")
        if publish_gate.get("status") == "review_required":
            actions.append(
                "If `publish_gate` is `review_required`, complete the manual review items before "
                "making an existing private repository public."
            )
    actions.append("Keep credentials, generated media, voice data, and model weights outside git.")
    return actions


def _write_public_verify_summary(path: Path, report: dict[str, Any]) -> None:
    checks = report.get("checks", {})
    publish_gate = report.get("publish_gate", {})
    lines = [
        "# Reverie Studio Public Verification",
        "",
        f"Overall status: `{report.get('overall_status', 'unknown')}`",
        f"Publish gate: `{publish_gate.get('status', 'unknown')}`",
        f"Created at: `{report.get('created_at', '')}`",
        "",
        "This report is public-safe. It does not contain credentials, generated media,",
        "voice data, model weights, or upload tokens.",
        "",
    ]

    recommendation = publish_gate.get("recommendation")
    if recommendation:
        lines.extend(["## Publish Recommendation", "", recommendation, ""])

    lines.extend([
        "## Machine Checks",
        "",
    ])
    for check in publish_gate.get("machine_checks", []):
        lines.append(
            f"- `{check.get('id', 'unknown')}`: `{check.get('status', 'unknown')}` - "
            f"{check.get('evidence', '')}"
        )

    manual_items = publish_gate.get("manual_review_items", [])
    if manual_items:
        lines.extend(["", "## Manual Review Before Publishing", ""])
        for item in manual_items:
            lines.append(
                f"- `{item.get('id', 'unknown')}`: `{item.get('status', 'unknown')}` - "
                f"{item.get('required_before_public_existing_repo', item.get('evidence', ''))}"
            )

    release_options = publish_gate.get("release_options") or []
    if release_options:
        lines.extend(["", "## Public Release Options", ""])
        for option in release_options:
            lines.append(
                f"- `{option.get('id', 'unknown')}`: `{option.get('status', 'unknown')}` - "
                f"{option.get('action', '')}"
            )

    failures = report.get("failures") or []
    if failures:
        lines.extend(["", "## Blocking Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)

    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    functions_audit = checks.get("functions_audit", {})
    functions_syntax = checks.get("functions_syntax", {})
    public_export = checks.get("public_export", {})
    vulnerabilities = functions_audit.get("vulnerabilities") or {}
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- JSON report: `public_verify_report.json`",
            "- Public demo manifest: `public_demo/run_manifest.json`",
            "- Public demo pipeline report: `public_demo/pipeline_report.md`",
        ]
    )
    if functions_audit.get("status") not in {None, "not_run"}:
        fix_advice = functions_audit.get("fix_advice") or {}
        force_fix_targets = fix_advice.get("force_fix_targets") or []
        lines.extend(
            [
                "",
                "## Optional Functions Audit",
                "",
                f"- Status: `{functions_audit.get('status')}`",
                f"- Total: `{_safe_int(vulnerabilities.get('total'))}`",
                f"- Moderate: `{_safe_int(vulnerabilities.get('moderate'))}`",
                f"- High: `{_safe_int(vulnerabilities.get('high'))}`",
                f"- Critical: `{_safe_int(vulnerabilities.get('critical'))}`",
                f"- Direct fix count: `{_safe_int(fix_advice.get('direct_fix_count'))}`",
            ]
        )
        if force_fix_targets:
            lines.append(f"- Force-fix targets: `{', '.join(force_fix_targets)}`")
        dependency_versions = _format_functions_dependency_versions_summary(
            functions_audit.get("direct_dependency_versions") or {}
        )
        if dependency_versions:
            lines.append(f"- Direct dependency versions: `{dependency_versions}`")

    if functions_syntax.get("status") not in {None, "not_run"}:
        lines.extend(
            [
                "",
                "## Optional Functions Syntax",
                "",
                f"- Status: `{functions_syntax.get('status')}`",
                f"- Detail: `{functions_syntax.get('detail', 'not_available')}`",
            ]
        )

    if public_export.get("status") not in {None, "not_run"}:
        manifest = public_export.get("manifest") or {}
        verify_report = public_export.get("verify") or {}
        lines.extend(
            [
                "",
                "## Optional Public Export",
                "",
                f"- Status: `{public_export.get('status')}`",
                f"- Archive: `{public_export.get('archive_path', 'not_available')}`",
                f"- Manifest: `{public_export.get('manifest_path', 'not_available')}`",
                f"- Verify status: `{verify_report.get('status', 'unknown')}`",
                f"- Archive SHA-256: `{manifest.get('archive_sha256', 'not_available')}`",
                f"- Git history included: `{str(bool(manifest.get('git_history_included'))).lower()}`",
            ]
        )
        release_guidance = manifest.get("release_guidance") or {}
        distribution_path = release_guidance.get("distribution_path")
        if distribution_path:
            lines.append(f"- Release guidance: `{distribution_path}`")
            lines.append(
                "- Existing repo history requires review: `{requires_review}`".format(
                    requires_review=str(
                        bool(release_guidance.get("existing_repo_history_requires_review")),
                    ).lower(),
                )
            )

    lines.extend(
        [
            "",
            "## Next Actions",
            "",
        ]
    )
    lines.extend(f"- {action}" for action in _summary_next_actions(report))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_publish_gate(
    *,
    failures: list[str],
    snapshot_findings: list[str],
    workspace_report: dict[str, Any],
    demo_safety: dict[str, Any],
    environment_status: str | None,
    python_compile_report: dict[str, Any],
    pytest_report: dict[str, Any] | None,
    history_filename_report: dict[str, Any] | None,
    functions_audit_report: dict[str, Any] | None,
    functions_syntax_report: dict[str, Any] | None,
    public_export_report: dict[str, Any] | None,
) -> dict[str, Any]:
    machine_checks = [
        {
            "id": "tracked_publish_set",
            "status": "pass" if not snapshot_findings else "blocked",
            "evidence": (
                "public_snapshot_check finding_count=0"
                if not snapshot_findings
                else "public_snapshot_check findings present"
            ),
        },
        {
            "id": "workspace_state",
            "status": workspace_report["status"],
            "evidence": "git status dirty_count={dirty_count}".format(
                dirty_count=_safe_int(workspace_report.get("dirty_count")),
            ),
        },
        {
            "id": "public_demo_safety",
            "status": "pass" if not any(demo_safety.get(key) for key in (
                "uses_credentials",
                "calls_external_services",
                "creates_media",
                "starts_upload",
            )) else "blocked",
            "evidence": "demo safety flags are all false",
        },
        {
            "id": "local_setup_doctor",
            "status": environment_status or "unknown",
            "evidence": "needs_setup is acceptable for a public clone; pass means this machine has required tools.",
        },
        {
            "id": "python_compile",
            "status": python_compile_report["status"],
            "evidence": "compileall -q src scripts tests",
        },
        {
            "id": "pytest",
            "status": pytest_report["status"] if pytest_report else "not_run",
            "evidence": "run with --with-pytest for full test evidence.",
        },
        {
            "id": "git_history_filenames",
            "status": history_filename_report["status"] if history_filename_report else "not_run",
            "evidence": _history_filename_evidence(history_filename_report),
        },
        {
            "id": "firebase_functions_dependency_audit",
            "status": functions_audit_report["status"] if functions_audit_report else "not_run",
            "evidence": (
                "run with --with-functions-audit for npm audit evidence."
                if not functions_audit_report
                else _functions_audit_evidence(functions_audit_report)
            ),
        },
        {
            "id": "firebase_functions_syntax",
            "status": functions_syntax_report["status"] if functions_syntax_report else "not_run",
            "evidence": _functions_syntax_evidence(functions_syntax_report),
        },
        {
            "id": "history_free_public_export",
            "status": public_export_report["status"] if public_export_report else "not_run",
            "evidence": _public_export_evidence(public_export_report),
        },
    ]
    publish_status = "blocked" if failures or any(
        check["status"] in {"blocked", "error", "fail", "timeout"} for check in machine_checks
    ) else "review_required"
    release_options = _release_options(
        snapshot_findings=snapshot_findings,
        history_filename_report=history_filename_report,
        public_export_report=public_export_report,
    )
    recommendation = _publish_recommendation(
        failures=failures,
        release_options=release_options,
    )
    return {
        "status": publish_status,
        "recommendation": recommendation,
        "machine_checks": machine_checks,
        "manual_review_items": _review_items(functions_audit_report, history_filename_report),
        "release_options": release_options,
    }


def run_public_verification(
    output_dir: Path | str = DEFAULT_VERIFY_OUT,
    *,
    backend_profile_id: str = "local_dry_run",
    quality_threshold: float = 0.75,
    with_pytest: bool = False,
    pytest_args: list[str] | None = None,
    pytest_timeout_seconds: int = 300,
    with_history_scan: bool = False,
    with_functions_audit: bool = False,
    functions_audit_timeout_seconds: int = 120,
    with_functions_syntax: bool = False,
    functions_syntax_timeout_seconds: int = 60,
    with_public_export: bool = False,
    allow_repo_output: bool = False,
) -> dict[str, Any]:
    """Run the public-safe verification bundle and return its report."""

    out = Path(output_dir).resolve()
    repo_root = REPO_ROOT.resolve()
    if _is_relative_to(out, repo_root) and not allow_repo_output:
        raise ValueError(
            "public verification output must be outside the repository "
            "(pass --allow-repo-output only for intentional local debugging)"
        )

    out.mkdir(parents=True, exist_ok=True)
    demo_out = out / "public_demo"

    snapshot_check = _load_public_snapshot_check()
    snapshot_findings = snapshot_check.run_check(repo_root)
    workspace_report = _run_workspace_state()
    environment_report = build_environment_report(repo_root)
    python_compile_report = _run_python_compile()
    demo_manifest = run_demo(
        DEFAULT_PACK_PATH,
        demo_out,
        backend_profile_id=backend_profile_id,
        quality_threshold=quality_threshold,
    )

    pytest_report = None
    if with_pytest:
        pytest_report = _run_pytest(pytest_args or ["-q"], pytest_timeout_seconds)
    history_filename_report = None
    if with_history_scan:
        history_findings = snapshot_check.run_history_filename_check(repo_root)
        history_filename_report = _build_history_filename_report(snapshot_check, history_findings)
    functions_audit_report = None
    if with_functions_audit:
        functions_audit_report = _run_functions_audit(functions_audit_timeout_seconds)
    functions_syntax_report = None
    if with_functions_syntax:
        functions_syntax_report = _run_functions_syntax_check(functions_syntax_timeout_seconds)
    public_export_report = None
    if with_public_export:
        public_export_report = _run_public_export(out, allow_repo_output=allow_repo_output)

    failures: list[str] = []
    warnings: list[str] = []
    if snapshot_findings:
        failures.append("public_snapshot_check reported release-blocking findings")
    if workspace_report["status"] == "error":
        failures.append("workspace_state check failed")

    demo_safety = demo_manifest.get("safety", {})
    if demo_safety.get("uses_credentials") or demo_safety.get("calls_external_services"):
        failures.append("public demo attempted credential or external-service behavior")
    if demo_safety.get("creates_media") or demo_safety.get("starts_upload"):
        failures.append("public demo attempted media generation or upload behavior")
    if demo_manifest.get("final_status") != "needs_human_review":
        failures.append("public demo did not preserve the manual review gate")

    if environment_report.get("overall_status") == "needs_setup":
        warnings.append("local tool setup is incomplete on this machine")
    elif environment_report.get("overall_status") != "pass":
        failures.append("environment doctor returned an unexpected blocking status")

    if python_compile_report["status"] != "pass":
        failures.append(f"python_compile failed: {python_compile_report['status']}")

    if pytest_report and pytest_report["status"] != "pass":
        failures.append(f"pytest returned {pytest_report['status']}")
    if history_filename_report and history_filename_report["status"] != "pass":
        failures.append("git history filename scan reported release-blocking findings")
    if functions_syntax_report and functions_syntax_report["status"] in {"error", "fail", "timeout"}:
        failures.append("Firebase Functions module did not load")
    if functions_syntax_report and functions_syntax_report["status"] == "not_available":
        warnings.append("Firebase Functions syntax check could not run; install functions dependencies first")
    if public_export_report and public_export_report["status"] != "pass":
        failures.append("history-free public export did not verify")

    if failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "needs_setup"
    else:
        overall_status = "pass"
    snapshot_report = _build_snapshot_report(snapshot_check, snapshot_findings)

    report = {
        "schema": "reverie.public_verify.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": "<repo_root>",
        "output_dir": "<verification_output>",
        "overall_status": overall_status,
        "failures": failures,
        "warnings": warnings,
        "publish_gate": _build_publish_gate(
            failures=failures,
            snapshot_findings=snapshot_findings,
            workspace_report=workspace_report,
            demo_safety=demo_safety,
            environment_status=environment_report.get("overall_status"),
            python_compile_report=python_compile_report,
            pytest_report=pytest_report,
            history_filename_report=history_filename_report,
            functions_audit_report=functions_audit_report,
            functions_syntax_report=functions_syntax_report,
            public_export_report=public_export_report,
        ),
        "checks": {
            "public_snapshot": snapshot_report,
            "workspace_state": workspace_report,
            "environment_doctor": {
                "status": environment_report.get("overall_status"),
                "report_path": _report_artifact_path(demo_out / "environment_report.json", out),
            },
            "python_compile": python_compile_report,
            "public_demo": {
                "status": demo_manifest.get("final_status"),
                "quality_status": demo_manifest.get("quality_gate", {}).get("status"),
                "report_path": _report_artifact_path(demo_out / "run_manifest.json", out),
                "safety": demo_safety,
            },
            "pytest": pytest_report or {"status": "not_run"},
            "git_history_filenames": history_filename_report or {"status": "not_run"},
            "functions_audit": functions_audit_report or {"status": "not_run"},
            "functions_syntax": functions_syntax_report or {"status": "not_run"},
            "public_export": public_export_report or {"status": "not_run"},
        },
    }
    (out / "public_verify_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_public_verify_summary(out / "public_verify_summary.md", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run public-safe Reverie Studio verification checks.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_VERIFY_OUT,
        help="Output directory for verification reports. Defaults outside the repository.",
    )
    parser.add_argument("--backend-profile", default="local_dry_run", help="Dry-run backend profile.")
    parser.add_argument("--quality-threshold", type=float, default=0.75, help="Dry-run quality threshold.")
    parser.add_argument("--with-pytest", action="store_true", help="Also run pytest after public safety checks.")
    parser.add_argument(
        "--with-history-scan",
        action="store_true",
        help="Also scan git history filenames using the public snapshot path rules.",
    )
    parser.add_argument(
        "--with-functions-audit",
        action="store_true",
        help="Also run npm audit for the optional Firebase Functions package.",
    )
    parser.add_argument(
        "--with-functions-syntax",
        action="store_true",
        help="Also require the Firebase Functions entrypoint after dependencies are installed.",
    )
    parser.add_argument(
        "--with-public-export",
        action="store_true",
        help="Also create and verify a history-free public source export under the output directory.",
    )
    parser.add_argument(
        "--pytest-arg",
        action="append",
        dest="pytest_args",
        help="Extra pytest argument. Repeat for multiple args. Defaults to -q when --with-pytest is used.",
    )
    parser.add_argument("--pytest-timeout", type=int, default=300, help="Pytest timeout in seconds.")
    parser.add_argument(
        "--functions-audit-timeout",
        type=int,
        default=120,
        help="Functions npm audit timeout in seconds.",
    )
    parser.add_argument(
        "--functions-syntax-timeout",
        type=int,
        default=60,
        help="Functions entrypoint load timeout in seconds.",
    )
    parser.add_argument("--allow-repo-output", action="store_true", help="Allow report output inside the repo.")
    parser.add_argument("--json", action="store_true", help="Print the full verification report JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_public_verification(
            args.out,
            backend_profile_id=args.backend_profile,
            quality_threshold=args.quality_threshold,
            with_pytest=args.with_pytest,
            pytest_args=args.pytest_args,
            pytest_timeout_seconds=args.pytest_timeout,
            with_history_scan=args.with_history_scan,
            with_functions_audit=args.with_functions_audit,
            functions_audit_timeout_seconds=args.functions_audit_timeout,
            with_functions_syntax=args.with_functions_syntax,
            functions_syntax_timeout_seconds=args.functions_syntax_timeout,
            with_public_export=args.with_public_export,
            allow_repo_output=args.allow_repo_output,
        )
    except ValueError as exc:
        print(f"Public verification: BLOCKED - {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        output_dir = Path(args.out).resolve()
        print(f"Public verification: {report['overall_status'].upper()}")
        print(f"Publish gate: {report['publish_gate']['status'].upper()}")
        print(f"Report: {output_dir / 'public_verify_report.json'}")
        print(f"Summary: {output_dir / 'public_verify_summary.md'}")
        release_options = report.get("publish_gate", {}).get("release_options") or []
        if release_options:
            print("Release options:")
            for option in release_options:
                print(
                    f"- {option.get('id', 'unknown')}: {option.get('status', 'unknown')} - "
                    f"{option.get('action', '')}"
                )
        for failure in report["failures"]:
            print(f"- FAIL: {failure}")
        for warning in report["warnings"]:
            print(f"- WARN: {warning}")
    return 1 if report["overall_status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
