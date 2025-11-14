"""Top-level CLI command dispatch for llmhistory."""

from __future__ import annotations

import sys

from llmhistory.cli_args import build_parser
from llmhistory.cli_export import run_export
from llmhistory.cli_tail import run_tail
from llmhistory.pruning import (
    run_cleanup_orphans,
    run_delete_older_than,
    run_delete_older_than_global,
    run_prune,
)


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the selected subcommand."""
    args_to_parse = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(args_to_parse)

    command = getattr(args, "command", "export")
    if command == "tail":
        return run_tail()
    if command == "prune":
        return run_prune(
            dry_run=bool(getattr(args, "dry_run", False)),
            yes=bool(getattr(args, "yes", False)),
        )
    if command == "delete-older-than":
        duration = str(args.duration)
        dry_run = bool(getattr(args, "dry_run", False))
        yes = bool(getattr(args, "yes", False))
        if bool(getattr(args, "global_mode", False)):
            return run_delete_older_than_global(duration, dry_run=dry_run, yes=yes)
        return run_delete_older_than(duration, dry_run=dry_run, yes=yes)
    if command == "cleanup-orphans":
        return run_cleanup_orphans(
            dry_run=bool(getattr(args, "dry_run", False)),
            yes=bool(getattr(args, "yes", False)),
        )
    return run_export(args)
