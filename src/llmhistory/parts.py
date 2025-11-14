"""Message-part loading and rendering helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from llmhistory.redaction import redact_base64_lines
from llmhistory.storage_index import read_json, safe_json_dumps

if TYPE_CHECKING:
    from pathlib import Path


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _join_chunks(chunks: list[str], separator: str) -> str:
    if not chunks:
        return ""
    return separator.join(chunks) + "\n"


def _ordered_part_files(part_dir: Path) -> list[Path]:
    ordered_parts: list[tuple[int, Path]] = []
    for part_file in part_dir.glob("prt_*.json"):
        data = read_json(part_file)
        if data is None:
            continue
        raw_time_data = data.get("time")
        time_data = raw_time_data if isinstance(raw_time_data, dict) else {}
        start = _safe_int(time_data.get("start"))
        ordered_parts.append((start, part_file))
    ordered_parts.sort(key=lambda pair: pair[0])
    return [part_file for _, part_file in ordered_parts]


def _append_tool_call(
    tool_calls: list[dict[str, Any]],
    tool_name: object,
    state: dict[str, Any],
) -> None:
    tool_calls.append(
        {
            "tool": tool_name,
            "status": state.get("status"),
            "input": state.get("input"),
            "output": state.get("output"),
        },
    )


def _append_tool_markdown(
    md_tools_chunks: list[str],
    tool_name: object,
    state: dict[str, Any],
) -> None:
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


def load_parts(
    storage: Path,
    mid: str,
    *,
    want_tool_calls: bool,
    want_md_tools: bool,
) -> tuple[str, list[dict[str, Any]], str]:
    """Load text and tool parts for a message ID from storage."""
    part_dir = storage / "part" / mid
    if not part_dir.is_dir():
        return "", [], ""

    content_chunks: list[str] = []
    md_tools_chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for part_file in _ordered_part_files(part_dir):
        data = read_json(part_file)
        if data is None:
            continue

        part_type = data.get("type")
        if part_type in ("text", "reasoning"):
            text = data.get("text") or ""
            if text:
                content_chunks.append(redact_base64_lines(str(text)))
            continue

        if part_type != "tool":
            continue

        tool_name = data.get("tool")
        raw_state = data.get("state")
        state = raw_state if isinstance(raw_state, dict) else {}

        if want_tool_calls:
            _append_tool_call(tool_calls, tool_name, state)
        if want_md_tools:
            _append_tool_markdown(md_tools_chunks, tool_name, state)

    content = _join_chunks(content_chunks, "\n\n")
    md_tools = _join_chunks(md_tools_chunks, "\n")
    return content, tool_calls, md_tools
