"""Drift tests for generated HTTP API markdown documentation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_http_api_docs_are_in_sync() -> None:
    """Generated docs should stay in sync with registered HTTP route files."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/generate_http_api_docs.py",
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
