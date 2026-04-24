"""Personality loading and system prompt rendering for Brain SDK."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Sequence

from lib.shared.language_model import InferenceSystemBlock

_PERSONALITIES_DIR = Path(__file__).parent / "personalities"
_SYSTEM_PROMPT_INSTRUCTIONS_PATH = (
    Path(__file__).parent / "system_prompt_instructions.txt"
)
_SYSTEM_TOOL_HINTS_TEMPLATE_PATH = (
    Path(__file__).parent / "system_tool_hints_template.txt"
)
_SYSTEM_TOOL_HINT_ITEM_TEMPLATE_PATH = (
    Path(__file__).parent / "system_tool_hint_item_template.txt"
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


def render_system_tool_hints(hints: Sequence[Any]) -> str:
    """Render compact tool-system hints from runtime-provided hint objects."""
    item_template = _SYSTEM_TOOL_HINT_ITEM_TEMPLATE_PATH.read_text(encoding="utf-8")
    items: list[str] = []
    for hint in hints:
        summary = str(getattr(hint, "summary", "")).strip()
        if summary == "":
            continue
        system_id = str(getattr(hint, "system_id", "")).strip()
        label = str(getattr(hint, "label", "")).strip() or system_id
        if label == "":
            continue
        items.append(
            _render_template(item_template, label=label, summary=summary).strip()
        )
    if len(items) == 0:
        return ""
    template = _SYSTEM_TOOL_HINTS_TEMPLATE_PATH.read_text(encoding="utf-8")
    return _render_template(template, tool_system_hint_items="\n".join(items))


def render_system_prompt_blocks(
    personality: str = "default",
    *,
    operator_profile: str = "Refer to me as 'boss'",
    system_tool_hints: str = "",
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
    combined_instructions = "\n".join(
        item
        for item in (instructions_text, system_tool_hints, system_prompt_append)
        if item != ""
    )
    return (
        InferenceSystemBlock(kind="assistant_persona", text=personality_text),
        InferenceSystemBlock(kind="operator_profile", text=operator_profile),
        InferenceSystemBlock(kind="instructions", text=combined_instructions),
    )
