"""Session resolution and metadata ordering helpers."""

from __future__ import annotations

import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from llmhistory.models import Message, SessionRef
from llmhistory.projects import CLI_SESSIONS_PROJECT_ID
from llmhistory.storage_index import read_json
from llmhistory.utils import eprint, resolve_executable, run_checked_command

if TYPE_CHECKING:
    from collections.abc import Iterable


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


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


def stable_parent_id(parent: object) -> str | None:
    """Normalize stored parent IDs and treat literal ``"null"`` as missing."""
    if parent in (None, "null"):
        return None
    return str(parent)


def sort_messages(messages: list[Message]) -> list[Message]:
    """Sort messages by creation time and stable message ID."""
    return sorted(messages, key=lambda message: (message.created_ms, message.mid))


def sort_message_files_by_created(message_dir: Path) -> list[Path]:
    """Sort message files by embedded created timestamp and filename."""
    if not message_dir.is_dir():
        return []

    pairs: list[tuple[int, Path]] = []
    for message_file in message_dir.glob("msg_*.json"):
        data = read_json(message_file)
        if not data:
            continue
        raw_time_data = data.get("time")
        if isinstance(raw_time_data, dict):
            created_raw = raw_time_data.get("created")
            created_ms = _safe_int(created_raw)
        else:
            created_ms = 0
        pairs.append((created_ms, message_file))

    pairs.sort(key=lambda pair: (pair[0], pair[1].name))
    return [message_file for _, message_file in pairs]


def session_updated_timestamp_seconds(message_dir: Path) -> float:
    """Return newest mtime among message files for a session directory."""
    if not message_dir.is_dir():
        return 0.0

    latest = 0.0
    for message_file in message_dir.glob("msg_*.json"):
        try:
            latest = max(latest, message_file.stat().st_mtime)
        except OSError:
            continue
    return latest


def session_modified_timestamp(
    session_file: Path,
    updated_ms: int,
    message_mtime: float | None = None,
) -> float:
    """Compute a best-effort modified timestamp for a session export."""
    updated_s = updated_ms / 1000.0 if updated_ms > 0 else 0.0
    latest = updated_s
    if message_mtime is not None:
        latest = max(latest, message_mtime)
    with suppress(OSError):
        latest = max(latest, session_file.stat().st_mtime)
    return latest


def _session_ref(session_file: Path, sid: str, message_dir: Path) -> SessionRef:
    data = read_json(session_file)
    time_data = {}
    parent_id = None
    if isinstance(data, dict):
        raw_time_data = data.get("time")
        if isinstance(raw_time_data, dict):
            time_data = raw_time_data
        parent_id = stable_parent_id(data.get("parent_id") or data.get("parentID"))
    if isinstance(time_data, dict):
        updated_raw = time_data.get("updated")
        created_raw = time_data.get("created")
        created_ms = _safe_int(created_raw)
        updated_ms = _safe_int(updated_raw) or created_ms
    else:
        updated_ms = 0
    sort_key = session_modified_timestamp(
        session_file,
        updated_ms,
        session_updated_timestamp_seconds(message_dir),
    )
    return SessionRef(
        sid=sid,
        session_file=session_file,
        message_dir=message_dir,
        sort_key=sort_key,
        parent_id=parent_id,
    )


def _iter_project_session_files(storage: Path, project_id: str) -> Iterable[Path]:
    sess_dir = storage / "session" / project_id
    if not sess_dir.is_dir():
        return []
    return sess_dir.glob("ses_*.json")


def _session_directory_matches_root(directory: str, root: Path) -> bool:
    resolved_root = root.resolve()
    root_looks_like_repo = (resolved_root / ".git").exists()
    try:
        resolved_directory = Path(directory).resolve()
    except OSError:
        return False

    if root_looks_like_repo:
        return resolved_directory == resolved_root
    return (
        resolved_directory == resolved_root
        or resolved_root in resolved_directory.parents
        or resolved_directory in resolved_root.parents
    )


def _iter_global_session_files(storage: Path, root: Path) -> Iterable[Path]:
    global_sess_dir = storage / "session" / "global"
    if not global_sess_dir.is_dir():
        return []

    matching: list[Path] = []
    for session_file in global_sess_dir.glob("ses_*.json"):
        data = read_json(session_file)
        if not data:
            continue
        directory = data.get("directory")
        if not isinstance(directory, str) or not directory:
            continue
        if _session_directory_matches_root(directory, root):
            matching.append(session_file)
    return matching


def _iter_cli_sessions(storage: Path) -> list[SessionRef]:
    try:
        result = run_checked_command(
            [resolve_executable("opencode"), "session", "list"],
        )
    except (subprocess.SubprocessError, OSError):
        return []

    session_refs: list[SessionRef] = []
    now = time.time()
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith("ses_"):
            continue
        sid = line.split(maxsplit=1)[0]
        session_refs.append(
            SessionRef(
                sid=sid,
                session_file=storage / "session" / "global" / f"{sid}.json",
                message_dir=storage / "message" / sid,
                sort_key=now,
                parent_id=None,
            ),
        )
        now -= 0.001

    return session_refs


def resolve_sessions(
    storage: Path,
    project_id: str,
    root: Path,
    *,
    export_all: bool,
    debug: bool,
) -> list[SessionRef]:
    """Resolve candidate sessions for a project/root combination."""
    message_root = storage / "message"
    sessions: list[SessionRef] = []

    directory_matched_sessions: list[SessionRef] = []
    directory_unknown_sessions: list[SessionRef] = []

    for session_file in _iter_project_session_files(storage, project_id):
        sid = session_file.stem
        message_dir = message_root / sid
        session_ref = _session_ref(session_file, sid, message_dir)

        data = read_json(session_file)
        directory = data.get("directory") if isinstance(data, dict) else None
        if isinstance(directory, str) and directory:
            if _session_directory_matches_root(directory, root):
                directory_matched_sessions.append(session_ref)
            continue

        directory_unknown_sessions.append(session_ref)

    sessions.extend(
        directory_matched_sessions or directory_unknown_sessions,
    )

    if project_id == CLI_SESSIONS_PROJECT_ID:
        sessions.extend(_iter_cli_sessions(storage))

    for session_file in _iter_global_session_files(storage, root):
        sid = session_file.stem
        message_dir = message_root / sid
        sessions.append(_session_ref(session_file, sid, message_dir))

    if not sessions:
        return []

    sessions.sort(key=lambda session_ref: session_ref.sort_key, reverse=True)

    if debug:
        eprint(f"[DEBUG] Found {len(sessions)} total sessions")

    return sessions if export_all else sessions[:1]


def load_session_metadata(sess_file: Path, sid: str) -> tuple[str, int, int]:
    """Load title and timestamps from a raw session metadata file."""
    data = read_json(sess_file)
    if not data:
        return f"Session_{sid}", 0, 0

    title = str(data.get("title") or "Untitled")
    raw_time_data = data.get("time")
    if isinstance(raw_time_data, dict):
        created = _safe_int(raw_time_data.get("created"))
        updated = _safe_int(raw_time_data.get("updated")) or created
    else:
        created = 0
        updated = 0
    return title, created, updated
