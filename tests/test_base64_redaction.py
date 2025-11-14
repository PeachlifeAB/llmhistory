"""Tests for base64-like content redaction in text and tool payloads."""

from pathlib import Path

from llmhistory.parts import load_parts
from llmhistory.redaction import redact_base64_lines
from llmhistory.storage_index import safe_json_dumps
from tests.test_utils import write_json


def _mk_base64ish_line(n: int) -> str:
    # No whitespace; base64-ish charset; long single line.
    # Include a base64 punctuation char so we don't accidentally match long
    # alphanumeric ids/hashes.
    if n <= 1:
        return "/"
    return ("A" * (n - 1)) + "/"


def test_redact_base64_lines_redacts_single_long_base64ish_line() -> None:
    """Redact a single long base64-like line."""
    s = _mk_base64ish_line(300)
    out = redact_base64_lines(s)
    assert out == "[redacted base64-like line len=300]"


def test_redact_base64_lines_does_not_redact_long_line_with_spaces() -> None:
    """Keep long lines that contain spaces unchanged."""
    s = ("A" * 200) + " " + ("A" * 200)
    out = redact_base64_lines(s)
    assert out == s


def test_redact_base64_lines_redacts_wrapped_base64ish_block() -> None:
    """Redact wrapped base64-like blocks while preserving surrounding text."""
    # Simulate wrapped output like OpenCode renders with a leading box-drawing prefix.
    wrapped = "\n".join(
        [
            "      │ " + _mk_base64ish_line(300),
            "      │ " + _mk_base64ish_line(300),
            "      │ " + _mk_base64ish_line(300),
            "tail",
        ],
    )
    out = redact_base64_lines(wrapped)
    assert "[redacted base64-like block lines=3" in out
    assert _mk_base64ish_line(300) not in out
    assert out.endswith("\ntail")


def test_redact_base64_lines_does_not_redact_long_non_base64ish_text() -> None:
    """Keep long non-base64-like text unchanged."""
    s = ("x" * 260) + ("!" * 50)
    out = redact_base64_lines(s)
    assert out == s


def test_redact_base64_lines_redacts_long_hex_blob() -> None:
    """Redact long hex blobs treated as base64-like content."""
    s = "deadbeef" * 200  # 1600 chars
    out = redact_base64_lines(s)
    assert out == "[redacted base64-like line len=1600]"


def test_safe_json_dumps_redacts_string_base64ish_line() -> None:
    """Apply line redaction when dumping a string via safe_json_dumps."""
    s = _mk_base64ish_line(300)
    assert safe_json_dumps(s) == "[redacted base64-like line len=300]"


def test_load_parts_redacts_text_part_content(tmp_path: Path) -> None:
    """Redact base64-like lines in text parts returned by load_parts."""
    storage = tmp_path / "storage"
    mid = "msg_1"

    write_json(
        storage / "part" / mid / "prt_1.json",
        {"type": "text", "text": "hello\n" + _mk_base64ish_line(300) + "\nworld"},
    )

    content, tool_calls, md_tools = load_parts(
        storage,
        mid,
        want_tool_calls=True,
        want_md_tools=True,
    )

    assert "hello" in content
    assert "[redacted base64-like line len=300]" in content
    assert tool_calls == []
    assert md_tools == ""


def test_load_parts_redacts_tool_calls_jsonl_objects(tmp_path: Path) -> None:
    """Keep tool_calls payload structure while preserving original values."""
    storage = tmp_path / "storage"
    mid = "msg_1"

    write_json(
        storage / "part" / mid / "prt_1.json",
        {
            "type": "tool",
            "tool": "t",
            "state": {
                "status": "completed",
                "input": {"payload": _mk_base64ish_line(300)},
                "output": [{"out": _mk_base64ish_line(257)}],
            },
        },
    )

    content, tool_calls, md_tools = load_parts(
        storage,
        mid,
        want_tool_calls=True,
        want_md_tools=False,
    )

    assert content == ""
    assert md_tools == ""
    assert tool_calls == [
        {
            "tool": "t",
            "status": "completed",
            "input": {"payload": _mk_base64ish_line(300)},
            "output": [{"out": _mk_base64ish_line(257)}],
        },
    ]


def test_load_parts_redacts_md_tools_rendering(tmp_path: Path) -> None:
    """Redact base64-like values in markdown tool rendering output."""
    storage = tmp_path / "storage"
    mid = "msg_1"

    write_json(
        storage / "part" / mid / "prt_1.json",
        {
            "type": "tool",
            "tool": "t",
            "state": {
                "input": _mk_base64ish_line(300),
                "output": _mk_base64ish_line(300),
            },
        },
    )

    _, _, md_tools = load_parts(storage, mid, want_tool_calls=False, want_md_tools=True)

    assert "[redacted base64-like line len=300]" in md_tools
    assert _mk_base64ish_line(300) not in md_tools
