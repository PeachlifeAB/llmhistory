"""Pi coding agent storage source integration for llmhistory exports."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, override

from llmhistory.models import Message, SessionExport, SessionRef
from llmhistory.redaction import redact_base64_lines
from llmhistory.session_resolve import session_modified_timestamp, sort_messages
from llmhistory.sources.base import StorageSource

_PI_ENV_AGENT_DIR = "PI_CODING_AGENT_DIR"
_PI_ENV_SESSION_DIR = "PI_CODING_AGENT_SESSION_DIR"


_DEFAULT_PI_AGENT_DIR = Path.home() / ".pi" / "agent"


def _get_default_agent_dir() -> Path:
    """Return the Pi agent directory, reading from env if set."""
    env_val = os.environ.get(_PI_ENV_AGENT_DIR, "").strip()
    if env_val:
        p = Path(env_val).expanduser()
        if p.name != "agent":
            p = p / "agent"
        return p
    return _DEFAULT_PI_AGENT_DIR


def _get_default_sessions_dir(agent_dir: Path | None = None) -> Path:
    """Return Pi sessions directory, reading PI_CODING_AGENT_SESSION_DIR env first."""
    env_val = os.environ.get(_PI_ENV_SESSION_DIR, "").strip()
    if env_val:
        return Path(env_val).expanduser()
    base = agent_dir if agent_dir is not None else _get_default_agent_dir()
    return base / "sessions"


def _all_sessions_dirs(storage: Path) -> list[Path]:
    """Return all Pi sessions directories to scan (deduped).

    Always includes ~/.pi/agent/sessions/ so sessions written before any
    PI_CODING_AGENT_DIR override are not missed.  When the env var points
    somewhere different, that location is appended.
    """
    env_sessions = os.environ.get(_PI_ENV_SESSION_DIR, "").strip()
    if env_sessions:
        # Explicit override: use only that dir
        return [Path(env_sessions).expanduser()]

    dirs: list[Path] = []
    default = _DEFAULT_PI_AGENT_DIR / "sessions"
    dirs.append(default)

    configured = storage / "sessions"
    if configured.resolve() != default.resolve():
        dirs.append(configured)

    return dirs


def _encode_path(cwd: str) -> str:
    """Encode an absolute path to Pi's session directory name format.

    Example: /Users/x/project -> --Users-x-project--
    """
    stripped = cwd.lstrip("/")
    encoded = stripped.replace("/", "-")
    return f"--{encoded}--"


def _is_pi_session_file(path: Path) -> bool:
    """Return True if the file's first parseable JSON line has type == 'session'."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    return data.get("type") == "session"
                return False
    except OSError:
        pass
    return False


def _read_pi_session_cwd(session_file: Path) -> str | None:
    """Read cwd from the first type=='session' line of a Pi session JSONL."""
    try:
        with session_file.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "session":
                    cwd = data.get("cwd")
                    return str(cwd) if isinstance(cwd, str) else None
    except OSError:
        pass
    return None


def _read_pi_session_id(session_file: Path) -> str | None:
    """Read id from the first type=='session' line of a Pi session JSONL."""
    try:
        with session_file.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "session":
                    sid = data.get("id")
                    return str(sid) if isinstance(sid, str) else None
    except OSError:
        pass
    return None


def _parse_pi_ts(ts: str) -> int:
    """Parse an ISO timestamp string to milliseconds since epoch."""
    if not ts:
        return 0
    try:
        # Normalize trailing Z
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        pass
    return 0


def _extract_pi_text(content: list[Any]) -> str:
    """Extract text content from Pi message content blocks (skip thinking blocks)."""
    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = str(block.get("text") or "")
            if text:
                chunks.append(redact_base64_lines(text))
    return "\n\n".join(chunks) + ("\n" if chunks else "")


def _extract_pi_tool_calls(content: list[Any]) -> list[dict[str, Any]]:
    """Extract toolCall blocks as normalized {id, name, input} dicts."""
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "toolCall":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "name": block.get("name", "unknown"),
                    "input": block.get("arguments", {}),
                }
            )
    return tool_calls


def _extract_pi_md_tools(content: list[Any]) -> str:
    """Format toolCall content blocks as a markdown string."""
    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "toolCall":
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


_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "__pycache__", ".tox", "dist", "build",
})


def _find_pi_sessions_in_dir(  # noqa: C901
    root: Path,
    max_depth: int = 4,
    skip_dirs: frozenset[Path] = frozenset(),
) -> list[Path]:
    """Walk root up to max_depth for .jsonl files that are Pi session files.

    Hidden dirs at depth 0 are skipped EXCEPT .pi and .llm.
    Large/irrelevant directories (node_modules, .git, etc.) are skipped at all depths.
    Directories in skip_dirs (resolved) are never descended into.
    """
    results: list[Path] = []
    resolved_skip = frozenset(p.resolve() for p in skip_dirs)

    def _walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_file() and entry.suffix == ".jsonl":
                if _is_pi_session_file(entry):
                    results.append(entry)
            elif entry.is_dir():
                if entry.resolve() in resolved_skip:
                    continue
                if entry.name in _SKIP_DIRS:
                    continue
                # At depth 0, skip hidden dirs except .pi and .llm
                hidden = entry.name.startswith(".")
                allowed_hidden = entry.name in (".pi", ".llm")
                if depth == 0 and hidden and not allowed_hidden:
                    continue
                _walk(entry, depth + 1)

    _walk(root, 0)
    return results


def _normalize_cwd(cwd: str) -> str:
    """Normalize cwd by stripping macOS /private prefix."""
    return cwd.removeprefix("/private")


def _cwds_match(cwd_a: str, cwd_b: str) -> bool:
    """Compare two cwd strings, normalizing /private prefix on both."""
    return _normalize_cwd(cwd_a) == _normalize_cwd(cwd_b)


def _parse_pi_session_messages(  # noqa: C901
    session_file: Path,
    *,
    want_tool_calls: bool,
) -> list[Message]:
    """Parse all type=='message' entries from a Pi session JSONL."""
    messages: list[Message] = []
    try:
        with session_file.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return messages

    # Skip the first line (session header)
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
        if entry.get("type") != "message":
            continue
        # Skip compaction entries
        if entry.get("agent") == "compaction":
            continue

        msg_payload = entry.get("message")
        if not isinstance(msg_payload, dict):
            continue

        role = msg_payload.get("role")
        # Skip toolResult role (tool outputs)
        if role == "toolResult":
            continue
        if role not in ("user", "assistant"):
            continue

        raw_content = msg_payload.get("content", [])
        content_list: list[Any] = raw_content if isinstance(raw_content, list) else []

        text_content = _extract_pi_text(content_list)
        tool_calls: list[dict[str, Any]] = []
        md_tools = ""
        if want_tool_calls:
            tool_calls = _extract_pi_tool_calls(content_list)
            md_tools = _extract_pi_md_tools(content_list)

        mid = str(entry.get("id") or f"{session_file.stem}_{len(messages)}")
        ts_str = str(entry.get("timestamp") or "")
        created_ms = _parse_pi_ts(ts_str)
        parent_id = entry.get("parentId")

        messages.append(
            Message(
                mid=mid,
                role=str(role),
                created_ms=created_ms,
                parent_id=str(parent_id) if parent_id is not None else None,
                agent=None,
                mode=None,
                summary=False,
                content=text_content,
                tool_calls=tool_calls,
                provider_id=str(msg_payload.get("provider") or "pi") or "pi",
                model_id=msg_payload.get("model"),
                md_tools=md_tools,
            )
        )

    return messages


class PiSource(StorageSource):
    """Storage source that exports sessions from Pi coding agent local storage."""

    @override
    def get_storage_path(self) -> Path:
        """Return the default Pi agent directory."""
        return _get_default_agent_dir()

    def _sessions_dir(self, storage: Path) -> Path:
        """Return the sessions directory, respecting env var overrides."""
        return _get_default_sessions_dir(storage)

    @override
    def resolve_project_ids(  # noqa: C901, PLR0912
        self,
        storage: Path,
        root: Path,
        *,
        sessions_dir: Path | None = None,
    ) -> list[str]:
        """Return project IDs (encoded CWD dir names) matching the active repo root.

        Checks both the global sessions directory and project-scoped .jsonl files.
        """
        resolved_root = root.resolve()
        root_str = _normalize_cwd(str(resolved_root))

        sessions_dirs = (
            [sessions_dir] if sessions_dir is not None else _all_sessions_dirs(storage)
        )

        matched_ids: list[str] = []
        seen_project_paths: set[Path] = set()

        # --- Global sessions dir scan (all candidate dirs) ---
        for effective_sessions_dir in sessions_dirs:
            if not effective_sessions_dir.is_dir():
                continue
            try:
                subdirs = [d for d in effective_sessions_dir.iterdir() if d.is_dir()]
            except OSError:
                continue

            for subdir in subdirs:
                subdir_resolved = subdir.resolve()
                if subdir_resolved in seen_project_paths:
                    continue
                # Find first .jsonl in this subdir to read cwd
                try:
                    jsonl_files = sorted(subdir.glob("*.jsonl"))
                except OSError:
                    continue
                for jsonl_file in jsonl_files:
                    cwd = _read_pi_session_cwd(jsonl_file)
                    if cwd is None:
                        continue
                    cwd_normalized = _normalize_cwd(cwd)
                    cwd_matches = (
                        cwd_normalized == root_str
                        or cwd_normalized.startswith(root_str + "/")
                    )
                    if cwd_matches:
                        seen_project_paths.add(subdir_resolved)
                        project_id = str(subdir)
                        if project_id not in matched_ids:
                            matched_ids.append(project_id)
                    break  # Only check first valid file per subdir

        # --- Project-scoped scan (sessions stored inside repo) ---
        # Skip the global sessions dirs so we don't double-count sessions
        # that live inside the project tree (e.g. ~/Developer/pi/agent/sessions/)
        project_scoped = _find_pi_sessions_in_dir(
            resolved_root,
            skip_dirs=frozenset(sessions_dirs),
        )
        for session_file in project_scoped:
            cwd = _read_pi_session_cwd(session_file)
            if cwd is None:
                continue
            cwd_normalized = _normalize_cwd(cwd)
            if cwd_normalized == root_str or cwd_normalized.startswith(root_str + "/"):
                project_id = str(session_file.parent)
                if project_id not in matched_ids:
                    matched_ids.append(project_id)

        return matched_ids

    @override
    def resolve_sessions(  # noqa: C901
        self,
        storage: Path,
        project_id: str,
        root: Path,
        all_sessions: object,
        debug: object,
    ) -> list[SessionRef]:
        """Return SessionRef objects for a Pi project ID.

        If project_id starts with '/', treat as absolute path (project-scoped).
        Otherwise use {sessions_dir}/{project_id}/.
        """
        if project_id.startswith("/"):
            # Project-scoped: project_id is an absolute directory path
            project_dir = Path(project_id)
        else:
            sessions_dir = self._sessions_dir(storage)
            project_dir = sessions_dir / project_id

        if not project_dir.is_dir():
            return []

        matched: list[SessionRef] = []
        try:
            jsonl_files = sorted(project_dir.glob("*.jsonl"))
        except OSError:
            return []

        for jsonl_file in jsonl_files:
            if not _is_pi_session_file(jsonl_file):
                continue
            sid = _read_pi_session_id(jsonl_file)
            if not sid:
                # Fall back to filename stem
                sid = jsonl_file.stem
            cwd = _read_pi_session_cwd(jsonl_file)
            if cwd is None:
                continue

            # Verify cwd matches root
            resolved_root = root.resolve()
            root_str = _normalize_cwd(str(resolved_root))
            cwd_normalized = _normalize_cwd(cwd)
            cwd_matches = cwd_normalized == root_str or cwd_normalized.startswith(
                root_str + "/"
            )
            if not cwd_matches:
                continue

            # Derive sort key from file mtime
            try:
                sort_key = jsonl_file.stat().st_mtime
            except OSError:
                sort_key = 0.0

            matched.append(
                SessionRef(
                    sid=sid,
                    session_file=jsonl_file,
                    message_dir=project_dir,
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
        """Derive title and timestamps from a Pi session JSONL file."""
        session_file = session_ref.session_file
        title: str | None = None
        created_ms: int = 0
        updated_ms: int = 0

        try:
            with session_file.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return f"Session_{session_ref.sid}", 0, 0

        # Check session header for timestamp
        for raw_line in lines[:1]:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("type") == "session":
                ts = str(data.get("timestamp") or "")
                if ts:
                    created_ms = _parse_pi_ts(ts)

        # Scan messages for title (first user text) and timestamps
        for raw_line in lines[1:]:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "message":
                continue
            if entry.get("agent") == "compaction":
                continue

            ts_str = str(entry.get("timestamp") or "")
            msg_ms = _parse_pi_ts(ts_str) if ts_str else 0
            if msg_ms:
                created_ms = msg_ms if not created_ms else min(created_ms, msg_ms)
                updated_ms = max(updated_ms, msg_ms)

            msg_payload = entry.get("message")
            if not isinstance(msg_payload, dict):
                continue
            role = msg_payload.get("role")
            if title is None and role == "user":
                raw_content = msg_payload.get("content", [])
                content_list: list[Any] = (
                    raw_content if isinstance(raw_content, list) else []
                )
                text = _extract_pi_text(content_list).strip()
                if text:
                    title = text[:80]

        final_title = title or f"Session_{session_ref.sid}"
        if not updated_ms:
            updated_ms = created_ms
        return final_title, created_ms, updated_ms

    @override
    def export_session(
        self,
        storage: Path,
        session_ref: SessionRef,
        want_tool_calls: object,
    ) -> SessionExport | None:
        """Export a Pi session JSONL into normalized Message objects."""
        session_file = session_ref.session_file

        # Read session header timestamp for created_ms
        created_ms: int = 0
        try:
            with session_file.open("r", encoding="utf-8", errors="replace") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        break
                    if isinstance(data, dict) and data.get("type") == "session":
                        ts = str(data.get("timestamp") or "")
                        if ts:
                            created_ms = _parse_pi_ts(ts)
                    break
        except OSError:
            return None

        messages = _parse_pi_session_messages(
            session_file,
            want_tool_calls=bool(want_tool_calls),
        )
        if not messages:
            return None

        message_created_values = [m.created_ms for m in messages if m.created_ms > 0]
        updated_ms: int
        try:
            updated_ms = int(session_file.stat().st_mtime * 1000)
        except OSError:
            updated_ms = (
                max(message_created_values) if message_created_values else created_ms
            )

        if not created_ms and message_created_values:
            created_ms = min(message_created_values)

        title, _, _ = self.load_session_metadata(session_ref)

        return SessionExport(
            title=title,
            created_ms=created_ms,
            updated_ms=updated_ms,
            modified_timestamp=session_modified_timestamp(session_file, updated_ms),
            messages=sort_messages(messages),
        )

    @property
    @override
    def source_name(self) -> str:
        """Return the source identifier used in output file naming."""
        return "pi"
