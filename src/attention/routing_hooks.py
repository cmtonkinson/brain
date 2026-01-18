"""Helpers to bind attention routing hooks to the skill framework."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from attention.routing_envelope import (
    build_approval_envelope,
    build_op_invocation_envelope,
    build_skill_invocation_envelope,
)
from attention.router import AttentionRouter
from skills.approvals import ApprovalProposal
from skills.context import SkillContext
from skills.registry import OpRuntimeEntry, SkillRuntimeEntry

SkillRoutingHook = Callable[[SkillRuntimeEntry, SkillContext, dict[str, Any]], Awaitable[None]]
OpRoutingHook = Callable[[OpRuntimeEntry, SkillContext, dict[str, Any]], Awaitable[None]]
ApprovalRoutingHook = Callable[[ApprovalProposal, SkillContext], Awaitable[None]]


def build_skill_routing_hook(router: AttentionRouter) -> SkillRoutingHook:
    """Build a routing hook for skill invocations."""

    async def _hook(
        entry: SkillRuntimeEntry, context: SkillContext, inputs: dict[str, Any]
    ) -> None:
        envelope = build_skill_invocation_envelope(entry, context, inputs)
        await router.route_envelope(envelope)

    return _hook


def build_op_routing_hook(router: AttentionRouter) -> OpRoutingHook:
    """Build a routing hook for op invocations."""

    async def _hook(entry: OpRuntimeEntry, context: SkillContext, inputs: dict[str, Any]) -> None:
        envelope = build_op_invocation_envelope(entry, context, inputs)
        await router.route_envelope(envelope)

    return _hook


def build_approval_router(router: AttentionRouter) -> ApprovalRoutingHook:
    """Build a routing hook for approval proposals."""

    async def _hook(proposal: ApprovalProposal, context: SkillContext) -> None:
        envelope = build_approval_envelope(proposal, context)
        await router.route_envelope(envelope)

    return _hook
