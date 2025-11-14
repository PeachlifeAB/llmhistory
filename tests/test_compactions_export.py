"""Tests for compactions markdown export behavior."""

import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def test_compactions_file_includes_only_compactions(tmp_path: Path) -> None:
    """Write only compaction messages into the compactions output file."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Minimal git repo root discovery
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    # OpenCode storage layout
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

    # Normal assistant message (not a compaction)
    write_json(
        storage / "message" / session_id / "msg_1.json",
        {"id": "msg_1", "role": "assistant", "time": {"created": 1100}},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Normal message"},
    )

    # Compaction message
    write_json(
        storage / "message" / session_id / "msg_2.json",
        {
            "id": "msg_2",
            "role": "assistant",
            "agent": "compaction",
            "time": {"created": 1200},
        },
    )
    write_json(
        storage / "part" / "msg_2" / "prt_1.json",
        {"type": "text", "text": "Compaction summary"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    r = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all", "--md"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    if not (r.returncode == 0):
        raise AssertionError(r.stderr)

    compactions_path = repo / ".llm" / "T-compactions.md"
    assert compactions_path.is_file()

    text = compactions_path.read_text(encoding="utf-8")
    assert "Compaction summary" in text
    assert "Normal message" not in text


def test_compactions_file_is_force_refreshed(tmp_path: Path) -> None:
    """Rewrite compactions output when force-refresh is enabled."""
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

    write_json(
        storage / "message" / session_id / "msg_1.json",
        {
            "id": "msg_1",
            "role": "assistant",
            "agent": "compaction",
            "time": {"created": 1100},
        },
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Compaction v1"},
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
    assert "Compaction v1" in compactions_path.read_text(encoding="utf-8")

    # Update compaction content
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Compaction v2"},
    )

    refreshed = subprocess.run(
        [
            "python3",
            str(exporter),
            "--storage",
            str(storage),
            "--all",
            "--md",
            "--force-refresh",
        ],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (refreshed.returncode == 0):
        raise AssertionError(refreshed.stderr)

    contents = compactions_path.read_text(encoding="utf-8")
    assert "Compaction v2" in contents
    assert "Compaction v1" not in contents
