"""Security regression tests for prune shell behavior."""

import json
import os
import subprocess
from pathlib import Path


def test_opencode_prune_project_id_lookup_handles_quotes_safely(tmp_path: Path) -> None:
    """Regression test for unsafe pattern building in project-id lookup.

    Previously, llmhistory-prune.sh embedded CURRENT_DIR directly into an rg pattern.
    If CURRENT_DIR contained quotes/metacharacters, it could break the pattern.
    We now resolve project id via jq field comparisons.
    """
    # Create a "repo" directory whose name includes a quote
    repo_dir = tmp_path / 'repo-with-quote"in-name'
    history_dir = repo_dir / ".llm"
    history_dir.mkdir(parents=True)

    # Provide a minimal OpenCode storage layout
    storage = tmp_path / "storage"
    project_dir = storage / "project"
    session_dir = storage / "session"
    project_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)

    project_id = "proj_123"
    (project_dir / f"{project_id}.json").write_text(
        json.dumps({"id": project_id, "worktree": str(repo_dir)}) + "\n",
        encoding="utf-8",
    )

    # pruner validates that session/<project_id> exists
    (session_dir / project_id).mkdir(parents=True)

    script_path = Path(__file__).resolve().parents[1] / "llmhistory-prune.sh"

    result = subprocess.run(
        ["bash", str(script_path)],
        check=False,
        cwd=repo_dir,
        env={**os.environ, "OPENCODE_STORAGE": str(storage)},
        input="n\n",
        text=True,
        capture_output=True,
        timeout=60,
    )

    # It may still exit non-zero later (no tracked sessions), but it must NOT fail
    # at the project-id lookup stage.
    assert "No matching project for current directory" not in result.stderr

    # Confirm it did identify the history dir (sanity check the code path ran)
    assert "Found .llm" in result.stderr

    # If it got far enough to compute counts, it will print tracked/stored sessions.
    # Accept either outcome, but ensure we didn't crash/bail early due to quoting.
    assert result.returncode in {0, 1}
