"""Interactive confirmation utilities for destructive commands."""

from __future__ import annotations

import sys

from llmhistory.utils import die


def stdin_is_tty() -> bool:
    """Return whether stdin is attached to an interactive terminal."""
    stdin = sys.stdin
    if stdin is None or not hasattr(stdin, "isatty"):
        return False
    try:
        return stdin.isatty()
    except OSError:
        return False


def confirm_or_die(*, operation: str, count: int, yes: bool, dry_run: bool) -> None:
    """Request confirmation for destructive operations or exit."""
    if dry_run or yes:
        return

    if not stdin_is_tty():
        die(
            "Refusing to prompt for confirmation in "
            f"non-interactive mode for '{operation}' "
            f"({count} sessions). Re-run with --yes.",
        )

    answer = input(f"{operation}: trash {count} sessions? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        die("Aborted.")
