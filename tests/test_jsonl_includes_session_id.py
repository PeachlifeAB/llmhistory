"""Tests ensuring JSONL exports include project and session identifiers."""

import json
import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def _init_minimal_repo_and_storage(tmp_path: Path) -> tuple[Path, Path, str, str]:
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
        {"id": session_id, "title": "T", "created_at": 1, "updated_at": 2},
    )

    return repo, storage, project_id, session_id


def test_jsonl_lines_include_project_id_and_session_id(tmp_path: Path) -> None:
    """Emit project_id and session_id fields on every JSONL line."""
    repo, storage, project_id, session_id = _init_minimal_repo_and_storage(tmp_path)

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

    r = subprocess.run(
        [
            "python3",
            str(exporter),
            "--storage",
            str(storage),
            "--all",
            "--json",
            "--quiet",
        ],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    assert r.returncode == 0

    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not (lines):
        msg = "Expected JSONL output on stdout in --quiet --json mode"
        raise AssertionError(msg)

    for ln in lines:
        obj = json.loads(ln)
        assert obj.get("project_id") == project_id
        assert obj.get("session_id") == session_id
