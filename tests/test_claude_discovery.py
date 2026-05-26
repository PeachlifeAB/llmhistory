"""Tests for Claude project discovery across worktrees and subdirectories."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from llmhistory.sources.claude import ClaudeSource


def _encode(path: Path) -> str:
    return str(path).replace(os.sep, "-").replace(".", "-")


def test_resolve_project_ids_finds_worktrees_and_subdirs(tmp_path: Path) -> None:
    """Resolve project ids for repo root, subdir, and linked worktree."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()

    subdir = repo_root / "subdir"
    subdir.mkdir()

    worktree_root = tmp_path / "worktree"
    worktree_root.mkdir()
    (worktree_root / ".git").write_text(f"gitdir: {repo_root}/.git/worktrees/worktree")

    other_root = tmp_path / "other"
    other_root.mkdir()
    (other_root / ".git").mkdir()

    claude_storage = tmp_path / "claude_projects"
    claude_storage.mkdir()

    p_repo = claude_storage / _encode(repo_root)
    p_repo.mkdir()

    p_subdir = claude_storage / _encode(subdir)
    p_subdir.mkdir()

    p_worktree = claude_storage / _encode(worktree_root)
    p_worktree.mkdir()

    p_other = claude_storage / _encode(other_root)
    p_other.mkdir()

    source = ClaudeSource()

    with patch.object(
        ClaudeSource,
        "_get_git_worktrees",
        return_value=[repo_root, worktree_root],
        create=True,
    ):
        project_ids = source.resolve_project_ids(claude_storage, repo_root)

    assert set(project_ids) == {p_repo.name, p_subdir.name, p_worktree.name}


def test_resolve_project_ids_rejects_sibling_prefix_matches(
    tmp_path: Path,
) -> None:
    """Do not treat a sibling project that shares the encoded prefix as a subdir."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()

    subdir = repo_root / "subdir"
    subdir.mkdir()

    sibling = tmp_path / "repo-other"
    sibling.mkdir()
    (sibling / ".git").mkdir()

    claude_storage = tmp_path / "claude_projects"
    claude_storage.mkdir()
    p_repo = claude_storage / _encode(repo_root)
    p_repo.mkdir()
    p_subdir = claude_storage / _encode(subdir)
    p_subdir.mkdir()
    p_sibling = claude_storage / _encode(sibling)
    p_sibling.mkdir()

    source = ClaudeSource()

    with patch.object(
        ClaudeSource,
        "_get_git_worktrees",
        return_value=[repo_root],
        create=True,
    ):
        project_ids = source.resolve_project_ids(claude_storage, repo_root)

    assert set(project_ids) == {p_repo.name, p_subdir.name}
    assert p_sibling.name not in project_ids


def test_resolve_project_ids_matches_private_alias(tmp_path: Path) -> None:
    """Match /private-prefixed worktrees to Claude's non-private project ids."""
    claude_storage = tmp_path / "claude_projects"
    claude_storage.mkdir()

    private_root = Path("/private/Users/example/.local/cache/llmhistory")
    nonprivate_root = Path("/Users/example/.local/cache/llmhistory")
    project_dir = claude_storage / _encode(nonprivate_root)
    project_dir.mkdir()

    source = ClaudeSource()

    with patch.object(
        ClaudeSource,
        "_get_git_worktrees",
        return_value=[private_root],
        create=True,
    ):
        project_ids = source.resolve_project_ids(claude_storage, private_root)

    assert project_ids == [project_dir.name]


def test_resolve_sessions_does_not_reject_foreign_cwd_in_matched_project(
    tmp_path: Path,
) -> None:
    """Do not reject sessions solely by event cwd after project-dir matching."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sibling = tmp_path / "repo-other"
    sibling.mkdir()

    claude_storage = tmp_path / "claude_projects"
    project_dir = claude_storage / _encode(repo_root)
    project_dir.mkdir(parents=True)

    session = project_dir / "11111111-1111-4111-8111-111111111111.jsonl"
    session.write_text(
        json.dumps({"type": "user", "cwd": str(sibling), "uuid": "u1"}) + "\n",
    )

    source = ClaudeSource()

    sessions = source.resolve_sessions(
        claude_storage,
        project_dir.name,
        repo_root,
        all_sessions=True,
        debug=False,
    )

    assert [session_ref.sid for session_ref in sessions] == [session.stem]
