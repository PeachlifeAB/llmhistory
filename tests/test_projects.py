"""Tests for project discovery helpers."""

from pathlib import Path

from llmhistory import projects
from tests.test_utils import write_json


def test_most_recent_activity_handles_malformed_timestamps(tmp_path: Path) -> None:
    """Treat malformed session timestamps as zero instead of crashing."""
    storage = tmp_path / "storage"
    session_file = storage / "session" / "proj_1" / "ses_1.json"
    write_json(session_file, {"time": {"updated": "bad", "created": "oops"}})

    assert projects.most_recent_activity_for_project(storage, "proj_1") >= 0.0
