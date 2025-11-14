"""Abstract source contract for export backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from llmhistory.models import SessionExport, SessionRef


class StorageSource(ABC):
    """Common interface implemented by each storage backend."""

    @abstractmethod
    def get_storage_path(self) -> Path:
        """Return the default storage root for this source."""

    @abstractmethod
    def resolve_project_ids(self, storage: Path, root: Path) -> list[str]:
        """Return project identifiers matching the active repository root."""

    @abstractmethod
    def resolve_sessions(
        self,
        storage: Path,
        project_id: str,
        root: Path,
        all_sessions: object,
        debug: object,
    ) -> list[SessionRef]:
        """Return candidate sessions for a project."""

    @abstractmethod
    def load_session_metadata(self, session_ref: SessionRef) -> tuple[str, int, int]:
        """Read title and time metadata for a session reference."""

    @abstractmethod
    def export_session(
        self,
        storage: Path,
        session_ref: SessionRef,
        want_tool_calls: object,
    ) -> SessionExport | None:
        """Export a session into normalized message objects."""

    def get_session_project_name(self, session_id: str) -> str | None:
        """Return the project name for a session, if available."""
        return None

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return a stable short identifier for the source."""
