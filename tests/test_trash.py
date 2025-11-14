"""Tests for trash helpers."""

from pathlib import Path

import pytest

from llmhistory import trash


def test_get_trash_dir_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the macOS trash location on Darwin."""
    monkeypatch.setattr(trash.sys, "platform", "darwin")
    assert trash.get_trash_dir() == Path.home() / ".Trash"


def test_get_trash_dir_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the FreeDesktop trash location on Linux."""
    monkeypatch.setattr(trash.sys, "platform", "linux")
    assert trash.get_trash_dir() == Path.home() / ".local/share/Trash"


def test_safe_move_retries_after_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retry with a fresh destination when a move collides."""
    src = tmp_path / "source.txt"
    src.write_text("payload")
    dest = tmp_path / "dest.txt"

    calls: list[tuple[str, str]] = []

    def fake_move(src_name: str, dest_name: str) -> str:
        calls.append((src_name, dest_name))
        if len(calls) == 1:
            Path(dest_name).write_text("existing")
            raise FileExistsError(dest_name)
        Path(src_name).rename(dest_name)
        return dest_name

    monkeypatch.setattr(trash.shutil, "move", fake_move)

    safe_move = trash.__dict__["_safe_move"]

    assert safe_move(src, dest) is True
    assert calls == [
        (str(src), str(dest)),
        (str(src), str(tmp_path / "dest.txt (1)")),
    ]
    assert not src.exists()
    assert (tmp_path / "dest.txt (1)").read_text() == "payload"


def test_safe_move_returns_false_on_move_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Return False when the move operation fails."""
    src = tmp_path / "source.txt"
    src.write_text("payload")
    dest = tmp_path / "dest.txt"

    def fake_move(src_name: str, dest_name: str) -> str:
        message = f"cannot move {src_name} -> {dest_name}"
        raise OSError(message)

    monkeypatch.setattr(trash.shutil, "move", fake_move)

    safe_move = trash.__dict__["_safe_move"]

    assert safe_move(src, dest) is False
    assert src.exists()
