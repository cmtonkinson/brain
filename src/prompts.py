"""Prompt loading and rendering utilities."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a prompt by name from the prompts directory."""
    filename = name if Path(name).suffix else f"{name}.txt"
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, replacements: dict[str, object] | None = None) -> str:
    """Render a prompt with {placeholders} replaced by provided values."""
    text = load_prompt(name)
    if not replacements:
        return text
    try:
        return text.format_map({key: str(value) for key, value in replacements.items()})
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "unknown"
        raise ValueError(f"Missing prompt placeholder: {missing}") from exc
