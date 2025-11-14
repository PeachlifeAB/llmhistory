"""Integration smoke tests and failure formatting helpers."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from disk, returning None for invalid objects."""
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _skip_integration(reason: str) -> None:
    pytest.skip(f"{reason}; skipping integration test")


def _has_required_subdirs(storage_path: Path) -> bool:
    required_subdirs = ["project", "session", "message", "part"]
    missing = [d for d in required_subdirs if not (storage_path / d).is_dir()]
    if missing:
        _skip_integration(
            "OpenCode storage is missing required subdirectories "
            f"({', '.join(missing)})",
        )
    return True


def _has_valid_field(paths: list[Path], field: str) -> bool:
    return any((data := _read_json(path)) and data.get(field) for path in paths)


def _validate_opencode_storage(storage_path: Path) -> None:
    """Skip integration tests when OpenCode storage is unavailable or invalid."""
    if not storage_path.is_dir():
        _skip_integration(
            "OpenCode storage not found at ~/.local/share/opencode/storage"
        )

    _has_required_subdirs(storage_path)

    project_files = sorted((storage_path / "project").glob("*.json"))
    if not project_files:
        _skip_integration("OpenCode storage has no project/*.json files")

    if not _has_valid_field(project_files, "worktree"):
        _skip_integration(
            "OpenCode storage has no valid project JSON with 'worktree' field"
        )

    session_files = sorted((storage_path / "session").glob("*/ses_*.json"))
    if not session_files:
        _skip_integration("OpenCode storage has no session/*/ses_*.json files")

    if not _has_valid_field(session_files, "id"):
        _skip_integration("OpenCode storage has no valid session JSON with 'id' field")


MAX_OUTPUT_LINES = 100


def _truncate_output(text: str, max_lines: int = MAX_OUTPUT_LINES) -> str:
    """Limit captured process output to the configured line budget."""
    if not text:
        return "(empty)"
    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return text.rstrip("\n")
    kept = lines[:max_lines]
    truncated_count = len(lines) - max_lines
    return "".join(kept).rstrip("\n") + f"\n... ({truncated_count} more lines)"


def _format_integration_failure(result: subprocess.CompletedProcess[str]) -> str:
    """Format subprocess failures with bounded stdout and stderr sections."""
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    lines = [
        "",
        "=" * 60,
        "INTEGRATION TEST FAILED",
        "=" * 60,
        f"Exit code: {result.returncode}",
        "",
        "-" * 40,
        f"STDOUT ({len(stdout)} chars):",
        "-" * 40,
        _truncate_output(stdout),
        "",
        "-" * 40,
        f"STDERR ({len(stderr)} chars):",
        "-" * 40,
        _truncate_output(stderr),
        "=" * 60,
    ]

    return "\n".join(lines)


@pytest.mark.integration
def test_integration_script_runs_successfully() -> None:
    """Run the integration shell script against local OpenCode storage."""
    # This is a smoke test around a real shell script that (by design) shells out
    # to OpenCode local storage. It can be slower than the purely synthetic unit
    # tests, so we allow a longer timeout.
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "test-integration.sh"

    if not script_path.is_file():
        pytest.fail(f"Missing integration script at {script_path}")

    storage_path = Path("~/.local/share/opencode/storage").expanduser()
    _validate_opencode_storage(storage_path)

    env = dict(os.environ)
    env.pop("AGENTSENSEI_DIR", None)
    env.pop("AERC_DIR", None)

    result = subprocess.run(
        ["bash", str(script_path)],
        check=False,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise AssertionError(_format_integration_failure(result))


def test_format_integration_failure_includes_stdout_and_stderr() -> None:
    """Include both output streams in formatted integration failures."""
    result = subprocess.CompletedProcess(
        args=["bash", "test-integration.sh"],
        returncode=7,
        stdout="STDOUT content\n",
        stderr="STDERR content\n",
    )

    msg = _format_integration_failure(result)
    assert "INTEGRATION TEST FAILED" in msg
    assert "Exit code: 7" in msg
    assert "STDOUT" in msg
    assert "STDOUT content" in msg
    assert "STDERR" in msg
    assert "STDERR content" in msg


def test_format_integration_failure_handles_empty_output() -> None:
    """Render empty output streams as explicit placeholders."""
    result = subprocess.CompletedProcess(
        args=["bash", "test-integration.sh"],
        returncode=1,
        stdout="",
        stderr=None,
    )

    msg = _format_integration_failure(result)
    assert "Exit code: 1" in msg
    assert "(empty)" in msg


def test_truncate_output_limits_long_output() -> None:
    """Keep only the configured number of lines for long outputs."""
    long_output = "\n".join(f"line {i}" for i in range(200))
    truncated = _truncate_output(long_output, max_lines=50)
    assert "line 0" in truncated
    assert "line 49" in truncated
    assert "line 50" not in truncated
    assert "(150 more lines)" in truncated
