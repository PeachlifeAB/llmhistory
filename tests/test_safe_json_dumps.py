"""Tests for safe_json_dumps basic behavior."""

from llmhistory.storage_index import safe_json_dumps


def test_safe_json_dumps_none_is_null() -> None:
    """Serialize None to JSON null."""
    if safe_json_dumps(None) != "null":
        raise AssertionError


def test_safe_json_dumps_str_passthrough() -> None:
    """Leave simple strings unchanged."""
    if safe_json_dumps("hello") != "hello":
        raise AssertionError
