"""Tests for compact CLI session status output."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmhistory import export_source_runner
from llmhistory.export_source_runner import (
    _PreparedSession,
    _render_prepared_session_statuses,
    _session_progress_line,
    _SessionOutputPaths,
)
from llmhistory.models import SessionExport, SessionRef
from llmhistory.utils import (
    _color_bold,
    _color_dim,
    _color_yellow,
    _format_relative_age_ms,
)


def test_format_relative_age_ms_uses_minutes_hours_and_days() -> None:
    """Format relative ages with minute, hour, and day units."""
    now_ms = 10 * 24 * 60 * 60 * 1000

    assert _format_relative_age_ms(now_ms - (5 * 60 * 1000), now_ms=now_ms) == "5m"
    assert _format_relative_age_ms(now_ms - (2 * 60 * 60 * 1000), now_ms=now_ms) == "2h"
    assert (
        _format_relative_age_ms(
            now_ms - (3 * 24 * 60 * 60 * 1000),
            now_ms=now_ms,
        )
        == "3d"
    )


def test_session_progress_line_uses_yellow_age_and_bold_title(
    monkeypatch: pytest.MonkeyPatch,
 ) -> None:
    """Style age in yellow and title in bold for root sessions."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    prepared = _prepared_session_from(
        {
            "sid": "ses_123",
            "updated_ms": 25 * 60 * 1000,
            "title": "My_Session",
            "is_selected": True,
            "should_write": True,
        },
    )
    line = _session_progress_line(prepared, "opencode", now_ms=30 * 60 * 1000)

    expected_age = _color_yellow("5m", enabled=True)
    expected_title = _color_bold("My_Session", enabled=True)
    expected_sid = _color_dim("ses_123", enabled=True)
    assert line == f"{expected_age} │ {expected_title} {expected_sid}"


def test_session_progress_line_without_color(
    monkeypatch: pytest.MonkeyPatch,
 ) -> None:
    """Emit plain text when stderr is not a TTY."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    prepared = _prepared_session_from(
        {
            "sid": "ses_123",
            "updated_ms": 25 * 60 * 1000,
            "title": "My_Session",
            "is_selected": True,
            "should_write": False,
        },
    )
    line = _session_progress_line(prepared, "opencode", now_ms=30 * 60 * 1000)

    expected_age = _color_yellow("5m", enabled=False)
    expected_title = _color_bold("My_Session", enabled=False)
    expected_sid = _color_dim("ses_123", enabled=False)
    assert line == f"{expected_age} │ {expected_title} {expected_sid}"


def test_render_prepared_session_statuses_groups_opencode_children(
    monkeypatch: pytest.MonkeyPatch,
 ) -> None:
    """Render parent sessions above child sessions for OpenCode."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    monkeypatch.setattr(
        export_source_runner,
        "_format_relative_age_ms",
        lambda ms, now_ms=None: {100_000: "1m", 120_000: "0m"}[ms],
    )
    source = SimpleNamespace(source_name="opencode")
    parent = _prepared_session_from(
        {
            "sid": "ses_parent",
            "updated_ms": 100_000,
            "title": "Parent",
            "is_selected": False,
            "should_write": False,
        },
    )
    child = _prepared_session_from(
        {
            "sid": "ses_child",
            "updated_ms": 120_000,
            "title": "Child",
            "parent_id": "ses_parent",
            "is_selected": True,
            "should_write": False,
        },
    )

    lines = _render_prepared_session_statuses(source, [child, parent])

    expected_parent = (
        f"1m │ {_color_bold('Parent', enabled=False)} "
        f"{_color_dim('ses_parent', enabled=False)}"
    )
    expected_child = (
        f"  0m └─ {_color_bold('Child', enabled=False)} "
        f"{_color_dim('ses_child', enabled=False)}"
    )
    assert lines == [expected_parent, expected_child]


def test_render_prepared_session_statuses_marks_out_of_scope_roots(
    monkeypatch: pytest.MonkeyPatch,
 ) -> None:
    """Mark selected roots whose parent exists outside the current scope."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    monkeypatch.setattr(
        export_source_runner,
        "_format_relative_age_ms",
        lambda ms, now_ms=None: {120_000: "0m"}[ms],
    )
    source = SimpleNamespace(source_name="opencode", get_session_project_name=lambda sid: "ExternalProject")
    prepared = _prepared_session_from(
        {
            "sid": "ses_child",
            "updated_ms": 120_000,
            "title": "Child",
            "parent_id": "ses_external_parent",
            "is_selected": True,
            "should_write": False,
        },
    )

    lines = _render_prepared_session_statuses(source, [prepared])

    expected = (
        f"0m │ {_color_bold('Child', enabled=False)} "
        f"{_color_dim('ses_child', enabled=False)}"
    )
    expected_footer = "ℹ️ 1 sessions was started in different folders: ExternalProject (1)"
    assert lines == [expected, "", _color_dim(expected_footer, enabled=False)]


def test_render_prepared_session_statuses_keeps_claude_flat(
    monkeypatch: pytest.MonkeyPatch,
 ) -> None:
    """Keep non-OpenCode sources flat because they lack session hierarchy."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    monkeypatch.setattr(
        export_source_runner,
        "_format_relative_age_ms",
        lambda ms, now_ms=None: {120_000: "0m"}[ms],
    )
    source = SimpleNamespace(source_name="claude")
    parent = _prepared_session_from(
        {
            "sid": "ses_parent",
            "updated_ms": 100_000,
            "title": "Parent",
            "is_selected": False,
            "should_write": False,
        },
    )
    child = _prepared_session_from(
        {
            "sid": "ses_child",
            "updated_ms": 120_000,
            "title": "Child",
            "parent_id": "ses_parent",
            "is_selected": True,
            "should_write": False,
        },
    )

    lines = _render_prepared_session_statuses(source, [parent, child])

    expected = (
        f"0m │ {_color_bold('Child', enabled=False)} "
        f"{_color_dim('ses_child', enabled=False)}"
    )
    assert lines == [expected]


def _prepared_session_from(values: dict[str, object]) -> _PreparedSession:
    sid = str(values["sid"])
    updated_ms = int(values["updated_ms"])
    title = str(values["title"])
    is_selected = bool(values["is_selected"])
    should_write = bool(values["should_write"])
    parent_id_value = values.get("parent_id")
    parent_id = str(parent_id_value) if parent_id_value is not None else None
    base = Path("fixtures") / sid
    sort_key = updated_ms / 1000.0
    return _PreparedSession(
        session_ref=SessionRef(
            sid=sid,
            session_file=base.with_suffix(".json"),
            message_dir=base,
            sort_key=sort_key,
            parent_id=parent_id,
        ),
        exported=SessionExport(
            title=title,
            created_ms=updated_ms,
            updated_ms=updated_ms,
            modified_timestamp=sort_key,
            messages=[],
        ),
        safe_title=title,
        paths=_SessionOutputPaths(
            md_path=base.with_suffix(".md"),
            jsonl_path=base.with_suffix(".jsonl"),
            compactions_path=Path(f"{base}-compactions.md"),
        ),
        is_selected=is_selected,
        should_write=should_write,
    )
