"""Tests for session resolution helpers."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from llmhistory import session_resolve
from llmhistory.projects import CLI_SESSIONS_PROJECT_ID


def test_sort_message_files_by_created_handles_malformed_timestamps(
    tmp_path: Path,
 ) -> None:
    """Treat malformed created timestamps as zero during sorting."""
    first = tmp_path / "msg_1.json"
    second = tmp_path / "msg_2.json"
    first.write_text('{"time": {"created": "bad"}}')
    second.write_text('{"time": {"created": "5"}}')

    files = session_resolve.sort_message_files_by_created(tmp_path)

    assert files == [first, second]


def test_load_session_metadata_handles_malformed_timestamps(
    tmp_path: Path,
 ) -> None:
    """Fall back to zero timestamps when session metadata is malformed."""
    session_file = tmp_path / "ses_test.json"
    session_file.write_text(
        '{"title": "Demo", "time": {"created": "bad", "updated": "oops"}}',
    )

    title, created, updated = session_resolve.load_session_metadata(
        session_file,
        "ses_test",
    )

    assert (title, created, updated) == ("Demo", 0, 0)


def test_resolve_sessions_uses_current_time_sort_keys_for_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
 ) -> None:
    """Keep CLI-discovered sessions ordered near the present, not at rank 1e6."""
    monkeypatch.setattr(session_resolve, "resolve_executable", lambda _: "opencode")
    monkeypatch.setattr(
        session_resolve,
        "run_checked_command",
        lambda _: SimpleNamespace(stdout="ses_new latest\nses_old older\n"),
    )
    monkeypatch.setattr(session_resolve.time, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(
        session_resolve,
        "_iter_project_session_files",
        lambda storage, project_id: [],
    )
    monkeypatch.setattr(
        session_resolve,
        "_iter_global_session_files",
        lambda storage, root: [],
    )

    sessions = session_resolve.resolve_sessions(
        tmp_path,
        CLI_SESSIONS_PROJECT_ID,
        tmp_path,
        export_all=True,
        debug=False,
    )

    assert [session.sid for session in sessions] == ["ses_new", "ses_old"]
    assert sessions[0].sort_key > 1_000_000.0
    assert sessions[0].sort_key > sessions[1].sort_key
