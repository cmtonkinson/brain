"""Unit tests for default skill policy evaluation."""

from skills.policy import DefaultPolicy, PolicyContext
from skills.registry import SkillRuntimeEntry, ActorPolicy
from skills.registry_schema import (
    AutonomyLevel,
    CallTargetKind,
    CallTargetRef,
    Entrypoint,
    EntrypointRuntime,
    LogicSkillDefinition,
    RateLimit,
    SkillKind,
    SkillStatus,
)


def _make_skill(capabilities, autonomy=AutonomyLevel.L1, rate_limit=None, policy_tags=None, actors=None):
    """Build a SkillRuntimeEntry for policy evaluation tests."""
    definition = LogicSkillDefinition(
        name="search_notes",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Search notes",
        kind=SkillKind.logic,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=capabilities,
        side_effects=[],
        autonomy=autonomy,
        policy_tags=policy_tags or [],
        entrypoint=Entrypoint(runtime=EntrypointRuntime.python, module="x", handler="run"),
        call_targets=[CallTargetRef(kind=CallTargetKind.op, name="dummy_op", version="1.0.0")],
        failure_modes=[
            {
                "code": "skill_unexpected_error",
                "description": "Unexpected skill failure.",
                "retryable": False,
            }
        ],
    )
    return SkillRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=autonomy,
        rate_limit=rate_limit,
        channels=None,
        actors=actors,
    )


def test_policy_denies_missing_capabilities():
    """Ensure missing capabilities deny policy evaluation."""
    policy = DefaultPolicy()
    skill = _make_skill(["obsidian.read", "vault.search"])
    context = PolicyContext(allowed_capabilities={"obsidian.read"})

    decision = policy.evaluate(skill, context)

    assert not decision.allowed
    assert any("capability_not_allowed" in reason for reason in decision.reasons)


def test_policy_denies_autonomy_exceeding_limit():
    """Ensure autonomy limits are enforced by policy."""
    policy = DefaultPolicy()
    skill = _make_skill(["obsidian.read"], autonomy=AutonomyLevel.L2)
    context = PolicyContext(allowed_capabilities={"obsidian.read"}, max_autonomy=AutonomyLevel.L1)

    decision = policy.evaluate(skill, context)

    assert not decision.allowed
    assert "autonomy_exceeds_limit" in decision.reasons


def test_policy_enforces_rate_limits():
    """Ensure rate limiting blocks excess invocations."""
    policy = DefaultPolicy()
    skill = _make_skill(["obsidian.read"], rate_limit=RateLimit(max_per_minute=1))
    context = PolicyContext(allowed_capabilities={"obsidian.read"}, confirmed=True)

    first = policy.evaluate(skill, context)
    second = policy.evaluate(skill, context)

    assert first.allowed
    assert not second.allowed
    assert "rate_limit_exceeded" in second.reasons


def test_policy_requires_review_tag():
    """Ensure review-required tags block unconfirmed execution."""
    policy = DefaultPolicy()
    skill = _make_skill(["obsidian.read"], policy_tags=["requires_review"])
    context = PolicyContext(allowed_capabilities={"obsidian.read"})

    decision = policy.evaluate(skill, context)

    assert not decision.allowed
    assert "review_required" in decision.reasons


def test_policy_allows_confirmed_review_tag():
    """Ensure confirmed review tags permit execution."""
    policy = DefaultPolicy()
    skill = _make_skill(["obsidian.read"], policy_tags=["requires_review"])
    context = PolicyContext(allowed_capabilities={"obsidian.read"}, confirmed=True)

    decision = policy.evaluate(skill, context)

    assert decision.allowed


def test_policy_denies_actor_override():
    """Ensure actor allowlists block disallowed actors."""
    policy = DefaultPolicy()
    skill = _make_skill(
        ["obsidian.read"],
        actors=ActorPolicy(allow={"brain"}, deny=set()),
    )
    context = PolicyContext(allowed_capabilities={"obsidian.read"}, actor="user")

    decision = policy.evaluate(skill, context)

    assert not decision.allowed
    assert "actor_not_allowed" in decision.reasons
