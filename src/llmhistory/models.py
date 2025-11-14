"""Core data models for messages and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class SessionRef:
    """Reference to a session with metadata."""

    sid: str
    session_file: Path
    message_dir: Path
    sort_key: float
    parent_id: str | None = None


@dataclass(frozen=True)
class MessageCandidate:
    """Candidate message file for export."""

    path: Path
    mid: str
    mtime: float


@dataclass(frozen=True)
class Message:
    """Parsed message with content and metadata."""

    mid: str
    role: str
    created_ms: int
    parent_id: str | None
    agent: str | None
    mode: str | None
    summary: bool
    content: str
    tool_calls: tuple[dict[str, Any], ...]
    provider_id: str | None = None
    model_id: str | None = None
    md_tools: str = ""

    def __post_init__(self) -> None:
        """Normalize tool call collections to an immutable tuple."""
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))


@dataclass(frozen=True)
class SessionExport:
    """Fully materialized session payload ready for output formatting."""

    title: str
    created_ms: int
    updated_ms: int
    modified_timestamp: float
    messages: tuple[Message, ...]

    def __post_init__(self) -> None:
        """Normalize message collections to an immutable tuple."""
        object.__setattr__(self, "messages", tuple(self.messages))
