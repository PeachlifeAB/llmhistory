# llmhistory

Export LLM conversation history (OpenCode, Claude Desktop) to Markdown and JSONL files.

## Features

- **Multi-source support**: Export from OpenCode and Claude Desktop/CLI
- **Tool call capture**: Exports all AI tool calls with inputs and outputs
- **Session-level exports**: Rewrites session outputs when the source session changed
- **Session tracking**: Each session saved to `.llm/` (includes a `-compactions.md` file)
- **Storage pruning**: Remove untracked sessions or delete by age
- **Pipe-friendly**: `-q` outputs content to stdout; `--output path` outputs just the path; `--output session` outputs the session ID; `--output compactionPath` outputs the per-session `-compactions.md` path

## Install

```bash
# Install via uv (recommended)
uv tool install -e .

# Or install from git
uv tool install git+https://github.com/dabvid/opencode-export.git
```

## Usage

### Export Sessions

```bash
llmhistory                         # Export most recent OpenCode session (markdown)
llmhistory --all                   # Export all OpenCode sessions
llmhistory --source claude         # Export Claude sessions
llmhistory --source all            # Export from all sources
llmhistory --json                  # Export as JSONL
llmhistory -q                      # Quiet: output file contents to stdout
llmhistory --output path           # Output only the path (for piping)
llmhistory --output session        # Output only the session ID (for piping)
llmhistory --output compactionPath # Output only the compactions path (for piping)
```

### Pruning & Cleanup

```bash
# Remove untracked sessions (not in any export)
llmhistory prune [--dry-run] [--yes]

# Delete sessions older than specified duration
llmhistory delete-older-than 30d [--dry-run] [--yes]
llmhistory delete-older-than 1y [--dry-run] [--yes]

# Duration formats: 1h, 30d, 8w, 4m (30 days/month), 1y (365 days/year)
```

**Flags:**
- `--dry-run`: Show what would be deleted without actually deleting
- `--yes`, `-y`: Skip confirmation prompt

## Command-line Options

| Option | Description |
|--------|-------------|
| `--all` | Export all sessions (default: most recent only) |
| `--md` | Export Markdown (default if neither `--md` nor `--json`) |
| `--json` | Export JSONL (`.jsonl`) |
| `-q`, `--quiet` | Suppress status; print file contents to stdout |
| `--output path` | Print only the exported path (requires markdown) |
| `--output session` | Print only the session ID |
| `--output compactionPath` | Print only the compactions markdown path (requires markdown; cannot combine with `--all`) |
| `--storage PATH` | Override storage root (default: `~/.local/share/opencode/storage`) |
| `--no-pbcopy` | Don't copy path to clipboard |
| `--debug` | Enable debug output on stderr |

Note: `-q` cannot combine `--md` and `--json` (ambiguous stdout).

## Piping Examples

```bash
# Search for bash commands
llmhistory -q | grep "Tool: bash"

# Count tool calls across all sessions
llmhistory -q --all | grep "Tool:" | wc -l

# Extract message IDs from JSONL
llmhistory -q --json | jq -r '.id'

# Extract session IDs from JSONL
llmhistory -q --json | jq -r '.session_id'

# Detect conversation restarts (parentID == null after /new)
llmhistory -q --json | jq -s '[.[] | select(.role == "user" and .parentID == null)] | length'
```

## Output Format

Markdown exports include user/assistant messages with timestamps, parent IDs, and tool calls.

Additionally, a per-session compactions file is always written:
- `.llm/<session-title>-compactions.md`

It contains only compaction messages detected by:
- `agent == "compaction"`

```markdown
### Tool: bash
**Input:**
{"command": "git status"}
**Output:**
On branch main
nothing to commit
```

JSONL exports include a `tool_calls` array per message.

### Conversation Restarts

OpenCode's `/new` command keeps the same session ID but sets `parentID: null` on the next user message.

## OpenCode Storage

Default location: `~/.local/share/opencode/storage/`

Structure:
- `project/*.json` - project metadata
- `session/<project_id>/ses_*.json` - session metadata
- `message/ses_<id>/msg_*.json` - messages
- `part/msg_<id>/prt_*.json` - message parts (text/tool)

## Requirements

- `python3`
- OpenCode with session storage

## Testing

```bash
# Fast local validation (default; excludes integration tests)
uv run python -m pytest

# Run integration tests explicitly
uv run python -m pytest -m integration

# Run full suite including integration tests
uv run python -m pytest -m "integration or not integration"
```
