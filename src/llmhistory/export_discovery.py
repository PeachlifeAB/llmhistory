"""Helpers for locating exported files and referenced sessions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from llmhistory.storage_index import read_json

if TYPE_CHECKING:
    from pathlib import Path


def find_kept_sessions(history_dir: Path) -> set[str]:
    """Collect session IDs currently referenced by the export index."""
    kept: set[str] = set()
    if not history_dir.is_dir():
        return kept

    index_path = history_dir / ".llmhistory-index.json"
    index = read_json(index_path)
    if not isinstance(index, dict):
        return kept

    raw_projects = index.get("projects")
    if not isinstance(raw_projects, dict):
        return kept
    for project_bucket in raw_projects.values():
        if not isinstance(project_bucket, dict):
            continue
        sessions = project_bucket.get("sessions")
        if not isinstance(sessions, dict):
            continue
        for session_id in sessions:
            kept.add(str(session_id))

    return kept


def _md_contains_session_id(path: Path, session_id: str) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file_handle:
            for _ in range(12):
                line = file_handle.readline()
                if not line:
                    break
                if f"`{session_id}`" in line:
                    return True
    except OSError:
        return False
    return False


def _jsonl_contains_session_id(path: Path, session_id: str) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file_handle:
            for line in file_handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("session_id") == session_id:
                    return True
    except OSError:
        return False
    return False


def find_export_files_for_session(history_dir: Path, session_id: str) -> list[Path]:
    """Find markdown and JSONL exports that reference a session ID."""
    files: list[Path] = []
    if not history_dir.is_dir():
        return files

    for export_file in history_dir.iterdir():
        if not export_file.is_file():
            continue
        if export_file.suffix == ".md" and _md_contains_session_id(
            export_file,
            session_id,
        ):
            files.append(export_file)
            continue
        if export_file.suffix == ".jsonl" and _jsonl_contains_session_id(
            export_file,
            session_id,
        ):
            files.append(export_file)

    return files
