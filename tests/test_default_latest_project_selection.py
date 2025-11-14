"""Tests for default project selection behavior."""

import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def test_default_export_prefers_exact_worktree_project_over_parent_match(
    tmp_path: Path,
) -> None:
    """Prefer exact worktree project match over broader parent directory matches."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = tmp_path / "storage"
    old_project = "proj_old"
    new_project = "proj_new"

    write_json(
        storage / "project" / f"{old_project}.json",
        {"id": old_project, "worktree": str(repo)},
    )
    write_json(
        storage / "project" / f"{new_project}.json",
        {"id": new_project, "worktree": str(tmp_path)},
    )

    write_json(
        storage / "session" / old_project / "ses_old.json",
        {"id": "ses_old", "title": "Old", "time": {"created": 1000, "updated": 1000}},
    )
    write_json(
        storage / "session" / new_project / "ses_new.json",
        {"id": "ses_new", "title": "New", "time": {"created": 1000, "updated": 9000}},
    )

    write_json(
        storage / "message" / "ses_old" / "msg_old.json",
        {"id": "msg_old", "role": "user", "time": {"created": 1100}},
    )
    write_json(
        storage / "part" / "msg_old" / "prt_1.json",
        {"type": "text", "text": "old"},
    )
    write_json(
        storage / "message" / "ses_new" / "msg_new.json",
        {"id": "msg_new", "role": "user", "time": {"created": 9100}},
    )
    write_json(
        storage / "part" / "msg_new" / "prt_1.json",
        {"type": "text", "text": "new"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (result.returncode == 0):
        raise AssertionError(result.stderr)

    history_dir = repo / ".llm"
    assert (history_dir / "Old.md").is_file()
    assert (history_dir / "Old-compactions.md").is_file()
    assert not (history_dir / "New.md").exists()
