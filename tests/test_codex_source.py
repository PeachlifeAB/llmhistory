"""Tests for CodexSource discovery and export."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from llmhistory.models import SessionRef
from llmhistory.sources.codex import CodexSource

if TYPE_CHECKING:
    from pathlib import Path


def _make_rollout(
    tmp_path: Path,
    session_id: str,
    cwd: str,
    messages: list[dict],
) -> Path:
    """Write a minimal rollout JSONL file under tmp_path/YYYY/MM/DD/."""
    session_dir = tmp_path / "2026" / "05" / "01"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"rollout-2026-05-01T00-00-00-{session_id}.jsonl"
    lines = [
        json.dumps({
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": cwd,
                "timestamp": "2026-05-01T00:00:00.000Z",
            },
        }),
    ] + [json.dumps(m) for m in messages]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_resolve_project_ids_matches_cwd(tmp_path: Path) -> None:
    """Resolve project IDs (session UUIDs) whose cwd matches the given root."""
    storage = tmp_path / "codex_sessions"
    storage.mkdir()

    root = tmp_path / "myrepo"
    root.mkdir()

    sid_match = "aaaaaaaa-0000-0000-0000-000000000001"
    sid_other = "bbbbbbbb-0000-0000-0000-000000000002"

    _make_rollout(storage, sid_match, str(root), [])
    _make_rollout(storage, sid_other, "/some/other/path", [])

    source = CodexSource()
    ids = source.resolve_project_ids(storage, root)
    assert sid_match in ids
    assert sid_other not in ids


def test_export_session_returns_messages(tmp_path: Path) -> None:
    """Export a Codex rollout into normalized Message objects."""
    storage = tmp_path / "codex_sessions"
    storage.mkdir()
    sid = "cccccccc-0000-0000-0000-000000000003"
    root = tmp_path / "myrepo"
    root.mkdir()

    messages_data = [
        {
            "type": "response_item",
            "timestamp": "2026-05-01T10:00:00.000Z",
            "payload": {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello codex"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-05-01T10:00:05.000Z",
            "payload": {
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello back"}],
            },
        },
    ]
    rollout = _make_rollout(storage, sid, str(root), messages_data)

    source = CodexSource()
    ref = SessionRef(
        sid=sid,
        session_file=rollout,
        message_dir=rollout.parent,
        sort_key=rollout.stat().st_mtime,
        parent_id=None,
    )
    export = source.export_session(storage, ref, want_tool_calls=False)

    assert export is not None
    assert len(export.messages) == 2
    assert export.messages[0].role == "user"
    assert export.messages[0].content.strip() == "Hello codex"
    assert export.messages[1].role == "assistant"
    assert export.messages[1].content.strip() == "Hello back"


def test_export_session_skips_developer_role(tmp_path: Path) -> None:
    """Developer-role messages (system prompts) are excluded from export."""
    storage = tmp_path / "codex_sessions"
    storage.mkdir()
    sid = "dddddddd-0000-0000-0000-000000000004"
    root = tmp_path / "myrepo"
    root.mkdir()

    messages_data = [
        {
            "type": "response_item",
            "timestamp": "2026-05-01T10:00:00.000Z",
            "payload": {
                "role": "developer",
                "content": [{"type": "input_text", "text": "System instructions"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-05-01T10:00:01.000Z",
            "payload": {
                "role": "user",
                "content": [{"type": "input_text", "text": "Real question"}],
            },
        },
    ]
    rollout = _make_rollout(storage, sid, str(root), messages_data)
    source = CodexSource()
    ref = SessionRef(
        sid=sid,
        session_file=rollout,
        message_dir=rollout.parent,
        sort_key=rollout.stat().st_mtime,
        parent_id=None,
    )
    export = source.export_session(storage, ref, want_tool_calls=False)
    assert export is not None
    assert all(m.role != "developer" for m in export.messages)
    assert len(export.messages) == 1
    assert export.messages[0].content.strip() == "Real question"
