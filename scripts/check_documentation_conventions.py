"""Validate project Markdown docs against documentation-conventions rules.

The checker targets ``README.md`` and ``docs/**/*.md`` and enforces the subset
of rules in ``docs/meta/documentation-conventions.md`` that can be validated
mechanically with low false-positive risk.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HR = "------------------------------------------------------------------------"
README_PATH = Path("README.md")
DOCS_GLOB = "docs/**/*.md"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
H2_RE = re.compile(r"^##\s+.+")
DASH_ONLY_RE = re.compile(r"^-+$")
END_RE = re.compile(r"^_End of (.+)_$")
STAR_BULLET_RE = re.compile(r"^\s*\*\s+")
SINGLE_ASTERISK_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
REFERENCE_LINK_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s+(\S+)")
INLINE_LINK_RE = re.compile(r"(?<!!)(\[[^\]]+\])\(([^)]+)\)")


@dataclass(frozen=True)
class Heading:
    """One parsed ATX heading in a Markdown file."""

    level: int
    text: str
    line: int


@dataclass(frozen=True)
class Violation:
    """One documentation-convention rule violation with source context."""

    path: Path
    line: int
    rule: str
    message: str

    def render(self) -> str:
        """Return a deterministic human-readable violation string."""
        return f"{self.path.as_posix()}:{self.line}: [{self.rule}] {self.message}"


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments for docs-convention validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional Markdown file paths to validate. Defaults to README + docs/**/*.md.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validation mode (default behavior). Included for script parity.",
    )
    return parser.parse_args()


def _strip_inline_code(line: str) -> str:
    """Return line text with inline backtick spans removed for safe regex checks."""
    return re.sub(r"`[^`]*`", "", line)


def _is_external_link_target(target: str) -> bool:
    """Return true when a Markdown link target points to an external URL."""
    normalized = target.strip().strip("<>")
    return normalized.startswith("http://") or normalized.startswith("https://")


def _discover_targets(repo_root: Path, requested_paths: list[str]) -> tuple[Path, ...]:
    """Return markdown files targeted for validation."""
    if requested_paths:
        return tuple((repo_root / path).resolve() for path in requested_paths)

    docs_paths = sorted(path.resolve() for path in repo_root.glob(DOCS_GLOB))
    return ((repo_root / README_PATH).resolve(), *docs_paths)


def _headings_for_lines(lines: list[str]) -> tuple[Heading, ...]:
    """Extract heading metadata while skipping fenced code blocks."""
    headings: list[Heading] = []
    in_code_fence = False

    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        match = HEADING_RE.match(line)
        if not match:
            continue

        heading_marks, heading_text = match.groups()
        headings.append(
            Heading(level=len(heading_marks), text=heading_text.strip(), line=idx)
        )

    return tuple(headings)


def _validate_file(*, repo_root: Path, file_path: Path) -> tuple[Violation, ...]:
    """Validate one Markdown file against mechanical convention rules."""
    try:
        rel_path = file_path.relative_to(repo_root)
    except ValueError:
        rel_path = file_path
    violations: list[Violation] = []

    if not file_path.exists():
        violations.append(
            Violation(
                path=rel_path,
                line=1,
                rule="missing-file",
                message="Target file does not exist.",
            )
        )
        return tuple(violations)

    lines = file_path.read_text(encoding="utf-8").splitlines()
    headings = _headings_for_lines(lines)
    h1_headings = [heading for heading in headings if heading.level == 1]

    if not lines:
        violations.append(
            Violation(
                path=rel_path,
                line=1,
                rule="empty-document",
                message="Document is empty.",
            )
        )
        return tuple(violations)

    first_line_match = HEADING_RE.match(lines[0])
    if first_line_match is None or len(first_line_match.group(1)) != 1:
        violations.append(
            Violation(
                path=rel_path,
                line=1,
                rule="h1-first-line",
                message="Line 1 must be a single h1 heading ('# Title').",
            )
        )

    if len(h1_headings) != 1:
        violations.append(
            Violation(
                path=rel_path,
                line=1,
                rule="single-h1",
                message="Document must contain exactly one h1 heading.",
            )
        )

    h1_title = h1_headings[0].text if h1_headings else ""

    if len(lines) < 2:
        violations.append(
            Violation(
                path=rel_path,
                line=1,
                rule="intro-required",
                message="Document must include an intro line directly below h1.",
            )
        )
    else:
        intro_line = lines[1].strip()
        if not intro_line:
            violations.append(
                Violation(
                    path=rel_path,
                    line=2,
                    rule="intro-no-blank",
                    message="No blank line is allowed between h1 and intro paragraph.",
                )
            )
        elif (
            intro_line.startswith("#") or intro_line == HR or intro_line.startswith(">")
        ):
            violations.append(
                Violation(
                    path=rel_path,
                    line=2,
                    rule="intro-paragraph",
                    message="Intro line below h1 should be paragraph text, not heading/hr/blockquote.",
                )
            )

    for heading in headings:
        next_line_index = heading.line
        if next_line_index >= len(lines):
            violations.append(
                Violation(
                    path=rel_path,
                    line=heading.line,
                    rule="heading-following-content",
                    message="Headings must be followed by content on the next line.",
                )
            )
            continue
        if not lines[next_line_index].strip():
            violations.append(
                Violation(
                    path=rel_path,
                    line=heading.line,
                    rule="heading-no-blank-line",
                    message="No blank line is allowed directly below any heading.",
                )
            )

        if heading.level == 2 and re.match(r"^\d+\s*([.):\-]|$)", heading.text):
            violations.append(
                Violation(
                    path=rel_path,
                    line=heading.line,
                    rule="h2-not-numbered",
                    message="h2 headings must not be numbered.",
                )
            )

        if re.match(r"^purpose(?:\b|:)", heading.text, flags=re.IGNORECASE):
            violations.append(
                Violation(
                    path=rel_path,
                    line=heading.line,
                    rule="no-purpose-heading",
                    message="Do not use an explicit 'Purpose' heading.",
                )
            )

    in_code_fence = False
    for idx, line in enumerate(lines, start=1):
        stripped_leading = line.lstrip()
        if stripped_leading.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        stripped = line.strip()
        if DASH_ONLY_RE.match(stripped):
            if stripped != HR:
                violations.append(
                    Violation(
                        path=rel_path,
                        line=idx,
                        rule="hr-length",
                        message="Horizontal rule must use exactly 72 dashes.",
                    )
                )
                continue

            if idx >= len(lines):
                violations.append(
                    Violation(
                        path=rel_path,
                        line=idx,
                        rule="hr-placement",
                        message="Horizontal rule must be followed by an h2 or footer line.",
                    )
                )
                continue

            next_line = lines[idx]
            next_line_stripped = next_line.strip()
            if not next_line_stripped:
                violations.append(
                    Violation(
                        path=rel_path,
                        line=idx,
                        rule="hr-no-blank-below",
                        message="No blank line is allowed between hr and heading/footer below it.",
                    )
                )
                continue

            if (
                H2_RE.match(next_line) is None
                and END_RE.match(next_line_stripped) is None
            ):
                violations.append(
                    Violation(
                        path=rel_path,
                        line=idx,
                        rule="hr-placement",
                        message="Horizontal rules may appear only directly above h2 headings or footer.",
                    )
                )

        if STAR_BULLET_RE.match(line):
            violations.append(
                Violation(
                    path=rel_path,
                    line=idx,
                    rule="unordered-list-marker",
                    message="Use '-' for unordered list items, not '*'.",
                )
            )

        line_without_code = _strip_inline_code(line)
        for match in SINGLE_ASTERISK_ITALIC_RE.finditer(line_without_code):
            inner = match.group(1)
            if not re.search(r"[A-Za-z0-9]", inner):
                continue
            violations.append(
                Violation(
                    path=rel_path,
                    line=idx,
                    rule="italic-underscore-style",
                    message="Use underscores for italics, not single-asterisk emphasis.",
                )
            )
            break

        reference_match = REFERENCE_LINK_DEF_RE.match(stripped)
        if reference_match is not None:
            target = reference_match.group(2)
            if not _is_external_link_target(target):
                violations.append(
                    Violation(
                        path=rel_path,
                        line=idx,
                        rule="reference-link-target",
                        message="Reference-style links should be used only for external URLs.",
                    )
                )

        for inline_match in INLINE_LINK_RE.finditer(line_without_code):
            target = inline_match.group(2)
            if _is_external_link_target(target):
                violations.append(
                    Violation(
                        path=rel_path,
                        line=idx,
                        rule="external-link-style",
                        message="Use reference-style syntax for external links.",
                    )
                )

    non_empty_line_numbers = [
        idx for idx, value in enumerate(lines, start=1) if value.strip()
    ]
    if len(non_empty_line_numbers) < 2:
        violations.append(
            Violation(
                path=rel_path,
                line=1,
                rule="footer-required",
                message="Document must end with hr + '_End of ..._' footer.",
            )
        )
        return tuple(violations)

    footer_line_number = non_empty_line_numbers[-1]
    footer_hr_line_number = non_empty_line_numbers[-2]
    footer_line = lines[footer_line_number - 1].strip()
    footer_hr_line = lines[footer_hr_line_number - 1].strip()

    if footer_hr_line_number != footer_line_number - 1:
        violations.append(
            Violation(
                path=rel_path,
                line=footer_hr_line_number,
                rule="footer-spacing",
                message="Footer hr must be immediately above '_End of ..._' line.",
            )
        )

    if footer_hr_line != HR:
        violations.append(
            Violation(
                path=rel_path,
                line=footer_hr_line_number,
                rule="footer-hr",
                message="Footer must include a 72-dash hr immediately above '_End of ..._'.",
            )
        )

    footer_match = END_RE.match(footer_line)
    if footer_match is None:
        violations.append(
            Violation(
                path=rel_path,
                line=footer_line_number,
                rule="footer-end-line",
                message="Last non-empty line must match '_End of <title>_'.",
            )
        )
    else:
        footer_title = footer_match.group(1)
        if rel_path == README_PATH:
            expected_footer_title = "README"
        else:
            expected_footer_title = h1_title

        if footer_title != expected_footer_title:
            violations.append(
                Violation(
                    path=rel_path,
                    line=footer_line_number,
                    rule="footer-title-match",
                    message=(
                        "Footer title must match the h1 exactly "
                        f"(expected '{expected_footer_title}')."
                    ),
                )
            )

    return tuple(violations)


def main() -> int:
    """Run docs-convention checks and exit non-zero on violations."""
    args = _parse_args()
    _ = args.check  # Option is intentionally accepted for script parity.

    repo_root = Path(__file__).resolve().parents[1]
    targets = _discover_targets(repo_root, args.paths)

    violations: list[Violation] = []
    for target in targets:
        violations.extend(_validate_file(repo_root=repo_root, file_path=target))

    violations.sort(
        key=lambda item: (item.path.as_posix(), item.line, item.rule, item.message)
    )

    if violations:
        print("Documentation convention violations found:", file=sys.stderr)
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        return 1

    print(f"Documentation conventions passed for {len(targets)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
