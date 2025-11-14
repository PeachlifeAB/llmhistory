"""Tests for stable compactions output when nothing changes."""

import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def test_compactions_file_does_not_grow_when_no_new_compactions(tmp_path: Path) -> None:
    """Keep compactions file unchanged when no compaction messages are added."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = tmp_path / "storage"
    project_id = "proj_1"
    session_id = "ses_1"

    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(repo)},
    )
    write_json(
        storage / "session" / project_id / f"{session_id}.json",
        {"id": session_id, "title": "T", "time": {"created": 1000, "updated": 2000}},
    )

    # Only a normal assistant message (not a compaction)
    write_json(
        storage / "message" / session_id / "msg_1.json",
        {"id": "msg_1", "role": "assistant", "time": {"created": 1100}},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Normal message"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    first = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all", "--md"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (first.returncode == 0):
        raise AssertionError(first.stderr)

    compactions_path = repo / ".llm" / "T-compactions.md"
    assert compactions_path.is_file()

    baseline = compactions_path.read_text(encoding="utf-8")

    second = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all", "--md"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (second.returncode == 0):
        raise AssertionError(second.stderr)

    after = compactions_path.read_text(encoding="utf-8")
    assert after == baseline
