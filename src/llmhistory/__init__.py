"""llmhistory - Export LLM conversation history (OpenCode, Claude) to Markdown/JSONL."""

from __future__ import annotations

# Re-export main entry point
from llmhistory.cli import main

# Re-export version helper
from llmhistory.utils import get_version

__all__ = ["get_version", "main"]
