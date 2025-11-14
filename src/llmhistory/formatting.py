"""Output formatters for markdown and JSONL exports."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from llmhistory.message_parse import _format_model_ref
from llmhistory.models import Message
from llmhistory.redaction import redact_base64_lines
from llmhistory.utils import format_date_ms


@dataclass(frozen=True)
class SessionHeader:
    """Session metadata written in markdown headers."""

    title: str
    sid: str
    created_ms: int
    updated_ms: int


def _write_message_to_md(file_handle: TextIO, message: Message, md_tools: str) -> None:
    file_handle.write(f"## {message.role.upper()}\n")
    file_handle.write(f"**Message ID:** `{message.mid}`\n")
    file_handle.write(f"**Date:** {format_date_ms(message.created_ms)}\n")
    parent = "null" if message.parent_id is None else f"`{message.parent_id}`"
    file_handle.write(f"**Parent ID:** {parent}\n")

    model_ref = _format_model_ref(message.provider_id, message.model_id)
    if model_ref:
        file_handle.write(f"**Model:** `{model_ref}`\n")
    if message.agent:
        file_handle.write(f"**Agent:** `{message.agent}`\n")

    file_handle.write("\n")
    if message.content:
        file_handle.write(message.content)
        if not message.content.endswith("\n"):
            file_handle.write("\n")
        file_handle.write("\n")

    if md_tools:
        file_handle.write(md_tools)
        if not md_tools.endswith("\n"):
            file_handle.write("\n")
        file_handle.write("\n")

    file_handle.write("\n")


def append_markdown_with_tools(
    md_path: Path,
    header: SessionHeader,
    message_blocks: Sequence[tuple[Message, str]],
) -> None:
    """Append a full session block, including markdown-rendered tool calls."""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    exists = md_path.exists()

    with md_path.open("a", encoding="utf-8") as file_handle:
        if not exists:
            file_handle.write(f"# Session: {header.title}\n")
            file_handle.write(f"**ID:** `{header.sid}`\n")
            file_handle.write(f"**Created:** {format_date_ms(header.created_ms)}\n")
            file_handle.write(f"**Updated:** {format_date_ms(header.updated_ms)}\n")
            file_handle.write("\n")
        else:
            file_handle.write(
                f"\n---\n**Updated:** {format_date_ms(header.updated_ms)}\n\n",
            )

        for message, md_tools in message_blocks:
            _write_message_to_md(file_handle, message, md_tools)


def append_compactions_markdown(
    md_path: Path,
    header: SessionHeader,
    message_blocks: Sequence[tuple[Message, str]],
) -> bool:
    """Append compaction-only messages for a session."""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    exists = md_path.exists()

    with md_path.open("a", encoding="utf-8") as file_handle:
        if not exists:
            file_handle.write(f"# Session: {header.title} (compactions)\n")
            file_handle.write(f"**ID:** `{header.sid}`\n")
            file_handle.write(f"**Created:** {format_date_ms(header.created_ms)}\n")
            file_handle.write(f"**Updated:** {format_date_ms(header.updated_ms)}\n")
            file_handle.write("\n")
        else:
            file_handle.write(
                f"\n---\n**Updated:** {format_date_ms(header.updated_ms)}\n\n",
            )

        for message, md_tools in message_blocks:
            _write_message_to_md(file_handle, message, md_tools)

    return True


def append_jsonl(
    jsonl_path: Path,
    project_id: str,
    session_id: str,
    messages: Sequence[Message],
) -> None:
    """Append exported messages to a JSONL file."""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as file_handle:
        for message in messages:
            payload = {
                "project_id": project_id,
                "session_id": session_id,
                "id": message.mid,
                "role": message.role,
                "timestamp": format_date_ms(message.created_ms),
                "parentID": message.parent_id,
                "content": message.content.rstrip("\n"),
                "tool_calls": message.tool_calls,
                "agent": message.agent,
                "provider_id": message.provider_id,
                "model_id": message.model_id,
            }
            serialized = json.dumps(payload, ensure_ascii=False)
            file_handle.write(redact_base64_lines(serialized))
            file_handle.write("\n")
