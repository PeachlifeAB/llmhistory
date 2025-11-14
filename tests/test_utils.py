"""Shared test helpers."""

import json
from pathlib import Path

DEFAULT_TIMEOUT_S = 60


def write_json(path: Path, data: dict) -> None:
    """Write a single JSON object with trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
