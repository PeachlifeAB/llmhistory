"""Codex CLI storage source integration for llmhistory exports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

from llmhistory.models import Message, SessionExport, SessionRef
from llmhistory.redaction import redact_base64_lines
from llmhistory.session_resolve import session_modified_timestamp, sort_messages
from llmhistory.sources.base import StorageSource

if TYPE_CHECKING:
    from collections.abc import Generator

DEFAULT_CODEX_STORAGE = Path.home() / ".codex" / "sessions"


def _parse_iso_ts(ts: str) -> int:
    """Parse an ISO 8601 timestamp string to milliseconds since epoch."""
    try:
        # Handle trailing Z as UTC
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def _iter_rollout_files(storage: Path) -> Generator[Path, None, None]:
    """Yield all rollout-*.jsonl files under storage/YYYY/MM/DD/ directories."""
    if not storage.is_dir():
        return
    for year_dir in sorted(storage.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue
                yield from sorted(day_dir.glob("rollout-*.jsonl"))


def _read_session_meta(rollout_file: Path) -> dict[str, Any] | None:
    """Read and return the session_meta payload from the first line of a rollout."""
    try:
        with rollout_file.open() as fh:
            first_line = fh.readline()
    except OSError:
        return None

    try:
        data = json.loads(first_line)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("type") != "session_meta":
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload


def _extract_text_from_content(content: list[dict[str, Any]]) -> str:
    """Extract and join text from input_text/output_text/text content blocks."""
    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in ("input_text", "output_text", "text"):
            text = str(block.get("text") or "")
            if text:
                chunks.append(redact_base64_lines(text))
    return "\n\n".join(chunks) + ("\n" if chunks else "")


def _extract_tool_calls_from_content(
    content: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract tool_call blocks as normalized {id, name, input} dicts."""
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_call":
            continue
        tool_calls.append(
            {
                "id": block.get("id"),
                "name": block.get("name"),
                "input": block.get("arguments"),
            }
        )
    return tool_calls


def _extract_md_tools_from_content(content: list[dict[str, Any]]) -> str:
    """Format tool_call blocks from a content list as a markdown string."""
    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_call":
            continue
        tool_name = block.get("name", "unknown")
        arguments = block.get("arguments")
        chunks.append("")
        chunks.append(f"### Tool: {tool_name}")
        chunks.append("**Input:**")
        chunks.append("```json")
        try:
            chunks.append(json.dumps(arguments, indent=2, ensure_ascii=False))
        except (TypeError, ValueError):
            chunks.append(str(arguments))
        chunks.append("```")
    return "\n".join(chunks) + ("\n" if chunks else "")


def _parse_rollout_messages(  # noqa: C901
    rollout_file: Path,
    *,
    want_tool_calls: bool,
) -> list[Message]:
    """Parse response_item entries from a rollout file into Message objects."""
    messages: list[Message] = []
    try:
        with rollout_file.open() as fh:
            lines = fh.readlines()
    except OSError:
        return messages

    # Skip first line (session_meta)
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "response_item":
            continue

        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        role = payload.get("role")
        if role == "developer":
            # Skip system prompts
            continue
        if role not in ("user", "assistant"):
            continue

        ts_str = str(entry.get("timestamp") or "")
        created_ms = _parse_iso_ts(ts_str) if ts_str else 0

        raw_content = payload.get("content")
        content_list: list[dict[str, Any]] = []
        if isinstance(raw_content, list):
            content_list = [c for c in raw_content if isinstance(c, dict)]

        text_content = _extract_text_from_content(content_list)
        tool_calls: list[dict[str, Any]] = []
        md_tools = ""
        if want_tool_calls:
            tool_calls = _extract_tool_calls_from_content(content_list)
            md_tools = _extract_md_tools_from_content(content_list)

        mid = f"{rollout_file.stem}_{len(messages)}"
        messages.append(
            Message(
                mid=mid,
                role=str(role),
                created_ms=created_ms,
                parent_id=None,
                agent=None,
                mode=None,
                summary=False,
                content=text_content,
                tool_calls=tool_calls,
                provider_id="openai",
                model_id=None,
                md_tools=md_tools,
            )
        )

    return messages


class CodexSource(StorageSource):
    """Storage source that exports sessions from Codex CLI local storage."""

    def get_storage_path(self) -> Path:
        """Return the default Codex sessions storage path."""
        return DEFAULT_CODEX_STORAGE

    @override
    def resolve_project_ids(self, storage: Path, root: Path) -> list[str]:
        """Return session UUIDs whose session_meta.cwd matches or is under root."""
        resolved_root = root.resolve()
        root_str = str(resolved_root).removeprefix("/private")
        matching: list[str] = []
        for rollout_file in _iter_rollout_files(storage):
            meta = _read_session_meta(rollout_file)
            if meta is None:
                continue
            session_id = meta.get("id")
            cwd = meta.get("cwd")
            if not isinstance(session_id, str) or not isinstance(cwd, str):
                continue
            try:
                resolved_cwd = Path(cwd).resolve()
            except OSError:
                continue
            # Normalize away macOS /private prefix before comparing
            cwd_str = str(resolved_cwd).removeprefix("/private")
            # Match if cwd is exactly root or cwd is a subdirectory of root
            matches_root = cwd_str == root_str or cwd_str.startswith(root_str + "/")
            if matches_root and session_id not in matching:
                matching.append(session_id)
        return matching

    @override
    def resolve_sessions(
        self,
        storage: Path,
        project_id: str,
        root: Path,
        all_sessions: object,
        debug: object,
    ) -> list[SessionRef]:
        """Return rollout files whose session UUID matches project_id."""
        matched: list[SessionRef] = []
        for rollout_file in _iter_rollout_files(storage):
            meta = _read_session_meta(rollout_file)
            if meta is None:
                continue
            session_id = meta.get("id")
            if session_id != project_id:
                continue
            ts_str = str(meta.get("timestamp") or "")
            sort_key = _parse_iso_ts(ts_str) / 1000.0 if ts_str else 0.0
            matched.append(
                SessionRef(
                    sid=project_id,
                    session_file=rollout_file,
                    message_dir=rollout_file.parent,
                    sort_key=sort_key,
                    parent_id=None,
                )
            )

        matched.sort(key=lambda sr: sr.sort_key, reverse=True)
        if not bool(all_sessions) and matched:
            return matched[:1]
        return matched

    @override
    def load_session_metadata(self, session_ref: SessionRef) -> tuple[str, int, int]:  # noqa: C901, PLR0912
        """Derive title and timestamps from the rollout file's session_meta."""
        rollout_file = session_ref.session_file
        meta = _read_session_meta(rollout_file)
        if meta is None:
            return f"Session_{session_ref.sid}", 0, 0

        ts_str = str(meta.get("timestamp") or "")
        created_ms = _parse_iso_ts(ts_str) if ts_str else 0

        # Look for the first user message text to use as title
        title: str | None = None
        try:
            with rollout_file.open() as fh:
                lines = fh.readlines()
        except OSError:
            lines = []

        for raw_line in lines[1:]:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") != "response_item":
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("role") != "user":
                continue
            raw_content = payload.get("content")
            if isinstance(raw_content, list):
                for block in raw_content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") in ("input_text", "text"):
                        text = str(block.get("text") or "").strip()
                        if text:
                            title = text[:80]
                            break
            if title is not None:
                break

        final_title = title or f"Session_{session_ref.sid}"
        # updated_ms: use file mtime or fall back to created
        try:
            updated_ms = int(rollout_file.stat().st_mtime * 1000)
        except OSError:
            updated_ms = created_ms

        return final_title, created_ms, updated_ms

    @override
    def export_session(
        self,
        storage: Path,
        session_ref: SessionRef,
        want_tool_calls: object,
    ) -> SessionExport | None:
        """Export a Codex rollout file into normalized Message objects."""
        rollout_file = session_ref.session_file
        meta = _read_session_meta(rollout_file)
        if meta is None:
            return None

        ts_str = str(meta.get("timestamp") or "")
        created_ms = _parse_iso_ts(ts_str) if ts_str else 0

        messages = _parse_rollout_messages(
            rollout_file, want_tool_calls=bool(want_tool_calls)
        )
        if not messages:
            return None

        message_created_values = [m.created_ms for m in messages if m.created_ms > 0]
        updated_ms: int
        try:
            updated_ms = int(rollout_file.stat().st_mtime * 1000)
        except OSError:
            updated_ms = (
                max(message_created_values) if message_created_values else created_ms
            )

        title_from_meta, _, _ = self.load_session_metadata(session_ref)

        return SessionExport(
            title=title_from_meta,
            created_ms=created_ms,
            updated_ms=updated_ms,
            modified_timestamp=session_modified_timestamp(rollout_file, updated_ms),
            messages=sort_messages(messages),
        )

    @property
    @override
    def source_name(self) -> str:
        """Return the source identifier used in output file naming."""
        return "codex"
