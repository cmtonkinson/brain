"""Skill execution runtime with validation and policy checks."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse

from .audit import AuditLogger
from .context import SkillContext
from .policy import PolicyContext, PolicyEvaluator
from .registry import SkillRegistryLoader, SkillRuntimeEntry
from .registry_schema import SkillStatus

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_CODE = "skill_unexpected_error"
DEFAULT_FAILURE_MESSAGE = "Skill failed unexpectedly."


class SkillRuntimeError(Exception):
    """Base exception for skill runtime failures."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the runtime error with a code and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


class SkillValidationError(SkillRuntimeError):
    """Raised when schema validation fails."""

    pass


class SkillPolicyError(SkillRuntimeError):
    """Raised when policy evaluation denies execution."""

    pass


class SkillExecutionError(SkillRuntimeError):
    """Raised when a skill adapter fails to execute."""

    pass


class SkillAdapter(Protocol):
    """Protocol for skill runtime adapters."""

    async def execute(
        self,
        skill: SkillRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        """Execute a skill and return its output payload."""
        ...


@dataclass(frozen=True)
class ExecutionResult:
    """Return payload for successful skill execution."""

    output: dict[str, Any]
    duration_ms: int


RoutingHook = Callable[[SkillRuntimeEntry, SkillContext, dict[str, Any]], Awaitable[None]]


async def _noop_routing_hook(
    skill: SkillRuntimeEntry, context: SkillContext, inputs: dict[str, Any]
) -> None:
    """Stub attention router hook for skill invocations."""
    logger.info(
        "attention routing stub",
        extra={
            "skill": skill.definition.name,
            "version": skill.definition.version,
            "actor": context.actor or "",
            "channel": context.channel or "",
        },
    )
    return None


class SkillRuntime:
    """Execute skills with schema validation, policy checks, and auditing."""

    def __init__(
        self,
        registry: SkillRegistryLoader,
        policy: PolicyEvaluator,
        adapters: dict[str, SkillAdapter],
        routing_hook: RoutingHook | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        """Initialize the runtime with registry, policy, and adapter bindings."""
        self._registry = registry
        self._policy = policy
        self._adapters = adapters
        self._routing_hook = routing_hook or _noop_routing_hook
        self._audit = audit_logger or AuditLogger()

    async def execute(
        self,
        name: str,
        inputs: dict[str, Any],
        context: SkillContext,
        version: str | None = None,
    ) -> ExecutionResult:
        """Execute a skill by name/version using the provided context."""
        skill = self._registry.get_skill(name, version)
        return await self._execute_skill(skill, inputs, context)

    async def _execute_skill(
        self,
        skill: SkillRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> ExecutionResult:
        """Run a skill end-to-end with validation, policy, and auditing."""
        start = time.time()
        if skill.status != SkillStatus.enabled:
            self._audit.record(
                skill,
                context,
                status="denied",
                duration_ms=None,
                inputs=inputs,
                error=f"skill_{skill.status.value}",
            )
            raise SkillPolicyError(
                "skill_unavailable",
                f"Skill {skill.definition.name} is {skill.status.value}.",
                {"status": skill.status.value},
            )
        try:
            self._validate_schema(inputs, skill.definition.inputs_schema, "inputs")
        except SkillValidationError as exc:
            self._audit.record(
                skill,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
            )
            raise

        await self._routing_hook(skill, context, inputs)

        policy_context = PolicyContext(
            actor=context.actor,
            channel=context.channel,
            allowed_capabilities=context.allowed_capabilities,
            max_autonomy=context.max_autonomy,
            confirmed=context.confirmed,
        )
        decision = self._policy.evaluate(skill, policy_context)
        if not decision.allowed:
            self._audit.record(
                skill,
                context,
                status="denied",
                duration_ms=None,
                inputs=inputs,
                error="; ".join(decision.reasons),
            )
            raise SkillPolicyError(
                "policy_denied",
                "Skill invocation denied by policy.",
                {"reasons": decision.reasons},
            )

        runtime_key = skill.definition.entrypoint.runtime.value
        adapter = self._adapters.get(runtime_key)
        if adapter is None:
            raise SkillExecutionError(
                "adapter_missing",
                f"No adapter for runtime {runtime_key}.",
            )

        try:
            output = await adapter.execute(skill, inputs, context)
        except SkillRuntimeError as exc:
            self._audit.record(
                skill,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
            )
            raise
        except Exception as exc:
            self._audit.record(
                skill,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                error=str(exc),
            )
            raise SkillExecutionError(
                DEFAULT_FAILURE_CODE,
                DEFAULT_FAILURE_MESSAGE,
                {"error": str(exc)},
            ) from exc

        try:
            self._validate_schema(output, skill.definition.outputs_schema, "outputs")
        except SkillValidationError as exc:
            self._audit.record(
                skill,
                context,
                status="failed",
                duration_ms=None,
                inputs=inputs,
                outputs=output,
                error=str(exc),
            )
            raise
        duration_ms = int((time.time() - start) * 1000)
        self._audit.record(
            skill,
            context,
            status="success",
            duration_ms=duration_ms,
            inputs=inputs,
            outputs=output,
        )
        logger.info(
            "skill execution",
            extra={
                "skill": skill.definition.name,
                "version": skill.definition.version,
                "duration_ms": duration_ms,
                "status": "success",
            },
        )
        return ExecutionResult(output=output, duration_ms=duration_ms)

    def _validate_schema(self, payload: Any, schema: dict[str, Any], label: str) -> None:
        """Validate a payload against a constrained JSON Schema subset."""
        enum_values = schema.get("enum")
        if enum_values is not None:
            _validate_enum(payload, enum_values, label)

        schema_type = schema.get("type")
        if schema_type:
            if not _matches_type(payload, schema_type):
                raise SkillValidationError(
                    "schema_type_mismatch",
                    f"{label} must be of type {schema_type}.",
                    {"expected": schema_type},
                )

        if schema_type == "object":
            required = schema.get("required", [])
            if not isinstance(required, list):
                raise SkillValidationError(
                    "schema_required_invalid",
                    f"{label} required must be a list.",
                    {"field": label},
                )
            missing = [key for key in required if key not in payload]
            if missing:
                raise SkillValidationError(
                    "schema_missing_required",
                    f"Missing required {label} fields: {missing}",
                    {"missing": missing},
                )
            properties = schema.get("properties", {})
            if properties and not isinstance(properties, dict):
                raise SkillValidationError(
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
                    raise SkillValidationError(
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
        raise SkillValidationError(
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
        raise SkillValidationError(
            "schema_format_type_mismatch",
            f"{label} must be a string for format {fmt}.",
            {"expected_format": fmt},
        )
    if fmt == "uri":
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            raise SkillValidationError(
                "schema_format_invalid",
                f"{label} must be a valid URI.",
                {"format": fmt},
            )
    if fmt == "date-time":
        candidate = value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise SkillValidationError(
                "schema_format_invalid",
                f"{label} must be a valid date-time.",
                {"format": fmt},
            ) from exc


def _validate_enum(value: Any, enum_values: list[Any], label: str) -> None:
    """Validate that a value is included in an enum list."""
    if value not in enum_values:
        raise SkillValidationError(
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
        raise SkillValidationError(
            "schema_min_length",
            f"{label} must be at least {min_length} characters.",
            {"minLength": min_length},
        )
    max_length = schema.get("maxLength")
    if max_length is not None and len(value) > max_length:
        raise SkillValidationError(
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
        raise SkillValidationError(
            "schema_minimum",
            f"{label} must be >= {minimum}.",
            {"minimum": minimum},
        )
    maximum = schema.get("maximum")
    if maximum is not None and value > maximum:
        raise SkillValidationError(
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
        raise SkillValidationError(
            "schema_type_mismatch",
            f"{label} must be an array.",
            {"expected": "array"},
        )
    min_items = schema.get("minItems")
    if min_items is not None and len(payload) < min_items:
        raise SkillValidationError(
            "schema_min_items",
            f"{label} must include at least {min_items} items.",
            {"minItems": min_items},
        )
    max_items = schema.get("maxItems")
    if max_items is not None and len(payload) > max_items:
        raise SkillValidationError(
            "schema_max_items",
            f"{label} must include at most {max_items} items.",
            {"maxItems": max_items},
        )
    if "items" in schema:
        _validate_array_items(payload, schema["items"], label, None, validator)
