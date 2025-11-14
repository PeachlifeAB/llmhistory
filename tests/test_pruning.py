"""Focused tests for pruning helpers."""

import os
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from llmhistory import pruning


def test_iter_all_sessions_from_db_falls_back_to_session_file_mtime(
    tmp_path: Path,
) -> None:
    """Use the session file mtime when the DB row has no updated timestamp."""
    storage = tmp_path / "storage"
    session_dir = storage / "session" / "project_1"
    session_dir.mkdir(parents=True)
    session_file = session_dir / "ses_abc.json"
    session_file.write_text("{}")
    mtime = 1_700_000_123.0
    session_file.touch()
    session_file.chmod(0o644)

    os.utime(session_file, (mtime, mtime))

    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE session (project_id TEXT, id TEXT, time_updated INTEGER)"
    )
    conn.execute(
        "INSERT INTO session (project_id, id, time_updated) VALUES (?, ?, ?)",
        ("project_1", "ses_abc", None),
    )
    conn.commit()
    conn.close()

    iter_all_sessions_from_db = pruning.__dict__["_iter_all_sessions_from_db"]
    rows = iter_all_sessions_from_db(storage)

    assert rows == [("project_1", "ses_abc", session_file, mtime)]


def test_delete_older_than_moves_exports_with_shutil(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Move export files with shutil.move instead of Path.rename."""
    history_dir = tmp_path / ".llm"
    history_dir.mkdir()
    export_file = history_dir / "old.md"
    export_file.write_text("old")

    monkeypatch.setattr(pruning, "get_storage_path", lambda: tmp_path / "storage")
    monkeypatch.setattr(pruning, "git_root", lambda: tmp_path)
    monkeypatch.setattr(pruning, "get_history_dir", lambda root: history_dir)
    monkeypatch.setattr(
        pruning, "resolve_project_id", lambda storage, root, debug=False: "project_1"
    )
    monkeypatch.setattr(pruning, "parse_duration", lambda _: timedelta(days=1))
    monkeypatch.setattr(pruning, "confirm_or_die", lambda **_: None)
    monkeypatch.setattr(
        pruning,
        "_iter_project_sessions",
        lambda storage, project_id: [
            ("ses_abc", tmp_path / "storage" / "session.json", 0.0)
        ],
    )
    monkeypatch.setattr(
        pruning,
        "find_export_files_for_session",
        lambda history_dir, session_id: [export_file],
    )
    monkeypatch.setattr(pruning, "_execute_trash_operation", lambda *args, **kwargs: 0)

    moved: list[tuple[str, str]] = []

    def fake_move(src: str, dest: str) -> str:
        moved.append((src, dest))
        return dest

    monkeypatch.setattr(pruning.shutil, "move", fake_move)

    assert pruning.run_delete_older_than("1d", dry_run=False, yes=True) == 0
    assert moved
    assert moved[0][0] == str(export_file)
