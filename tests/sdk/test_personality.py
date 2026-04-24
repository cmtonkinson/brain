"""Unit tests for personality loading and system prompt rendering."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.sdk.personality import (
    PersonalityNotFoundError,
    _render_template,
    render_system_prompt_blocks,
    render_system_tool_hints,
)


# ---------------------------------------------------------------------------
# _render_template
# ---------------------------------------------------------------------------


def test_render_template_replaces_known_variables() -> None:
    """Known template variables should be substituted."""
    assert _render_template("Hello {{ name }}", name="World") == "Hello World"


def test_render_template_handles_whitespace_in_braces() -> None:
    """Whitespace inside double-brace placeholders should be tolerated."""
    assert _render_template("{{  name  }}", name="X") == "X"


def test_render_template_raises_on_unresolved_placeholders() -> None:
    """Unresolved placeholders should raise ValueError."""
    with pytest.raises(ValueError, match="unresolved"):
        _render_template("{{ name }} {{ age }}", name="X")


def test_render_template_returns_unchanged_when_no_placeholders() -> None:
    """Static strings with no placeholders should pass through unchanged."""
    assert _render_template("no vars here") == "no vars here"


# ---------------------------------------------------------------------------
# render_system_prompt_blocks
# ---------------------------------------------------------------------------


def test_render_system_prompt_blocks_returns_three_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System prompt should produce exactly 3 blocks with correct kinds."""
    import lib.sdk.personality as personality_mod

    personalities_dir = tmp_path / "personalities"
    personalities_dir.mkdir()
    (personalities_dir / "default.md").write_text("I am Brain.", encoding="utf-8")
    instructions_path = tmp_path / "instructions.txt"
    instructions_path.write_text("Follow these rules.", encoding="utf-8")

    monkeypatch.setattr(personality_mod, "_PERSONALITIES_DIR", personalities_dir)
    monkeypatch.setattr(
        personality_mod, "_SYSTEM_PROMPT_INSTRUCTIONS_PATH", instructions_path
    )

    blocks = render_system_prompt_blocks()

    assert len(blocks) == 3
    assert blocks[0].kind == "assistant_persona"
    assert blocks[0].text == "I am Brain."
    assert blocks[1].kind == "operator_profile"
    assert blocks[2].kind == "instructions"
    assert "Follow these rules." in blocks[2].text


def test_render_system_prompt_blocks_raises_for_missing_personality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requesting a non-existent personality should raise PersonalityNotFoundError."""
    import lib.sdk.personality as personality_mod

    personalities_dir = tmp_path / "personalities"
    personalities_dir.mkdir()
    monkeypatch.setattr(personality_mod, "_PERSONALITIES_DIR", personalities_dir)

    with pytest.raises(PersonalityNotFoundError, match="ghost"):
        render_system_prompt_blocks("ghost")


def test_render_system_prompt_blocks_includes_tool_hints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-empty tool hints should appear in the instructions block."""
    import lib.sdk.personality as personality_mod

    personalities_dir = tmp_path / "personalities"
    personalities_dir.mkdir()
    (personalities_dir / "default.md").write_text("Persona.", encoding="utf-8")
    instructions_path = tmp_path / "instructions.txt"
    instructions_path.write_text("Base instructions.", encoding="utf-8")

    monkeypatch.setattr(personality_mod, "_PERSONALITIES_DIR", personalities_dir)
    monkeypatch.setattr(
        personality_mod, "_SYSTEM_PROMPT_INSTRUCTIONS_PATH", instructions_path
    )

    blocks = render_system_prompt_blocks(
        system_tool_hints="<tool_hints>Vault: files</tool_hints>"
    )

    assert "<tool_hints>Vault: files</tool_hints>" in blocks[2].text


def test_render_system_prompt_blocks_includes_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """system_prompt_append should appear in the instructions block."""
    import lib.sdk.personality as personality_mod

    personalities_dir = tmp_path / "personalities"
    personalities_dir.mkdir()
    (personalities_dir / "default.md").write_text("Persona.", encoding="utf-8")
    instructions_path = tmp_path / "instructions.txt"
    instructions_path.write_text("Base.", encoding="utf-8")

    monkeypatch.setattr(personality_mod, "_PERSONALITIES_DIR", personalities_dir)
    monkeypatch.setattr(
        personality_mod, "_SYSTEM_PROMPT_INSTRUCTIONS_PATH", instructions_path
    )

    blocks = render_system_prompt_blocks(system_prompt_append="Extra appendix.")

    assert "Extra appendix." in blocks[2].text


# ---------------------------------------------------------------------------
# render_system_tool_hints
# ---------------------------------------------------------------------------


def test_render_system_tool_hints_returns_empty_for_no_hints() -> None:
    """Empty hint sequence should return empty string."""
    assert render_system_tool_hints(()) == ""


def test_render_system_tool_hints_skips_items_without_summary() -> None:
    """Hint objects with empty summary should be skipped."""
    hints = [
        SimpleNamespace(system_id="vault", label="Vault", summary=""),
    ]
    assert render_system_tool_hints(hints) == ""


def test_render_system_tool_hints_renders_label_and_summary() -> None:
    """Rendered output should contain the label and summary from each hint."""
    hints = [
        SimpleNamespace(
            system_id="service_vault_authority",
            label="Vault Authority",
            summary="Personal knowledge base.",
        ),
    ]
    result = render_system_tool_hints(hints)
    assert "Vault Authority" in result
    assert "Personal knowledge base." in result
    assert "<tool_hints>" in result
