"""Drift tests for generated capability markdown documentation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_capability_docs_are_in_sync() -> None:
    """Generated docs should stay in sync with registered capabilities."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/generate_capability_docs.py",
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


def test_capability_docs_group_skills_by_kind() -> None:
    """Generated docs should group logic and pipeline skills into kind sections."""
    repo_root = Path(__file__).resolve().parents[2]
    content = (repo_root / "docs/capabilities.md").read_text(encoding="utf-8")

    logic_section = content.split("## `Logic Skills`", 1)[1]
    logic_section = logic_section.split(
        "------------------------------------------------------------------------", 1
    )[0]

    assert "### `demo-echo\n" in logic_section
    assert "### `object-get-base64\n" in logic_section
    assert "## `Capability Engine Service`" not in content
    assert "`logic_skill` `1.0.0`  \n" in content
