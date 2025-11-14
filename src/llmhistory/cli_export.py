"""CLI export workflow orchestration."""

import argparse
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from llmhistory.cli_io import do_pbcopy, print_file_to_stdout, write_line_to_stdout
from llmhistory.export_source_runner import SourceExportContext, export_single_source
from llmhistory.projects import git_root
from llmhistory.sources import ClaudeSource, OpenCodeSource, StorageSource
from llmhistory.storage_index import load_index, save_index_atomic
from llmhistory.utils import die, eprint, get_history_dir


def _latest_file(path_pattern: str, history_dir: Path) -> Path | None:
    candidates = [
        path
        for path in history_dir.glob(path_pattern)
        if path.is_file() and not path.name.startswith(".")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime)


def _latest_markdown_file(history_dir: Path) -> Path | None:
    candidates = [
        path
        for path in history_dir.glob("*.md")
        if path.is_file()
        and not path.name.startswith(".")
        and not path.name.endswith("-compactions.md")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime)


def _first_file(path_pattern: str, history_dir: Path) -> Path | None:
    candidates = sorted(
        [
            path
            for path in history_dir.glob(path_pattern)
            if path.is_file() and not path.name.startswith(".")
        ],
    )
    return candidates[0] if candidates else None


def _first_markdown_file(history_dir: Path) -> Path | None:
    candidates = sorted(
        [
            path
            for path in history_dir.glob("*.md")
            if path.is_file()
            and not path.name.startswith(".")
            and not path.name.endswith("-compactions.md")
        ],
    )
    return candidates[0] if candidates else None


def _resolve_sources(source_selection: str) -> list[StorageSource]:
    sources: list[StorageSource] = []
    if source_selection in ("opencode", "all"):
        sources.append(OpenCodeSource())
    if source_selection in ("claude", "all"):
        sources.append(ClaudeSource())
    return sources


@dataclass(frozen=True)
class RecentPaths:
    """Most-recent and fallback output paths resolved for CLI return modes."""

    most_recent_md_path: Path | None
    latest_generated_json: Path | None
    most_recent_compactions_md_path: Path | None
    first_md_path: Path | None
    first_json_path: Path | None
    first_compactions_md_path: Path | None


def _resolve_output_modes(args: argparse.Namespace) -> tuple[bool, bool, bool]:
    output_json = bool(args.json)
    output_md = bool(args.md)
    compactions_only = bool(getattr(args, "compactions", False))
    if compactions_only:
        output_md = False
        output_json = False
    if not output_json and not output_md and not compactions_only:
        output_md = True
    return output_json, output_md, compactions_only


def _validate_output_args(
    args: argparse.Namespace,
    *,
    output_json: bool,
    output_md: bool,
    compactions_only: bool,
) -> None:
    if args.quiet and output_json and output_md:
        die("--quiet cannot be combined with both --json and --md (ambiguous stdout)")
    if args.output == "path" and not output_md:
        die("--output path requires markdown output (default or --md)")
    if args.output == "compactionPath" and not compactions_only and not output_md:
        die(
            "--output compactionPath requires --compactions "
            "or markdown output (default or --md)",
        )
    if args.output == "session" and args.all:
        die("--output session cannot be combined with --all")
    if args.output == "compactionPath" and args.all and not compactions_only:
        die("--output compactionPath cannot be combined with --all")


def _existing_paths(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.exists()]


def _latest_path(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda path: path.stat().st_mtime) if paths else None


def _resolve_recent_paths(
    history_dir: Path,
    generated_md_paths: list[Path],
    generated_json_paths: list[Path],
    generated_compactions_paths: list[Path],
    *,
    all_sessions: bool,
) -> RecentPaths:
    latest_generated_md = _latest_path(_existing_paths(generated_md_paths))
    latest_generated_json = _latest_path(_existing_paths(generated_json_paths))
    latest_generated_compactions = _latest_path(
        _existing_paths(generated_compactions_paths),
    )

    if all_sessions:
        most_recent_md_path = latest_generated_md or _latest_markdown_file(history_dir)
        most_recent_compactions_md_path = latest_generated_compactions or _latest_file(
            "*-compactions.md",
            history_dir,
        )
    else:
        most_recent_md_path = (
            latest_generated_md
            or (generated_md_paths[0] if generated_md_paths else None)
            or _latest_markdown_file(history_dir)
        )
        most_recent_compactions_md_path = (
            latest_generated_compactions
            or (generated_compactions_paths[0] if generated_compactions_paths else None)
            or _latest_file("*-compactions.md", history_dir)
        )

    return RecentPaths(
        most_recent_md_path=most_recent_md_path,
        latest_generated_json=latest_generated_json,
        most_recent_compactions_md_path=most_recent_compactions_md_path,
        first_md_path=_first_markdown_file(history_dir),
        first_json_path=_first_file("*.jsonl", history_dir),
        first_compactions_md_path=_first_file("*-compactions.md", history_dir),
    )


def _handle_output_shortcuts(
    args: argparse.Namespace,
    recent_paths: RecentPaths,
    most_recent_session_id: str | None,
) -> bool:
    if args.output == "path":
        path = recent_paths.most_recent_md_path or recent_paths.first_md_path
        if path is not None:
            write_line_to_stdout(str(path))
            do_pbcopy(str(path), no_pbcopy=args.no_pbcopy, debug=args.debug)
        elif not args.quiet:
            eprint("No markdown outputs were generated; no path to return.")
        return True

    if args.output == "session":
        if most_recent_session_id is not None:
            write_line_to_stdout(most_recent_session_id)
            do_pbcopy(
                most_recent_session_id,
                no_pbcopy=args.no_pbcopy,
                debug=args.debug,
            )
        elif not args.quiet:
            eprint("No sessions were exported; no session ID to return.")
        return True

    if args.output == "compactionPath":
        path = (
            recent_paths.most_recent_compactions_md_path
            or recent_paths.first_compactions_md_path
        )
        if path is not None:
            write_line_to_stdout(str(path))
            do_pbcopy(str(path), no_pbcopy=args.no_pbcopy, debug=args.debug)
        elif not args.quiet:
            eprint(
                "No compactions outputs were generated; no compactionPath to return.",
            )
        return True

    return False


def _emit_outputs_in_quiet_mode(
    written_outputs: list[Path],
    *,
    output_json: bool,
    output_md: bool,
) -> None:
    for path in written_outputs:
        if output_json and path.suffix == ".jsonl":
            print_file_to_stdout(path)
        if (
            output_md
            and path.suffix == ".md"
            and not path.name.endswith("-compactions.md")
        ):
            print_file_to_stdout(path)


def _copy_default_result(
    args: argparse.Namespace,
    recent_paths: RecentPaths,
    *,
    compactions_only: bool,
    output_json: bool,
    output_md: bool,
) -> None:
    if compactions_only and recent_paths.most_recent_compactions_md_path is not None:
        write_line_to_stdout(str(recent_paths.most_recent_compactions_md_path))
        do_pbcopy(
            str(recent_paths.most_recent_compactions_md_path),
            no_pbcopy=args.no_pbcopy,
            debug=args.debug,
        )
        return

    if output_json and not output_md:
        json_path = recent_paths.latest_generated_json or recent_paths.first_json_path
        if json_path is not None:
            write_line_to_stdout(str(json_path))
            do_pbcopy(str(json_path), no_pbcopy=args.no_pbcopy, debug=args.debug)
        return

    if recent_paths.most_recent_md_path is not None:
        write_line_to_stdout(str(recent_paths.most_recent_md_path))
        do_pbcopy(
            str(recent_paths.most_recent_md_path),
            no_pbcopy=args.no_pbcopy,
            debug=args.debug,
        )


def run_export(args: argparse.Namespace) -> int:
    """Export sessions for selected source(s) according to CLI flags."""
    run_started_at = datetime.now(UTC)
    run_started_perf = time.perf_counter()

    output_json, output_md, compactions_only = _resolve_output_modes(args)
    _validate_output_args(
        args,
        output_json=output_json,
        output_md=output_md,
        compactions_only=compactions_only,
    )

    if not args.quiet and not args.output:
        eprint(f"🕒 Run started: {run_started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    root = git_root()
    history_dir = get_history_dir(root)
    index = load_index(history_dir)

    written_outputs: list[Path] = []
    most_recent_session_id: str | None = None
    generated_md_paths: list[Path] = []
    generated_json_paths: list[Path] = []
    generated_compactions_paths: list[Path] = []

    for source in _resolve_sources(getattr(args, "source", "opencode")):
        storage = (
            Path(args.storage)
            if source.source_name == "opencode"
            else source.get_storage_path()
        )
        (
            source_outputs,
            source_recent_session_id,
            source_recent_md_path,
            source_recent_json_path,
            source_recent_compactions_path,
        ) = export_single_source(
            source=source,
            context=SourceExportContext(
                root=root,
                history_dir=history_dir,
                storage=storage,
                index=index,
                args=args,
                output_md=output_md,
                output_json=output_json,
                compactions_only=compactions_only,
            ),
        )
        written_outputs.extend(source_outputs)
        if source_recent_session_id is not None:
            most_recent_session_id = source_recent_session_id
        if source_recent_md_path is not None:
            generated_md_paths.append(source_recent_md_path)
        if source_recent_json_path is not None:
            generated_json_paths.append(source_recent_json_path)
        if source_recent_compactions_path is not None:
            generated_compactions_paths.append(source_recent_compactions_path)

    save_index_atomic(history_dir, index)

    recent_paths = _resolve_recent_paths(
        history_dir,
        generated_md_paths,
        generated_json_paths,
        generated_compactions_paths,
        all_sessions=args.all,
    )

    if _handle_output_shortcuts(
        args,
        recent_paths=recent_paths,
        most_recent_session_id=most_recent_session_id,
    ):
        return 0

    if args.quiet:
        _emit_outputs_in_quiet_mode(
            written_outputs,
            output_json=output_json,
            output_md=output_md,
        )

    if not args.quiet:
        elapsed_s = time.perf_counter() - run_started_perf
        eprint(f"🎉 Complete. Wrote {len(written_outputs)} outputs.")
        eprint(f"⏱️ Execution time: {elapsed_s:.2f}s")
        _copy_default_result(
            args,
            recent_paths,
            compactions_only=compactions_only,
            output_json=output_json,
            output_md=output_md,
        )

    return 0
