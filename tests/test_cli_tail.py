"""Tests for the markdown tail helper."""

from pathlib import Path

import pytest

from llmhistory import cli_tail


def test_run_tail_prints_appended_content_after_truncation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print appended content and recover after the file is truncated."""
    md_path = tmp_path / "latest.md"
    md_path.write_text("hello")

    states = iter(["append", "truncate", "append-again", "stop"])

    def fake_sleep(_: float) -> None:
        state = next(states)
        if state == "append":
            md_path.write_text("hello world")
            return
        if state == "truncate":
            md_path.write_text("bye")
            return
        if state == "append-again":
            md_path.write_text("bye!!!")
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_tail, "get_md_path", lambda: md_path)
    monkeypatch.setattr(cli_tail.time, "sleep", fake_sleep)

    assert cli_tail.run_tail() == 0
    assert capsys.readouterr().out == " worldbye!!!"
