"""Tests for compact CLI session status output."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmhistory import export_source_runner
from llmhistory.export_source_runner import (
    _PreparedSession,
    _render_prepared_session_statuses,
    _session_progress_lines,
    _SessionOutputPaths,
)
from llmhistory.models import SessionExport, SessionRef
from llmhistory.utils import (
    _color_dim,
    _color_underline,
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


def test_session_progress_lines_root_two_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root sessions render as two lines: branch+meta then indent+filename."""
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
    lines = _session_progress_lines(prepared, "opencode", now_ms=30 * 60 * 1000)

    assert len(lines) == 2
    assert _color_yellow("5m", enabled=True) in lines[0]
    assert "└─" in lines[0]
    assert _color_dim("ses_123", enabled=True) in lines[0]
    assert _color_underline(".llm/My_Session.md", enabled=True) in lines[1]


def test_session_progress_lines_root_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root sessions render plain text when stderr is not a TTY."""
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
    lines = _session_progress_lines(prepared, "opencode", now_ms=30 * 60 * 1000)

    assert len(lines) == 2
    assert "5m" in lines[0]
    assert "└─" in lines[0]
    assert "ses_123" in lines[0]
    assert ".llm/My_Session.md" in lines[1]


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

    # 2 lines for parent + 2 lines for child
    assert len(lines) == 4
    # Parent line 1: branch + age + sid
    assert "└─" in lines[0]
    assert "1m" in lines[0]
    assert "ses_parent" in lines[0]
    # Parent line 2: filename
    assert ".llm/Parent.md" in lines[1]
    # Child line 1: indented branch + age + sid
    assert "0m" in lines[2]
    assert "ses_child" in lines[2]
    # Child line 2: filename
    assert ".llm/Child.md" in lines[3]


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
    source = SimpleNamespace(
        source_name="opencode",
        get_session_project_name=lambda sid: "ExternalProject",
    )
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

    # 2 session lines + blank + footer
    assert len(lines) == 4
    assert "0m" in lines[0]
    assert "ses_child" in lines[0]
    assert ".llm/Child.md" in lines[1]
    assert lines[2] == ""
    assert "ExternalProject" in lines[3]


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

    # Only selected child, 2 lines
    assert len(lines) == 2
    assert "0m" in lines[0]
    assert "ses_child" in lines[0]
    assert ".llm/Child.md" in lines[1]


def _prepared_session_from(values: dict[str, object]) -> _PreparedSession:
    sid = str(values["sid"])
    updated_ms = int(values["updated_ms"])
    title = str(values["title"])
    is_selected = bool(values["is_selected"])
    should_write = bool(values["should_write"])
    parent_id_value = values.get("parent_id")
    parent_id = str(parent_id_value) if parent_id_value is not None else None
    base = Path("fixtures") / title
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
