"""Test that codex and pi are recognized as valid --source values."""
from __future__ import annotations

from llmhistory.cli_args import build_parser
from llmhistory.cli_export import _resolve_sources


def test_codex_source_accepted() -> None:
    """--source codex is a valid CLI argument."""
    parser = build_parser()
    args = parser.parse_args(["--source", "codex"])
    assert args.source == "codex"


def test_pi_source_accepted() -> None:
    """--source pi is a valid CLI argument."""
    parser = build_parser()
    args = parser.parse_args(["--source", "pi"])
    assert args.source == "pi"


def test_all_source_includes_codex_and_pi() -> None:
    """--source all instantiates all four sources including codex and pi."""
    sources = _resolve_sources("all")
    names = [s.source_name for s in sources]
    assert "codex" in names
    assert "pi" in names
