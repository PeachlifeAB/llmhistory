"""Claude Desktop source integration for llmhistory exports."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, cast, override

from llmhistory.models import Message, SessionExport, SessionRef
from llmhistory.redaction import redact_base64_lines
from llmhistory.session_resolve import sort_messages
from llmhistory.sources.base import StorageSource
from llmhistory.utils import resolve_executable, run_checked_command

DEFAULT_CLAUDE_STORAGE = Path.home() / ".claude" / "projects"
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _encode_path_to_dirname(path: str) -> str:
    return path.replace("/", "-").replace(".", "-")


def _parse_iso_timestamp(ts: str) -> int:
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def _safe_json_dumps(obj: object) -> str:
    try:
        raw = json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        raw = str(obj)
    return redact_base64_lines(raw)


def _extract_text_content(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return redact_base64_lines(content)

    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            block_type = block.get("type")
            if block_type == "text":
                chunks.append(str(block.get("text") or ""))
            elif block_type == "tool_result":
                result_content = block.get("content")
                if isinstance(result_content, str):
                    chunks.append(result_content)
        return redact_base64_lines("\n".join(chunks))

    return ""


def _extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content", [])
    if not isinstance(content, list):
        return []

    calls: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") != "tool_use":
            continue
        calls.append(
            {
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input": block.get("input", {}),
            },
        )
    return calls


def _extract_md_tools(message: dict[str, Any]) -> str:
    content = message.get("content", [])
    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for block in content:
        if block.get("type") != "tool_use":
            continue
        name = block.get("name", "unknown")
        input_dump = _safe_json_dumps(block.get("input", {}))
        chunks.append(f"### Tool: {name}\n**Input:**\n{input_dump}\n")
    return "\n".join(chunks)


class ClaudeSource(StorageSource):
    """Storage source for Claude Desktop/CLI session exports."""

    def get_storage_path(self) -> Path:
        """Return the default Claude projects storage path."""
        return DEFAULT_CLAUDE_STORAGE

    def _get_git_worktrees(self, root: Path) -> list[Path]:
        try:
            result = run_checked_command(
                [resolve_executable("git"), "worktree", "list", "--porcelain"],
                cwd=root,
            )
        except (subprocess.SubprocessError, OSError):
            return [root]

        worktrees = [
            Path(line.removeprefix("worktree ").strip())
            for line in result.stdout.splitlines()
            if line.startswith("worktree ")
        ]

        return worktrees or [root]

    def resolve_project_ids(self, storage: Path, root: Path) -> list[str]:
        """Resolve Claude project IDs that correspond to the repository worktree(s)."""
        if not storage.is_dir():
            return []

        prefixes = set()
        for worktree in self._get_git_worktrees(root):
            worktree_str = str(worktree)
            prefixes.add(_encode_path_to_dirname(worktree_str))
            if worktree_str.startswith("/private"):
                prefixes.add(
                    _encode_path_to_dirname(worktree_str.removeprefix("/private")),
                )

        matches: list[str] = []
        for entry in storage.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if name in prefixes:
                matches.append(name)
                continue
            for prefix in prefixes:
                if name.startswith(prefix + "-"):
                    matches.append(name)
                    break
        return matches

    @override
    def resolve_sessions(
        self,
        storage: Path,
        project_id: str,
        root: Path,
        all_sessions: object,
        debug: object,
    ) -> list[SessionRef]:
        """Load candidate Claude sessions for a project ID."""
        _ = root
        _ = debug
        project_dir = storage / project_id
        if not project_dir.is_dir():
            return []

        sessions: list[SessionRef] = []
        for session_file in project_dir.iterdir():
            if session_file.suffix != ".jsonl" or session_file.name.startswith(
                "agent-",
            ):
                continue
            sid = session_file.stem
            if not UUID_PATTERN.match(sid):
                continue
            try:
                stat = session_file.stat()
            except OSError:
                continue
            if stat.st_size == 0:
                continue

            sessions.append(
                SessionRef(
                    sid=sid,
                    session_file=session_file,
                    message_dir=session_file.parent,
                    sort_key=stat.st_mtime,
                    parent_id=None,
                ),
            )

        sessions.sort(key=lambda session_ref: session_ref.sort_key, reverse=True)
        if not bool(all_sessions) and sessions:
            return [sessions[0]]
        return sessions

    def load_session_metadata(self, session_ref: SessionRef) -> tuple[str, int, int]:
        """Extract title plus first/last message timestamps from a Claude session."""
        title: str | None = None
        first_ts: int | None = None
        last_ts: int | None = None

        try:
            with session_ref.session_file.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as file_handle:
                for line in file_handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if event_type == "summary":
                        summary = event.get("summary")
                        if summary:
                            title = str(summary)
                    if event_type in ("user", "assistant"):
                        ts = _parse_iso_timestamp(str(event.get("timestamp") or ""))
                        if ts:
                            first_ts = ts if first_ts is None else min(first_ts, ts)
                            last_ts = ts if last_ts is None else max(last_ts, ts)
        except OSError:
            pass

        if not title:
            title = self._title_from_first_user(session_ref.session_file)

        return title, first_ts or 0, last_ts or 0

    @override
    def export_session(
        self,
        storage: Path,
        session_ref: SessionRef,
        want_tool_calls: object,
    ) -> SessionExport | None:
        """Export a Claude session to normalized message objects."""
        _ = storage
        want_tool_calls_bool = bool(want_tool_calls)
        title, created_ms, updated_ms = self.load_session_metadata(session_ref)

        messages: list[Message] = []
        try:
            with session_ref.session_file.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as file_handle:
                for line in file_handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") not in ("user", "assistant") or event.get(
                        "isMeta",
                    ):
                        continue
                    mid = str(event.get("uuid") or "")
                    if not mid:
                        continue
                    message = self._event_to_message(
                        event,
                        mid,
                        want_tool_calls=want_tool_calls_bool,
                    )
                    if message is not None:
                        messages.append(message)
        except OSError:
            return None

        if not messages:
            return None

        modified_timestamp = max(session_ref.sort_key, updated_ms / 1000.0)
        return SessionExport(
            title=title,
            created_ms=created_ms,
            updated_ms=updated_ms,
            modified_timestamp=modified_timestamp,
            messages=sort_messages(messages),
        )

    def _event_to_message(
        self,
        event: dict[str, Any],
        mid: str,
        *,
        want_tool_calls: bool,
    ) -> Message | None:
        role = event.get("type")
        if role not in ("user", "assistant"):
            return None

        payload_raw = event.get("message")
        payload = (
            cast("dict[str, Any]", payload_raw) if isinstance(payload_raw, dict) else {}
        )
        tool_calls: list[dict[str, Any]] = []
        md_tools = ""
        if role == "assistant":
            if want_tool_calls:
                tool_calls = _extract_tool_calls(payload)
            md_tools = _extract_md_tools(payload)

        return Message(
            mid=mid,
            role=str(role),
            created_ms=_parse_iso_timestamp(str(event.get("timestamp") or "")),
            parent_id=event.get("parentUuid"),
            agent=None,
            mode=None,
            summary=False,
            content=_extract_text_content(payload),
            tool_calls=tool_calls,
            provider_id="claude",
            model_id=payload.get("model"),
            md_tools=md_tools,
        )

    @staticmethod
    def _title_from_first_user(path: Path) -> str:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as file_handle:
                for line in file_handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "user":
                        continue
                    message = (
                        event.get("message")
                        if isinstance(event.get("message"), dict)
                        else {}
                    )
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()[:80].replace("\n", " ")
        except OSError:
            pass
        return f"Claude_session_{path.stem[:12]}"

    @property
    def source_name(self) -> str:
        """Return the source identifier used in output file naming."""
        return "claude"
