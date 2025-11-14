"""Tests for Claude project discovery across worktrees and subdirectories."""

import os
from pathlib import Path
from unittest.mock import patch

from llmhistory.sources.claude import ClaudeSource


def test_resolve_project_ids_finds_worktrees_and_subdirs(tmp_path: Path) -> None:
    """Resolve project ids for repo root, subdir, and linked worktree."""
    # 1. Setup simulated file system
    # /repo (main git repo)
    # /repo/subdir
    # /worktree (git worktree of /repo)
    # /other (unrelated repo)

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

    # 2. Setup simulated Claude storage
    claude_storage = tmp_path / "claude_projects"
    claude_storage.mkdir()

    # Helper to encode path like Claude (replacing / with -)
    def encode(p: Path) -> str:
        return str(p).replace(os.sep, "-").replace(".", "-")

    # Create project dirs in Claude storage
    p_repo = claude_storage / encode(repo_root)
    p_repo.mkdir()

    p_subdir = claude_storage / encode(subdir)
    p_subdir.mkdir()

    p_worktree = claude_storage / encode(worktree_root)
    p_worktree.mkdir()

    p_other = claude_storage / encode(other_root)
    p_other.mkdir()

    # 3. Initialize source with mocked storage path
    source = ClaudeSource()

    # Mock _get_git_worktrees to return our simulated paths
    # (Since we are not creating a real git repo with worktrees in this test)
    with (
        patch.object(ClaudeSource, "get_storage_path", return_value=claude_storage),
        patch.object(
            ClaudeSource,
            "_get_git_worktrees",
            return_value=[repo_root, worktree_root],
            create=True,
        ),
    ):
        # 4. Run discovery from the context of 'repo_root'
        # It should find:
        # - repo_root (direct match)
        # - subdir (subdirectory of repo)
        # - worktree (shares git root/common dir)
        # It should NOT find:
        # - other (different repo)

        # Discovery should match directories belonging to the same repo/worktree.
        # For the test, we assume we are running FROM repo_root.

        # NOTE: Current implementation only looks for encode(repo_root).
        # We expect this test to FAIL initially for subdir/worktree paths.

        project_ids = source.resolve_project_ids(claude_storage, repo_root)

        # We expect to find 3 projects eventually
        found_names = set(project_ids)
        expected_names = {p_repo.name, p_subdir.name, p_worktree.name}

        # This assertion will fail with current implementation (only finds p_repo)
        assert found_names == expected_names
