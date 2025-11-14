"""Tests for OpenCode project id resolution across path variants."""

from pathlib import Path

from llmhistory.projects import resolve_project_ids
from tests.test_utils import write_json


def test_resolve_project_ids_matches_resolved_real_path(tmp_path: Path) -> None:
    """Match project ids when running from a nested subdirectory."""
    storage = tmp_path / "storage"
    repo_root = tmp_path / "repo"
    nested = repo_root / "nested"
    nested.mkdir(parents=True)

    project_id = "proj_1"
    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(repo_root)},
    )

    matches = resolve_project_ids(storage, nested)
    assert matches == [project_id]


def test_resolve_project_ids_uses_resolve_for_symlinked_root(tmp_path: Path) -> None:
    """Match project ids when cwd is a symlink to the real repo root."""
    storage = tmp_path / "storage"
    real_repo = tmp_path / "real_repo"
    real_repo.mkdir(parents=True)

    symlink_repo = tmp_path / "symlink_repo"
    symlink_repo.symlink_to(real_repo, target_is_directory=True)

    project_id = "proj_1"
    write_json(
        storage / "project" / f"{project_id}.json",
        {"id": project_id, "worktree": str(real_repo)},
    )

    matches = resolve_project_ids(storage, symlink_repo)
    assert matches == [project_id]
