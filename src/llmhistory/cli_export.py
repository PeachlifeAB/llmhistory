"""CLI export workflow orchestration."""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from llmhistory.cli_io import do_pbcopy, print_file_to_stdout, write_line_to_stdout
from llmhistory.export_source_runner import SourceExportContext, export_single_source
from llmhistory.projects import git_root
from llmhistory.sources import (
    ClaudeSource,
    CodexSource,
    OpenCodeSource,
    PiSource,
    StorageSource,
)
from llmhistory.storage_index import load_index, save_index_atomic
from llmhistory.utils import (
    COLOR_CYAN,
    COLOR_GRAY,
    COLOR_UNDERLINE,
    _color,
    die,
    eprint,
    get_history_dir,
)


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
    all_sources: list[StorageSource] = [
        OpenCodeSource(),
        ClaudeSource(),
        CodexSource(),
        PiSource(),
    ]
    if source_selection == "all":
        return [s for s in all_sources if s.is_installed()]
    return [s for s in all_sources if s.source_name == source_selection]


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


def _best_md_path(md_paths_with_ms: list[tuple[int, Path]]) -> Path | None:
    """Pick the md path whose session has the highest updated_ms."""
    existing = [(ms, p) for ms, p in md_paths_with_ms if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda t: t[0])[1]


def _resolve_recent_paths(  # noqa: PLR0913
    history_dir: Path,
    generated_md_paths: list[Path],
    generated_json_paths: list[Path],
    generated_compactions_paths: list[Path],
    md_paths_with_ms: list[tuple[int, Path]],
    *,
    all_sessions: bool,
) -> RecentPaths:
    # Use session updated_ms to pick the most recent across sources (file mtime is
    # unreliable when multiple sources write files in the same second)
    latest_generated_md = _best_md_path(md_paths_with_ms) or _latest_path(
        _existing_paths(generated_md_paths)
    )
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


def _print_last_session(
    args: argparse.Namespace,
    full_path: Path,
    label: str = "Last session",
) -> None:
    """Print a labelled footer to stderr; write full path to stdout only when piped."""
    eprint(f"▸ {_color(label, COLOR_CYAN)}")
    eprint(_color("─" * 49, COLOR_GRAY))
    if full_path.is_relative_to(Path.cwd()):
        display = str(full_path.relative_to(Path.cwd()))
    else:
        display = str(full_path)
    eprint(f"  {_color(display, COLOR_UNDERLINE)}")
    if not sys.stdout.isatty():
        write_line_to_stdout(str(full_path))
    do_pbcopy(str(full_path), no_pbcopy=args.no_pbcopy, debug=args.debug)


def _copy_default_result(
    args: argparse.Namespace,
    recent_paths: RecentPaths,
    *,
    compactions_only: bool,
    output_json: bool,
    output_md: bool,
) -> None:
    if compactions_only and recent_paths.most_recent_compactions_md_path is not None:
        _print_last_session(
            args, recent_paths.most_recent_compactions_md_path,
            "Last compaction",
        )
        return

    if output_json and not output_md:
        json_path = recent_paths.latest_generated_json or recent_paths.first_json_path
        if json_path is not None:
            _print_last_session(args, json_path, "Last session")
        return

    if recent_paths.most_recent_md_path is not None:
        _print_last_session(args, recent_paths.most_recent_md_path)


def run_export(args: argparse.Namespace) -> int:  # noqa: C901
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

    latest_mode = getattr(args, "latest", False)

    if not args.quiet and not args.output and not latest_mode and args.debug:
        eprint(f"🕒 Run started: {run_started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    root = git_root()
    history_dir = get_history_dir(root)
    index = load_index(history_dir)

    written_outputs: list[Path] = []
    most_recent_session_id: str | None = None
    generated_md_paths: list[Path] = []
    generated_json_paths: list[Path] = []
    generated_compactions_paths: list[Path] = []
    # Per-source latest paths for --latest display and cross-source recency ranking
    latest_per_source: list[tuple[str, Path, Path | None]] = []
    # (updated_ms, md_path) pairs for picking the globally most-recent session
    md_paths_with_ms: list[tuple[int, Path]] = []

    source_selection = getattr(args, "source", "all")
    is_all_mode = source_selection == "all"

    for source in _resolve_sources(source_selection):
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
            source_most_recent_updated_ms,
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
                warn_if_no_projects=not is_all_mode,
                show_source_header=is_all_mode,
            ),
        )
        written_outputs.extend(source_outputs)
        if source_recent_session_id is not None:
            most_recent_session_id = source_recent_session_id
        if source_recent_md_path is not None:
            generated_md_paths.append(source_recent_md_path)
            md_paths_with_ms.append(
                (source_most_recent_updated_ms, source_recent_md_path)
            )
            latest_per_source.append((
                source.source_name,
                source_recent_md_path,
                source_recent_compactions_path,
            ))
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
        md_paths_with_ms,
        all_sessions=args.all,
    )

    if getattr(args, "latest", False):
        return _handle_latest(args, latest_per_source, recent_paths)

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
        if args.debug:
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


def _handle_latest(
    args: argparse.Namespace,
    latest_per_source: list[tuple[str, Path, Path | None]],
    recent_paths: RecentPaths,
) -> int:
    """Handle --latest: show latest session + compaction per harness."""
    is_piped = not sys.stdout.isatty()

    if is_piped:
        # Pipe mode: print the single most recently changed session path
        path = recent_paths.most_recent_md_path or recent_paths.first_md_path
        if path is not None:
            write_line_to_stdout(str(path))
        return 0

    # Interactive mode: show latest session and compaction per harness
    for source_name, md_path, compaction_path in latest_per_source:
        eprint(f"[{source_name}] {md_path}")
        if compaction_path is not None and compaction_path.exists():
            eprint(f"[{source_name}] compaction: {compaction_path}")

    # Still output the most recent path to stdout and clipboard
    path = recent_paths.most_recent_md_path or recent_paths.first_md_path
    if path is not None:
        write_line_to_stdout(str(path))
        do_pbcopy(str(path), no_pbcopy=args.no_pbcopy, debug=args.debug)

    return 0
