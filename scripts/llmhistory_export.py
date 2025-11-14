"""Legacy module entrypoint for llmhistory CLI."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
src_str = str(SRC)
if src_str not in sys.path:
    sys.path.insert(0, src_str)


def main() -> int:
    """Run the llmhistory CLI from the legacy script path."""
    cli_main = importlib.import_module("llmhistory.cli").main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
