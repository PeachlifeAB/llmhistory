#!/usr/bin/env bash
set -euo pipefail

# Integration test for llmhistory
# Runs the exporter twice per target to verify idempotency.
#
# Optional external targets:
# - set AGENTSENSEI_DIR to test another repo
# - set AERC_DIR to test a repo with multiple OpenCode project IDs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_CMD="uv run python scripts/llmhistory_export.py"
COMMON_FLAGS="--no-pbcopy"
HISTORY_DIR=".llm"

echo "======================================"
echo "OpenCode Export Integration Tests"
echo "======================================"
echo ""

# Resolve repo root (portable)
if OPENCODE_EXPORT_DIR=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null); then
	:
elif [ -d "$SCRIPT_DIR/.git" ]; then
	# Fallback: only assume SCRIPT_DIR is the repo root if it contains a .git directory.
	OPENCODE_EXPORT_DIR="$SCRIPT_DIR"
else
	echo "✗ FAIL: could not resolve repo root (not a git repo): $SCRIPT_DIR" >&2
	exit 1
fi

AGENTSENSEI_DIR=${AGENTSENSEI_DIR:-""}
AERC_DIR=${AERC_DIR:-""}

# Test 1: llmhistory project
echo "Test 1: llmhistory project"
cd "$OPENCODE_EXPORT_DIR"
echo "  Run 1:"
$EXPORT_CMD $COMMON_FLAGS
if [ ! -d "$HISTORY_DIR" ]; then
	echo "    ✗ FAIL: .llm not created" >&2
	exit 1
fi
echo ""
echo "  Run 2:"
$EXPORT_CMD $COMMON_FLAGS
# Default output is Markdown (.md)
if ! ls -1 "$HISTORY_DIR"/*.md >/dev/null 2>&1; then
	echo "    ✗ FAIL: No .md exports found" >&2
	exit 1
fi
echo ""

echo "  Run 2b (--json):"
$EXPORT_CMD $COMMON_FLAGS --json --force-refresh
if ! ls -1 "$HISTORY_DIR"/*.jsonl >/dev/null 2>&1; then
	echo "    ✗ FAIL: No .jsonl exports found after --json" >&2
	exit 1
fi
echo ""

echo "  Run 3 (--output path):"
PATH_ONLY_LINES=()
while IFS= read -r line; do
	PATH_ONLY_LINES+=("$line")
done < <($EXPORT_CMD $COMMON_FLAGS --output path)
if [ "${#PATH_ONLY_LINES[@]}" -ne 1 ]; then
	echo "    ✗ FAIL: Expected a single line path, got ${#PATH_ONLY_LINES[@]} lines" >&2
	exit 1
fi
PATH_ONLY="${PATH_ONLY_LINES[0]}"
if [ -n "$PATH_ONLY" ] && [ -f "$PATH_ONLY" ]; then
	echo "    Path: $PATH_ONLY"
else
	echo "    ✗ FAIL: Did not return an existing file path" >&2
	exit 1
fi
echo "  ✓ PASS"
echo ""

# Test 2: agentsensei project (optional)
echo "Test 2: agentsensei project (optional)"
if [ -n "$AGENTSENSEI_DIR" ] && [ -d "$AGENTSENSEI_DIR" ]; then
	cd "$AGENTSENSEI_DIR"
	echo "  Run 1:"
	$EXPORT_CMD $COMMON_FLAGS
	if [ ! -d "$HISTORY_DIR" ] || ! ls -1 "$HISTORY_DIR"/*.md >/dev/null 2>&1; then
		echo "    ✗ FAIL: missing .llm or .md exports" >&2
		exit 1
	fi
	echo ""
	echo "  Run 2:"
	$EXPORT_CMD $COMMON_FLAGS
	if ! ls -1 "$HISTORY_DIR"/*.md >/dev/null 2>&1; then
		echo "    ✗ FAIL: no .md exports found" >&2
		exit 1
	fi
	echo "  ✓ PASS"
else
	echo "  (skipped) Set AGENTSENSEI_DIR to enable this test"
fi
echo ""

# Test 3: aerc project (multiple project IDs) (optional)
echo "Test 3: aerc project (multiple project IDs) (optional)"
if [ -n "$AERC_DIR" ] && [ -d "$AERC_DIR" ]; then
	cd "$AERC_DIR"
	echo "  Run 1:"
	$EXPORT_CMD $COMMON_FLAGS
	if [ ! -d "$HISTORY_DIR" ] || ! ls -1 "$HISTORY_DIR"/*.md >/dev/null 2>&1; then
		echo "    ✗ FAIL: missing .llm or .md exports" >&2
		exit 1
	fi
	echo ""
	echo "  Run 2:"
	$EXPORT_CMD $COMMON_FLAGS
	if ! ls -1 "$HISTORY_DIR"/*.md >/dev/null 2>&1; then
		echo "    ✗ FAIL: no .md exports found" >&2
		exit 1
	fi
	echo "  ✓ PASS"
else
	echo "  (skipped) Set AERC_DIR to enable this test"
fi
echo ""

echo "======================================"
echo "✅ ALL TESTS PASSED"
echo "======================================"
