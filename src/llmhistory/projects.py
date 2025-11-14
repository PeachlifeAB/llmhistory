"""Project discovery and source-selection helpers."""

from __future__ import annotations

import subprocess
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from llmhistory.storage_index import read_json
from llmhistory.utils import (
    DEFAULT_OPENCODE_STORAGE,
    die,
    eprint,
    resolve_executable,
    run_checked_command,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

CLI_SESSIONS_PROJECT_ID = "__cli_sessions__"


def git_root() -> Path:
    """Return the current Git repository root, or cwd on failure."""
    try:
        result = run_checked_command(
            [resolve_executable("git"), "rev-parse", "--show-toplevel"],
        )
        return Path(result.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return Path.cwd()


def iter_project_files(storage: Path) -> Iterable[Path]:
    """Iterate OpenCode project metadata files in storage."""
    project_dir = storage / "project"
    if not project_dir.is_dir():
        return []
    return project_dir.glob("*.json")


def _resolved_path(path_value: str) -> Path:
    try:
        return Path(path_value).resolve()
    except OSError:
        return Path(path_value).absolute()


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _has_cli_sessions() -> bool:
    try:
        result = run_checked_command(
            [resolve_executable("opencode"), "session", "list"],
        )
    except (subprocess.SubprocessError, OSError):
        return False

    return "ses_" in result.stdout


def resolve_project_ids(storage: Path, root: Path) -> list[str]:
    """Resolve project IDs in storage that correspond to a repository root."""
    resolved_root = root.resolve()
    root_looks_like_repo = (resolved_root / ".git").exists()
    exact_matches: list[str] = []
    compatible_matches: list[str] = []
    for project_file in iter_project_files(storage):
        data = read_json(project_file)
        if not data:
            continue
        worktree = data.get("worktree")
        if not isinstance(worktree, str) or not worktree:
            continue

        resolved_worktree = _resolved_path(worktree)
        if resolved_worktree == resolved_root:
            exact_matches.append(project_file.stem)
            continue

        if resolved_root in resolved_worktree.parents:
            compatible_matches.append(project_file.stem)
            continue

        if not root_looks_like_repo and resolved_worktree in resolved_root.parents:
            compatible_matches.append(project_file.stem)

    direct_matches = exact_matches or compatible_matches
    if direct_matches:
        return direct_matches

    try:
        is_default_storage = storage.resolve() == DEFAULT_OPENCODE_STORAGE.resolve()
    except OSError:
        is_default_storage = storage == DEFAULT_OPENCODE_STORAGE

    if is_default_storage and _has_cli_sessions():
        return [CLI_SESSIONS_PROJECT_ID]

    return []


def most_recent_activity_for_project(storage: Path, project_id: str) -> float:
    """Return the latest observed activity timestamp for a project."""
    session_resolve = import_module("llmhistory.session_resolve")
    session_updated_timestamp_seconds = (
        session_resolve.session_updated_timestamp_seconds
    )

    session_dir = storage / "session" / project_id
    message_root = storage / "message"
    if not session_dir.is_dir():
        return 0.0

    most_recent = 0.0
    for session_file in session_dir.glob("ses_*.json"):
        session_data = read_json(session_file)
        time_data = {}
        if isinstance(session_data, dict):
            raw_time_data = session_data.get("time")
            if isinstance(raw_time_data, dict):
                time_data = raw_time_data
        created_ms = _safe_int(time_data.get("created"))
        updated_ms = _safe_int(time_data.get("updated")) or created_ms
        message_dir = message_root / session_file.stem
        message_updated = session_updated_timestamp_seconds(message_dir)
        try:
            session_file_mtime = session_file.stat().st_mtime
        except OSError:
            session_file_mtime = 0.0
        most_recent = max(
            most_recent,
            updated_ms / 1000.0,
            message_updated,
            session_file_mtime,
        )
    return most_recent


def resolve_project_id(storage: Path, root: Path, *, debug: bool) -> str:
    """Resolve a single best-match project ID for the repository root."""
    matches = resolve_project_ids(storage, root)
    if not matches:
        die(f"No OpenCode project found for {root}")

    if len(matches) == 1:
        return matches[0]

    scored = sorted(
        (
            (most_recent_activity_for_project(storage, project_id), project_id)
            for project_id in matches
        ),
        reverse=True,
    )
    if debug:
        eprint(
            "[DEBUG] Multiple projects matched. "
            f"Selected {scored[0][1]} (activity={scored[0][0]})",
        )
    return scored[0][1]


def get_storage_path() -> Path:
    """Return the default OpenCode storage path."""
    return Path(DEFAULT_OPENCODE_STORAGE)
