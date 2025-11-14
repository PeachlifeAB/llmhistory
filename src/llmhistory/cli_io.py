"""I/O helpers for stdout output and clipboard copy."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from llmhistory.utils import eprint

if TYPE_CHECKING:
    from pathlib import Path


def print_file_to_stdout(path: Path) -> None:
    """Write a file's text content to stdout."""
    sys.stdout.write(path.read_text(encoding="utf-8", errors="replace"))


def write_line_to_stdout(value: str) -> None:
    """Write a single text line to stdout."""
    sys.stdout.write(f"{value}\n")


def _clipboard_command() -> list[str] | None:
    """Return a platform-specific clipboard command if available."""
    linux_command: list[str] | None = None
    if sys.platform == "darwin":
        pbcopy = shutil.which("pbcopy")
        if pbcopy is not None:
            return [pbcopy]
        return None
    if sys.platform.startswith("linux"):
        xclip = shutil.which("xclip")
        if xclip is not None:
            linux_command = [xclip, "-selection", "clipboard"]
        else:
            xsel = shutil.which("xsel")
            if xsel is not None:
                linux_command = [xsel, "--clipboard", "--input"]
        return linux_command
    if sys.platform.startswith("win"):
        clip = shutil.which("clip")
        if clip is not None:
            return [clip]
    return None


def do_pbcopy(value: str, *, no_pbcopy: bool = False, debug: bool = False) -> None:
    """Copy a string value to the system clipboard when available."""
    if no_pbcopy:
        return

    command = _clipboard_command()
    if command is None:
        if debug:
            eprint("⚠️ clipboard unavailable on this platform")
        return

    try:
        result = subprocess.run(  # noqa: S603
            command,
            check=False,
            input=value.encode("utf-8"),
            capture_output=True,
        )
        if debug and result.returncode != 0:
            stderr_output = result.stderr.strip()
            if stderr_output:
                eprint(f"⚠️ pbcopy failed (exit {result.returncode}): {stderr_output}")
            else:
                eprint(f"⚠️ pbcopy failed (exit {result.returncode})")
    except (subprocess.SubprocessError, OSError) as exc:
        if debug:
            eprint(f"⚠️ clipboard command failed: {exc}")
