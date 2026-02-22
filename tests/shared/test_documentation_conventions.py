"""Validation tests for Markdown documentation conventions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_project_docs_follow_documentation_conventions() -> None:
    """README and docs markdown should satisfy documentation convention checks."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/check_documentation_conventions.py",
        "--check",
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
