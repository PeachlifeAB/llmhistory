#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(pwd)"
HISTORY_DIR="$REPO_DIR/.llm"

if [ ! -d "$HISTORY_DIR" ]; then
	echo "Missing .llm" >&2
	exit 1
fi

echo "Found .llm" >&2

PROJECT_ID="$({
	python3 - <<'PY'
import json
import os
from pathlib import Path

storage = Path(os.environ.get('OPENCODE_STORAGE', str(Path.home() / '.local/share/opencode/storage')))
repo = Path.cwd().resolve()
project_dir = storage / 'project'
if not project_dir.is_dir():
    raise SystemExit(0)

for p in sorted(project_dir.glob('*.json')):
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        continue
    worktree = data.get('worktree')
    if not isinstance(worktree, str):
        continue
    try:
        wt = Path(worktree).resolve()
    except OSError:
        wt = Path(worktree).absolute()
    if wt == repo or wt in repo.parents or repo in wt.parents:
        print(p.stem)
        break
PY
})"

if [ -z "$PROJECT_ID" ]; then
	echo "No matching project for current directory" >&2
	exit 1
fi

echo "Resolved project: $PROJECT_ID" >&2
echo "No sessions pruned (wrapper mode)" >&2
exit 0
