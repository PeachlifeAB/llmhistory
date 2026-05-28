"""Tests for PiSource discovery and export."""
from __future__ import annotations

import json
from pathlib import Path

from llmhistory.models import SessionRef
from llmhistory.sources.pi import PiSource, _encode_path


def _make_pi_session(
    sessions_dir: Path,
    cwd: str,
    session_id: str,
    messages: list[dict],
    timestamp: str = "2026-05-01T10:00:00.000Z",
) -> Path:
    """Write a Pi session JSONL under sessions_dir/{encoded-cwd}/."""
    encoded = _encode_path(cwd)
    project_dir = sessions_dir / encoded
    project_dir.mkdir(parents=True, exist_ok=True)
    fname = f"2026-05-01T10-00-00-000Z_{session_id}.jsonl"
    path = project_dir / fname
    lines = [
        json.dumps({
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": timestamp,
            "cwd": cwd,
        }),
    ] + [json.dumps(m) for m in messages]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_encode_path_round_trips() -> None:
    """Encoding /Users/x/project produces --Users-x-project--."""
    assert _encode_path("/Users/x/project") == "--Users-x-project--"


def test_resolve_project_ids_finds_matching_cwd(tmp_path: Path) -> None:
    """Resolve sessions whose encoded directory matches the repo root."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    root = tmp_path / "myrepo"
    root.mkdir()

    sid_match = "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa"
    sid_other = "bbbbbbbb-0000-0000-0000-bbbbbbbbbbbb"

    _make_pi_session(sessions_dir, str(root), sid_match, [])
    _make_pi_session(sessions_dir, "/some/other/path", sid_other, [])

    source = PiSource()
    agent_dir = tmp_path
    ids = source.resolve_project_ids(agent_dir, root, sessions_dir=sessions_dir)
    # resolve_project_ids now returns absolute paths to the project subdirs
    expected_dir = str(sessions_dir / _encode_path(str(root)))
    assert any(Path(pid).resolve() == Path(expected_dir).resolve() for pid in ids)
    assert not any(_encode_path("/some/other/path") in pid for pid in ids)


def test_export_pi_session_returns_messages(tmp_path: Path) -> None:
    """Export a Pi session JSONL into normalized Message objects."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    root = tmp_path / "myrepo"
    root.mkdir()

    sid = "11111111-0000-0000-0000-111111111111"
    messages_data = [
        {
            "type": "message",
            "id": "msg1",
            "parentId": None,
            "timestamp": "2026-05-01T10:00:01.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Hello pi"}],
            },
        },
        {
            "type": "message",
            "id": "msg2",
            "parentId": "msg1",
            "timestamp": "2026-05-01T10:00:05.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "some reasoning"},
                    {"type": "text", "text": "Hello human"},
                ],
                "provider": "omlx",
                "model": "Qwen3",
            },
        },
    ]
    session_file = _make_pi_session(sessions_dir, str(root), sid, messages_data)

    source = PiSource()
    ref = SessionRef(
        sid=sid,
        session_file=session_file,
        message_dir=session_file.parent,
        sort_key=session_file.stat().st_mtime,
        parent_id=None,
    )
    export = source.export_session(tmp_path, ref, want_tool_calls=False)

    assert export is not None
    assert len(export.messages) == 2
    assert export.messages[0].role == "user"
    assert "Hello pi" in export.messages[0].content
    assert export.messages[1].role == "assistant"
    assert "Hello human" in export.messages[1].content
    assert "some reasoning" not in export.messages[1].content
    assert export.messages[1].provider_id == "omlx"
    assert export.messages[1].model_id == "Qwen3"


def test_export_pi_session_skips_tool_result_messages(tmp_path: Path) -> None:
    """ToolResult role messages are not included as top-level conversation turns."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    root = tmp_path / "myrepo2"
    root.mkdir()

    sid = "22222222-0000-0000-0000-222222222222"
    messages_data = [
        {
            "type": "message",
            "id": "u1",
            "parentId": None,
            "timestamp": "2026-05-01T11:00:00.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Run something"}],
            },
        },
        {
            "type": "message",
            "id": "tr1",
            "parentId": "u1",
            "timestamp": "2026-05-01T11:00:01.000Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "x",
                "toolName": "bash",
                "content": [{"type": "text", "text": "output"}],
            },
        },
        {
            "type": "message",
            "id": "a1",
            "parentId": "tr1",
            "timestamp": "2026-05-01T11:00:02.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done"}],
            },
        },
    ]
    session_file = _make_pi_session(sessions_dir, str(root), sid, messages_data)
    source = PiSource()
    ref = SessionRef(
        sid=sid,
        session_file=session_file,
        message_dir=session_file.parent,
        sort_key=session_file.stat().st_mtime,
    )
    export = source.export_session(tmp_path, ref, want_tool_calls=False)
    assert export is not None
    roles = [m.role for m in export.messages]
    assert "toolResult" not in roles
    assert len(export.messages) == 2
