"""Op execution runtime with validation and policy checks."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse
from datetime import datetime, timezone

from .context import SkillContext
from .approvals import (
    ApprovalDecision,
    ApprovalProposal,
    ApprovalRecorder,
    InMemoryApprovalRecorder,
    approval_denial_reason,
    approval_required,
    approval_token_reason_label,
    build_proposal,
    build_proposal_id,
)
from .op_audit import OpAuditLogger
from .policy import PolicyContext, PolicyEvaluator, build_policy_metadata
from .registry import OpRegistryLoader, OpRuntimeEntry
from .registry_schema import SkillStatus

logger = logging.getLogger(__name__)

DEFAULT_OP_FAILURE_CODE = "op_unexpected_error"
DEFAULT_OP_FAILURE_MESSAGE = "Op failed unexpectedly."


class OpRuntimeError(Exception):
    """Base exception for op runtime failures."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the runtime error with a code and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


class OpValidationError(OpRuntimeError):
    """Raised when schema validation fails."""

    pass


class OpPolicyError(OpRuntimeError):
    """Raised when policy evaluation denies execution."""

    pass


class OpExecutionError(OpRuntimeError):
    """Raised when an op adapter fails to execute."""

    pass


class OpAdapter(Protocol):
    """Protocol for op runtime adapters."""

    async def execute(
        self,
        op_entry: OpRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        """Execute an op and return its output payload."""
        ...


@dataclass(frozen=True)
class OpExecutionResult:
    """Return payload for successful op execution."""

    output: dict[str, Any]
    duration_ms: int


RoutingHook = Callable[[OpRuntimeEntry, SkillContext, dict[str, Any]], Awaitable[None]]
ApprovalRoutingHook = Callable[[ApprovalProposal, SkillContext], Awaitable[None]]


async def _noop_routing_hook(
    op_entry: OpRuntimeEntry, context: SkillContext, inputs: dict[str, Any]
) -> None:
    """Stub attention router hook for op invocations."""
    logger.info(
        "attention routing stub",
        extra={
            "op": op_entry.definition.name,
            "version": op_entry.definition.version,
            "actor": context.actor or "",
            "channel": context.channel or "",
        },
    )
    return None


async def _noop_approval_router(proposal: ApprovalProposal, context: SkillContext) -> None:
    """Stub attention router hook for approval proposals."""
    logger.info(
        "approval routing stub",
        extra={
            "proposal_id": proposal.proposal_id,
            "op": proposal.action_name,
            "version": proposal.action_version,
            "actor": context.actor or "",
            "channel": context.channel or "",
        },
    )
    return None


class OpRuntime:
    """Execute ops with schema validation, policy checks, and auditing."""

    def __init__(
        self,
        registry: OpRegistryLoader,
        policy: PolicyEvaluator,
        adapters: dict[str, OpAdapter],
        routing_hook: RoutingHook | None = None,
        approval_router: ApprovalRoutingHook | None = None,
        approval_recorder: ApprovalRecorder | None = None,
        audit_logger: OpAuditLogger | None = None,
    ) -> None:
        """Initialize the op runtime with registry, policy, and adapter bindings."""
        self._registry = registry
        self._policy = policy
        self._adapters = adapters
        self._routing_hook = routing_hook or _noop_routing_hook
        self._approval_router = approval_router or _noop_approval_router
        self._approval_recorder = approval_recorder or InMemoryApprovalRecorder()
        self._audit = audit_logger or OpAuditLogger()

    async def execute(
        self,
        name: str,
        inputs: dict[str, Any],
        context: SkillContext,
        version: str | None = None,
    ) -> OpExecutionResult:
        """Execute an op by name/version using the provided context."""
        op_entry = self._registry.get_op(name, version)
        return await self._execute_op(op_entry, inputs, context)

    async def _execute_op(
        self,
        op_entry: OpRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> OpExecutionResult:
        """Run an op end-to-end with validation, policy, and auditing."""
        start = time.time()
        if op_entry.status != SkillStatus.enabled:
            self._audit.record(
                op_entry,
                context,
                status="denied",
                duration_ms=None,
                inputs=inputs,
                error=f"op_{op_entry.status.value}",
            )
            raise OpPolicyError(
                "op_unavailable",
                f"Op {op_entry.definition.name} is {op_entry.status.value}.",
                {"status": op_entry.status.value},
            )
        try:
            self._validate_schema(inputs, op_entry.definition.inputs_schema, "inputs")
        except OpValidationError as exc:
            self._audit.record(
                op_entry,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
            )
            raise

        await self._routing_hook(op_entry, context, inputs)

        proposal_id = build_proposal_id(op_entry, context, inputs)
        policy_context = PolicyContext(
            actor=context.actor,
            channel=context.channel,
            allowed_capabilities=context.allowed_capabilities,
            max_autonomy=context.max_autonomy,
            confirmed=context.confirmed,
            proposal_id=proposal_id,
            approval_token=context.approval_token,
        )
        try:
            decision = self._policy.evaluate(op_entry, policy_context)
        except Exception as exc:
            logger.exception(
                "policy evaluation failed",
                extra={"op": op_entry.definition.name, "version": op_entry.definition.version},
            )
            metadata = build_policy_metadata(op_entry, policy_context)
            metadata["policy.error"] = str(exc)
            reasons = ["policy_error"]
            self._audit.record(
                op_entry,
                context,
                status="denied",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
                policy_reasons=reasons,
                policy_metadata=metadata,
            )
            raise OpPolicyError(
                "policy_error",
                "Op invocation denied due to policy evaluation error.",
                {"error": str(exc)},
            ) from exc
        if not decision.allowed:
            await self._handle_approval_denial(op_entry, context, inputs, decision)
            await self._record_approval_decision(op_entry, context, decision)
            self._audit.record(
                op_entry,
                context,
                status="denied",
                duration_ms=None,
                inputs=inputs,
                error="; ".join(decision.reasons),
                policy_reasons=decision.reasons,
                policy_metadata=decision.metadata,
            )
            raise OpPolicyError(
                "policy_denied",
                "Op invocation denied by policy.",
                {"reasons": decision.reasons},
            )
        await self._record_approval_decision(op_entry, context, decision)

        runtime_key = op_entry.definition.runtime.value
        adapter = self._adapters.get(runtime_key)
        if adapter is None:
            raise OpExecutionError(
                "adapter_missing",
                f"No adapter for runtime {runtime_key}.",
            )

        try:
            output = await adapter.execute(op_entry, inputs, context)
        except OpRuntimeError as exc:
            self._audit.record(
                op_entry,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
                policy_reasons=decision.reasons,
                policy_metadata=decision.metadata,
            )
            raise
        except Exception as exc:
            self._audit.record(
                op_entry,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
                policy_reasons=decision.reasons,
                policy_metadata=decision.metadata,
            )
            raise OpExecutionError(
                DEFAULT_OP_FAILURE_CODE,
                DEFAULT_OP_FAILURE_MESSAGE,
                {"error": str(exc)},
            ) from exc

        try:
            self._validate_schema(output, op_entry.definition.outputs_schema, "outputs")
        except OpValidationError as exc:
            self._audit.record(
                op_entry,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                outputs=output,
                error=str(exc),
                policy_reasons=decision.reasons,
                policy_metadata=decision.metadata,
            )
            raise
        duration_ms = int((time.time() - start) * 1000)
        self._audit.record(
            op_entry,
            context,
            status="success",
            duration_ms=duration_ms,
            inputs=inputs,
            outputs=output,
            policy_reasons=decision.reasons,
            policy_metadata=decision.metadata,
        )
        logger.info(
            "op execution",
            extra={
                "op": op_entry.definition.name,
                "version": op_entry.definition.version,
                "duration_ms": duration_ms,
                "status": "success",
            },
        )
        return OpExecutionResult(output=output, duration_ms=duration_ms)

    async def _handle_approval_denial(
        self,
        op_entry: OpRuntimeEntry,
        context: SkillContext,
        inputs: dict[str, Any],
        decision: Any,
    ) -> None:
        """Generate and route approval proposals for approval-gated denials."""
        if not approval_required(op_entry):
            return
        reason = approval_denial_reason(decision.reasons)
        if reason is None:
            return
        extra_reasons = [
            r
            for r in decision.reasons
            if r not in {"approval_required", "review_required"}
            and not r.startswith("approval_token_")
        ]
        if extra_reasons:
            return
        proposal = build_proposal(op_entry, context, inputs, reason)
        self._approval_recorder.record_proposal(proposal)
        await self._approval_router(proposal, context)

    async def _record_approval_decision(
        self,
        op_entry: OpRuntimeEntry,
        context: SkillContext,
        decision: Any,
    ) -> None:
        """Record approvals or token rejections tied to op execution."""
        if not approval_required(op_entry):
            return
        proposal_id = decision.metadata.get("policy.context.proposal_id", "")
        if not proposal_id or not context.actor:
            return
        token_valid = decision.metadata.get("policy.approval.token_valid") == "true"
        token_reason = decision.metadata.get("policy.approval.token_reason", "")
        token_status = decision.metadata.get("policy.approval.token_status", "")
        if token_valid or context.confirmed:
            reason = "approval_token" if token_valid else "confirmed"
            decision_record = ApprovalDecision(
                proposal_id=proposal_id,
                actor=context.actor,
                decision="approved",
                decided_at=datetime.now(timezone.utc).isoformat(),
                reason=reason,
                token_used=token_valid,
            )
            self._approval_recorder.record_decision(decision_record)
            return
        if any(reason.startswith("approval_token_") for reason in decision.reasons):
            label = token_status or approval_token_reason_label(token_reason)
            decision_record = ApprovalDecision(
                proposal_id=proposal_id,
                actor=context.actor,
                decision="expired" if label == "expired" else "rejected",
                decided_at=datetime.now(timezone.utc).isoformat(),
                reason=token_reason,
                token_used=True,
            )
            self._approval_recorder.record_decision(decision_record)

    def _validate_schema(self, payload: Any, schema: dict[str, Any], label: str) -> None:
        """Validate a payload against a constrained JSON Schema subset."""
        enum_values = schema.get("enum")
        if enum_values is not None:
            _validate_enum(payload, enum_values, label)

        schema_type = schema.get("type")
        if schema_type:
            if not _matches_type(payload, schema_type):
                raise OpValidationError(
                    "schema_type_mismatch",
                    f"{label} must be of type {schema_type}.",
                    {"expected": schema_type},
                )

        if schema_type == "object":
            required = schema.get("required", [])
            if not isinstance(required, list):
                raise OpValidationError(
                    "schema_required_invalid",
                    f"{label} required must be a list.",
                    {"field": label},
                )
            missing = [key for key in required if key not in payload]
            if missing:
                raise OpValidationError(
                    "schema_missing_required",
                    f"Missing required {label} fields: {missing}",
                    {"missing": missing},
                )
            properties = schema.get("properties", {})
            if properties and not isinstance(properties, dict):
                raise OpValidationError(
                    "schema_properties_invalid",
                    f"{label} properties must be an object.",
                    {"field": label},
                )
            additional = schema.get("additionalProperties")
            allow_additional = additional
            if allow_additional is None:
                allow_additional = False if properties else True
            unknown = [key for key in payload if key not in properties]
            if unknown:
                if allow_additional is True:
                    pass
                elif isinstance(allow_additional, dict):
                    for key in unknown:
                        self._validate_schema(payload[key], allow_additional, f"{label}.{key}")
                else:
                    logger.error("schema_unknown_field: %s unknown=%s", label, unknown)
                    raise OpValidationError(
                        "schema_unknown_field",
                        f"Unknown {label} fields: {unknown}",
                        {"unknown": unknown},
                    )
            for key, prop_schema in properties.items():
                if key not in payload:
                    continue
                self._validate_schema(payload[key], prop_schema, f"{label}.{key}")

        if schema_type == "array":
            _validate_array_constraints(payload, schema, label, self._validate_schema)
        if schema_type == "string" and "format" in schema:
            _validate_format(payload, schema["format"], label)
        if schema_type == "string":
            _validate_string_constraints(payload, schema, label)
        if schema_type in {"integer", "number"}:
            _validate_number_constraints(payload, schema, label)


def _matches_type(payload: Any, schema_type: str) -> bool:
    """Check whether a payload matches a JSON Schema primitive type."""
    if schema_type == "string":
        return isinstance(payload, str)
    if schema_type == "array":
        return isinstance(payload, list)
    if schema_type == "object":
        return isinstance(payload, dict)
    if schema_type == "integer":
        return isinstance(payload, int) and not isinstance(payload, bool)
    if schema_type == "number":
        return isinstance(payload, (int, float)) and not isinstance(payload, bool)
    if schema_type == "boolean":
        return isinstance(payload, bool)
    return True


def _validate_array_items(
    payload: Any,
    item_schema: dict[str, Any],
    label: str,
    key: str | None,
    validator: Callable[[Any, dict[str, Any], str], None],
) -> None:
    """Validate array items against their item schema."""
    if not isinstance(payload, list):
        raise OpValidationError(
            "schema_type_mismatch",
            f"{label} must be an array.",
            {"expected": "array"},
        )
    for idx, item in enumerate(payload):
        field_label = f"{label}[{idx}]" if key is None else f"{label}.{key}[{idx}]"
        validator(item, item_schema, field_label)


def _validate_format(value: Any, fmt: str, label: str) -> None:
    """Validate string formats for schema values."""
    if not isinstance(value, str):
        raise OpValidationError(
            "schema_format_type_mismatch",
            f"{label} must be a string for format {fmt}.",
            {"expected_format": fmt},
        )
    if fmt == "uri":
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            raise OpValidationError(
                "schema_format_invalid",
                f"{label} must be a valid URI.",
                {"format": fmt},
            )
    if fmt == "date-time":
        candidate = value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise OpValidationError(
                "schema_format_invalid",
                f"{label} must be a valid date-time.",
                {"format": fmt},
            ) from exc


def _validate_enum(value: Any, enum_values: list[Any], label: str) -> None:
    """Validate that a value is included in an enum list."""
    if value not in enum_values:
        raise OpValidationError(
            "schema_enum_mismatch",
            f"{label} must be one of {enum_values}.",
            {"enum": enum_values},
        )


def _validate_string_constraints(value: Any, schema: dict[str, Any], label: str) -> None:
    """Validate string length constraints."""
    if not isinstance(value, str):
        return
    min_length = schema.get("minLength")
    if min_length is not None and len(value) < min_length:
        raise OpValidationError(
            "schema_min_length",
            f"{label} must be at least {min_length} characters.",
            {"minLength": min_length},
        )
    max_length = schema.get("maxLength")
    if max_length is not None and len(value) > max_length:
        raise OpValidationError(
            "schema_max_length",
            f"{label} must be at most {max_length} characters.",
            {"maxLength": max_length},
        )


def _validate_number_constraints(value: Any, schema: dict[str, Any], label: str) -> None:
    """Validate numeric range constraints."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    minimum = schema.get("minimum")
    if minimum is not None and value < minimum:
        raise OpValidationError(
            "schema_minimum",
            f"{label} must be >= {minimum}.",
            {"minimum": minimum},
        )
    maximum = schema.get("maximum")
    if maximum is not None and value > maximum:
        raise OpValidationError(
            "schema_maximum",
            f"{label} must be <= {maximum}.",
            {"maximum": maximum},
        )


def _validate_array_constraints(
    payload: Any,
    schema: dict[str, Any],
    label: str,
    validator: Callable[[Any, dict[str, Any], str], None],
) -> None:
    """Validate array size and item schemas."""
    if not isinstance(payload, list):
        raise OpValidationError(
            "schema_type_mismatch",
            f"{label} must be an array.",
            {"expected": "array"},
        )
    min_items = schema.get("minItems")
    if min_items is not None and len(payload) < min_items:
        raise OpValidationError(
            "schema_min_items",
            f"{label} must include at least {min_items} items.",
            {"minItems": min_items},
        )
    max_items = schema.get("maxItems")
    if max_items is not None and len(payload) > max_items:
        raise OpValidationError(
            "schema_max_items",
            f"{label} must include at most {max_items} items.",
            {"maxItems": max_items},
        )
    if "items" in schema:
        _validate_array_items(payload, schema["items"], label, None, validator)
