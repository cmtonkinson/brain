"""Validation tests for Markdown documentation conventions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_documentation_conventions_check(
    *paths: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the documentation conventions checker for the provided paths."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/check_documentation_conventions.py",
        "--check",
    ]
    command.extend(str(path) for path in paths)
    return subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_project_docs_follow_documentation_conventions() -> None:
    """Project docs and component READMEs should satisfy conventions checks."""
    completed = _run_documentation_conventions_check()
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_documentation_conventions_require_two_blank_lines_before_footer(
    tmp_path: Path,
) -> None:
    """The checker should enforce the footer spacing documented in the meta doc."""
    doc_path = tmp_path / "sample.md"
    doc_path.write_text(
        "# Sample\n"
        "Intro paragraph.\n"
        "\n"
        "------------------------------------------------------------------------\n"
        "_End of Sample_\n",
        encoding="utf-8",
    )

    completed = _run_documentation_conventions_check(doc_path)

    assert completed.returncode == 1
    assert "footer-blank-lines" in completed.stderr
