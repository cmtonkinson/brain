"""Concrete Relay inbound service implementation."""

from __future__ import annotations

import json
import re
import shlex
import time
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError

from lib.sdk.client import BrainClient
from lib.sdk.meta import MetaOverrides
from lib.shared.config import ApprovalResponseSettings
from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    new_meta,
    success,
    validate_meta,
)
from lib.shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    dependency_error,
    internal_error,
    validation_error,
)
from lib.shared.inbound_adapter import (
    InboundAdapterDependencyError,
    InboundAdapterInternalError,
    InboundCallbackRegistrar,
    InboundCallbackResult,
)
from lib.shared.inbound_message import InboundMessage
from lib.shared.logging import get_logger, public_api_instrumented
from lib.shared.phone_number import normalize_e164
from services.effect.relay._outbound.service import RelayOutboundService
from services.effect.relay._inbound.component import SERVICE_COMPONENT_ID
from services.effect.relay._shared import validation_error_from_pydantic
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)
from services.effect.relay._inbound.domain import (
    HealthStatus,
    IngestResult,
    RegisterInboundCallbacksResult,
)
from services.effect.relay._inbound.service import RelayInboundService
from services.effect.relay._inbound.validation import (
    IngestInboundMessageRequest,
    PollOperatorInstructionRequest,
)
from services.state.cache.service import CacheService
from services.reason.recall.service import (
    ConversationalMemoryContext,
    InboundInstructionRecord,
    RecallService,
)

_LOGGER = get_logger(__name__)
_POLL_INTERVAL_SECONDS = 0.25
_NAMED_ARG_RE = re.compile(r"--([a-zA-Z][a-zA-Z0-9_-]*)(?:[ =](\S+))?")
_SLASH_OUTPUT_MODEL = "inbound-slash-command"
_SLASH_OUTPUT_PROVIDER = "brain-core"
_SLASH_OUTPUT_REASONING_LEVEL = "system"


def _parse_slash_args(
    args_text: str, input_schema: dict[str, Any] | None
) -> dict[str, Any]:
    """Parse named slash-command arguments into a typed input payload.

    Accepted shapes:

    * ``--key value`` and ``--key=value`` (with or without ``=``)
    * ``--key "value with spaces"`` and ``--key='quoted'`` (single or double
      quotes; surrounding quotes are stripped)
    * ``--flag`` with no following value (boolean true)

    Values are coerced against ``input_schema`` so a literal like ``"1800"``
    arrives at the call target as ``int(1800)`` for an integer-typed field.
    A coercion failure leaves the raw string in place; downstream validation
    will surface a useful error.

    When no ``--`` flags are present, falls back to the
    single-string-property positional shortcut.
    """
    if not args_text.strip():
        return {}
    try:
        tokens = shlex.split(args_text)
    except ValueError:
        # Unbalanced quotes; leave raw text alone and let the positional
        # shortcut deal with it.
        tokens = []

    properties = _properties_of(input_schema)
    result: dict[str, Any] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("--"):
            i += 1
            continue
        body = token[2:]
        if "=" in body:
            raw_key, raw_value = body.split("=", 1)
            value: Any = raw_value
        else:
            raw_key = body
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                value = tokens[i + 1]
                i += 1
            else:
                value = True
        key = raw_key.replace("-", "_")
        result[key] = _coerce_to_schema(value, properties.get(key))
        i += 1

    if result:
        return result
    positional_field = _single_string_input_field(input_schema)
    if positional_field is not None:
        return {positional_field: args_text.strip()}
    return result


def _properties_of(input_schema: dict[str, Any] | None) -> dict[str, Any]:
    """Return the ``properties`` dict from a canonical JSON Schema, or empty."""
    if not isinstance(input_schema, dict):
        return {}
    properties = input_schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _coerce_to_schema(value: Any, field_schema: Any) -> Any:
    """Coerce one parsed slash value to the type declared in its schema."""
    if value is True or value is False or value is None:
        return value
    if not isinstance(field_schema, dict):
        return value
    schema_type = field_schema.get("type")
    if isinstance(value, str):
        if schema_type == "integer" or (
            isinstance(schema_type, list) and "integer" in schema_type
        ):
            try:
                return int(value)
            except ValueError:
                return value
        if schema_type == "number" or (
            isinstance(schema_type, list) and "number" in schema_type
        ):
            try:
                return float(value)
            except ValueError:
                return value
        if schema_type == "boolean" or (
            isinstance(schema_type, list) and "boolean" in schema_type
        ):
            lower = value.lower()
            if lower in {"true", "1", "yes"}:
                return True
            if lower in {"false", "0", "no"}:
                return False
            return value
    return value


def _single_string_input_field(input_schema: dict[str, Any] | None) -> str | None:
    """Return the unambiguous string field for positional slash args.

    Two patterns qualify:
    * exactly one required property of string type (siblings may be optional);
    * no required properties and exactly one string-typed property overall.

    Returns ``None`` when the candidate is ambiguous or no property is a
    string type.
    """
    if not isinstance(input_schema, dict):
        return None
    properties = input_schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return None
    required = input_schema.get("required") or []
    if not isinstance(required, list):
        return None

    candidate: str | None = None
    if len(required) == 1:
        if isinstance(required[0], str):
            candidate = required[0]
    elif len(required) == 0:
        string_props = [
            name
            for name, prop in properties.items()
            if isinstance(name, str) and _has_string_type(prop)
        ]
        if len(string_props) == 1:
            candidate = string_props[0]

    if candidate is None:
        return None
    schema = properties.get(candidate)
    if not isinstance(schema, dict) or not _has_string_type(schema):
        return None
    return candidate


def _has_string_type(schema: Any) -> bool:
    """Return True when one JSON Schema fragment admits the string type."""
    if not isinstance(schema, dict):
        return False
    schema_type = schema.get("type")
    if schema_type == "string":
        return True
    if isinstance(schema_type, list) and "string" in schema_type:
        return True
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any(
        isinstance(item, dict) and item.get("type") == "string" for item in any_of
    ):
        return True
    return False


def _render_slash_output(output: Any, simple_output_path: str | None) -> str:
    """Format op output for delivery to the operator."""
    if output is None:
        return "Done."
    if isinstance(output, str):
        return output
    if simple_output_path:
        val: Any = output
        for part in simple_output_path.split("."):
            val = val.get(part) if isinstance(val, dict) else None
        return str(val) if val is not None else json.dumps(output, indent=2)
    return json.dumps(output, indent=2)


def _estimate_token_count(text: str) -> int:
    """Return a bounded rough token count for Recall metadata."""
    return max(1, (len(text) + 3) // 4)


def _inbound_instruction_record(message: InboundMessage) -> InboundInstructionRecord:
    """Map Relay's normalized inbound DTO into Recall's turn metadata DTO."""
    reaction_target = message.reaction.target if message.reaction is not None else None
    return InboundInstructionRecord(
        sender_e164=message.sender.e164,
        message_text=message.message_text,
        timestamp_ms=message.timestamp_ms,
        source_device=message.source_device,
        source=message.channel,
        group_id=None if message.thread is None else message.thread.id,
        quote_target_timestamp_ms=(
            None if message.reply_to is None else message.reply_to.timestamp_ms
        ),
        reaction_target_timestamp_ms=(
            None if reaction_target is None else reaction_target.timestamp_ms
        ),
        reaction_emoji=None if message.reaction is None else message.reaction.text,
        approval_intent=None if message.approval is None else message.approval.intent,
        reply_to_proposal_token=message.reply_to_proposal_token or None,
        reaction_to_proposal_token=message.reaction_to_proposal_token or None,
    )


class DefaultRelayInboundService(RelayInboundService):
    """Relay inbound implementation for normalized operator messages."""

    def __init__(
        self,
        *,
        settings: RelayInboundServiceSettings,
        identity: RelayInboundIdentitySettings,
        inbound_adapters: Sequence[InboundCallbackRegistrar],
        cache_service: CacheService,
        outbound_service: RelayOutboundService | None = None,
        recall_service: RecallService | None = None,
        approval_response_settings: ApprovalResponseSettings | None = None,
        brain_client: BrainClient | None = None,
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._inbound_adapters = tuple(inbound_adapters)
        self._cache_service = cache_service
        self._outbound_service = outbound_service
        self._recall_service = recall_service
        self._approval_response_settings = (
            approval_response_settings
            if approval_response_settings is not None
            else ApprovalResponseSettings()
        )
        self._brain_client = brain_client
        self._operator_e164 = normalize_e164(
            raw=identity.operator_contact_e164,
            default_dial_code=identity.default_dial_code,
        )

    def _handle_slash_command(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> Envelope[IngestResult]:
        """Resolve and invoke one slash command inline; route output via ARS."""
        if message.slash_command is None:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "slash command is required", code=codes.INVALID_ARGUMENT
                    )
                ],
            )
        command_name = message.slash_command.name
        args_text = message.slash_command.args_text
        command_text = f"/{command_name}"
        if args_text.strip() != "":
            command_text = f"{command_text} {args_text.strip()}"

        if self._brain_client is None:
            output = f"/{command_name}: slash commands not available (brain_client not configured)."
        else:
            descriptor = self._brain_client.resolve_slash_command(name=command_name)
            if descriptor is None:
                output = f"Unknown command: /{command_name}. Type /help for available commands."
            else:
                input_payload = _parse_slash_args(args_text, descriptor.input_schema)
                try:
                    result = self._brain_client.invoke_op(
                        op_id=descriptor.op_id,
                        input_payload=input_payload,
                        actor="operator",
                        channel=message.channel,
                        message_text=command_text,
                        slash_authenticity=message.slash_authenticity,
                    )
                    output = _render_slash_output(
                        result.output, descriptor.simple_output_path
                    )
                except Exception as exc:  # noqa: BLE001
                    output = f"/{command_name} failed: {exc}"

        session_id = self._record_slash_inbound_turn(meta=meta, instruction=message)
        conversational_memory = (
            None
            if session_id is None
            else ConversationalMemoryContext(
                session_id=session_id,
                model=_SLASH_OUTPUT_MODEL,
                provider=_SLASH_OUTPUT_PROVIDER,
                token_count=_estimate_token_count(output),
                reasoning_level=_SLASH_OUTPUT_REASONING_LEVEL,
            )
        )
        if self._outbound_service is not None:
            route_meta = new_meta(
                kind=meta.kind,
                source=str(SERVICE_COMPONENT_ID),
                principal=meta.principal,
                trace_id=meta.trace_id,
                parent_id=meta.envelope_id,
            )
            route_result = self._outbound_service.route_notification(
                meta=route_meta,
                channel=message.channel,
                message=output,
                force=True,
                conversational_memory=conversational_memory,
            )
            if not route_result.ok:
                _LOGGER.warning(
                    "slash command output routing failed",
                    extra={"command": command_name, "channel": message.channel},
                )
        else:
            _LOGGER.warning(
                "slash command output cannot be routed: no outbound_service",
                extra={"command": command_name, "channel": message.channel},
            )

        _LOGGER.debug(
            "inbound handled slash command",
            extra={"command": command_name, "channel": message.channel},
        )
        return success(
            meta=meta,
            payload=IngestResult(
                accepted=True,
                queued=False,
                queue_name="",
                reason="slash command handled",
                message=message,
            ),
        )

    def _record_slash_inbound_turn(
        self,
        *,
        meta: EnvelopeMeta,
        instruction: InboundMessage,
    ) -> str | None:
        """Persist an intercepted slash command as an inbound Recall turn."""
        if self._recall_service is None:
            return None

        session_meta = new_meta(
            kind=meta.kind,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )
        session = self._recall_service.get_latest_or_create_session(meta=session_meta)
        if not session.ok or session.payload is None:
            _LOGGER.warning(
                "slash command inbound cannot be recorded: session lookup failed",
                extra={"channel": instruction.channel},
            )
            return None

        session_id = session.payload.value.id
        record_meta = new_meta(
            kind=meta.kind,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=session_meta.envelope_id,
        )
        record = self._recall_service.record_inbound_turn(
            meta=record_meta,
            session_id=session_id,
            message=instruction.message_text,
            instruction=_inbound_instruction_record(instruction),
        )
        if record.ok:
            return session_id
        _LOGGER.warning(
            "slash command inbound cannot be recorded",
            extra={"channel": instruction.channel, "session_id": session_id},
        )
        return None

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def ingest_inbound_message(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> Envelope[IngestResult]:
        """Validate and enqueue one normalized inbound operator message."""
        request, errors = self._validate_request(
            meta=meta,
            model=IngestInboundMessageRequest,
            payload={"message": message.model_dump(mode="python")},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None
        message = request.message

        sender_e164 = message.sender.e164.strip()
        if sender_e164 and sender_e164 != self._operator_e164:
            _LOGGER.info(
                "inbound ignored inbound message from non-operator sender",
                extra={
                    "sender_e164": sender_e164,
                    "expected_sender_e164": self._operator_e164,
                    "channel": message.channel,
                },
            )
            return success(
                meta=meta,
                payload=IngestResult(
                    accepted=False,
                    queued=False,
                    queue_name=self._settings.queue_name,
                    reason="sender is not configured operator",
                    message=message,
                ),
            )

        _LOGGER.debug(
            "inbound accepted operator instruction",
            extra={
                "channel": message.channel,
                "sender_e164": sender_e164,
                "message_text": message.message_text,
            },
        )
        if message.slash_command is not None:
            slash_result = self._handle_slash_command(
                meta=meta,
                message=message,
            )
            if not slash_result.ok:
                return failure(meta=meta, errors=slash_result.errors)
            return success(
                meta=meta,
                payload=IngestResult(
                    accepted=True,
                    queued=False,
                    queue_name=self._settings.queue_name,
                    reason="slash command handled",
                    message=message,
                ),
            )
        message = self._with_resolved_approval_links(meta=meta, message=message)
        self._record_approval_response(meta=meta, message=message)
        enqueued = self._cache_service.push_queue(
            meta=meta,
            component_id=str(SERVICE_COMPONENT_ID),
            queue=self._settings.queue_name,
            value=message.relay_payload(),
        )
        if not enqueued.ok:
            return failure(meta=meta, errors=enqueued.errors)

        return success(
            meta=meta,
            payload=IngestResult(
                accepted=True,
                queued=True,
                queue_name=self._settings.queue_name,
                reason="accepted",
                message=message,
            ),
        )

    def _record_approval_response(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> None:
        """Best-effort persistence of operator approval/rejection responses."""
        if self._brain_client is None or message.approval is None:
            return
        token = (
            message.approval.token.strip()
            or message.reply_to_proposal_token.strip()
            or message.reaction_to_proposal_token.strip()
        )
        if token == "":
            return
        try:
            self._brain_client.policy_approval_response(
                proposal_token=token,
                intent=message.approval.intent,
                meta=MetaOverrides(
                    source=str(SERVICE_COMPONENT_ID),
                    principal=meta.principal,
                    trace_id=meta.trace_id,
                    parent_id=meta.envelope_id,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "approval response persistence failed",
                extra={
                    "token": token,
                    "intent": message.approval.intent,
                    "error": str(exc),
                },
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def register_inbound_callbacks(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[RegisterInboundCallbacksResult]:
        """Register in-process inbound callbacks with owned adapters."""
        callback = self._build_adapter_callback()
        results = []
        try:
            for adapter in self._inbound_adapters:
                results.append(adapter.register_callback(callback=callback))
        except InboundAdapterDependencyError as exc:
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "inbound adapter unavailable",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                    )
                ],
            )
        except InboundAdapterInternalError as exc:
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "inbound adapter internal failure",
                    )
                ],
            )

        detail = "; ".join(result.detail for result in results)
        return success(
            meta=meta,
            payload=RegisterInboundCallbacksResult(
                registered=all(result.registered for result in results),
                detail=detail or "no inbound adapters configured",
            ),
        )

    def _build_adapter_callback(self):
        """Return one adapter callback that ingests normalized inbound messages."""

        def _callback(
            *, meta: EnvelopeMeta, message: InboundMessage
        ) -> InboundCallbackResult:
            result = self.ingest_inbound_message(
                meta=meta,
                message=message,
            )
            if result.ok and result.payload is not None:
                payload = result.payload.value
                return InboundCallbackResult(
                    accepted=payload.accepted,
                    queued=payload.queued,
                    reason=payload.reason,
                    queue_name=payload.queue_name,
                    sender_e164=None
                    if payload.message is None
                    else payload.message.sender.e164,
                    timestamp_ms=None
                    if payload.message is None
                    else payload.message.timestamp_ms,
                )
            if len(result.errors) == 0:
                raise InboundAdapterInternalError("inbound callback failed")
            error = result.errors[0]
            if error.category == ErrorCategory.DEPENDENCY:
                raise InboundAdapterDependencyError(error.message)
            if error.category == ErrorCategory.INTERNAL:
                raise InboundAdapterInternalError(error.message)
            return InboundCallbackResult(
                accepted=False,
                queued=False,
                reason=error.message,
            )

        return _callback

    def _with_resolved_approval_links(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> InboundMessage:
        """Attach Relay-resolved proposal tokens for replies and reactions."""
        reply_token = self._resolve_proposal_token(
            meta=meta,
            channel=message.channel,
            target_timestamp_ms=None
            if message.reply_to is None
            else message.reply_to.timestamp_ms,
        )
        reaction_token = self._resolve_proposal_token(
            meta=meta,
            channel=message.channel,
            target_timestamp_ms=None
            if message.reaction is None or message.reaction.target is None
            else message.reaction.target.timestamp_ms,
        )
        return message.model_copy(
            update={
                "reply_to_proposal_token": reply_token or "",
                "reaction_to_proposal_token": reaction_token or "",
            }
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def poll_operator_instruction(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[InboundMessage | None]:
        """Pop the next queued operator instruction, optionally long-polling."""
        request, errors = self._validate_request(
            meta=meta,
            model=PollOperatorInstructionRequest,
            payload={"wait_timeout_seconds": wait_timeout_seconds},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        queues = (self._settings.queue_name,)
        deadline = time.monotonic() + request.wait_timeout_seconds
        while True:
            for queue in queues:
                popped = self._cache_service.pop_queue(
                    meta=meta,
                    component_id=str(SERVICE_COMPONENT_ID),
                    queue=queue,
                )
                if not popped.ok:
                    return failure(meta=meta, errors=popped.errors)

                if popped.payload is not None and popped.payload.value is not None:
                    entry = popped.payload.value
                    try:
                        message = InboundMessage.model_validate(entry.value)
                    except ValidationError:
                        return failure(
                            meta=meta,
                            errors=[
                                internal_error(
                                    "queued operator instruction payload is invalid",
                                    code=codes.INTERNAL_ERROR,
                                )
                            ],
                        )
                    _LOGGER.debug(
                        "inbound dequeued operator instruction",
                        extra={
                            "channel": message.channel,
                            "sender_e164": message.sender.e164,
                            "message_text": message.message_text,
                        },
                    )
                    return success(meta=meta, payload=message)

            now = time.monotonic()
            if now >= deadline:
                return success(meta=meta, payload=None)

            sleep_seconds = min(_POLL_INTERVAL_SECONDS, deadline - now)
            if sleep_seconds <= 0.0:
                return success(meta=meta, payload=None)
            time.sleep(sleep_seconds)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Relay inbound and inbound-adapter readiness state."""
        adapter_ready = True
        adapter_details = []
        for index, adapter in enumerate(self._inbound_adapters):
            try:
                health = adapter.health()
            except InboundAdapterDependencyError as exc:
                adapter_ready = False
                adapter_details.append(f"adapter_{index}=unavailable:{exc}")
            except InboundAdapterInternalError as exc:
                adapter_ready = False
                adapter_details.append(f"adapter_{index}=failed:{exc}")
            else:
                adapter_ready = adapter_ready and health.adapter_ready
                adapter_details.append(f"adapter_{index}={health.detail}")

        if not adapter_details:
            adapter_details.append("adapters=none")

        detail_parts = [*adapter_details, "cas=not_assessed"]
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=adapter_ready,
                cas_ready=True,
                detail="; ".join(detail_parts),
            ),
        )

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, Any],
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate envelope metadata and operation payloads with stable errors."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return None, [validation_error(str(exc), code=codes.INVALID_ARGUMENT)]

        try:
            request = model.model_validate(payload)
        except ValidationError as exc:
            return None, [validation_error_from_pydantic(exc)]

        return request, []

    def _resolve_proposal_token(
        self,
        *,
        meta: EnvelopeMeta,
        channel: str,
        target_timestamp_ms: int | None,
    ) -> str | None:
        """Resolve one quoted/reacted message timestamp to a proposal token."""
        if self._outbound_service is None or target_timestamp_ms is None:
            _LOGGER.verbose(
                "inbound skipped proposal token resolution",
                extra={
                    "channel": channel,
                    "target_timestamp_ms": target_timestamp_ms,
                    "outbound_configured": self._outbound_service is not None,
                },
            )
            return None

        lookup_meta = new_meta(
            kind=meta.kind,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )
        result = self._outbound_service.resolve_approval_notification_proposal_token(
            meta=lookup_meta,
            channel=channel,
            target_timestamp_ms=target_timestamp_ms,
        )
        resolved_token: str | None = None
        if not result.ok or result.payload is None:
            _LOGGER.verbose(
                "inbound proposal token lookup failed",
                extra={
                    "channel": channel,
                    "target_timestamp_ms": target_timestamp_ms,
                    "lookup_ok": result.ok,
                    "error_codes": [error.code for error in result.errors],
                },
            )
            return None
        token = result.payload.value
        if token is not None and str(token).strip() != "":
            resolved_token = str(token).strip()
        _LOGGER.verbose(
            "inbound proposal token lookup completed",
            extra={
                "channel": channel,
                "target_timestamp_ms": target_timestamp_ms,
                "resolved_proposal_token": resolved_token,
            },
        )
        return resolved_token
