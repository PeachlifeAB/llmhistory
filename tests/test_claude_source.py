"""Tests for Claude path encoding helpers."""

from llmhistory.sources.claude import _encode_path_to_dirname


def test_encode_path_handles_dots() -> None:
    """Encode dotted path segments into Claude project directory names."""
    path = "/Users/davidaberg/.claude-worktrees/AcubizDev/stupefied-tu"
    expected = "-Users-davidaberg--claude-worktrees-AcubizDev-stupefied-tu"
    assert _encode_path_to_dirname(path) == expected


def test_encode_path_handles_slashes() -> None:
    """Encode slash-separated paths into Claude project directory names."""
    path = "/Users/davidaberg/Developer/project"
    expected = "-Users-davidaberg-Developer-project"
    assert _encode_path_to_dirname(path) == expected
