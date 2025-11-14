"""Per-source export orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from llmhistory.formatting import (
    SessionHeader,
    append_compactions_markdown,
    append_jsonl,
    append_markdown_with_tools,
)
from llmhistory.storage_index import get_export_state, update_export_state
from llmhistory.utils import (
    _color_bold,
    _color_cyan,
    _color_dim,
    _color_yellow,
    _format_relative_age_ms,
    eprint,
    sanitize,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from llmhistory.models import Message, SessionExport, SessionRef
    from llmhistory.sources.base import StorageSource

_TITLE_SUFFIX_RE = re.compile(r"(\.md|\.jsonl|\.json)+$")


def _safe_export_title(source_name: str, title: str) -> str:
    safe_title = sanitize(title)
    safe_title = _TITLE_SUFFIX_RE.sub("", safe_title)
    if not safe_title:
        safe_title = "Untitled"
    if source_name != "opencode":
        safe_title = f"{source_name}-{safe_title}"
    return safe_title


def _collect_compactions(messages: list[Message]) -> list[tuple[Message, str]]:
    return [(message, "") for message in messages if message.agent == "compaction"]


def _session_agent_label(prepared: _PreparedSession) -> str | None:
    for message in prepared.exported.messages:
        label = message.agent or message.mode
        if not label:
            continue
        token = re.split(r"[^a-zA-Z0-9]+", label.strip().lower(), maxsplit=1)[0]
        if token:
            return token
    return None


def _nested_display_title(prepared: _PreparedSession) -> str:
    title = prepared.safe_title.removesuffix("_subagent")
    agent_label = _session_agent_label(prepared)
    if agent_label and title.endswith(f"_{agent_label}"):
        title = title[: -(len(agent_label) + 1)]
    if agent_label:
        badge = _color_cyan(f"[{agent_label}]")
        return f"{badge} {title}"
    return title


def _session_progress_line(
    prepared: _PreparedSession,
    source_name: str,  # noqa: ARG001
    now_ms: int | None = None,
    *,
    depth: int = 0,
) -> str:
    age = _format_relative_age_ms(prepared.exported.updated_ms, now_ms=now_ms)
    age_styled = _color_yellow(age)
    title = prepared.safe_title if depth == 0 else _nested_display_title(prepared)
    sid_display = _color_dim(prepared.session_ref.sid)
    title_styled = _color_bold(title)
    body = f"{title_styled} {sid_display}"

    prefix = "│ " if depth == 0 else "└─ "
    indent = "  " * depth if depth > 0 else ""
    return f"{indent}{age_styled} {prefix}{body}"


def _latest_session_sort_key(
    source: StorageSource,
    storage: Path,
    project_id: str,
    root: Path,
    *,
    debug: bool,
) -> float:
    sessions = source.resolve_sessions(
        storage,
        project_id,
        root,
        all_sessions=True,
        debug=debug,
    )
    if not sessions:
        return 0.0
    return sessions[0].sort_key


@dataclass(frozen=True)
class SourceExportContext:
    """All export settings required to process one source."""

    root: Path
    history_dir: Path
    storage: Path
    index: dict
    args: argparse.Namespace
    output_md: bool
    output_json: bool
    compactions_only: bool


@dataclass(frozen=True)
class _SessionOutputPaths:
    md_path: Path
    jsonl_path: Path
    compactions_path: Path


@dataclass(frozen=True)
class _RecentOutputPaths:
    md_path: Path | None = None
    json_path: Path | None = None
    compactions_path: Path | None = None


@dataclass(frozen=True)
class _SessionWriteRequest:
    project_id: str
    session_id: str
    exported_title: str
    created_ms: int
    updated_ms: int
    messages: list[Message]
    paths: _SessionOutputPaths


@dataclass(frozen=True)
class _PreparedSession:
    session_ref: SessionRef
    exported: SessionExport
    safe_title: str
    paths: _SessionOutputPaths
    is_selected: bool
    should_write: bool


@dataclass(frozen=True)
class _PrepareSessionsRequest:
    project_id: str
    sessions: list[SessionRef]
    write_session_ids: set[str]
    recent_paths: _RecentOutputPaths


def _select_project_ids(
    source: StorageSource,
    context: SourceExportContext,
    project_ids: list[str],
) -> list[str]:
    if source.source_name != "opencode" or context.args.all or len(project_ids) <= 1:
        return project_ids
    return [
        max(
            project_ids,
            key=lambda project_id: _latest_session_sort_key(
                source,
                context.storage,
                project_id,
                context.root,
                debug=context.args.debug,
            ),
        ),
    ]


def _set_recent_existing_paths(
    context: SourceExportContext,
    paths: _SessionOutputPaths,
    recent_paths: _RecentOutputPaths,
) -> _RecentOutputPaths:
    next_recent_md = recent_paths.md_path
    next_recent_json = recent_paths.json_path
    next_recent_compactions = recent_paths.compactions_path
    if (
        context.output_md
        and not context.compactions_only
        and next_recent_md is None
        and paths.md_path.exists()
    ):
        next_recent_md = paths.md_path
    if next_recent_compactions is None and paths.compactions_path.exists():
        next_recent_compactions = paths.compactions_path
    if context.output_json and next_recent_json is None and paths.jsonl_path.exists():
        next_recent_json = paths.jsonl_path
    return _RecentOutputPaths(
        md_path=next_recent_md,
        json_path=next_recent_json,
        compactions_path=next_recent_compactions,
    )


def _should_write_outputs(
    context: SourceExportContext,
    exported_modified_timestamp: float,
    previous_timestamp: float,
    paths: _SessionOutputPaths,
) -> bool:
    missing_markdown = (
        context.output_md
        and not context.compactions_only
        and not paths.md_path.exists()
    )
    missing_jsonl = context.output_json and not paths.jsonl_path.exists()
    missing_compactions = not paths.compactions_path.exists()
    return (
        context.args.force_refresh
        or exported_modified_timestamp > previous_timestamp
        or missing_markdown
        or missing_jsonl
        or missing_compactions
    )


def _unlink_previous_outputs(
    context: SourceExportContext,
    paths: _SessionOutputPaths,
) -> None:
    if context.output_md:
        paths.md_path.unlink(missing_ok=True)
    if context.output_json:
        paths.jsonl_path.unlink(missing_ok=True)
    paths.compactions_path.unlink(missing_ok=True)


def _write_session_outputs(
    context: SourceExportContext,
    request: _SessionWriteRequest,
    written_outputs: list[Path],
) -> tuple[Path | None, Path | None, Path | None, str | None]:
    recent_md: Path | None = None
    recent_json: Path | None = None
    recent_compactions: Path | None = None
    recent_session_id: str | None = None
    session_header = SessionHeader(
        title=request.exported_title,
        sid=request.session_id,
        created_ms=request.created_ms,
        updated_ms=request.updated_ms,
    )

    if context.output_md and not context.compactions_only:
        append_markdown_with_tools(
            request.paths.md_path,
            session_header,
            [(message, message.md_tools) for message in request.messages],
        )
        written_outputs.append(request.paths.md_path)
        recent_md = request.paths.md_path
        recent_session_id = request.session_id

    compaction_blocks = _collect_compactions(request.messages)
    if append_compactions_markdown(
        request.paths.compactions_path,
        session_header,
        compaction_blocks,
    ):
        written_outputs.append(request.paths.compactions_path)
        recent_compactions = request.paths.compactions_path

    if context.output_json:
        append_jsonl(
            request.paths.jsonl_path,
            request.project_id,
            request.session_id,
            request.messages,
        )
        written_outputs.append(request.paths.jsonl_path)
        recent_json = request.paths.jsonl_path
        recent_session_id = request.session_id

    return recent_md, recent_json, recent_compactions, recent_session_id


def _paths_for_title(history_dir: Path, safe_title: str) -> _SessionOutputPaths:
    return _SessionOutputPaths(
        md_path=history_dir / f"{safe_title}.md",
        jsonl_path=history_dir / f"{safe_title}.jsonl",
        compactions_path=history_dir / f"{safe_title}-compactions.md",
    )


def _prepare_sessions(
    source: StorageSource,
    context: SourceExportContext,
    request: _PrepareSessionsRequest,
) -> tuple[list[_PreparedSession], _RecentOutputPaths]:
    prepared_sessions: list[_PreparedSession] = []
    next_recent_paths = request.recent_paths

    for session_ref in request.sessions:
        exported = source.export_session(
            context.storage,
            session_ref,
            want_tool_calls=context.output_json,
        )
        if exported is None:
            continue

        safe_title = _safe_export_title(source.source_name, exported.title)
        paths = _paths_for_title(context.history_dir, safe_title)
        next_recent_paths = _set_recent_existing_paths(
            context,
            paths,
            next_recent_paths,
        )
        previous_timestamp = get_export_state(
            context.index,
            request.project_id,
            session_ref.sid,
        )
        is_selected = session_ref.sid in request.write_session_ids
        prepared_sessions.append(
            _PreparedSession(
                session_ref=session_ref,
                exported=exported,
                safe_title=safe_title,
                paths=paths,
                is_selected=is_selected,
                should_write=is_selected
                and _should_write_outputs(
                    context,
                    exported.modified_timestamp,
                    previous_timestamp,
                    paths,
                ),
            ),
        )

    return prepared_sessions, next_recent_paths


def _group_prepared_opencode_sessions(
    prepared_sessions: list[_PreparedSession],
) -> tuple[
    list[_PreparedSession],
    dict[str, list[_PreparedSession]],
    dict[str, bool],
    dict[str, str],
]:
    sessions_by_id = {
        prepared.session_ref.sid: prepared for prepared in prepared_sessions
    }
    children_by_parent: dict[str, list[_PreparedSession]] = {}
    roots: list[_PreparedSession] = []
    out_of_scope_parents: dict[str, str] = {}
    subtree_has_selected: dict[str, bool] = {}
    subtree_sort_key: dict[str, float] = {}

    for prepared in prepared_sessions:
        parent_id = prepared.session_ref.parent_id
        if parent_id is not None and parent_id in sessions_by_id:
            children_by_parent.setdefault(parent_id, []).append(prepared)
        else:
            roots.append(prepared)
            if parent_id is not None:
                out_of_scope_parents[prepared.session_ref.sid] = parent_id

    def visit(prepared: _PreparedSession) -> tuple[bool, float]:
        children = children_by_parent.get(prepared.session_ref.sid, [])
        children.sort(key=lambda child: child.session_ref.sort_key, reverse=True)
        has_selected = prepared.is_selected
        max_sort_key = prepared.session_ref.sort_key
        for child in children:
            child_has_selected, child_sort_key = visit(child)
            has_selected = has_selected or child_has_selected
            max_sort_key = max(max_sort_key, child_sort_key)
        subtree_has_selected[prepared.session_ref.sid] = has_selected
        subtree_sort_key[prepared.session_ref.sid] = max_sort_key
        return has_selected, max_sort_key

    for root in roots:
        visit(root)

    roots.sort(
        key=lambda prepared: subtree_sort_key.get(prepared.session_ref.sid, 0.0),
        reverse=True,
    )
    return roots, children_by_parent, subtree_has_selected, out_of_scope_parents


def _render_prepared_session_statuses(
    source: StorageSource,
    prepared_sessions: list[_PreparedSession],
) -> list[str]:
    if source.source_name != "opencode":
        return [
            _session_progress_line(prepared, source.source_name)
            for prepared in prepared_sessions
            if prepared.is_selected
        ]

    (
        roots,
        children_by_parent,
        subtree_has_selected,
        out_of_scope_parents,
    ) = _group_prepared_opencode_sessions(prepared_sessions)
    lines: list[str] = []

    def append_lines(
        prepared: _PreparedSession,
        depth: int,
        *,
        ancestor_selected: bool = False,
    ) -> None:
        has_selected = subtree_has_selected.get(prepared.session_ref.sid, False)
        branch_selected = ancestor_selected or prepared.is_selected
        if not has_selected and not branch_selected:
            return
        lines.append(
            _session_progress_line(
                prepared,
                source.source_name,
                depth=depth,
            ),
        )
        for child in children_by_parent.get(prepared.session_ref.sid, []):
            append_lines(child, depth + 1, ancestor_selected=branch_selected)

    for root in roots:
        append_lines(root, 0)

    if out_of_scope_parents:
        project_counts: dict[str, int] = {}
        for parent_id in out_of_scope_parents.values():
            proj_name = source.get_session_project_name(parent_id) or "Unknown Project"
            project_counts[proj_name] = project_counts.get(proj_name, 0) + 1
        
        if project_counts:
            lines.append("")
            total_out_of_scope = len(out_of_scope_parents)
            summary_parts = [f"{name} ({count})" for name, count in sorted(project_counts.items())]
            summary_str = ", ".join(summary_parts)
            lines.append(_color_dim(f"ℹ️ {total_out_of_scope} sessions was started in different folders: {summary_str}"))

    return lines


def _export_project_sessions(
    source: StorageSource,
    context: SourceExportContext,
    *,
    project_id: str,
    written_outputs: list[Path],
    recent_paths: _RecentOutputPaths,
) -> tuple[str | None, _RecentOutputPaths, list[_PreparedSession]]:
    selected_sessions = source.resolve_sessions(
        context.storage,
        project_id,
        context.root,
        all_sessions=context.args.all,
        debug=context.args.debug,
    )
    sessions = source.resolve_sessions(
        context.storage,
        project_id,
        context.root,
        all_sessions=context.args.all or source.source_name == "opencode",
        debug=context.args.debug,
    )
    next_recent_session_id = selected_sessions[0].sid if selected_sessions else None
    prepared_sessions, next_recent_paths = _prepare_sessions(
        source,
        context,
        _PrepareSessionsRequest(
            project_id=project_id,
            sessions=sessions,
            write_session_ids={session.sid for session in selected_sessions},
            recent_paths=recent_paths,
        ),
    )

    for prepared in prepared_sessions:
        if not prepared.should_write:
            continue

        _unlink_previous_outputs(context, prepared.paths)
        recent_md, recent_json, recent_compactions, recent_session_id = (
            _write_session_outputs(
                context,
                _SessionWriteRequest(
                    project_id=project_id,
                    session_id=prepared.session_ref.sid,
                    exported_title=prepared.exported.title,
                    created_ms=prepared.exported.created_ms,
                    updated_ms=prepared.exported.updated_ms,
                    messages=prepared.exported.messages,
                    paths=prepared.paths,
                ),
                written_outputs,
            )
        )
        next_recent_paths = _RecentOutputPaths(
            md_path=recent_md or next_recent_paths.md_path,
            json_path=recent_json or next_recent_paths.json_path,
            compactions_path=recent_compactions or next_recent_paths.compactions_path,
        )
        if recent_session_id is not None:
            next_recent_session_id = recent_session_id

        update_export_state(
            context.index,
            project_id,
            prepared.session_ref.sid,
            prepared.exported.modified_timestamp,
        )

    return next_recent_session_id, next_recent_paths, prepared_sessions


def export_single_source(
    source: StorageSource,
    context: SourceExportContext,
) -> tuple[list[Path], str | None, Path | None, Path | None, Path | None]:
    """Export sessions for one source and return generated output paths."""
    written_outputs: list[Path] = []
    most_recent_session_id: str | None = None
    recent_paths = _RecentOutputPaths()
    prepared_sessions: list[_PreparedSession] = []

    project_ids = source.resolve_project_ids(context.storage, context.root)
    if not project_ids:
        if not context.args.quiet:
            eprint(f"⚠️ No {source.source_name} projects found for {context.root}")
        return written_outputs, None, None, None, None

    project_ids = _select_project_ids(source, context, project_ids)

    for project_id in project_ids:
        (
            project_recent_session_id,
            recent_paths,
            project_prepared_sessions,
        ) = _export_project_sessions(
            source,
            context,
            project_id=project_id,
            written_outputs=written_outputs,
            recent_paths=recent_paths,
        )
        prepared_sessions.extend(project_prepared_sessions)
        if project_recent_session_id is not None:
            most_recent_session_id = project_recent_session_id

    if not context.args.quiet and not context.args.output:
        for line in _render_prepared_session_statuses(source, prepared_sessions):
            eprint(line)

    return (
        written_outputs,
        most_recent_session_id,
        recent_paths.md_path,
        recent_paths.json_path,
        recent_paths.compactions_path,
    )
