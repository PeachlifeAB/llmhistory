#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${OPENCODE_EXPORT_PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
	echo "interpreter not found: $PYTHON_BIN" >&2
	exit 127
fi

_SELF="${BASH_SOURCE[0]}"
while [ -L "$_SELF" ]; do _SELF="$(readlink "$_SELF")"; done
SCRIPT_DIR="$(cd "$(dirname "$_SELF")" && pwd)"
exec "$PYTHON_BIN" "$SCRIPT_DIR/scripts/llmhistory_export.py" "$@"
