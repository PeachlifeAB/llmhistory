"""Tests for --force-refresh flag behavior."""

import json
import os
import subprocess
from pathlib import Path

from tests.test_utils import DEFAULT_TIMEOUT_S, write_json


def _init_repo_and_storage(
    tmp_path: Path,
    num_sessions: int = 1,
) -> tuple[Path, Path, str, list[str]]:
    """Create minimal repo and storage with specified number of sessions."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = tmp_path / "storage"
    project_id = "proj_1"
    session_ids = [f"ses_{i}" for i in range(1, num_sessions + 1)]

    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(repo)},
    )

    for i, sid in enumerate(session_ids):
        # Each session has increasing timestamps so ordering is deterministic
        write_json(
            storage / "session" / project_id / f"{sid}.json",
            {
                "id": sid,
                "title": f"Session{i + 1}",
                "time": {"created": 1000 + i, "updated": 2000 + i},
            },
        )
        write_json(
            storage / "message" / sid / f"msg_{i + 1}.json",
            {"id": f"msg_{i + 1}", "role": "user", "time": {"created": 3000 + i}},
        )
        write_json(
            storage / "part" / f"msg_{i + 1}" / f"prt_{i + 1}.json",
            {"type": "text", "text": f"Hello from session {i + 1}"},
        )

    return repo, storage, project_id, session_ids


def _run_export(repo: Path, storage: Path, *args: str) -> subprocess.CompletedProcess:
    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    return subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), *args],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for ln in path.read_text().splitlines() if ln.strip())


def _get_jsonl_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# -----------------------------------------------------------------------------
# Test: --json --force-refresh rewrites latest session's .jsonl only
# -----------------------------------------------------------------------------
def test_force_refresh_json_latest_only(tmp_path: Path) -> None:
    """Force-refresh only the latest JSONL export when --all is not set."""
    repo, storage, _project_id, _session_ids = _init_repo_and_storage(
        tmp_path,
        num_sessions=2,
    )
    history_dir = repo / ".llm"

    # First export: all sessions with --all --json
    r1 = _run_export(repo, storage, "--all", "--json")
    assert r1.returncode == 0

    # Both .jsonl files should exist
    jsonl1 = history_dir / "Session1.jsonl"
    jsonl2 = history_dir / "Session2.jsonl"
    assert jsonl1.exists()
    assert jsonl2.exists()

    initial_lines_1 = _count_jsonl_lines(jsonl1)
    initial_lines_2 = _count_jsonl_lines(jsonl2)
    assert initial_lines_1 >= 1
    assert initial_lines_2 >= 1

    # Run again without --all to append to latest (Session2)
    r2 = _run_export(repo, storage, "--json")
    assert r2.returncode == 0

    # Session2 should have more lines (appended), Session1 unchanged
    # Due to incremental export, might not append if no new messages
    # But the file should still exist
    assert jsonl2.exists()

    # Now force-refresh latest only (Session2)
    r3 = _run_export(repo, storage, "--json", "--force-refresh")
    assert r3.returncode == 0

    # Session2.jsonl should be rewritten (back to 1 line), Session1 unchanged
    final_lines_1 = _count_jsonl_lines(jsonl1)
    final_lines_2 = _count_jsonl_lines(jsonl2)

    if final_lines_1 != initial_lines_1:
        msg = "Session1.jsonl should be unchanged"
        raise AssertionError(msg)
    if final_lines_2 != 1:
        msg = "Session2.jsonl should be rewritten with exactly 1 message"
        raise AssertionError(
            msg,
        )


# -----------------------------------------------------------------------------
# Test: --all --json --force-refresh rewrites all .jsonl files
# -----------------------------------------------------------------------------
def test_force_refresh_json_all_sessions(tmp_path: Path) -> None:
    """Force-refresh all JSONL exports when --all is set."""
    repo, storage, _project_id, _session_ids = _init_repo_and_storage(
        tmp_path,
        num_sessions=2,
    )
    history_dir = repo / ".llm"

    # First export
    r1 = _run_export(repo, storage, "--all", "--json")
    assert r1.returncode == 0

    jsonl1 = history_dir / "Session1.jsonl"
    jsonl2 = history_dir / "Session2.jsonl"

    # Manually append garbage to both files to simulate old/stale data
    with jsonl1.open("a") as f:
        f.write('{"garbage": true}\n')
    with jsonl2.open("a") as f:
        f.write('{"garbage": true}\n')

    lines_before_1 = _count_jsonl_lines(jsonl1)
    lines_before_2 = _count_jsonl_lines(jsonl2)
    assert lines_before_1 >= 2  # original + garbage
    assert lines_before_2 >= 2

    # Force refresh all
    r2 = _run_export(repo, storage, "--all", "--json", "--force-refresh")
    assert r2.returncode == 0

    # Both files should be rewritten (garbage gone)
    final_lines_1 = _count_jsonl_lines(jsonl1)
    final_lines_2 = _count_jsonl_lines(jsonl2)

    if final_lines_1 != 1:
        msg = "Session1.jsonl should have exactly 1 message after force-refresh"
        raise AssertionError(
            msg,
        )
    if final_lines_2 != 1:
        msg = "Session2.jsonl should have exactly 1 message after force-refresh"
        raise AssertionError(
            msg,
        )

    # Verify no garbage records remain
    for rec in _get_jsonl_records(jsonl1) + _get_jsonl_records(jsonl2):
        assert "garbage" not in rec
        assert "session_id" in rec
        assert "project_id" in rec


# -----------------------------------------------------------------------------
# Test: --md --force-refresh rewrites latest session's .md only
# -----------------------------------------------------------------------------
def test_force_refresh_md_latest_only(tmp_path: Path) -> None:
    """Force-refresh only the latest markdown export."""
    repo, storage, _project_id, _session_ids = _init_repo_and_storage(
        tmp_path,
        num_sessions=2,
    )
    history_dir = repo / ".llm"

    # First export all
    r1 = _run_export(repo, storage, "--all", "--md")
    assert r1.returncode == 0

    md1 = history_dir / "Session1.md"
    md2 = history_dir / "Session2.md"
    assert md1.exists()
    assert md2.exists()

    # Append garbage to both
    md1_original = md1.read_text()
    md2_original = md2.read_text()
    md1.write_text(md1_original + "\n<!-- GARBAGE1 -->\n")
    md2.write_text(md2_original + "\n<!-- GARBAGE2 -->\n")

    assert "GARBAGE1" in md1.read_text()
    assert "GARBAGE2" in md2.read_text()

    # Force refresh latest only (Session2 is latest by updated_at)
    r2 = _run_export(repo, storage, "--md", "--force-refresh")
    assert r2.returncode == 0

    # Session1 should still have garbage, Session2 should not
    if "GARBAGE1" not in md1.read_text():
        msg = "Session1.md should be unchanged"
        raise AssertionError(msg)
    if "GARBAGE2" in md2.read_text():
        msg = "Session2.md should be rewritten without garbage"
        raise AssertionError(
            msg,
        )


# -----------------------------------------------------------------------------
# Test: --all --force-refresh (default md) rewrites all .md files
# -----------------------------------------------------------------------------
def test_force_refresh_md_all_sessions(tmp_path: Path) -> None:
    """Force-refresh all markdown exports when --all is set."""
    repo, storage, _project_id, _session_ids = _init_repo_and_storage(
        tmp_path,
        num_sessions=2,
    )
    history_dir = repo / ".llm"

    # First export
    r1 = _run_export(repo, storage, "--all")
    assert r1.returncode == 0

    md1 = history_dir / "Session1.md"
    md2 = history_dir / "Session2.md"

    # Append garbage
    md1.write_text(md1.read_text() + "\n<!-- GARBAGE1 -->\n")
    md2.write_text(md2.read_text() + "\n<!-- GARBAGE2 -->\n")

    # Force refresh all
    r2 = _run_export(repo, storage, "--all", "--force-refresh")
    assert r2.returncode == 0

    # Both should be clean
    assert "GARBAGE1" not in md1.read_text()
    assert "GARBAGE2" not in md2.read_text()


# -----------------------------------------------------------------------------
# Test: --all --json --md --force-refresh rewrites both formats
# -----------------------------------------------------------------------------
def test_force_refresh_both_formats(tmp_path: Path) -> None:
    """Force-refresh both markdown and JSONL outputs in one run."""
    repo, storage, _project_id, _session_ids = _init_repo_and_storage(
        tmp_path,
        num_sessions=1,
    )
    history_dir = repo / ".llm"

    # First export both formats
    r1 = _run_export(repo, storage, "--all", "--json", "--md")
    assert r1.returncode == 0

    md1 = history_dir / "Session1.md"
    jsonl1 = history_dir / "Session1.jsonl"
    assert md1.exists()
    assert jsonl1.exists()

    # Add garbage to both
    md1.write_text(md1.read_text() + "\n<!-- MD_GARBAGE -->\n")
    with jsonl1.open("a") as f:
        f.write('{"jsonl_garbage": true}\n')

    assert "MD_GARBAGE" in md1.read_text()
    assert _count_jsonl_lines(jsonl1) >= 2

    # Force refresh both
    r2 = _run_export(repo, storage, "--all", "--json", "--md", "--force-refresh")
    assert r2.returncode == 0

    # Both should be clean
    assert "MD_GARBAGE" not in md1.read_text()
    assert _count_jsonl_lines(jsonl1) == 1

    records = _get_jsonl_records(jsonl1)
    assert len(records) == 1
    assert "jsonl_garbage" not in records[0]
    assert records[0].get("session_id") == "ses_1"
    assert records[0].get("project_id") == "proj_1"


# -----------------------------------------------------------------------------
# Test: --force-refresh ensures JSONL has new schema (session_id/project_id)
# -----------------------------------------------------------------------------
def test_force_refresh_retrofits_jsonl_schema(tmp_path: Path) -> None:
    """Rebuild JSONL files using the current schema during force-refresh."""
    repo, storage, _project_id, _session_ids = _init_repo_and_storage(
        tmp_path,
        num_sessions=1,
    )
    history_dir = repo / ".llm"
    history_dir.mkdir(parents=True, exist_ok=True)

    # Create a fake old-schema JSONL file (missing session_id/project_id)
    jsonl1 = history_dir / "Session1.jsonl"
    old_record = {"id": "msg_old", "role": "user", "content": "old message"}
    jsonl1.write_text(json.dumps(old_record) + "\n")

    # Verify old schema
    records_before = _get_jsonl_records(jsonl1)
    assert len(records_before) == 1
    assert "session_id" not in records_before[0]
    assert "project_id" not in records_before[0]

    # Force refresh
    r = _run_export(repo, storage, "--json", "--force-refresh")
    assert r.returncode == 0

    # Verify new schema
    records_after = _get_jsonl_records(jsonl1)
    assert len(records_after) == 1
    assert records_after[0].get("session_id") == "ses_1"
    assert records_after[0].get("project_id") == "proj_1"
    if "msg_old" in records_after[0].get("id", ""):
        msg = "Old record should be gone"
        raise AssertionError(msg)
