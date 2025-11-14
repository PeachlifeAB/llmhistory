"""OpenCode storage source integration for llmhistory exports."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, override

from llmhistory.message_parse import parse_message_file
from llmhistory.models import Message, SessionExport, SessionRef
from llmhistory.parts import load_parts
from llmhistory.projects import resolve_project_ids as oc_resolve_project_ids
from llmhistory.session_resolve import (
    load_session_metadata,
    session_modified_timestamp,
    session_updated_timestamp_seconds,
    sort_message_files_by_created,
    sort_messages,
    stable_parent_id,
)
from llmhistory.session_resolve import (
    resolve_sessions as oc_resolve_sessions,
)
from llmhistory.sources.base import StorageSource
from llmhistory.storage_index import safe_json_dumps
from llmhistory.utils import (
    DEFAULT_OPENCODE_STORAGE,
    eprint,
    resolve_executable,
    run_checked_command,
)

_SESSION_LIST_LINE_RE = re.compile(r"^(ses_\S+)\s{2,}(.*?)\s{2,}.*$")
_SESSION_ROW_SQL = (
    "select title, time_created, time_updated from session where id='__SID__' limit 1"
)
_MESSAGE_ROWS_SQL = (
    "select id, time_created, data "
    "from message where session_id='__SID__' "
    "order by time_created, id"
)
_PART_ROWS_SQL = (
    "select message_id, data "
    "from part where session_id='__SID__' "
    "order by time_created, id"
)
_PROJECT_IDS_BY_WORKTREE_SQL = "select id from project where worktree='__WORKTREE__'"
_SESSIONS_BY_PROJECT_SQL = (
    "select id, parent_id, time_updated from session where project_id='__PID__' "
    "order by time_updated desc"
)


def _sql_with_session_id(sql: str, session_id: str) -> str:
    escaped_sid = session_id.replace("'", "''")
    return sql.replace("__SID__", escaped_sid)


def _sql_with_worktree(sql: str, worktree: str) -> str:
    return sql.replace("__WORKTREE__", worktree.replace("'", "''"))


def _sql_with_project_id(sql: str, project_id: str) -> str:
    return sql.replace("__PID__", project_id.replace("'", "''"))


class OpenCodeSource(StorageSource):
    """Storage source that exports sessions from OpenCode local storage."""

    def get_storage_path(self) -> Path:
        """Return the default OpenCode storage path."""
        return DEFAULT_OPENCODE_STORAGE

    def resolve_project_ids(self, storage: Path, root: Path) -> list[str]:
        """Resolve project IDs for a repository root, trying DB first."""
        db_ids = self._resolve_project_ids_from_db(root)
        if db_ids:
            return db_ids
        return oc_resolve_project_ids(storage, root)

    def _resolve_project_ids_from_db(self, root: Path) -> list[str]:
        """Query the OpenCode DB for project IDs matching the given root."""
        resolved_root = root.resolve()
        candidates: list[str] = []
        # Try exact match first, then parent/child matches
        for worktree_path in [resolved_root, *resolved_root.parents]:
            rows = self._db_query_rows(
                _sql_with_worktree(
                    _PROJECT_IDS_BY_WORKTREE_SQL,
                    str(worktree_path),
                )
            )
            ids = [str(row["id"]) for row in rows if "id" in row]
            if ids and worktree_path == resolved_root:
                return ids
            candidates.extend(ids)
            if worktree_path == resolved_root.anchor:
                break
        # Also check if root is a subdirectory of any project worktree
        if not candidates:
            all_projects = self._db_query_rows("select id, worktree from project")
            for proj in all_projects:
                pid = proj.get("id")
                wt = proj.get("worktree")
                if not isinstance(pid, str) or not isinstance(wt, str):
                    continue
                try:
                    resolved_wt = Path(wt).resolve()
                except OSError:
                    continue
                if resolved_root == resolved_wt or resolved_wt in resolved_root.parents:
                    candidates.append(pid)
        return candidates

    @override
    def resolve_sessions(
        self,
        storage: Path,
        project_id: str,
        root: Path,
        all_sessions: object,
        debug: object,
    ) -> list[SessionRef]:
        """Resolve candidate sessions, trying DB first then file storage."""
        db_sessions = self._resolve_sessions_from_db(
            storage, project_id, debug=bool(debug)
        )
        if db_sessions:
            if bool(all_sessions):
                return db_sessions
            roots = [s for s in db_sessions if s.parent_id is None]
            return roots[:1] if roots else db_sessions[:1]
        return oc_resolve_sessions(
            storage,
            project_id,
            root,
            export_all=bool(all_sessions),
            debug=bool(debug),
        )

    def _resolve_sessions_from_db(
        self,
        storage: Path,
        project_id: str,
        *,
        debug: bool,
    ) -> list[SessionRef]:
        """Query the OpenCode DB for sessions belonging to a project."""
        rows = self._db_query_rows(
            _sql_with_project_id(_SESSIONS_BY_PROJECT_SQL, project_id)
        )
        if not rows:
            return []

        session_refs: list[SessionRef] = []
        for row in rows:
            sid = row.get("id")
            if not isinstance(sid, str):
                continue
            updated_ms = int(row.get("time_updated") or 0)
            sort_key = updated_ms / 1000.0
            # session_file and message_dir may not exist in DB-only storage
            session_file = storage / "session" / project_id / f"{sid}.json"
            message_dir = storage / "message" / sid
            session_refs.append(
                SessionRef(
                    sid=sid,
                    session_file=session_file,
                    message_dir=message_dir,
                    sort_key=sort_key,
                    parent_id=stable_parent_id(row.get("parent_id")),
                )
            )

        session_refs.sort(key=lambda sr: sr.sort_key, reverse=True)
        if debug:
            eprint(f"[DEBUG] Found {len(session_refs)} total sessions")
        return session_refs

    def load_session_metadata(self, session_ref: SessionRef) -> tuple[str, int, int]:
        """Load title and timestamps for a session reference."""
        return load_session_metadata(session_ref.session_file, session_ref.sid)

    @override
    def export_session(
        self,
        storage: Path,
        session_ref: SessionRef,
        want_tool_calls: object,
    ) -> SessionExport | None:
        """Export a session from DB first, then fallback to storage files."""
        want_tool_calls_bool = bool(want_tool_calls)
        from_db = self._export_session_from_db(
            session_ref.sid,
            session_ref.session_file,
            want_tool_calls=want_tool_calls_bool,
        )
        if from_db is not None:
            return from_db
        return self._export_session_from_storage(
            storage,
            session_ref,
            want_tool_calls=want_tool_calls_bool,
        )

    def _find_db_path(self) -> Path | None:
        """Locate the OpenCode SQLite database file."""
        candidate = DEFAULT_OPENCODE_STORAGE.parent / "opencode.db"
        return candidate if candidate.exists() else None

    def _db_query_rows(self, sql: str) -> list[dict[str, Any]]:
        db_path = self._find_db_path()
        if db_path is not None:
            return self._sqlite_query_rows(db_path, sql)
        return self._cli_query_rows(sql)

    def _sqlite_query_rows(self, db_path: Path, sql: str) -> list[dict[str, Any]]:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sql)
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def _cli_query_rows(self, sql: str) -> list[dict[str, Any]]:
        try:
            result = run_checked_command(
                [resolve_executable("opencode"), "db", sql, "--format", "json"],
            )
        except (subprocess.SubprocessError, OSError):
            return []

        try:
            rows = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _title_from_session_list(self, session_id: str) -> str | None:
        try:
            result = run_checked_command(
                [resolve_executable("opencode"), "session", "list"],
            )
        except (subprocess.SubprocessError, OSError):
            return None

        for raw_line in result.stdout.splitlines():
            match = _SESSION_LIST_LINE_RE.match(raw_line.rstrip())
            if match is None:
                continue
            if match.group(1) != session_id:
                continue
            title = match.group(2).strip()
            return title or None
        return None

    @staticmethod
    def _parts_by_message_id(
        part_rows: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        parts_by_mid: dict[str, list[dict[str, Any]]] = {}
        for part_row in part_rows:
            message_id = part_row.get("message_id")
            part_data_text = part_row.get("data")
            if not isinstance(message_id, str) or not isinstance(part_data_text, str):
                continue
            try:
                part_data = json.loads(part_data_text)
            except json.JSONDecodeError:
                continue
            if isinstance(part_data, dict):
                parts_by_mid.setdefault(message_id, []).append(part_data)
        return parts_by_mid

    def _message_from_db_row(
        self,
        message_row: dict[str, Any],
        parts_by_mid: dict[str, list[dict[str, Any]]],
        *,
        want_tool_calls: bool,
    ) -> Message | None:
        mid = message_row.get("id")
        message_data_text = message_row.get("data")
        if not isinstance(mid, str) or not isinstance(message_data_text, str):
            return None

        try:
            message_data = json.loads(message_data_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(message_data, dict):
            return None

        role = message_data.get("role")
        if role not in ("user", "assistant"):
            return None

        created_ms_value = int(message_row.get("time_created") or 0)
        raw_time_data = message_data.get("time")
        if isinstance(raw_time_data, dict):
            created_ms_value = int(raw_time_data.get("created") or created_ms_value)

        provider_id, model_id = self._parse_provider_model(message_data)
        content, tool_calls, md_tools = self._parse_parts(
            parts_by_mid.get(mid, []),
            want_tool_calls=want_tool_calls,
        )
        return Message(
            mid=mid,
            role=str(role),
            created_ms=created_ms_value,
            parent_id=stable_parent_id(message_data.get("parentID")),
            agent=str(message_data.get("agent"))
            if message_data.get("agent") is not None
            else None,
            mode=str(message_data.get("mode"))
            if message_data.get("mode") is not None
            else None,
            summary=bool(message_data.get("summary")),
            content=content,
            tool_calls=tool_calls,
            provider_id=provider_id,
            model_id=model_id,
            md_tools=md_tools,
        )

    def _messages_from_db_rows(
        self,
        message_rows: list[dict[str, Any]],
        parts_by_mid: dict[str, list[dict[str, Any]]],
        *,
        want_tool_calls: bool,
    ) -> list[Message]:
        messages: list[Message] = []
        for message_row in message_rows:
            message = self._message_from_db_row(
                message_row,
                parts_by_mid,
                want_tool_calls=want_tool_calls,
            )
            if message is not None:
                messages.append(message)
        return messages

    def _export_session_from_db(
        self,
        session_id: str,
        session_file: Path,
        *,
        want_tool_calls: bool,
    ) -> SessionExport | None:
        session_rows = self._db_query_rows(
            _sql_with_session_id(_SESSION_ROW_SQL, session_id),
        )
        session_row = session_rows[0] if session_rows else {}

        message_rows = self._db_query_rows(
            _sql_with_session_id(_MESSAGE_ROWS_SQL, session_id),
        )
        if not message_rows:
            return None

        part_rows = self._db_query_rows(
            _sql_with_session_id(_PART_ROWS_SQL, session_id),
        )
        parts_by_mid = self._parts_by_message_id(part_rows)
        messages = self._messages_from_db_rows(
            message_rows,
            parts_by_mid,
            want_tool_calls=want_tool_calls,
        )

        if not messages:
            return None

        message_created_values = [
            message.created_ms for message in messages if message.created_ms > 0
        ]
        first_message_created = (
            min(message_created_values) if message_created_values else 0
        )
        last_message_created = (
            max(message_created_values) if message_created_values else 0
        )

        title = str(
            session_row.get("title")
            or self._title_from_session_list(session_id)
            or f"Session_{session_id}",
        )
        created_ms = int(session_row.get("time_created") or first_message_created)
        updated_ms = int(
            session_row.get("time_updated") or created_ms or last_message_created,
        )

        return SessionExport(
            title=title,
            created_ms=created_ms,
            updated_ms=updated_ms,
            modified_timestamp=session_modified_timestamp(session_file, updated_ms),
            messages=sort_messages(messages),
        )

    def _parse_provider_model(
        self,
        info: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        provider = info.get("providerID")
        model = info.get("modelID")
        model_ref = info.get("model")

        if isinstance(model_ref, dict):
            model_ref_dict = dict(model_ref)
            provider = provider or model_ref_dict.get("providerID")
            model = model or model_ref_dict.get("modelID")

        provider_id = str(provider) if provider is not None else None
        model_id = str(model) if model is not None else None
        return provider_id, model_id

    def _parse_parts(
        self,
        parts_raw: object,
        *,
        want_tool_calls: bool,
    ) -> tuple[str, list[dict[str, Any]], str]:
        if not isinstance(parts_raw, list):
            return "", [], ""

        text_chunks: list[str] = []
        md_tools_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for part in parts_raw:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type in ("text", "reasoning"):
                text = str(part.get("text") or "")
                if text:
                    text_chunks.append(text)
                continue
            if part_type != "tool":
                continue

            tool_name = part.get("tool")
            state_raw = part.get("state")
            state: dict[str, Any] = {}
            if isinstance(state_raw, dict):
                state = state_raw
            if want_tool_calls:
                tool_calls.append(
                    {
                        "tool": tool_name,
                        "status": state.get("status"),
                        "input": state.get("input"),
                        "output": state.get("output"),
                    },
                )

            md_tools_chunks.append("")
            md_tools_chunks.append(f"### 🔧 Tool: {tool_name}")
            md_tools_chunks.append("**Input:**")
            md_tools_chunks.append("```json")
            md_tools_chunks.append(safe_json_dumps(state.get("input")))
            md_tools_chunks.append("```")
            if "output" in state:
                md_tools_chunks.append("**Output:**")
                md_tools_chunks.append("```")
                md_tools_chunks.append(safe_json_dumps(state.get("output")))
                md_tools_chunks.append("```")

        content = "\n\n".join(text_chunks) + ("\n" if text_chunks else "")
        md_tools = "\n".join(md_tools_chunks) + ("\n" if md_tools_chunks else "")
        return content, tool_calls, md_tools

    def _export_session_from_storage(
        self,
        storage: Path,
        session_ref: SessionRef,
        *,
        want_tool_calls: bool,
    ) -> SessionExport | None:
        title, created_ms, updated_ms = load_session_metadata(
            session_ref.session_file,
            session_ref.sid,
        )

        messages: list[Message] = []
        for message_file in sort_message_files_by_created(session_ref.message_dir):
            parsed = parse_message_file(message_file)
            if not parsed:
                continue

            (
                mid,
                role,
                message_created_ms,
                parent_id,
                agent,
                mode,
                summary,
                provider_id,
                model_id,
            ) = parsed

            content, tool_calls, md_tools = load_parts(
                storage,
                mid,
                want_tool_calls=want_tool_calls,
                want_md_tools=True,
            )
            messages.append(
                Message(
                    mid=mid,
                    role=role,
                    created_ms=message_created_ms,
                    parent_id=parent_id,
                    agent=agent,
                    mode=mode,
                    summary=summary,
                    content=content,
                    tool_calls=tool_calls,
                    provider_id=provider_id,
                    model_id=model_id,
                    md_tools=md_tools,
                ),
            )

        if not messages:
            return None

        return SessionExport(
            title=title,
            created_ms=created_ms,
            updated_ms=updated_ms,
            modified_timestamp=session_modified_timestamp(
                session_ref.session_file,
                updated_ms,
                session_updated_timestamp_seconds(session_ref.message_dir),
            ),
            messages=sort_messages(messages),
        )

    def get_session_project_name(self, session_id: str) -> str | None:
        sql = _sql_with_session_id(
            "SELECT project.worktree FROM session JOIN project ON session.project_id = project.id WHERE session.id='__SID__'", 
            session_id
        )
        rows = self._db_query_rows(sql)
        if not rows:
            return None
        worktree = rows[0].get("worktree")
        if not worktree:
            return None
        return Path(worktree).name

    @property
    def source_name(self) -> str:
        """Return the source identifier used in output file naming."""
        return "opencode"
