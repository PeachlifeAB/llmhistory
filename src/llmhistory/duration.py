"""Duration parsing helpers for pruning commands."""

from __future__ import annotations

import re
from datetime import timedelta

DURATION_PATTERN = re.compile(r"^(\d+)([hdwmy])$")


def parse_duration(range_str: str) -> timedelta:
    """Parse a compact duration like `30d` or `8w` into `timedelta`."""
    match = DURATION_PATTERN.match(range_str)
    if not match:
        help_text = "Invalid duration format: "
        help_text += f"{range_str}. Use format like 1h, 30d, 8w, 4m, 1y"
        raise ValueError(
            help_text,
        )

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    if unit == "m":
        return timedelta(days=value * 30)
    if unit == "y":
        return timedelta(days=value * 365)

    msg = f"Unknown unit: {unit}"
    raise ValueError(msg)
