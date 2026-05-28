"""Tests for path/session-only output modes."""

import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def _init_minimal_repo_and_storage(tmp_path: Path) -> tuple[Path, Path]:
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

    return repo, storage


def test_output_path_returns_existing_path_on_idempotent_run(tmp_path: Path) -> None:
    """Return existing markdown path on repeated --output path runs."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    history_dir = repo / ".llm"

    # One message + one part
    session_id = "ses_1"
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

    # First run writes markdown
    r1 = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--output", "path"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r1.returncode == 0
    first_path = Path(r1.stdout.strip())
    assert first_path.is_file()

    # Second run should still return the existing markdown path, even if no new messages
    r2 = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--output", "path"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r2.returncode == 0
    second_path = Path(r2.stdout.strip())
    assert second_path == first_path
    assert second_path.is_file()

    # Sanity: markdown exists in history directory
    assert any(history_dir.glob("*.md"))


def test_json_mode_prints_latest_jsonl_path_on_idempotent_run(tmp_path: Path) -> None:
    """Return existing JSONL path on repeated --json runs."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    session_id = "ses_1"
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

    first = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--json", "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert first.returncode == 0
    first_path = Path(first.stdout.strip())
    assert first_path.is_file()
    assert first_path.suffix == ".jsonl"

    second = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--json", "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert second.returncode == 0
    second_path = Path(second.stdout.strip())
    assert second_path == first_path
    assert second_path.is_file()
    assert second.returncode == 0  # idempotent run succeeds


def test_output_path_prints_nothing_when_no_messages(tmp_path: Path) -> None:
    """Print no stdout path when no messages can be exported."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    r = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--output", "path"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r.returncode == 0
    assert r.stdout == ""
    assert "No markdown outputs were generated" in r.stderr


def test_quiet_disallows_md_and_json_combination(tmp_path: Path) -> None:
    """Reject ambiguous --quiet usage with both markdown and JSON outputs."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    r = subprocess.run(
        [
            "python3",
            str(exporter),
            "--storage",
            str(storage),
            "--quiet",
            "--md",
            "--json",
        ],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r.returncode != 0
    assert "--quiet cannot be combined with both --json and --md" in r.stderr


def test_output_session_returns_session_id(tmp_path: Path) -> None:
    """Return session id when exporting with --output session."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    # Add a message so export actually produces output
    session_id = "ses_1"
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
        ["python3", str(exporter), "--storage", str(storage), "--output", "session"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "ses_1"


def test_output_session_returns_session_id_when_no_messages(tmp_path: Path) -> None:
    """Return session id even when the session has no exportable messages."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    r = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--output", "session"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "ses_1"


def test_output_session_works_with_json_only(tmp_path: Path) -> None:
    """--output session should work even when only JSON is exported (no markdown)."""
    repo, storage = _init_minimal_repo_and_storage(tmp_path)

    session_id = "ses_1"
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
            "--json",
            "--output",
            "session",
        ],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "ses_1"


def test_default_output_path_prefers_selected_latest_session_not_latest_file_mtime(
    tmp_path: Path,
) -> None:
    """Use selected latest session, not file mtime, for default output path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = tmp_path / "storage"
    project_id = "proj_1"
    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(repo)},
    )

    write_json(
        storage / "session" / project_id / "ses_1.json",
        {"id": "ses_1", "title": "T1", "time": {"created": 1000, "updated": 1000}},
    )
    write_json(
        storage / "session" / project_id / "ses_2.json",
        {"id": "ses_2", "title": "T2", "time": {"created": 1000, "updated": 9000}},
    )

    write_json(
        storage / "message" / "ses_1" / "msg_1.json",
        {"id": "msg_1", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Hello1"},
    )
    write_json(
        storage / "message" / "ses_2" / "msg_2.json",
        {"id": "msg_2", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_2" / "prt_1.json",
        {"type": "text", "text": "Hello2"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    first = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all", "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (first.returncode == 0):
        raise AssertionError(first.stderr)

    history_dir = repo / ".llm"
    t1 = history_dir / "T1.md"
    t2 = history_dir / "T2.md"
    assert t1.is_file()
    assert t2.is_file()

    os.utime(t1, (3000.0, 3000.0))
    os.utime(t2, (1000.0, 1000.0))

    second = subprocess.run(
        [
            "python3",
            str(exporter),
            "--storage",
            str(storage),
            "--output",
            "path",
            "--no-pbcopy",
        ],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (second.returncode == 0):
        raise AssertionError(second.stderr)
    assert second.stdout.strip() == str(t2)


def test_default_run_rewrites_missing_latest_markdown_even_with_stale_index(
    tmp_path: Path,
) -> None:
    """Rebuild missing latest markdown even if index state is stale."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = tmp_path / "storage"
    project_id = "proj_1"
    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(repo)},
    )

    write_json(
        storage / "session" / project_id / "ses_1.json",
        {"id": "ses_1", "title": "Older", "time": {"created": 1000, "updated": 1000}},
    )
    write_json(
        storage / "session" / project_id / "ses_2.json",
        {"id": "ses_2", "title": "Latest", "time": {"created": 1000, "updated": 9000}},
    )

    write_json(
        storage / "message" / "ses_1" / "msg_1.json",
        {"id": "msg_1", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "old"},
    )
    write_json(
        storage / "message" / "ses_2" / "msg_2.json",
        {"id": "msg_2", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_2" / "prt_1.json",
        {"type": "text", "text": "new"},
    )

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    first = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all", "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (first.returncode == 0):
        raise AssertionError(first.stderr)

    latest_path = repo / ".llm" / "Latest.md"
    older_path = repo / ".llm" / "Older.md"
    assert latest_path.is_file()
    assert older_path.is_file()

    latest_path.unlink()
    assert not latest_path.exists()

    second = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not (second.returncode == 0):
        raise AssertionError(second.stderr)
    assert second.stdout.strip() == str(latest_path)
    assert latest_path.is_file()
