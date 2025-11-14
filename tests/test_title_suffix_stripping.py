"""Tests for title suffix normalization when writing markdown files."""

import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def test_title_suffix_stripping_repeated_suffixes(tmp_path: Path) -> None:
    """Strip repeated known suffixes from generated markdown title filenames."""
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
        {"id": session_id, "title": "report.json.md", "created_at": 1, "updated_at": 2},
    )

    write_json(
        storage / "message" / session_id / "msg_1.json",
        {"id": "msg_1", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Hello"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage)],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert result.returncode == 0

    history_dir = repo / ".llm"
    assert (history_dir / "report.md").is_file()


def test_title_suffix_stripping_fallback_to_untitled(tmp_path: Path) -> None:
    """Fall back to Untitled when stripping leaves an empty title."""
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
        {"id": session_id, "title": ".md.json.jsonl", "created_at": 1, "updated_at": 2},
    )

    write_json(
        storage / "message" / session_id / "msg_1.json",
        {"id": "msg_1", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Hello"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage)],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert result.returncode == 0

    history_dir = repo / ".llm"
    assert (history_dir / "Untitled.md").is_file()
