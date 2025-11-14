"""Tail helper for the most recent markdown export."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from llmhistory.projects import git_root
from llmhistory.utils import die, get_history_dir

if TYPE_CHECKING:
    from pathlib import Path


def get_md_path() -> Path | None:
    """Return the newest non-compactions markdown export path."""
    root = git_root()
    history_dir = get_history_dir(root)
    if not history_dir.is_dir():
        return None

    md_files = [
        path
        for path in history_dir.glob("*.md")
        if not path.name.startswith(".") and not path.name.endswith("-compactions.md")
    ]
    if not md_files:
        return None
    return max(md_files, key=lambda path: path.stat().st_mtime)


def run_tail() -> int:
    """Follow appended content in the most recent markdown export."""
    md_path = get_md_path()
    if md_path is None:
        die("No markdown file found in .llm/")
        return 1

    last_size = md_path.stat().st_size
    with md_path.open("r", encoding="utf-8", errors="replace") as file_handle:
        file_handle.seek(last_size)
        try:
            while True:
                time.sleep(1.0)
                new_size = md_path.stat().st_size
                if new_size < last_size:
                    last_size = 0
                    file_handle.seek(0)
                    continue
                if new_size == last_size:
                    continue
                file_handle.seek(last_size)
                chunk = file_handle.read(new_size - last_size)
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                last_size = new_size
        except KeyboardInterrupt:
            return 0
