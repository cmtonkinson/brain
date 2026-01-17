"""Seed skill tests for basic read/write behaviors."""

from pathlib import Path

import pytest

from skills.adapters.python_adapter import PythonSkillAdapter
from skills.services import SkillServices
from skills.errors import SkillPolicyError
from test.skills.harness import SkillTestHarness, DryRunResult
from test.skills.mocks.obsidian import MockObsidianClient
from test.skills.mocks.fixtures import SAMPLE_NOTES


@pytest.mark.asyncio
async def test_search_notes_skill():
    """Search returns expected note matches."""
    harness = SkillTestHarness(
        registry_path=Path("config/skill-registry.json"),
        capabilities_path=Path("config/capabilities.json"),
    )
    obsidian = MockObsidianClient(notes=dict(SAMPLE_NOTES))

    result = await harness.run(
        "search_notes",
        {"query": "Alpha"},
        adapters={"python": PythonSkillAdapter()},
        allow_capabilities={"obsidian.read", "vault.search"},
        services=SkillServices(obsidian=obsidian),
    )

    assert "Alpha" in " ".join(result.output["results"])


@pytest.mark.asyncio
async def test_create_note_dry_run():
    """Dry-run create_note does not write to Obsidian."""
    harness = SkillTestHarness(
        registry_path=Path("config/skill-registry.json"),
        capabilities_path=Path("config/capabilities.json"),
    )
    obsidian = MockObsidianClient(notes={})

    result = await harness.run(
        "create_note",
        {"path": "Notes/New.md", "content": "Hello"},
        adapters={"python": PythonSkillAdapter()},
        allow_capabilities={"obsidian.write"},
        services=SkillServices(obsidian=obsidian),
        dry_run=True,
    )

    assert isinstance(result, DryRunResult)
    assert result.dry_run is True
    assert "obsidian.write" in result.side_effects
    assert "Notes/New.md" not in obsidian.notes


@pytest.mark.asyncio
async def test_create_note_requires_write_capability():
    """Create note is denied without write capability."""
    harness = SkillTestHarness(
        registry_path=Path("config/skill-registry.json"),
        capabilities_path=Path("config/capabilities.json"),
    )
    obsidian = MockObsidianClient(notes={})

    with pytest.raises(SkillPolicyError):
        await harness.run(
            "create_note",
            {"path": "Notes/Denied.md", "content": "Nope"},
            adapters={"python": PythonSkillAdapter()},
            allow_capabilities=set(),
            services=SkillServices(obsidian=obsidian),
        )
