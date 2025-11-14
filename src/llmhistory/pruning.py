"""Pruning and cleanup commands for storage maintenance."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from llmhistory.confirm import confirm_or_die
from llmhistory.duration import parse_duration
from llmhistory.export_discovery import (
    find_export_files_for_session,
    find_kept_sessions,
)
from llmhistory.projects import get_storage_path, git_root, resolve_project_id
from llmhistory.storage_index import update_index_remove_session
from llmhistory.trash import get_trash_dir, trash_orphan_parts, trash_session
from llmhistory.utils import die, eprint, get_history_dir

if TYPE_CHECKING:
    from pathlib import Path


def _session_mtime(storage: Path, session_file: Path) -> float | None:
    session_id = session_file.stem
    message_dir = storage / "message" / session_id
    try:
        if message_dir.is_dir():
            return message_dir.stat().st_mtime
        return session_file.stat().st_mtime
    except OSError:
        return None


def _iter_project_sessions(
    storage: Path,
    project_id: str,
) -> list[tuple[str, Path, float]]:
    session_dir = storage / "session" / project_id
    if not session_dir.is_dir():
        return []

    rows: list[tuple[str, Path, float]] = []
    for session_file in session_dir.glob("ses_*.json"):
        mtime = _session_mtime(storage, session_file)
        if mtime is None:
            continue
        rows.append((session_file.stem, session_file, mtime))
    return rows


def _iter_all_sessions_from_db(
    storage: Path,
) -> list[tuple[str, str, Path, float]]:
    db_path = storage.parent / "opencode.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = conn.execute("SELECT project_id, id, time_updated FROM session")
            rows: list[tuple[str, str, Path, float]] = []
            for project_id, session_id, time_updated_ms in cur.fetchall():
                fake_path = storage / "session" / str(project_id) / f"{session_id}.json"
                if time_updated_ms is None:
                    try:
                        updated_s = fake_path.stat().st_mtime
                    except OSError:
                        continue
                else:
                    updated_s = int(time_updated_ms) / 1000.0
                rows.append((str(project_id), str(session_id), fake_path, updated_s))
            return rows
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _iter_all_sessions(storage: Path) -> list[tuple[str, str, Path, float]]:
    db_rows = _iter_all_sessions_from_db(storage)
    if db_rows:
        return db_rows

    root = storage / "session"
    if not root.is_dir():
        return []

    rows: list[tuple[str, str, Path, float]] = []
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        project_id = project_dir.name
        for session_file in project_dir.glob("ses_*.json"):
            mtime = _session_mtime(storage, session_file)
            if mtime is None:
                continue
            rows.append((project_id, session_file.stem, session_file, mtime))
    return rows


def _execute_trash_operation(
    sessions_to_trash: set[str],
    storage: Path,
    history_dir: Path,
    project_id: str,
    *,
    dry_run: bool,
) -> int:
    if not sessions_to_trash:
        eprint("✨ Nothing to trash.")
        return 0

    prefix = "[DRY RUN] " if dry_run else ""
    eprint(f"{prefix}🗑️  {len(sessions_to_trash)} sessions to trash")

    trashed_count = 0
    for session_id in sorted(sessions_to_trash):
        if dry_run:
            eprint(f"  Would trash: {session_id}")
            continue
        if trash_session(storage, project_id, session_id):
            update_index_remove_session(history_dir, project_id, session_id)
            trashed_count += 1
        else:
            eprint(f"  ⚠️  Session not found: {session_id}")

    if not dry_run:
        eprint(f"✅ Moved {trashed_count} sessions to system trash (~/.Trash)")
    return 0


def run_prune(*, dry_run: bool = False, yes: bool = False) -> int:
    """Trash sessions not referenced by current export outputs."""
    storage = get_storage_path()
    root = git_root()
    history_dir = get_history_dir(root)

    if not history_dir.is_dir():
        die(f"History directory not found: {history_dir}")

    project_id = resolve_project_id(storage, root, debug=False)
    kept_sessions = find_kept_sessions(history_dir)
    eprint(f"📋 Found {len(kept_sessions)} sessions referenced in exports")

    all_sessions = {
        session_id for session_id, _, _ in _iter_project_sessions(storage, project_id)
    }
    eprint(f"📦 Found {len(all_sessions)} sessions in storage")

    untracked = all_sessions - kept_sessions
    if not untracked:
        eprint("✨ No untracked sessions found.")
        return 0

    confirm_or_die(operation="prune", count=len(untracked), yes=yes, dry_run=dry_run)
    return _execute_trash_operation(
        untracked,
        storage,
        history_dir,
        project_id,
        dry_run=dry_run,
    )


def run_delete_older_than_global(
    range_str: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
) -> int:
    """Trash sessions older than a duration across all projects."""
    storage = get_storage_path()
    root = git_root()
    history_dir = get_history_dir(root)

    try:
        duration = parse_duration(range_str)
    except ValueError as exc:
        die(str(exc))
        return 1

    cutoff_dt = datetime.now(UTC) - duration
    cutoff = cutoff_dt.timestamp()
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    eprint("🌍 GLOBAL MODE - scanning all projects")
    eprint(f"🕒 Cutoff time: {cutoff_str} (older sessions will be trashed)")

    old_by_project: dict[str, set[str]] = {}
    for project_id, session_id, _, mtime in _iter_all_sessions(storage):
        if mtime >= cutoff:
            continue
        old_by_project.setdefault(project_id, set()).add(session_id)

    total_old = sum(len(sessions) for sessions in old_by_project.values())
    eprint(
        f"📦 Found {total_old} sessions older than {range_str} "
        f"across {len(old_by_project)} projects",
    )

    if total_old == 0:
        eprint("✨ No old sessions found.")
        return 0

    confirm_or_die(
        operation="delete-older-than --global",
        count=total_old,
        yes=yes,
        dry_run=dry_run,
    )

    trashed_count = 0
    for project_id, sessions in old_by_project.items():
        for session_id in sorted(sessions):
            if dry_run:
                eprint(f"  Would trash: {project_id}/{session_id}")
                continue
            if trash_session(storage, project_id, session_id):
                update_index_remove_session(history_dir, project_id, session_id)
                trashed_count += 1
            else:
                eprint(f"  ⚠️  Session not found: {project_id}/{session_id}")

    if not dry_run:
        eprint(f"✅ Moved {trashed_count} sessions to system trash (~/.Trash)")
    return 0


def run_delete_older_than(
    range_str: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
) -> int:
    """Trash sessions older than a duration for the current project."""
    storage = get_storage_path()
    root = git_root()
    history_dir = get_history_dir(root)

    if not history_dir.is_dir():
        die(f"History directory not found: {history_dir}")

    project_id = resolve_project_id(storage, root, debug=False)

    try:
        duration = parse_duration(range_str)
    except ValueError as exc:
        die(str(exc))
        return 1

    cutoff_dt = datetime.now(UTC) - duration
    cutoff = cutoff_dt.timestamp()
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    eprint(f"🕒 Cutoff time: {cutoff_str} (older sessions will be trashed)")

    old_sessions: set[str] = {
        session_id
        for session_id, _, mtime in _iter_project_sessions(storage, project_id)
        if mtime < cutoff
    }

    eprint(f"📦 Found {len(old_sessions)} sessions older than {range_str}")
    if not old_sessions:
        eprint("✨ No old sessions found.")
        return 0

    export_files_to_trash: list[Path] = []
    for session_id in old_sessions:
        export_files_to_trash.extend(
            find_export_files_for_session(history_dir, session_id),
        )

    if export_files_to_trash:
        eprint(f"📄 Found {len(export_files_to_trash)} export files to trash")

    total_count = len(old_sessions) + len(export_files_to_trash)
    confirm_or_die(
        operation="delete-older-than",
        count=total_count,
        yes=yes,
        dry_run=dry_run,
    )

    if export_files_to_trash and not dry_run:
        trash_dir = get_trash_dir()
        trash_dir.mkdir(parents=True, exist_ok=True)
        for export_file in export_files_to_trash:
            destination = trash_dir / export_file.name
            if destination.exists():
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                destination = (
                    trash_dir / f"{export_file.stem}_{timestamp}{export_file.suffix}"
                )
            shutil.move(str(export_file), str(destination))
        eprint(f"✅ Moved {len(export_files_to_trash)} export files to trash")

    return _execute_trash_operation(
        old_sessions,
        storage,
        history_dir,
        project_id,
        dry_run=dry_run,
    )


def run_cleanup_orphans(*, dry_run: bool = False, yes: bool = False) -> int:
    """Trash orphaned part directories not linked to any message."""
    storage = get_storage_path()
    eprint("🔍 Scanning for orphaned part directories...")

    orphan_count = trash_orphan_parts(storage, dry_run=True)
    if orphan_count == 0:
        eprint("✨ No orphaned part directories found.")
        return 0

    eprint(f"📦 Found {orphan_count} orphaned part directories")
    confirm_or_die(
        operation="cleanup-orphans",
        count=orphan_count,
        yes=yes,
        dry_run=dry_run,
    )

    if dry_run:
        eprint(f"[DRY RUN] Would trash {orphan_count} orphaned directories")
        return 0

    trashed = trash_orphan_parts(storage, dry_run=False)
    eprint(f"✅ Moved {trashed} orphaned directories to system trash (~/.Trash)")
    return 0
