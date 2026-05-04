"""Concrete Relay inbound service implementation."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from lib.sdk.client import BrainClient
from lib.shared.approval import normalize_approval_intent
from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.config import ApprovalResponseSettings
from lib.shared.envelope import (
    Envelope,
    EnvelopeKind,
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
from lib.shared.logging import get_logger, public_api_instrumented
from resources.adapters.console.adapter import ConsoleAdapter
from resources.adapters.signal import (
    SignalAdapter,
    SignalInboundCallbackResult,
    SignalAdapterDependencyError,
    SignalAdapterInternalError,
    summarize_signal_payload,
)
from services.effect.relay._outbound.service import RelayOutboundService
from services.effect.relay._inbound.component import SERVICE_COMPONENT_ID
from services.effect.relay._shared import validation_error_from_pydantic
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)
from services.effect.relay._inbound.domain import (
    ConsoleEnqueueResult,
    HealthStatus,
    IngestResult,
    NormalizedOperatorMessage,
    RegisterSignalCallbackResult,
)
from services.effect.relay._inbound.service import RelayInboundService
from services.effect.relay._inbound.validation import (
    EnqueueConsoleMessageRequest,
    IngestSignalMessageRequest,
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
_SLASH_COMMAND_RE = re.compile(r"^/([a-zA-Z][a-zA-Z0-9-]*)(?:\s+(.*))?$", re.DOTALL)
_NAMED_ARG_RE = re.compile(r"--([a-zA-Z][a-zA-Z0-9_-]*)(?:[ =](\S+))?")
_SLASH_OUTPUT_MODEL = "inbound-slash-command"
_SLASH_OUTPUT_PROVIDER = "brain-core"
_SLASH_OUTPUT_REASONING_LEVEL = "system"


def _parse_slash_command(message_text: str) -> tuple[str, str] | None:
    """Return (command_name, args_text) or None if not a slash command."""
    m = _SLASH_COMMAND_RE.match(message_text.strip())
    if m is None:
        return None
    return m.group(1).lower(), (m.group(2) or "").strip()


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


class DefaultRelayInboundService(RelayInboundService):
    """Relay inbound implementation that normalizes Signal events and queues them."""

    def __init__(
        self,
        *,
        settings: RelayInboundServiceSettings,
        identity: RelayInboundIdentitySettings,
        adapter: SignalAdapter,
        cache_service: CacheService,
        console_adapter: ConsoleAdapter | None = None,
        outbound_service: RelayOutboundService | None = None,
        recall_service: RecallService | None = None,
        approval_response_settings: ApprovalResponseSettings | None = None,
        brain_client: BrainClient | None = None,
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._adapter = adapter
        self._console_adapter = console_adapter
        self._cache_service = cache_service
        self._outbound_service = outbound_service
        self._recall_service = recall_service
        self._approval_response_settings = (
            approval_response_settings
            if approval_response_settings is not None
            else ApprovalResponseSettings()
        )
        self._brain_client = brain_client
        self._operator_e164 = _normalize_e164(
            raw=identity.operator_signal_contact_e164,
            default_dial_code=identity.default_dial_code,
        )

    def _mint_signal_slash_proof(
        self, command_text: str
    ) -> SlashAuthenticityProof | None:
        """Ask the Signal Adapter to mint a proof for an operator-channel slash command.

        Returns ``None`` when the secret is unavailable; the slash dispatch
        falls through to the standard approval gate, which will deny the
        invocation rather than silently bypassing the gate.
        """
        try:
            return self._adapter.mint_slash_authenticity_proof(
                channel="signal",
                message_text=command_text,
            )
        except SignalAdapterDependencyError:
            _LOGGER.warning(
                "signal adapter could not mint slash authenticity proof; "
                "slash command will be denied by the approval gate"
            )
            return None

    def _handle_slash_command(
        self,
        *,
        meta: EnvelopeMeta,
        command_name: str,
        args_text: str,
        source: str,
        instruction: NormalizedOperatorMessage | None = None,
        slash_authenticity: SlashAuthenticityProof | None = None,
    ) -> Envelope[ConsoleEnqueueResult]:
        """Resolve and invoke one slash command inline; route output via ARS."""
        command_text = f"/{command_name}"
        if args_text.strip() != "":
            command_text = f"{command_text} {args_text.strip()}"
        if instruction is None:
            instruction = NormalizedOperatorMessage(
                source=source,
                message_text=command_text,
                timestamp_ms=int(time.time() * 1000),
            )

        # Signal-channel slash commands are minted by the Signal Adapter at
        # dispatch time; Console-channel proofs arrive on the inbound payload.
        # Relay never holds the secret.
        if slash_authenticity is None and source == "signal":
            slash_authenticity = self._mint_signal_slash_proof(command_text)

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
                        channel=source,
                        message_text=command_text,
                        slash_authenticity=slash_authenticity,
                    )
                    output = _render_slash_output(
                        result.output, descriptor.simple_output_path
                    )
                except Exception as exc:  # noqa: BLE001
                    output = f"/{command_name} failed: {exc}"

        session_id = self._record_slash_inbound_turn(meta=meta, instruction=instruction)
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
            self._outbound_service.route_notification(
                meta=route_meta,
                channel=source,
                message=output,
                force=True,
                conversational_memory=conversational_memory,
            )
        else:
            _LOGGER.warning(
                "slash command output cannot be routed: no outbound_service",
                extra={"command": command_name, "source": source},
            )

        _LOGGER.debug(
            "inbound handled slash command",
            extra={"command": command_name, "source": source},
        )
        return success(
            meta=meta,
            payload=ConsoleEnqueueResult(queued=False, queue_name=""),
        )

    def _record_slash_inbound_turn(
        self,
        *,
        meta: EnvelopeMeta,
        instruction: NormalizedOperatorMessage,
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
                extra={"channel": instruction.source},
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
            instruction=InboundInstructionRecord.model_validate(
                instruction.model_dump(mode="python")
            ),
        )
        if record.ok:
            return session_id
        _LOGGER.warning(
            "slash command inbound cannot be recorded",
            extra={"channel": instruction.source, "session_id": session_id},
        )
        return None

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def ingest_signal_message(
        self,
        *,
        meta: EnvelopeMeta,
        raw_body_json: str,
    ) -> Envelope[IngestResult]:
        """Validate/normalize one raw Signal payload and enqueue accepted messages."""
        request, errors = self._validate_request(
            meta=meta,
            model=IngestSignalMessageRequest,
            payload={
                "raw_body_json": raw_body_json,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        _LOGGER.verbose(
            "inbound received raw signal payload",
            extra={
                "raw_body_json": request.raw_body_json,
                "payload_sha256": hashlib.sha256(
                    request.raw_body_json.encode("utf-8")
                ).hexdigest(),
                **summarize_signal_payload(request.raw_body_json),
            },
        )

        message, parse_error = self._normalize_signal_message(
            meta=meta,
            raw_body_json=request.raw_body_json,
        )
        if parse_error is not None:
            payload_summary = summarize_signal_payload(
                raw_body_json=request.raw_body_json
            )
            _LOGGER.warning(
                "inbound rejected signal payload: invalid",
                extra={"error": parse_error.message, **payload_summary},
            )
            return failure(meta=meta, errors=[parse_error])
        if message is None:
            ignored_reason, payload_summary = _ignored_payload_reason(
                raw_body_json=request.raw_body_json
            )
            _LOGGER.info(
                "inbound ignored signal payload",
                extra={
                    "reason": ignored_reason,
                    **payload_summary,
                },
            )
            return success(
                meta=meta,
                payload=IngestResult(
                    accepted=False,
                    queued=False,
                    queue_name=self._settings.queue_name,
                    reason=ignored_reason,
                ),
            )

        if message.sender_e164 != self._operator_e164:
            _LOGGER.info(
                "inbound ignored inbound message from non-operator sender",
                extra={
                    "sender_e164": message.sender_e164,
                    "expected_sender_e164": self._operator_e164,
                    "channel": message.source,
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
                "channel": message.source,
                "sender_e164": message.sender_e164,
                "message_text": message.message_text,
            },
        )
        parsed = _parse_slash_command(message.message_text)
        if parsed is not None:
            command_name, args_text = parsed
            slash_result = self._handle_slash_command(
                meta=meta,
                command_name=command_name,
                args_text=args_text,
                source=message.source,
                instruction=message,
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
        queue_payload = {
            "source": message.source,
            "sender_e164": message.sender_e164,
            "message_text": message.message_text,
            "timestamp_ms": message.timestamp_ms,
            "source_device": message.source_device,
            "group_id": message.group_id,
            "quote_target_timestamp_ms": message.quote_target_timestamp_ms,
            "reaction_target_timestamp_ms": message.reaction_target_timestamp_ms,
            "reaction_emoji": message.reaction_emoji,
            "approval_intent": message.approval_intent,
            "reply_to_proposal_token": message.reply_to_proposal_token,
            "reaction_to_proposal_token": message.reaction_to_proposal_token,
            # Explicitly no dedupe/idempotency marker in v1.
        }
        enqueued = self._cache_service.push_queue(
            meta=meta,
            component_id=str(SERVICE_COMPONENT_ID),
            queue=self._settings.queue_name,
            value=queue_payload,
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

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def enqueue_console_message(
        self,
        *,
        meta: EnvelopeMeta,
        message_text: str,
        slash_authenticity: SlashAuthenticityProof | None = None,
    ) -> Envelope[ConsoleEnqueueResult]:
        """Normalize and enqueue one inbound console operator message."""
        request, errors = self._validate_request(
            meta=meta,
            model=EnqueueConsoleMessageRequest,
            payload={"message_text": message_text},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        parsed = _parse_slash_command(request.message_text)
        if parsed is not None:
            command_name, args_text = parsed
            return self._handle_slash_command(
                meta=meta,
                command_name=command_name,
                args_text=args_text,
                source="console",
                slash_authenticity=slash_authenticity,
            )

        message = NormalizedOperatorMessage(
            source="console",
            message_text=request.message_text,
            timestamp_ms=int(time.time() * 1000),
        )

        queue_payload = message.model_dump(mode="python")
        enqueued = self._cache_service.push_queue(
            meta=meta,
            component_id=str(SERVICE_COMPONENT_ID),
            queue=self._settings.console_queue_name,
            value=queue_payload,
        )
        if not enqueued.ok:
            return failure(meta=meta, errors=enqueued.errors)

        _LOGGER.debug(
            "inbound accepted console operator instruction",
            extra={
                "channel": "console",
                "message_text": request.message_text,
            },
        )
        return success(
            meta=meta,
            payload=ConsoleEnqueueResult(
                queued=True,
                queue_name=self._settings.console_queue_name,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def register_signal_callback(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[RegisterSignalCallbackResult]:
        """Register one in-process inbound callback with the Signal adapter."""
        try:
            result = self._adapter.register_callback(
                callback=self._build_signal_inbound_callback()
            )
        except SignalAdapterDependencyError as exc:
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "signal adapter unavailable",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_signal"},
                    )
                ],
            )
        except SignalAdapterInternalError as exc:
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "signal adapter internal failure",
                        metadata={"adapter": "adapter_signal"},
                    )
                ],
            )

        return success(
            meta=meta,
            payload=RegisterSignalCallbackResult(
                registered=result.registered,
                detail=result.detail,
            ),
        )

    def _build_signal_inbound_callback(self):
        """Return one adapter callback that ingests raw Signal payloads in-process."""

        def _callback(*, raw_body_json: str) -> SignalInboundCallbackResult:
            result = self.ingest_signal_message(
                meta=new_meta(
                    kind=EnvelopeKind.EVENT,
                    source="adapter_signal",
                    principal="operator",
                ),
                raw_body_json=raw_body_json,
            )
            if result.ok and result.payload is not None:
                payload = result.payload.value
                return SignalInboundCallbackResult(
                    accepted=payload.accepted,
                    queued=payload.queued,
                    reason=payload.reason,
                    sender_e164=None
                    if payload.message is None
                    else payload.message.sender_e164,
                    timestamp_ms=None
                    if payload.message is None
                    else payload.message.timestamp_ms,
                )
            if len(result.errors) == 0:
                raise SignalAdapterInternalError("inbound callback failed")
            error = result.errors[0]
            if error.category == ErrorCategory.DEPENDENCY:
                raise SignalAdapterDependencyError(error.message)
            if error.category == ErrorCategory.INTERNAL:
                raise SignalAdapterInternalError(error.message)
            return SignalInboundCallbackResult(
                accepted=False,
                queued=False,
                reason=error.message,
            )

        return _callback

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def poll_operator_instruction(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[NormalizedOperatorMessage | None]:
        """Pop the next queued operator instruction, optionally long-polling."""
        request, errors = self._validate_request(
            meta=meta,
            model=PollOperatorInstructionRequest,
            payload={"wait_timeout_seconds": wait_timeout_seconds},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        queues = (
            self._settings.console_queue_name,
            self._settings.queue_name,
        )
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
                        message = NormalizedOperatorMessage.model_validate(entry.value)
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
                            "channel": message.source,
                            "sender_e164": message.sender_e164,
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
        """Return Relay inbound and owned adapter readiness state."""
        try:
            adapter_health = self._adapter.health()
        except SignalAdapterDependencyError as exc:
            adapter_health = None
            adapter_detail = str(exc) or "signal adapter unavailable"
        except SignalAdapterInternalError as exc:
            adapter_health = None
            adapter_detail = str(exc) or "signal adapter failure"
        else:
            adapter_detail = adapter_health.detail

        detail_parts = [f"adapter={adapter_detail}", "cas=not_assessed"]
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=False
                if adapter_health is None
                else adapter_health.adapter_ready,
                cas_ready=True,
                detail="; ".join(detail_parts),
            ),
        )

    def _normalize_signal_message(
        self,
        *,
        meta: EnvelopeMeta,
        raw_body_json: str,
    ) -> tuple[NormalizedOperatorMessage | None, ErrorDetail | None]:
        """Parse + normalize one inbound Signal payload into a canonical message DTO."""
        try:
            payload = json.loads(raw_body_json)
        except json.JSONDecodeError:
            return None, validation_error(
                "raw_body_json must be valid JSON",
                code=codes.INVALID_ARGUMENT,
            )
        if not isinstance(payload, dict):
            return None, validation_error(
                "raw_body_json must decode to an object",
                code=codes.INVALID_ARGUMENT,
            )

        candidate = payload
        data = payload.get("data")
        if isinstance(data, dict):
            candidate = data

        envelope = _extract_envelope(candidate)
        message_payload = _extract_message_payload(envelope)

        sender_raw = _first_non_empty(
            envelope,
            "source",
            "sourceNumber",
            "sender",
            "from",
            "sender_e164",
        )
        message_text = _first_non_empty(
            message_payload,
            "message",
            "message_text",
            "text",
            "body",
        )
        if message_text == "":
            message_text = _first_non_empty(
                envelope,
                "message",
                "message_text",
                "text",
                "body",
            )
        if message_text == "":
            message_text = _first_non_empty(
                candidate,
                "message",
                "message_text",
                "text",
                "body",
            )

        timestamp_ms = _parse_timestamp_ms(
            envelope.get("timestamp_ms")
            or envelope.get("timestamp")
            or envelope.get("sourceTimestamp")
            or candidate.get("timestamp_ms")
            or candidate.get("timestamp")
            or candidate.get("sourceTimestamp")
        )
        if timestamp_ms is None:
            return None, validation_error(
                "payload timestamp is required and must be numeric",
                code=codes.INVALID_ARGUMENT,
            )

        if sender_raw == "":
            return None, validation_error(
                "sender identity is required",
                code=codes.INVALID_ARGUMENT,
            )

        try:
            sender_e164 = _normalize_e164(
                raw=sender_raw,
                default_dial_code=self._identity.default_dial_code,
            )
        except ValueError as exc:
            return None, validation_error(
                str(exc),
                code=codes.INVALID_ARGUMENT,
            )

        group_id = _extract_group_id(message_payload) or _extract_group_id(envelope)
        quote_target = _parse_optional_int(
            _extract_nested(message_payload, "quote", "timestamp")
            or _extract_nested(message_payload, "quote", "id")
            or candidate.get("quote_target_timestamp_ms")
        )
        reaction_target = _parse_optional_int(
            _extract_nested(message_payload, "reaction", "targetSentTimestamp")
            or _extract_nested(message_payload, "reaction", "targetTimestamp")
            or candidate.get("reaction_target_timestamp_ms")
        )
        reaction_emoji = _extract_reaction_emoji(message_payload) or _first_non_empty(
            candidate,
            "reaction_emoji",
        )
        _LOGGER.verbose(
            "inbound normalized signal approval evidence",
            extra={
                "sender_raw": sender_raw,
                "timestamp_ms": timestamp_ms,
                "message_text": message_text,
                "group_id": group_id,
                "quote_target_timestamp_ms": quote_target,
                "reaction_target_timestamp_ms": reaction_target,
                "reaction_emoji": reaction_emoji,
                "contains_quote": isinstance(message_payload.get("quote"), dict),
                "contains_reaction": isinstance(message_payload.get("reaction"), dict),
                "payload_shape": _signal_payload_shape(candidate),
            },
        )
        if message_text == "" and reaction_target is None and reaction_emoji == "":
            return None, None
        reply_to_proposal_token = self._resolve_proposal_token(
            meta=meta,
            channel="signal",
            target_timestamp_ms=quote_target,
        )
        reaction_to_proposal_token = self._resolve_proposal_token(
            meta=meta,
            channel="signal",
            target_timestamp_ms=reaction_target,
        )

        source_device = str(
            envelope.get("sourceDevice")
            or envelope.get("source_device")
            or candidate.get("sourceDevice")
            or candidate.get("device")
            or candidate.get("source_device")
            or ""
        )

        return (
            NormalizedOperatorMessage(
                sender_e164=sender_e164,
                message_text=message_text,
                timestamp_ms=timestamp_ms,
                source_device=source_device,
                source="signal",
                group_id=group_id,
                quote_target_timestamp_ms=quote_target,
                reaction_target_timestamp_ms=reaction_target,
                reaction_emoji=None if reaction_emoji == "" else reaction_emoji,
                approval_intent=normalize_approval_intent(
                    message_text=message_text,
                    reaction_emoji=reaction_emoji,
                    settings=self._approval_response_settings,
                ),
                reply_to_proposal_token=reply_to_proposal_token,
                reaction_to_proposal_token=reaction_to_proposal_token,
            ),
            None,
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
        """Resolve one quoted/reacted Signal timestamp to a proposal token."""
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


def _ignored_payload_reason(raw_body_json: str) -> tuple[str, dict[str, object]]:
    """Return one stable ignore reason plus a diagnostic payload summary."""
    payload_summary = summarize_signal_payload(raw_body_json=raw_body_json)
    exception_type = str(payload_summary.get("exception_type") or "").strip()
    if exception_type != "":
        return f"signal exception event: {exception_type}", payload_summary
    return "non-message payload", payload_summary


def _extract_group_id(payload: dict[str, Any]) -> str | None:
    """Extract optional group identifier from common Signal payload shapes."""
    group_id = payload.get("group_id")
    if isinstance(group_id, str) and group_id.strip() != "":
        return group_id

    group_info = payload.get("groupInfo")
    if isinstance(group_info, dict):
        group_id = group_info.get("groupId") or group_info.get("id")
        if isinstance(group_id, str) and group_id.strip() != "":
            return group_id
    return None


def _extract_reaction_emoji(payload: dict[str, Any]) -> str:
    """Extract one reaction emoji from common Signal payload shapes."""
    reaction = payload.get("reaction")
    if not isinstance(reaction, dict):
        return ""
    return _first_non_empty(
        reaction,
        "emoji",
        "emojiShortName",
        "emoji_short_name",
    )


def _signal_payload_shape(candidate: dict[str, Any]) -> str:
    """Return a stable description of the normalized payload shape."""
    envelope = candidate.get("envelope")
    if not isinstance(envelope, dict):
        return "candidate"
    if isinstance(envelope.get("dataMessage"), dict):
        return "envelope.dataMessage"
    if isinstance(envelope.get("syncMessage"), dict):
        return "envelope.syncMessage"
    return "envelope"


def _extract_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Return nested Signal envelope when present; otherwise the payload itself."""
    envelope = payload.get("envelope")
    if isinstance(envelope, dict):
        return envelope
    return payload


def _extract_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested message object most likely to contain message fields."""
    data_message = payload.get("dataMessage")
    if isinstance(data_message, dict):
        return data_message

    sync_message = payload.get("syncMessage")
    if isinstance(sync_message, dict):
        sent_message = sync_message.get("sentMessage")
        if isinstance(sent_message, dict):
            return sent_message

    return payload


def _extract_nested(payload: dict[str, Any], parent: str, child: str) -> Any:
    """Read one nested mapping field when parent is an object."""
    parent_value = payload.get(parent)
    if isinstance(parent_value, dict):
        return parent_value.get(child)
    return None


def _first_non_empty(payload: dict[str, Any], *keys: str) -> str:
    """Return first non-empty scalar string value for the provided keys."""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate != "":
            return candidate
    return ""


def _parse_timestamp_ms(value: Any) -> int | None:
    """Parse inbound Signal timestamps in seconds or milliseconds to milliseconds."""
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return None

    # Heuristic: 10-digit Unix timestamps are seconds.
    if parsed < 1_000_000_000_000:
        return parsed * 1000
    return parsed


def _parse_optional_int(value: Any) -> int | None:
    """Parse optional integer-like value; return None when absent/invalid."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _normalize_e164(*, raw: str, default_dial_code: str) -> str:
    """Normalize phone number input to canonical E.164 format."""
    candidate = raw.strip()
    if candidate == "":
        raise ValueError("phone number must be non-empty")

    dial_code = "".join(char for char in default_dial_code if char.isdigit())
    if dial_code == "":
        raise ValueError("default_dial_code must contain digits")

    digits = "".join(char for char in candidate if char.isdigit() or char == "+")
    if digits.startswith("+"):
        normalized = "+" + "".join(char for char in digits[1:] if char.isdigit())
    else:
        normalized_digits = "".join(char for char in digits if char.isdigit())
        if normalized_digits.startswith("00"):
            normalized_digits = normalized_digits[2:]
        else:
            if dial_code == "1" and len(normalized_digits) == 10:
                normalized_digits = f"1{normalized_digits}"
            elif not normalized_digits.startswith(dial_code):
                normalized_digits = f"{dial_code}{normalized_digits}"
        normalized = f"+{normalized_digits}"

    if not normalized.startswith("+"):
        raise ValueError("phone number must normalize to E.164")

    digits_only = normalized[1:]
    if len(digits_only) < 8 or len(digits_only) > 15:
        raise ValueError("phone number must contain 8-15 digits in E.164 form")
    if not digits_only.isdigit():
        raise ValueError("phone number must contain only digits after '+'")
    return normalized
