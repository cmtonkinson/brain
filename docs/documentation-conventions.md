# Documentation Conventions
This document describes the structure & format rules for Markdown documents
within this project.

Yes, this is a meta doc about docs &mdash; Yo Dawg.

------------------------------------------------------------------------
## Document Structure
- **h1 reserved for doc title** — every doc begins with a single `# Title` on
  line 1. No other h1s appear anywhere in the document.
- **Intro paragraph follows the h1** — a brief sentence or two describing what
  the document covers. No blank line between the h1 and the intro paragraph.
- **Glossary note follows the intro** — where applicable, add a blockquote after
  the intro paragraph:
  `> Check the [Glossary] for key terms such as _X_, _Y_, et cetera.`
- **Footer** — every doc ends with a 72-dash hr followed by `_End of <title>_`
  where `<title>` matches the h1 text exactly.

------------------------------------------------------------------------
## Headings
- h2s are the primary section headings; they are **not numbered** (no `1)`,
  `2)`, etc.).
- No explicit "Purpose" heading — fold purpose/intro text into the opening
  paragraph under the h1.
- **No blank line under any heading** — the first content line follows
  immediately.

------------------------------------------------------------------------
## Horizontal Rules
- Use exactly 72 dashes: `------------------------------------------------------------------------`
- Never use short `---` rules.
- hrs appear **only** in two places:
  1. Directly above an h2.
  2. In the footer (above `_End of ..._`).
- **No blank line between an hr and the heading or footer text below it.**

------------------------------------------------------------------------
## Inline Formatting
- Use `_underscores_` for italics, not `*asterisks*`.
- Use `-` for unordered list items, not `*`.
- Backtick file names, paths, class names, method names, constants, and other
  code references (e.g., `EnvelopeMeta`, `services/state/`, `trace_id`).
- Trail directory references with `/` (e.g., `services/`, `docs/`).
- Italicize defined Glossary terms on at least first/significant use in a
  document (e.g., _Service_, _Resource_, _Layer_).

------------------------------------------------------------------------
## Links
- Use inline link syntax `[text](target)`. Unfortunately, Obsidian does not
  correctly navigate reference-style links to internal documents.
- Use reference-style links for external references (e.g. `[text]` inline, with
  an alphabetized collection of `[text]: uri`

------------------------------------------------------------------------
## Generated Docs
- Generated documentation (e.g. `docs/glossary.md`, managed by `make docs`)
  should also adhere to these rules.

------------------------------------------------------------------------
## Exceptions
- `README.md` carries a single exception to these rules: it uses the project
  title as its h1, rather than document name.

------------------------------------------------------------------------
_End of Documentation Conventions_
