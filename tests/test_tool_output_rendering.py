"""Tests for markdown rendering of tool outputs."""

from pathlib import Path

from llmhistory.parts import load_parts
from tests.test_utils import write_json


def test_load_parts_renders_tool_output_null(tmp_path: Path) -> None:
    """Render null tool output as literal JSON null in markdown."""
    storage = tmp_path / "storage"

    mid = "msg_1"
    write_json(
        storage / "part" / mid / "prt_1.json",
        {"type": "tool", "tool": "t", "state": {"input": None, "output": None}},
    )

    _, _, md_tools = load_parts(storage, mid, want_tool_calls=False, want_md_tools=True)

    assert "**Output:**" in md_tools
    assert "null" in md_tools
