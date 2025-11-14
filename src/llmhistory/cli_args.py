"""Argument parser construction for the llmhistory CLI."""

from __future__ import annotations

import argparse
from typing import TypeVar, cast

from llmhistory.utils import DEFAULT_OPENCODE_STORAGE, get_version

_T = TypeVar("_T")


def _add_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="Export all sessions")
    parser.add_argument("--json", action="store_true", help="Export JSONL (.jsonl)")
    parser.add_argument("--md", action="store_true", help="Export Markdown (.md)")
    parser.add_argument(
        "--compactions",
        action="store_true",
        help="Export only compactions markdown",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress status messages",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--no-pbcopy",
        action="store_true",
        help="Do not copy path to clipboard",
    )
    parser.add_argument(
        "--output",
        choices=["path", "session", "compactionPath"],
        help=(
            "Pipe-friendly output: 'path' prints markdown file path, "
            "'session' prints session ID, "
            "'compactionPath' prints compactions markdown file path"
        ),
    )
    parser.add_argument(
        "--source",
        choices=["opencode", "claude", "all"],
        default="opencode",
        help="Export source: opencode (default), claude, or all",
    )
    parser.add_argument(
        "--storage",
        default=str(DEFAULT_OPENCODE_STORAGE),
        help=(
            "Storage root "
            "(auto-detected for --source claude; default: OpenCode storage)"
        ),
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Delete and rewrite output files (retrofits old JSONL schema)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for all supported subcommands."""
    parser = argparse.ArgumentParser(
        description=(
            "Export LLM conversation history "
            "(OpenCode, Claude Desktop) to markdown and JSONL"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
    )

    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser("export", help="Export session history")
    _add_export_arguments(export_parser)
    export_parser.set_defaults(command="export")

    tail_parser = subparsers.add_parser("tail", help="Tail most recent markdown export")
    tail_parser.set_defaults(command="tail")

    prune_parser = subparsers.add_parser("prune", help="Prune untracked sessions")
    prune_parser.add_argument("--dry-run", action="store_true")
    prune_parser.add_argument("--yes", "-y", action="store_true")
    prune_parser.set_defaults(command="prune")

    delete_parser = subparsers.add_parser(
        "delete-older-than",
        help="Delete sessions older than duration",
    )
    delete_parser.add_argument("duration")
    delete_parser.add_argument("--dry-run", action="store_true")
    delete_parser.add_argument("--yes", "-y", action="store_true")
    delete_parser.add_argument("--global", dest="global_mode", action="store_true")
    delete_parser.set_defaults(command="delete-older-than")

    cleanup_parser = subparsers.add_parser(
        "cleanup-orphans",
        help="Trash orphaned part directories",
    )
    cleanup_parser.add_argument("--dry-run", action="store_true")
    cleanup_parser.add_argument("--yes", "-y", action="store_true")
    cleanup_parser.set_defaults(command="cleanup-orphans")

    _add_export_arguments(parser)
    parser.set_defaults(command="export")
    return parser


def get_arg(args: argparse.Namespace, name: str, default: _T) -> _T:
    """Read an argparse attribute, falling back to ``default`` when missing."""
    value = getattr(args, name, None)
    return cast("_T", default if value is None else value)
