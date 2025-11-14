"""Tests for confirmation helpers."""

import types

import pytest

from llmhistory import confirm


def test_stdin_is_tty_returns_false_when_stdin_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat missing stdin as non-interactive."""
    monkeypatch.setattr(confirm.sys, "stdin", None)

    assert confirm.stdin_is_tty() is False


def test_stdin_is_tty_returns_false_when_isatty_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat stdin objects without isatty as non-interactive."""
    monkeypatch.setattr(confirm.sys, "stdin", types.SimpleNamespace())

    assert confirm.stdin_is_tty() is False
