"""Public release safety checks for the Reverie Studio snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


BLOCKED_ROOTS = {
    ".claude",
    ".gstack",
    ".opennexus",
    "daily",
    "data",
    "graphs",
    "node_modules",
    "out",
    "outputs",
    "public",
    "release",
    "temp",
    "tmp",
}

BLOCKED_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bin",
    ".ckpt",
    ".db",
    ".docx",
    ".exe",
    ".flac",
    ".gguf",
    ".gif",
    ".jpeg",
    ".jpg",
    ".log",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".onnx",
    ".pdf",
    ".pickle",
    ".pkl",
    ".png",
    ".pth",
    ".pt",
    ".rar",
    ".revpack",
    ".safetensors",
    ".sqlite",
    ".wav",
    ".webp",
    ".zip",
}

BLOCKED_FILENAMES = {
    ".env",
    "client_secrets.json",
    "credentials.json",
    "firebase_credentials.json",
    "licenses.db",
    "token.pickle",
}

ALLOWED_FILENAMES = {
    ".env.example",
}

BLOCKED_FILENAME_PATTERNS = {
    "env_file": re.compile(r"^\.env(\..+)?$"),
    "credential_file": re.compile(
        r"(credential|credentials|client[_-]?secret|oauth|token|service[_-]?account)",
        re.IGNORECASE,
    ),
}

CONTENT_PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "aws_access_key": re.compile(r"(AKIA|ASIA)[0-9A-Z]{16}"),
    "stripe_live_key": re.compile(r"(sk|rk)_live_[A-Za-z0-9]{16,}"),
    "huggingface_token": re.compile(r"hf_[A-Za-z0-9]{20,}"),
    "npm_token": re.compile(r"npm_[A-Za-z0-9]{20,}"),
    "google_oauth_token": re.compile(r"ya29\.[A-Za-z0-9_-]+"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "discord_webhook": re.compile(r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]{40,}"),
    "telegram_bot_token": re.compile(r"bot[0-9]{6,}:[A-Za-z0-9_-]{30,}"),
    "private_key_block": re.compile(r"BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY"),
    "private_user": re.compile(r"(kky86|aftersleep123|C:\\Users\\kky86|C:/Users/kky86)"),
    "private_project_path": re.compile(r"(C:\\Anti reverie|C:/Anti reverie|D:\\AI)"),
    "specific_living_artist_style": re.compile(r"junji[\s_-]*ito", re.IGNORECASE),
}

CONTENT_SCAN_SKIP = {
    Path("scripts/public_snapshot_check.py"),
}


def _git_lines(args: list[str], cwd: Path | None = None) -> list[str]:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line.strip()]


def _tracked_files(repo_root: Path) -> list[Path]:
    return [Path(line) for line in _git_lines(["ls-files"], cwd=repo_root)]


def _is_blocked_path(path: Path) -> str | None:
    parts = path.parts
    if parts and parts[0] in BLOCKED_ROOTS:
        return f"blocked root: {parts[0]}"
    if path.name in ALLOWED_FILENAMES:
        return None
    if path.name in BLOCKED_FILENAMES:
        return f"blocked filename: {path.name}"
    for pattern in BLOCKED_FILENAME_PATTERNS.values():
        if pattern.search(path.name):
            return f"blocked filename pattern: {path.name}"
    if path.suffix.lower() in BLOCKED_EXTENSIONS:
        return f"blocked extension: {path.suffix}"
    return None


def _scan_contents(repo_root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    for rel_path in files:
        if rel_path in CONTENT_SCAN_SKIP:
            continue
        path = repo_root / rel_path
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                continue
        for label, pattern in CONTENT_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{rel_path}: content pattern matched: {label}")
    return findings


def run_check(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    files = _tracked_files(repo_root)
    findings: list[str] = []
    for path in files:
        reason = _is_blocked_path(path)
        if reason:
            findings.append(f"{path}: {reason}")
    findings.extend(_scan_contents(repo_root, files))
    return findings


def run_history_filename_check(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    history_paths = _git_lines(
        ["log", "--all", "--full-history", "--name-only", "--pretty=format:"],
        cwd=repo_root,
    )
    findings: list[str] = []
    seen: set[str] = set()
    for raw_path in history_paths:
        display_path = raw_path.replace("\\", "/")
        rel_path = Path(display_path)
        if display_path in seen:
            continue
        seen.add(display_path)
        reason = _is_blocked_path(rel_path)
        if reason:
            findings.append(f"{display_path}: historical {reason}")
    return findings


def _finding_reason(finding: str) -> str:
    _, separator, detail = finding.partition(": ")
    if not separator:
        return "unknown"
    reason, _, _ = detail.partition(": ")
    return reason or "unknown"


def build_json_report(findings: list[str]) -> dict[str, object]:
    finding_types: dict[str, int] = {}
    fingerprints = []
    for finding in findings:
        reason = _finding_reason(finding)
        finding_types[reason] = finding_types.get(reason, 0) + 1
        fingerprints.append({
            "reason": reason,
            "fingerprint": hashlib.sha256(finding.encode("utf-8")).hexdigest()[:16],
        })
    return {
        "schema": "reverie.public_snapshot_check.v1",
        "status": "fail" if findings else "pass",
        "finding_count": len(findings),
        "finding_types": finding_types,
        "finding_fingerprints": fingerprints[:50],
        "truncated_finding_fingerprints": max(0, len(fingerprints) - 50),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check the tracked public snapshot for release blockers.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a redacted machine-readable report instead of raw local paths.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_root = Path(__file__).resolve().parents[1]
    repo_root = Path(_git_lines(["rev-parse", "--show-toplevel"], cwd=script_root)[0])
    findings = run_check(repo_root)
    if args.json:
        print(json.dumps(build_json_report(findings), indent=2, ensure_ascii=False))
        return 1 if findings else 0
    if findings:
        print("Public snapshot check: NEEDS REVIEW")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Public snapshot check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
