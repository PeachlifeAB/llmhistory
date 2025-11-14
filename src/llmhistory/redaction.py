"""Redaction helpers for large base64-like and hex payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REDACT_BASE64_LINE_LEN = 256
REDACT_BASE64_WRAPPED_LINE_LEN = 128
REDACT_BASE64_WRAPPED_MIN_RUN = 3
REDACT_HEX_LINE_LEN = 512
BASE64_ALLOWED_CHAR_RATIO = 0.97


def _looks_like_base64_line(s: str, *, min_len: int) -> bool:
    if len(s) <= min_len:
        return False

    # Base64-ish blobs are typically a single long token.
    if any(ch.isspace() for ch in s):
        return False

    allowed = 0
    has_non_alnum = False
    for ch in s:
        if "A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9" or ch in "+/=_-":
            allowed += 1
            if not ch.isalnum():
                has_non_alnum = True

    # High ratio + at least one base64-ish punctuation to avoid false positives
    # (e.g. long ids/hashes that are purely [A-Za-z0-9]).
    return has_non_alnum and (allowed / len(s)) >= BASE64_ALLOWED_CHAR_RATIO


def _looks_like_hex_line(s: str, *, min_len: int) -> bool:
    if len(s) <= min_len:
        return False

    if any(ch.isspace() for ch in s):
        return False

    # Hex strings are a common way to embed binary-like payloads.
    # Keep this threshold higher than base64 to avoid false positives.
    if len(s) % 2 != 0:
        return False

    return all(ch in "0123456789abcdefABCDEF" for ch in s)


def _strip_wrapped_prefix(line: str) -> str:
    # OpenCode often wraps long lines with indentation + a box-drawing bar.
    s = line.lstrip()
    if s.startswith("│"):
        s = s[1:]
        s = s.removeprefix(" ")
    return s


def _wrapped_run_end(
    lines: list[str],
    start: int,
    is_wrapped: Callable[[str], bool],
) -> int:
    end = start
    while end < len(lines) and is_wrapped(lines[end]):
        end += 1
    return end


def _append_wrapped_redaction(
    out_lines: list[str],
    lines: list[str],
    start: int,
    end: int,
) -> None:
    run_len = end - start
    total_payload_len = sum(
        len(_strip_wrapped_prefix(line)) for line in lines[start:end]
    )
    if run_len >= REDACT_BASE64_WRAPPED_MIN_RUN:
        out_lines.append(
            "[redacted base64-like block "
            f"lines={run_len} total_len={total_payload_len}]",
        )
        return
    for line in lines[start:end]:
        payload = _strip_wrapped_prefix(line)
        out_lines.append(f"[redacted base64-like line len={len(payload)}]")


def redact_base64_lines(text: str) -> str:
    """Redact lines and wrapped blocks that look like encoded binary payloads."""
    if not text:
        return text

    lines = text.splitlines(keepends=False)

    def is_raw(line: str) -> bool:
        return _looks_like_base64_line(
            line,
            min_len=REDACT_BASE64_LINE_LEN,
        ) or _looks_like_hex_line(line, min_len=REDACT_HEX_LINE_LEN)

    def is_wrapped(line: str) -> bool:
        payload = _strip_wrapped_prefix(line)
        if payload == line:
            return False
        return _looks_like_base64_line(payload, min_len=REDACT_BASE64_WRAPPED_LINE_LEN)

    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        if is_raw(lines[i]):
            out_lines.append(f"[redacted base64-like line len={len(lines[i])}]")
            i += 1
            continue

        if not is_wrapped(lines[i]):
            out_lines.append(lines[i])
            i += 1
            continue

        end = _wrapped_run_end(lines, i, is_wrapped)
        _append_wrapped_redaction(out_lines, lines, i, end)
        i = end

    return "\n".join(out_lines)
