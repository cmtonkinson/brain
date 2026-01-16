"""Skill composition API for nested invocation."""

from __future__ import annotations

from typing import Any, Protocol, TYPE_CHECKING

from .context import SkillContext
from .errors import SkillRuntimeError
from .registry import SkillRuntimeEntry
from .registry_schema import CallTargetKind, CallTargetRef

if TYPE_CHECKING:
    from .op_runtime import OpExecutionResult
    from .runtime import ExecutionResult


class SkillExecutor(Protocol):
    """Protocol for invoking skills via the runtime."""

    async def execute(
        self,
        name: str,
        inputs: dict[str, Any],
        context: SkillContext,
        version: str | None = None,
    ) -> "ExecutionResult":
        """Execute a skill by name."""
        ...


class OpExecutor(Protocol):
    """Protocol for invoking ops via the runtime."""

    async def execute(
        self,
        name: str,
        inputs: dict[str, Any],
        context: SkillContext,
        version: str | None = None,
    ) -> "OpExecutionResult":
        """Execute an op by name."""
        ...


class SkillComposer:
    """Enforce declared call targets for nested skill and op invocation."""

    def __init__(self, runtime: SkillExecutor, op_runtime: OpExecutor | None = None) -> None:
        """Initialize the composer with skill and op executors."""
        self._runtime = runtime
        self._op_runtime = op_runtime

    async def invoke(
        self,
        parent_skill: SkillRuntimeEntry,
        parent_context: SkillContext,
        name: str,
        inputs: dict[str, Any],
        version: str | None = None,
        *,
        target_kind: CallTargetKind = CallTargetKind.skill,
    ) -> "ExecutionResult" | "OpExecutionResult":
        """Invoke a declared call target on behalf of a logic skill."""
        _ensure_call_target_allowed(parent_skill, target_kind, name, version)
        if target_kind == CallTargetKind.skill:
            skill = self._runtime._registry.get_skill(name, version)
            child_context = parent_context.child(skill.definition.capabilities)
            return await self._runtime.execute(name, inputs, child_context, version=version)
        if self._op_runtime is None:
            raise SkillRuntimeError(
                "op_runtime_missing",
                "Op runtime is not configured for call targets.",
            )
        op_entry = self._op_runtime._registry.get_op(name, version)
        child_context = parent_context.child(op_entry.definition.capabilities)
        return await self._op_runtime.execute(name, inputs, child_context, version=version)


class SkillInvocation:
    """Bound invocation helper for logic skills."""

    def __init__(
        self,
        composer: SkillComposer,
        parent_skill: SkillRuntimeEntry,
        parent_context: SkillContext,
    ) -> None:
        """Initialize with a composer and bound parent context."""
        self._composer = composer
        self._parent_skill = parent_skill
        self._parent_context = parent_context

    async def invoke_skill(
        self,
        name: str,
        inputs: dict[str, Any],
        version: str | None = None,
    ) -> "ExecutionResult":
        """Invoke a declared downstream skill."""
        return await self._composer.invoke(
            self._parent_skill,
            self._parent_context,
            name,
            inputs,
            version=version,
            target_kind=CallTargetKind.skill,
        )

    async def invoke_op(
        self,
        name: str,
        inputs: dict[str, Any],
        version: str | None = None,
    ) -> "OpExecutionResult":
        """Invoke a declared downstream op."""
        return await self._composer.invoke(
            self._parent_skill,
            self._parent_context,
            name,
            inputs,
            version=version,
            target_kind=CallTargetKind.op,
        )


def _ensure_call_target_allowed(
    parent_skill: SkillRuntimeEntry,
    target_kind: CallTargetKind,
    name: str,
    version: str | None,
) -> None:
    """Validate that a call target is declared by the parent skill."""
    call_targets = parent_skill.definition.call_targets
    for target in call_targets:
        if target.kind != target_kind:
            continue
        if target.name != name:
            continue
        if version is None:
            return
        if target.version is None or target.version == version:
            return
    raise SkillRuntimeError(
        "call_target_not_allowed",
        f"Call target {target_kind.value}:{name}@{version or '*'} not declared.",
    )
