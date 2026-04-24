"""Drift tests for generated op markdown documentation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_op_docs_are_in_sync() -> None:
    """Generated docs should stay in sync with registered ops."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/generate_op_docs.py",
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


def test_op_docs_group_ops_by_kind() -> None:
    """Generated docs should group logic and pipeline ops into kind sections."""
    repo_root = Path(__file__).resolve().parents[2]
    content = (repo_root / "docs/ops.md").read_text(encoding="utf-8")

    logic_section = content.split("## `Logic Ops`", 1)[1]
    logic_section = logic_section.split(
        "------------------------------------------------------------------------", 1
    )[0]

    assert "### `demo-echo`\n" in logic_section
    assert "### `object-get-base64`\n" in logic_section
    assert "## `Execution Service`" not in content
    assert "`logic` `1.0.0` `effect: read` `approval: never`  \n" in content
