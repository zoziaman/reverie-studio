import os
from typing import Iterable, Optional


SOURCE_ROOT_MARKERS = ("src", "assets", "data")
RUNTIME_BUNDLE_MARKERS = ("assets", "data", "output")


def normalize_path(path: str) -> str:
    """Return a normalized absolute path."""
    return os.path.normpath(os.path.realpath(os.path.abspath(path)))


def has_markers(path: str, markers: Iterable[str]) -> bool:
    """Return True when every marker exists directly under path."""
    return all(os.path.exists(os.path.join(path, marker)) for marker in markers)


def looks_like_source_root(path: str) -> bool:
    """Best-effort check for the development workspace root."""
    return os.path.isdir(path) and has_markers(path, SOURCE_ROOT_MARKERS)


def looks_like_runtime_bundle(path: str) -> bool:
    """Best-effort check for a packaged runtime directory."""
    return (
        os.path.isdir(path)
        and has_markers(path, RUNTIME_BUNDLE_MARKERS)
        and not os.path.isdir(os.path.join(path, "src"))
    )


def normalize_runtime_base_dir(
    candidate: str,
    source_root: Optional[str] = None,
    is_binary_runtime: bool = False,
) -> str:
    """
    Normalize the runtime base directory.

    In source mode, collapse accidental nested runtime bundles such as
    ``C:\\Project\\Project`` back to the source workspace root.
    """
    if not candidate:
        return normalize_path(source_root) if source_root else ""

    normalized = normalize_path(candidate)
    normalized_source = normalize_path(source_root) if source_root else ""

    if is_binary_runtime or not normalized_source:
        return normalized

    parent = os.path.dirname(normalized)
    if (
        parent == normalized_source
        and os.path.basename(normalized).lower() == os.path.basename(normalized_source).lower()
        and looks_like_source_root(normalized_source)
        and looks_like_runtime_bundle(normalized)
    ):
        return normalized_source

    return normalized


def project_path(base_dir: str, *parts: str) -> str:
    """Join parts under the normalized project root."""
    return normalize_path(os.path.join(base_dir, *parts))


def is_dev_mode_enabled(base_dir: str = "", data_dir: str = "") -> bool:
    """Return True when local development overrides are enabled."""
    candidates = []
    if data_dir:
        candidates.append(os.path.join(data_dir, ".dev"))
    if base_dir:
        candidates.append(os.path.join(base_dir, ".dev"))
    candidates.append(".dev")

    return any(os.path.exists(path) for path in candidates) or os.environ.get(
        "REVERIE_DEV_MODE",
        "0",
    ) == "1"
