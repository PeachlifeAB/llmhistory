"""Tests for export discovery helpers."""

from pathlib import Path

from llmhistory.export_discovery import _jsonl_contains_session_id


def test_jsonl_contains_session_id_skips_non_dict_rows(tmp_path: Path) -> None:
    """Ignore non-dict JSONL rows instead of raising AttributeError."""
    path = tmp_path / "session.jsonl"
    path.write_text('[]\n"text"\n{"session_id": "ses_2"}\n')

    assert _jsonl_contains_session_id(path, "ses_1") is False
