"""Tests for shell wrapper behavior around Python interpreter selection."""

import os
import subprocess
from pathlib import Path


def test_opencode_export_sh_reports_missing_python3(tmp_path: Path) -> None:
    """Return code 127 and stderr hint when configured python is missing."""
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "llmhistory.sh"
    assert script.is_file()

    env = dict(os.environ)
    env["OPENCODE_EXPORT_PYTHON"] = "python3_DOES_NOT_EXIST"

    result = subprocess.run(
        ["bash", str(script), "--help"],
        check=False,
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 127
    assert "interpreter not found: python3_DOES_NOT_EXIST" in result.stderr
