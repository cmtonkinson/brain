"""Drift tests for generated Service API markdown documentation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_l1_public_api_docs_are_in_sync() -> None:
    """Generated docs should stay in sync with service interface source files."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/generate_service_api_docs.py",
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
