"""Read, validate, and update the incremental export index."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from llmhistory.redaction import redact_base64_lines
from llmhistory.utils import INDEX_VERSION

if TYPE_CHECKING:
    from pathlib import Path


def read_json(path: Path) -> dict[str, Any] | None:
    """Read JSON from disk and return only dictionary payloads."""
    try:
        with path.open("r", encoding="utf-8") as file_handle:
            obj = json.load(file_handle)
        return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def safe_json_dumps(obj: object) -> str:
    """Serialize a value for markdown while redacting base64-like blobs."""
    if obj is None:
        return "null"
    if isinstance(obj, str):
        return redact_base64_lines(obj)
    return redact_base64_lines(json.dumps(obj, indent=2, ensure_ascii=False))


def _ensure_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def validate_or_repair_index(index: dict[str, Any]) -> dict[str, Any]:
    """Normalize index shape and coerce legacy fields to the current schema."""
    repaired: dict[str, Any] = {"version": INDEX_VERSION, "projects": {}}
    projects = _ensure_dict(index.get("projects"))

    for project_id, project_data in projects.items():
        if not isinstance(project_id, str):
            continue
        project_bucket = _ensure_dict(project_data)
        sessions = _ensure_dict(project_bucket.get("sessions"))

        repaired_sessions: dict[str, dict[str, float]] = {}
        for session_id, session_data in sessions.items():
            if not isinstance(session_id, str):
                continue
            session_bucket = _ensure_dict(session_data)
            timestamp_raw = session_bucket.get(
                "last_modified_timestamp",
                session_bucket.get("last_export_mtime", 0.0),
            )
            try:
                timestamp_value = float(timestamp_raw)
            except (TypeError, ValueError):
                timestamp_value = 0.0
            repaired_sessions[session_id] = {"last_modified_timestamp": timestamp_value}

        repaired["projects"][project_id] = {"sessions": repaired_sessions}

    return repaired


def load_index(history_dir: Path) -> dict[str, Any]:
    """Load the persisted export index or return a fresh default."""
    index_path = history_dir / ".llmhistory-index.json"
    if not index_path.exists():
        return {"version": INDEX_VERSION, "projects": {}}

    data = read_json(index_path)
    if not data:
        return {"version": INDEX_VERSION, "projects": {}}

    return validate_or_repair_index(data)


def save_index_atomic(history_dir: Path, index: dict[str, Any]) -> None:
    """Persist the export index atomically via a temporary file."""
    history_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = history_dir / ".llmhistory-index.json.tmp"
    final_path = history_dir / ".llmhistory-index.json"

    with tmp_path.open("w", encoding="utf-8") as file_handle:
        json.dump(
            validate_or_repair_index(index),
            file_handle,
            indent=2,
            sort_keys=True,
        )
        file_handle.write("\n")

    tmp_path.replace(final_path)


def _get_session_bucket(
    index: dict[str, Any],
    project_id: str,
    session_id: str,
) -> dict[str, Any]:
    projects = index.setdefault("projects", {})
    if not isinstance(projects, dict):
        index["projects"] = {}
        projects = index["projects"]
    project_bucket = projects.setdefault(project_id, {})
    if not isinstance(project_bucket, dict):
        projects[project_id] = {}
        project_bucket = projects[project_id]
    sessions = project_bucket.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        project_bucket["sessions"] = {}
        sessions = project_bucket["sessions"]
    session_bucket = sessions.setdefault(session_id, {})
    if not isinstance(session_bucket, dict):
        sessions[session_id] = {}
        session_bucket = sessions[session_id]
    return session_bucket


def get_export_state(index: dict[str, Any], project_id: str, session_id: str) -> float:
    """Return the last exported modified timestamp for a session."""
    projects = _ensure_dict(index.get("projects"))
    project_bucket = _ensure_dict(projects.get(project_id))
    sessions = _ensure_dict(project_bucket.get("sessions"))
    session_bucket = _ensure_dict(sessions.get(session_id))

    value = session_bucket.get(
        "last_modified_timestamp",
        session_bucket.get("last_export_mtime", 0.0),
    )
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def update_export_state(
    index: dict[str, Any],
    project_id: str,
    session_id: str,
    last_modified_timestamp: float,
    _unused_message_ids: set[str] | None = None,
) -> None:
    """Record the latest exported modified timestamp for a session."""
    session_bucket = _get_session_bucket(index, project_id, session_id)
    session_bucket["last_modified_timestamp"] = float(last_modified_timestamp)
    session_bucket.pop("last_export_mtime", None)
    session_bucket.pop("last_export_mids_at_mtime", None)


def update_index_remove_session(
    history_dir: Path,
    project_id: str,
    session_id: str,
) -> None:
    """Remove a session entry from the persisted export index."""
    index = load_index(history_dir)
    projects = index.setdefault("projects", {})
    if not isinstance(projects, dict):
        index["projects"] = {}
        projects = index["projects"]
    project_bucket = projects.setdefault(project_id, {})
    if not isinstance(project_bucket, dict):
        projects[project_id] = {}
        project_bucket = projects[project_id]
    sessions = project_bucket.get("sessions")
    if not isinstance(sessions, dict):
        project_bucket["sessions"] = {}
        sessions = project_bucket["sessions"]
    if session_id in sessions:
        del sessions[session_id]
        save_index_atomic(history_dir, index)
