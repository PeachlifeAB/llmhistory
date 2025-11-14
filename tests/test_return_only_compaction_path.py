"""Tests for --output compactionPath behavior."""

import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def test_return_only_compaction_path(tmp_path: Path) -> None:
    """Print only the compactions markdown path in compactionPath mode."""
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

    r = subprocess.run(
        [
            "python3",
            str(exporter),
            "--storage",
            str(storage),
            "--md",
            "--output",
            "compactionPath",
            "--no-pbcopy",
        ],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    if not (r.returncode == 0):
        raise AssertionError(r.stderr)

    expected_path = repo / ".llm" / "T-compactions.md"
    assert r.stdout == f"{expected_path}\n"
    assert expected_path.is_file()
