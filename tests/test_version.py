"""Version command tests for editable installs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_editable_install_cli_is_executable(tmp_path: Path) -> None:
    """Verify the installed CLI is executable and returns help.

    Installs from working tree and keeps it installed for user testing/validation.
    """
    if sys.platform.startswith("win"):
        pytest.skip("Windows not supported by this test")

    repo_root = _repo_root()

    tool_bin = Path(
        subprocess.check_output(["uv", "tool", "dir", "--bin"]).decode().strip(),
    )
    opencode_export_path = tool_bin / "llmhistory"

    # Install from working tree, keep it installed for user validation
    subprocess.check_call(
        ["uv", "tool", "install", "--force", str(repo_root)],
    )

    # Print version for visibility (first thing after date)
    version_result = subprocess.run(
        [str(opencode_export_path), "--version"],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    version_str = version_result.stdout.strip()
    assert version_str.startswith("llmhistory ")

    result = subprocess.run(
        [str(opencode_export_path), "--help"],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    if result.returncode != 0:
        msg = f"CLI returned code {result.returncode}: {result.stderr}"
        raise AssertionError(
            msg,
        )
    assert "--help" in result.stdout


def test_editable_install_version_format(tmp_path: Path) -> None:  # noqa: C901
    """Emit version string with expected git hash and timestamp segments."""
    if sys.platform.startswith("win"):
        pytest.skip("Windows not supported by this test")

    repo_root = _repo_root()

    tags = subprocess.run(
        ["git", "tag", "--list"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not tags:
        pytest.skip("No git tags — hatch-vcs cannot produce a versioned build")

    tool_bin = Path(
        subprocess.check_output(["uv", "tool", "dir", "--bin"]).decode().strip(),
    )
    opencode_export_path = tool_bin / "llmhistory"

    # Install from working tree, keep it installed for user validation
    subprocess.check_call(
        ["uv", "tool", "install", "--force", str(repo_root)],
    )

    out = (
        subprocess.check_output(
            [str(opencode_export_path), "--version"],
            cwd=repo_root,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        .decode()
        .strip()
    )

    # Print version for visibility (first thing after date)

    if not (out.startswith("llmhistory ")):
        msg = f"Version should start with 'llmhistory ': {out}"
        raise AssertionError(
            msg,
        )

    if "+g" not in out:
        msg = f"Version should contain '+g' for git hash: {out}"
        raise AssertionError(msg)
    hash_part = out.split("+g")[1][:7]
    if len(hash_part) != 7:
        msg = f"Git hash should be 7 chars: {hash_part}"
        raise AssertionError(msg)
    if not (all(c in "0123456789abcdef" for c in hash_part)):
        msg = f"Git hash should be hex: {hash_part}"
        raise AssertionError(
            msg,
        )

    # Version contains .devN distance from tag (e.g. 0.1.2.dev8+gd90ea87c8)
    if ".dev" not in out:
        msg = f"Version should contain '.dev' for distance from tag: {out}"
        raise AssertionError(msg)

    # Also verify the dev-venv version (uv run) has the full timestamp.
    # uv tool install strips local segments, so check importlib.metadata directly.
    venv_ver = subprocess.check_output(
        ["uv", "run", "python", "-c",
         "from importlib.metadata import version; print(version('llmhistory'))"],
        cwd=repo_root,
        env={**os.environ, "PYTHONUTF8": "1"},
    ).decode().strip()
    if ".d20" not in venv_ver:
        msg = f"Dev-venv version should contain '.d20' timestamp: {venv_ver}"
        raise AssertionError(msg)
    timestamp = venv_ver.rsplit(".d", 1)[1]
    if len(timestamp) != 14:
        msg = f"Timestamp should be 14 chars, got {len(timestamp)}: {timestamp}"
        raise AssertionError(msg)
    if not timestamp.isdigit():
        msg = f"Timestamp should be all digits: {timestamp}"
        raise AssertionError(msg)
