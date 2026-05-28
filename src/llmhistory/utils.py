"""Shared constants and utility helpers for llmhistory."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from asyncio import subprocess as aio_subprocess
from datetime import UTC, datetime
from pathlib import Path

INDEX_VERSION = 1
DEFAULT_OPENCODE_STORAGE = Path.home() / ".local/share/opencode/storage"
HISTORY_DIR_NAME = ".llm"
_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version

    def _get_version() -> str:
        try:
            return pkg_version("llmhistory")
        except PackageNotFoundError:
            return "0.0.0+local"

except ImportError:

    def _get_version() -> str:
        return "0.0.0+local"


def get_version() -> str:
    """Return the installed llmhistory version string."""
    return _get_version()


def eprint(msg: str) -> None:
    """Write a diagnostic message to stderr."""
    sys.stderr.write(f"{msg}\n")


def die(msg: str) -> None:
    """Exit the process with an error message."""
    eprint(f"❌ {msg}")
    raise SystemExit(1)


def sanitize(name: str) -> str:
    """Convert arbitrary names into a filesystem-safe stem."""
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    return sanitized[:200]


def format_date_ms(ms: int | None) -> str:
    """Format epoch milliseconds as an ISO-8601 timestamp."""
    if ms is None:
        return "(unknown)"
    dt = datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    iso = dt.isoformat(timespec="milliseconds")
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    return iso


def _format_relative_age_ms(ms: int | None, *, now_ms: int | None = None) -> str:
    if ms is None or ms <= 0:
        return "?m"

    reference_ms = (
        int(datetime.now(UTC).timestamp() * 1000) if now_ms is None else now_ms
    )
    delta_ms = max(0, reference_ms - ms)
    delta_minutes = delta_ms // 60_000
    if delta_minutes < _MINUTES_PER_HOUR:
        return f"{delta_minutes}m"

    delta_hours = delta_minutes // _MINUTES_PER_HOUR
    if delta_hours < _HOURS_PER_DAY:
        return f"{delta_hours}h"

    delta_days = delta_hours // _HOURS_PER_DAY
    return f"{delta_days}d"


def _color(text: str, code: int, *, enabled: bool | None = None) -> str:
    """Apply an ANSI color code to text, respecting terminal detection."""
    color_enabled = sys.stderr.isatty() if enabled is None else enabled
    if not color_enabled:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


# Named color constants
COLOR_BOLD = 1
COLOR_UNDERLINE = 4
COLOR_GRAY = 90
COLOR_YELLOW = 33
COLOR_MAGENTA = 35
COLOR_CYAN = 36


def _color_red(text: str, *, enabled: bool | None = None) -> str:
    return _color(text, 31, enabled=enabled)


def _color_gray(text: str, *, enabled: bool | None = None) -> str:
    return _color(text, COLOR_GRAY, enabled=enabled)


def _color_dim(text: str, *, enabled: bool | None = None) -> str:
    """Apply dim/bright styling (ANSI code 2)."""
    return _color(text, 2, enabled=enabled)


def _color_magenta(text: str, *, enabled: bool | None = None) -> str:
    """Apply magenta color for agent badges."""
    return _color(text, COLOR_MAGENTA, enabled=enabled)


def _color_cyan(text: str, *, enabled: bool | None = None) -> str:
    """Apply cyan color for source headers."""
    return _color(text, COLOR_CYAN, enabled=enabled)


def _color_yellow(text: str, *, enabled: bool | None = None) -> str:
    """Apply yellow color for age badges."""
    return _color(text, COLOR_YELLOW, enabled=enabled)


def _color_bold(text: str, *, enabled: bool | None = None) -> str:
    """Apply bold styling."""
    return _color(text, COLOR_BOLD, enabled=enabled)


def _color_underline(text: str, *, enabled: bool | None = None) -> str:
    """Apply underline styling."""
    return _color(text, COLOR_UNDERLINE, enabled=enabled)


def get_history_dir(root: Path) -> Path:
    """Return the export history directory for a repository root."""
    return root / HISTORY_DIR_NAME


def resolve_executable(command: str) -> str:
    """Resolve a command from PATH to an absolute executable path when possible."""
    return shutil.which(command) or command


def run_checked_command(
    command: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with captured text output and ``check=True`` enabled."""
    result = _run_command(
        command,
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    async def _run() -> subprocess.CompletedProcess[str]:
        process = await aio_subprocess.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd is not None else None,
            stdin=aio_subprocess.PIPE if input_text is not None else None,
            stdout=aio_subprocess.PIPE,
            stderr=aio_subprocess.PIPE,
        )
        stdout_raw, stderr_raw = await process.communicate(
            input_text.encode("utf-8") if input_text is not None else None,
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=int(process.returncode or 0),
            stdout=stdout_raw.decode("utf-8", errors="replace"),
            stderr=stderr_raw.decode("utf-8", errors="replace"),
        )

    result = asyncio.run(_run())
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result
