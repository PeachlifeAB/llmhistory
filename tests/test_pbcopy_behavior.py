"""Tests for clipboard copy behavior across output modes."""

import asyncio
import os
import platform
import subprocess
from pathlib import Path

import pytest

from llmhistory import cli_io
from tests.test_utils import DEFAULT_TIMEOUT_S, write_json

MACOS_ONLY = pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="pbcopy/pbpaste are macOS-only",
)


def _create_minimal_storage(tmp_path: Path, repo: Path) -> Path:
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
    write_json(
        storage / "message" / session_id / "msg_1.json",
        {"id": "msg_1", "role": "user", "created_at": 10},
    )
    write_json(
        storage / "part" / "msg_1" / "prt_1.json",
        {"type": "text", "text": "Hello"},
    )

    return storage


def test_no_pbcopy_flag_avoids_calling_pbcopy(tmp_path: Path) -> None:
    """Do not invoke pbcopy when --no-pbcopy is passed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = _create_minimal_storage(tmp_path, repo)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    # Create a fake pbcopy that would fail if called.
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    pbcopy = fakebin / "pbcopy"
    pbcopy.write_text(
        "#!/usr/bin/env sh\necho PB_COPY_WAS_CALLED >&2\nexit 42\n",
        encoding="utf-8",
    )
    pbcopy.chmod(0o755)

    env["PATH"] = f"{fakebin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--no-pbcopy"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    assert result.returncode == 0
    assert "PB_COPY_WAS_CALLED" not in result.stderr


def test_debug_logs_pbcopy_failure(tmp_path: Path) -> None:
    """Log pbcopy failures in debug mode while still succeeding."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = _create_minimal_storage(tmp_path, repo)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    # Fake pbcopy that fails
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    pbcopy = fakebin / "pbcopy"
    pbcopy.write_text(
        "#!/usr/bin/env sh\necho PB_COPY_WAS_CALLED >&2\nexit 42\n",
        encoding="utf-8",
    )
    pbcopy.chmod(0o755)

    env["PATH"] = f"{fakebin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--debug"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    assert result.returncode == 0
    assert "PB_COPY_WAS_CALLED" in result.stderr
    assert "pbcopy failed" in result.stderr


def test_do_pbcopy_works_inside_running_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid asyncio.run failures when clipboard copy is called from a running loop."""
    monkeypatch.setattr(cli_io, "_clipboard_command", lambda: ["fake-pbcopy"])

    captured: dict[str, object] = {}

    def fake_run(
        args: list[str],
        *,
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["check"] = check
        captured["input"] = kwargs["input"]
        captured["capture_output"] = kwargs["capture_output"]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(cli_io.subprocess, "run", fake_run)

    async def run_test() -> None:
        cli_io.do_pbcopy("hello", debug=True)

    asyncio.run(run_test())

    assert captured == {
        "args": ["fake-pbcopy"],
        "check": False,
        "input": b"hello",
        "capture_output": True,
    }


@MACOS_ONLY
def test_output_path_calls_pbcopy_with_path(tmp_path: Path) -> None:
    """--output path should pbcopy the markdown file path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = _create_minimal_storage(tmp_path, repo)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--output", "path"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    assert result.returncode == 0
    # stdout should have the path
    stdout_path = result.stdout.strip()
    assert stdout_path.endswith(".md")

    # Verify pbcopy worked by checking pbpaste
    paste_result = subprocess.run(
        ["pbpaste"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert paste_result.returncode == 0
    assert paste_result.stdout.strip() == stdout_path


@MACOS_ONLY
def test_output_session_calls_pbcopy_with_session_id(tmp_path: Path) -> None:
    """--output session should pbcopy the session ID."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = _create_minimal_storage(tmp_path, repo)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    result = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--output", "session"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )

    assert result.returncode == 0
    # stdout should have the session ID
    stdout_session = result.stdout.strip()
    assert stdout_session == "ses_1"

    # Verify pbcopy worked by checking pbpaste
    paste_result = subprocess.run(
        ["pbpaste"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert paste_result.returncode == 0
    assert paste_result.stdout.strip() == "ses_1"


@MACOS_ONLY
def test_default_mode_idempotent_run_still_copies_path(tmp_path: Path) -> None:
    """Keep copying the markdown path on idempotent default-mode runs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = _create_minimal_storage(tmp_path, repo)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    r1 = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage)],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r1.returncode == 0

    md_path = Path(r1.stdout.strip())
    assert md_path.is_file()

    # Ensure we aren't getting a false positive due to clipboard carrying over
    subprocess.run(["pbcopy"], input=b"SENTINEL", check=False)

    r2 = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage)],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r2.returncode == 0

    # Should still print the existing path
    assert Path(r2.stdout.strip()) == md_path

    paste_result = subprocess.run(
        ["pbpaste"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert paste_result.returncode == 0
    assert paste_result.stdout.strip() == str(md_path)


@MACOS_ONLY
def test_all_mode_idempotent_run_copies_last_modified_path(tmp_path: Path) -> None:
    """Copy the newest markdown path when rerunning with --all."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = tmp_path / "storage"
    project_id = "proj_1"

    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(repo)},
    )

    # Two sessions so we can select the newest by mtime.
    write_json(
        storage / "session" / project_id / "ses_1.json",
        {"id": "ses_1", "title": "T1", "created_at": 1, "updated_at": 2},
    )
    write_json(
        storage / "session" / project_id / "ses_2.json",
        {"id": "ses_2", "title": "T2", "created_at": 1, "updated_at": 2},
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

    r1 = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r1.returncode == 0

    history_dir = repo / ".llm"
    t1 = history_dir / "T1.md"
    t2 = history_dir / "T2.md"
    assert t1.is_file()
    assert t2.is_file()

    # Make T2 deterministically the "last modified" file.
    os.utime(t1, (1000.0, 1000.0))
    os.utime(t2, (2000.0, 2000.0))

    subprocess.run(["pbcopy"], input=b"SENTINEL", check=False)

    r2 = subprocess.run(
        ["python3", str(exporter), "--storage", str(storage), "--all"],
        check=False,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    assert r2.returncode == 0

    # Should print and pbcopy the newest file.
    assert r2.stdout.strip() == str(t2)

    paste_result = subprocess.run(
        ["pbpaste"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert paste_result.returncode == 0
    assert paste_result.stdout.strip() == str(t2)


def test_output_path_respects_no_pbcopy_flag(tmp_path: Path) -> None:
    """--output path --no-pbcopy should not call pbcopy."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    storage = _create_minimal_storage(tmp_path, repo)

    exporter = Path(__file__).resolve().parents[1] / "scripts/llmhistory_export.py"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    # Fake pbcopy that would fail if called
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    pbcopy = fakebin / "pbcopy"
    pbcopy.write_text(
        "#!/usr/bin/env sh\necho PB_COPY_WAS_CALLED >&2\nexit 42\n",
        encoding="utf-8",
    )
    pbcopy.chmod(0o755)

    env["PATH"] = f"{fakebin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
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

    assert result.returncode == 0
    assert "PB_COPY_WAS_CALLED" not in result.stderr
