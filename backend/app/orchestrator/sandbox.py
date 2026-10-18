"""Agents may only write inside projects/<run_id>/. Anything resolving outside is rejected."""

from pathlib import Path

from app.config import get_settings


class SandboxError(ValueError):
    pass


def run_dir(run_id: str) -> Path:
    root = get_settings().projects_dir.resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise SandboxError(f"Invalid run id: {run_id!r}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_path(run_id: str, relative: str) -> Path:
    base = run_dir(run_id)
    if Path(relative).is_absolute():
        raise SandboxError(f"Absolute paths are not allowed: {relative!r}")
    path = (base / relative).resolve()
    if path != base and base not in path.parents:
        raise SandboxError(f"Path escapes the run folder: {relative!r}")
    return path


def write_text(run_id: str, relative: str, text: str) -> Path:
    path = safe_path(run_id, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_bytes(run_id: str, relative: str, data: bytes) -> Path:
    path = safe_path(run_id, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
