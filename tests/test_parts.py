"""Tests for part ordering helpers."""

from pathlib import Path

from llmhistory.parts import _ordered_part_files
from tests.test_utils import write_json


def test_ordered_part_files_handles_malformed_start_values(tmp_path: Path) -> None:
    """Treat malformed part start timestamps as zero instead of crashing."""
    write_json(tmp_path / "prt_2.json", {"time": {"start": "bad"}})
    write_json(tmp_path / "prt_1.json", {"time": {"start": 5}})

    files = _ordered_part_files(tmp_path)

    assert files == [tmp_path / "prt_2.json", tmp_path / "prt_1.json"]
