"""Personality loading and system prompt rendering for Brain SDK."""

from __future__ import annotations

from pathlib import Path
import re

from packages.brain_shared.language_model import InferenceSystemBlock

_PERSONALITIES_DIR = Path(__file__).parent / "personalities"
_SYSTEM_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "system_prompt_template.txt"
_SYSTEM_PROMPT_INSTRUCTIONS_PATH = (
    Path(__file__).parent / "system_prompt_instructions.txt"
)
_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class PersonalityNotFoundError(Exception):
    """Raised when the requested personality file does not exist."""


def _render_template(template: str, /, **values: str) -> str:
    """Render one double-brace template and reject unresolved placeholders."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return values[key]

    rendered = _TEMPLATE_VAR_RE.sub(_replace, template)
    unresolved = _TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(
            f"unresolved personality template placeholders: {', '.join(sorted(unresolved))}"
        )
    return rendered


def render_system_prompt(
    personality: str = "default",
    *,
    operator_profile: str = "Refer to me as 'boss'",
    system_prompt_append: str = "",
) -> str:
    """Load one personality and render the system prompt template.

    Raises PersonalityNotFoundError when the named personality file is missing.
    """
    personality_path = _PERSONALITIES_DIR / f"{personality}.md"
    if not personality_path.exists():
        raise PersonalityNotFoundError(
            f"personality '{personality}' not found at {personality_path}"
        )
    template = _SYSTEM_PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    blocks = render_system_prompt_blocks(
        personality,
        operator_profile=operator_profile,
        system_prompt_append=system_prompt_append,
    )
    return _render_template(
        template,
        personality=blocks[0].text,
        operator_profile=blocks[1].text,
        system_prompt_instructions=blocks[2].text,
        system_prompt_append="",
    )


def render_system_prompt_blocks(
    personality: str = "default",
    *,
    operator_profile: str = "Refer to me as 'boss'",
    system_prompt_append: str = "",
) -> tuple[InferenceSystemBlock, ...]:
    """Load one personality and return canonical system blocks for inference."""
    personality_path = _PERSONALITIES_DIR / f"{personality}.md"
    if not personality_path.exists():
        raise PersonalityNotFoundError(
            f"personality '{personality}' not found at {personality_path}"
        )
    personality_text = personality_path.read_text(encoding="utf-8")
    instructions_text = _SYSTEM_PROMPT_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    combined_instructions = instructions_text
    if system_prompt_append != "":
        combined_instructions = f"{instructions_text}\n{system_prompt_append}"
    return (
        InferenceSystemBlock(kind="assistant_persona", text=personality_text),
        InferenceSystemBlock(kind="operator_profile", text=operator_profile),
        InferenceSystemBlock(kind="instructions", text=combined_instructions),
    )
