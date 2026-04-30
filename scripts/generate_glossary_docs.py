"""Generate Markdown glossary docs from canonical YAML source."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

DOC_NAME = "Glossary"
HR = "------------------------------------------------------------------------"
DEFAULT_INPUT = "docs/meta/glossary.yaml"
DEFAULT_OUTPUT = "docs/glossary.md"
GENERATED_NOTE = (
    "*This document is generated from `docs/meta/glossary.yaml`. Do not edit by hand.*"
)


@dataclass(frozen=True)
class GlossaryTerm:
    """One glossary term and definition entry."""

    term: str
    definition: str
    note: str | None = None


def _title_case_term(term: str) -> str:
    """Return normalized title-cased display text for a glossary term.

    All-uppercase tokens (e.g. acronyms like ``SDK``, ``MCP``, ``API``) keep
    their original casing rather than being collapsed to ``Sdk``.
    """
    parts = term.split()
    rendered: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.isupper():
            rendered.append(part)
        else:
            rendered.append(part[:1].upper() + part[1:].lower())
    return " ".join(rendered)


def _normalize_definition_terms(*, definition: str, known_terms: list[str]) -> str:
    """Ensure known term references are title-cased and italicized in a definition.

    Backtick-quoted spans are protected from replacement so inline code
    like ``trace_id`` is never mangled by partial term matches.
    """
    # Temporarily replace backtick-quoted spans with placeholders.
    code_spans: list[str] = []

    def _shelter_code(match: re.Match[str]) -> str:
        code_spans.append(match.group(0))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    normalized = re.sub(r"`[^`]+`", _shelter_code, definition)

    for source_term in sorted(known_terms, key=len, reverse=True):
        display_term = _title_case_term(source_term)
        escaped = re.escape(source_term)

        pattern = re.compile(
            rf"(?<![A-Za-z0-9_])({escaped})(?![A-Za-z0-9_])",
            flags=re.IGNORECASE,
        )

        def _replace(match: re.Match[str], _dt: str = display_term) -> str:
            start = match.start()
            end = match.end()
            left_char = normalized[start - 1] if start > 0 else ""
            right_char = normalized[end] if end < len(normalized) else ""

            # If already italicized, just enforce title casing.
            if left_char == "*" and right_char == "*":
                return _dt
            return f"*{_dt}*"

        normalized = pattern.sub(_replace, normalized)

    # Restore backtick-quoted spans.
    for i, span in enumerate(code_spans):
        normalized = normalized.replace(f"\x00CODE{i}\x00", span)

    return normalized


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for glossary generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help="Path to glossary YAML input file.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Path to generated Markdown output file.",
    )
    return parser.parse_args()


def _load_glossary(path: Path) -> tuple[str, list[GlossaryTerm]]:
    """Load and validate glossary YAML data."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("glossary YAML root must be a mapping")

    title = str(raw.get("title", "")).strip()
    if not title:
        raise ValueError("glossary title is required")

    terms_raw = raw.get("terms")
    if not isinstance(terms_raw, list):
        raise ValueError("glossary terms must be a list")

    terms: list[GlossaryTerm] = []
    raw_terms: list[str] = []
    for item in terms_raw:
        if not isinstance(item, dict):
            raise ValueError("each glossary term entry must be a mapping")
        term = str(item.get("term", "")).strip()
        definition = str(item.get("definition", "")).strip()
        if not term:
            raise ValueError("glossary term is required")
        if not definition:
            raise ValueError(f"definition is required for term '{term}'")
        note_raw = item.get("note")
        note = str(note_raw).strip() if note_raw is not None else None
        raw_terms.append(term)
        terms.append(GlossaryTerm(term=term, definition=definition, note=note))

    normalized_terms = [
        GlossaryTerm(
            term=term.term,
            definition=_normalize_definition_terms(
                definition=term.definition, known_terms=raw_terms
            ),
            note=(
                _normalize_definition_terms(definition=term.note, known_terms=raw_terms)
                if term.note is not None
                else None
            ),
        )
        for term in terms
    ]

    normalized_terms.sort(key=lambda item: item.term.casefold())
    return title, normalized_terms


def _render_markdown(*, title: str, terms: list[GlossaryTerm]) -> str:
    """Render glossary markdown in deterministic bullet format."""
    lines = [f"# {DOC_NAME}", GENERATED_NOTE, "", HR, "## Terms"]
    for item in terms:
        line = f"* **{item.term} &mdash;** {item.definition}"
        if item.note is not None:
            line += f"\n  *(Note: {item.note})*"
        lines.append(line)
    lines.append("")
    lines.append("")
    lines.append(HR)
    lines.append(f"_End of {DOC_NAME}_")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Generate glossary markdown from canonical YAML file."""
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    input_path = (repo_root / args.input).resolve()
    output_path = (repo_root / args.output).resolve()

    try:
        title, terms = _load_glossary(input_path)
        markdown = _render_markdown(title=title, terms=terms)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to generate glossary docs: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
