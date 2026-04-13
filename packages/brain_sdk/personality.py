"""Personality loading and system prompt rendering for Brain SDK."""

from __future__ import annotations

from pathlib import Path
import re

_PERSONALITIES_DIR = Path(__file__).parent / "personalities"
_TEMPLATE_PATH = _PERSONALITIES_DIR / "_template.txt"
_TEMPLATE_VAR_RE = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")


class PersonalityNotFoundError(Exception):
    """Raised when the requested personality file does not exist."""


def _render_template(template: str, /, **values: str) -> str:
    """Render one double-brace template and reject unresolved placeholders."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    unresolved = _TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(
            f"unresolved personality template placeholders: {', '.join(sorted(unresolved))}"
        )
    return rendered


def render_system_prompt(personality: str = "default") -> str:
    """Load one personality and render the system prompt template.

    Raises PersonalityNotFoundError when the named personality file is missing.
    """
    personality_path = _PERSONALITIES_DIR / f"{personality}.md"
    if not personality_path.exists():
        raise PersonalityNotFoundError(
            f"personality '{personality}' not found at {personality_path}"
        )
    identity = personality_path.read_text(encoding="utf-8").strip()
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _render_template(template, identity=identity)
