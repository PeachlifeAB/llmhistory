"""Tests for persisted storage index mutations."""

from pathlib import Path

from llmhistory.storage_index import (
    load_index,
    save_index_atomic,
    update_index_remove_session,
)


def test_update_index_remove_session_persists_deletion(tmp_path: Path) -> None:
    """Delete the requested session from the stored index on disk."""
    index = {
        "version": 1,
        "projects": {
            "proj_1": {
                "sessions": {
                    "ses_keep": {"last_modified_timestamp": 1.0},
                    "ses_drop": {"last_modified_timestamp": 2.0},
                }
            }
        },
    }
    save_index_atomic(tmp_path, index)

    update_index_remove_session(tmp_path, "proj_1", "ses_drop")

    reloaded = load_index(tmp_path)
    sessions = reloaded["projects"]["proj_1"]["sessions"]
    assert "ses_drop" not in sessions
    assert "ses_keep" in sessions
