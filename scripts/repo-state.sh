#!/usr/bin/env bash
# ETA: ~1s observed 2026-03-29
set -euo pipefail

printf 'pwd=%s\n' "$PWD"
ls -al
git status --porcelain=v1 -b
git log -7 --oneline
git diff --stat
git branch --list

printf 'python3=%s\n' "$(command -v python3)"
python3 --version
printf 'uv=%s\n' "$(command -v uv)"
uv --version

if command -v llmhistory >/dev/null 2>&1; then
	tool_path="$(command -v llmhistory)"
	printf 'llmhistory=%s\n' "$tool_path"
	TOOL_PATH="$tool_path" python3 - <<'PY'
from pathlib import Path
import os
print('llmhistory_real=' + str(Path(os.path.realpath(os.environ['TOOL_PATH']))))
PY
else
	printf 'llmhistory=%s\n' '<not found>'
fi
