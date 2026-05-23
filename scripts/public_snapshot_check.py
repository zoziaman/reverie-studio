"""Public release safety checks for the Reverie Studio snapshot."""

from __future__ import annotations

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

CONTENT_PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "google_oauth_token": re.compile(r"ya29\.[A-Za-z0-9_-]+"),
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
    if path.name in BLOCKED_FILENAMES:
        return f"blocked filename: {path.name}"
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


def main() -> int:
    script_root = Path(__file__).resolve().parents[1]
    repo_root = Path(_git_lines(["rev-parse", "--show-toplevel"], cwd=script_root)[0])
    findings = run_check(repo_root)
    if findings:
        print("Public snapshot check: NEEDS REVIEW")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Public snapshot check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
