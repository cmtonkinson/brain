"""Unit tests for skill context behavior."""

from skills.context import SkillContext


def test_child_context_cannot_escalate_capabilities():
    """Child contexts cannot gain new capabilities."""
    parent = SkillContext(allowed_capabilities={"obsidian.read", "vault.search"})

    child = parent.child({"obsidian.read", "obsidian.write"})

    assert child.allowed_capabilities == {"obsidian.read"}
    assert child.parent_invocation_id == parent.invocation_id
    assert child.trace_id == parent.trace_id
