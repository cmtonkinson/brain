"""Concrete Switchboard Service implementation."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from pydantic import BaseModel, ValidationError

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    utc_now,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    dependency_error,
    internal_error,
    policy_error,
    validation_error,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.signal import (
    HttpSignalAdapter,
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterInternalError,
    resolve_signal_adapter_settings,
)
from services.action.switchboard.component import SERVICE_COMPONENT_ID
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
    resolve_switchboard_identity_settings,
    resolve_switchboard_service_settings,
)
from services.action.switchboard.domain import (
    HealthStatus,
    IngestResult,
    NormalizedSignalMessage,
    RegisterSignalWebhookResult,
)
from services.action.switchboard.service import SwitchboardService
from services.action.switchboard.validation import (
    IngestSignalWebhookRequest,
    RegisterSignalWebhookRequest,
)
from services.state.cache_authority.service import CacheAuthorityService

_LOGGER = get_logger(__name__)

_COUNTRY_DIAL_CODES: dict[str, str] = {
    "US": "1",
    "CA": "1",
    "GB": "44",
    "AU": "61",
    "DE": "49",
    "FR": "33",
    "JP": "81",
}


class DefaultSwitchboardService(SwitchboardService):
    """Switchboard implementation that normalizes Signal events and queues them."""

    def __init__(
        self,
        *,
        settings: SwitchboardServiceSettings,
        identity: SwitchboardIdentitySettings,
        adapter: SignalAdapter,
        cache_service: CacheAuthorityService,
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._adapter = adapter
        self._cache_service = cache_service
        self._operator_e164 = _normalize_e164(
            raw=identity.operator_signal_e164,
            default_country_code=identity.default_country_code,
        )

    @classmethod
    def from_settings(
        cls,
        *,
        settings: BrainSettings,
        cache_service: CacheAuthorityService,
    ) -> "DefaultSwitchboardService":
        """Build Switchboard + owned adapter from typed root settings."""
        service_settings = resolve_switchboard_service_settings(settings)
        identity = resolve_switchboard_identity_settings(settings)
        adapter_settings = resolve_signal_adapter_settings(settings)
        return cls(
            settings=service_settings,
            identity=identity,
            adapter=HttpSignalAdapter(settings=adapter_settings),
            cache_service=cache_service,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def ingest_signal_webhook(
        self,
        *,
        meta: EnvelopeMeta,
        raw_body_json: str,
        header_timestamp: str,
        header_signature: str,
    ) -> Envelope[IngestResult]:
        """Validate/normalize one Signal webhook and enqueue accepted messages."""
        request, errors = self._validate_request(
            meta=meta,
            model=IngestSignalWebhookRequest,
            payload={
                "raw_body_json": raw_body_json,
                "header_timestamp": header_timestamp,
                "header_signature": header_signature,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        verified, verification_error = self._verify_signature(
            raw_body_json=request.raw_body_json,
            header_timestamp=request.header_timestamp,
            header_signature=request.header_signature,
        )
        if not verified:
            assert verification_error is not None
            return failure(meta=meta, errors=[verification_error])

        message, parse_error = self._normalize_signal_message(
            raw_body_json=request.raw_body_json,
        )
        if parse_error is not None:
            return failure(meta=meta, errors=[parse_error])
        if message is None:
            return success(
                meta=meta,
                payload=IngestResult(
                    accepted=False,
                    queued=False,
                    queue_name=self._settings.queue_name,
                    reason="non-message payload",
                ),
            )

        if message.sender_e164 != self._operator_e164:
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

        queue_payload = {
            "source": message.source,
            "sender_e164": message.sender_e164,
            "message_text": message.message_text,
            "timestamp_ms": message.timestamp_ms,
            "source_device": message.source_device,
            "group_id": message.group_id,
            "quote_target_timestamp_ms": message.quote_target_timestamp_ms,
            "reaction_target_timestamp_ms": message.reaction_target_timestamp_ms,
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
    def register_signal_webhook(
        self,
        *,
        meta: EnvelopeMeta,
        callback_url: str,
    ) -> Envelope[RegisterSignalWebhookResult]:
        """Register callback URI/secret with owned Signal adapter."""
        request, errors = self._validate_request(
            meta=meta,
            model=RegisterSignalWebhookRequest,
            payload={
                "callback_url": callback_url,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        secret = self._identity.webhook_shared_secret.strip()
        if secret == "":
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "profile.webhook_shared_secret is not configured",
                        code=codes.INTERNAL_ERROR,
                    )
                ],
            )

        try:
            result = self._adapter.register_webhook(
                callback_url=str(request.callback_url),
                shared_secret=secret,
                operator_e164=self._operator_e164,
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
            payload=RegisterSignalWebhookResult(
                registered=result.registered,
                callback_url=str(request.callback_url),
                detail=result.detail,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Switchboard + adapter/CAS readiness state."""
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

        cas_health = self._cache_service.health(meta=meta)
        cas_ready = cas_health.ok
        cas_detail = ""
        if cas_health.payload is not None:
            payload = cas_health.payload.value
            cas_ready = bool(getattr(payload, "service_ready", False)) and bool(
                getattr(payload, "substrate_ready", False)
            )
            cas_detail = str(getattr(payload, "detail", ""))
        if len(cas_health.errors) > 0:
            cas_detail = "; ".join(error.message for error in cas_health.errors)

        detail_parts = [
            f"adapter={adapter_detail}",
            f"cas={cas_detail or 'ok'}",
        ]
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=False
                if adapter_health is None
                else adapter_health.adapter_ready,
                cas_ready=cas_ready,
                detail="; ".join(detail_parts),
            ),
        )

    def _verify_signature(
        self,
        *,
        raw_body_json: str,
        header_timestamp: str,
        header_signature: str,
    ) -> tuple[bool, ErrorDetail | None]:
        """Verify HMAC timestamp/signature headers against configured secret."""
        secret = self._identity.webhook_shared_secret.strip()
        if secret == "":
            return False, internal_error(
                "profile.webhook_shared_secret is not configured",
                code=codes.INTERNAL_ERROR,
            )

        try:
            timestamp = int(header_timestamp)
        except ValueError:
            return False, validation_error(
                "header_timestamp must be an integer unix timestamp",
                code=codes.INVALID_ARGUMENT,
            )

        now_ts = int(utc_now().timestamp())
        if self._settings.signature_tolerance_seconds > 0:
            delta_seconds = abs(now_ts - timestamp)
            if delta_seconds > self._settings.signature_tolerance_seconds:
                return False, policy_error(
                    "webhook timestamp is outside accepted tolerance",
                    code=codes.PERMISSION_DENIED,
                )

        expected = hmac.new(
            key=secret.encode("utf-8"),
            msg=f"{timestamp}.{raw_body_json}".encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        signatures = _parse_signatures(header_signature)
        if any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            return True, None
        return False, policy_error(
            "webhook signature mismatch",
            code=codes.PERMISSION_DENIED,
        )

    def _normalize_signal_message(
        self,
        *,
        raw_body_json: str,
    ) -> tuple[NormalizedSignalMessage | None, ErrorDetail | None]:
        """Parse + normalize one webhook payload into a canonical message DTO."""
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

        sender_raw = _first_non_empty(
            candidate,
            "source",
            "sourceNumber",
            "sender",
            "from",
            "sender_e164",
        )
        message_text = _first_non_empty(
            candidate,
            "message",
            "message_text",
            "text",
            "body",
        )
        if message_text == "":
            return None, None

        timestamp_ms = _parse_timestamp_ms(
            candidate.get("timestamp_ms")
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
                default_country_code=self._identity.default_country_code,
            )
        except ValueError as exc:
            return None, validation_error(
                str(exc),
                code=codes.INVALID_ARGUMENT,
            )

        group_id = _extract_group_id(candidate)
        quote_target = _parse_optional_int(
            _extract_nested(candidate, "quote", "timestamp")
            or candidate.get("quote_target_timestamp_ms")
        )
        reaction_target = _parse_optional_int(
            _extract_nested(candidate, "reaction", "targetTimestamp")
            or candidate.get("reaction_target_timestamp_ms")
        )

        source_device = str(
            candidate.get("sourceDevice")
            or candidate.get("device")
            or candidate.get("source_device")
            or ""
        )

        return (
            NormalizedSignalMessage(
                sender_e164=sender_e164,
                message_text=message_text,
                timestamp_ms=timestamp_ms,
                source_device=source_device,
                source="signal",
                group_id=group_id,
                quote_target_timestamp_ms=quote_target,
                reaction_target_timestamp_ms=reaction_target,
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
            return None, [_validation_error_from_pydantic(exc)]

        return request, []


def _validation_error_from_pydantic(exc: ValidationError) -> ErrorDetail:
    """Map first pydantic validation error into shared validation contract."""
    first_error = exc.errors()[0]
    location = first_error.get("loc") or ()
    field = str(location[0]) if len(location) > 0 else "payload"
    message = str(first_error.get("msg", "invalid payload"))
    return validation_error(f"{field}: {message}", code=codes.INVALID_ARGUMENT)


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
    """Parse webhook timestamps in seconds or milliseconds to milliseconds."""
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


def _parse_signatures(header_signature: str) -> tuple[str, ...]:
    """Parse signature header into normalized hex digest candidates."""
    candidates: list[str] = []
    for part in header_signature.split(","):
        token = part.strip()
        if token == "":
            continue
        if "=" in token:
            _prefix, token = token.split("=", maxsplit=1)
        token = token.strip().lower()
        if token != "":
            candidates.append(token)
    return tuple(candidates)


def _normalize_e164(*, raw: str, default_country_code: str) -> str:
    """Normalize phone number input to canonical E.164 format."""
    candidate = raw.strip()
    if candidate == "":
        raise ValueError("phone number must be non-empty")

    digits = "".join(char for char in candidate if char.isdigit() or char == "+")
    if digits.startswith("+"):
        normalized = "+" + "".join(char for char in digits[1:] if char.isdigit())
    else:
        normalized_digits = "".join(char for char in digits if char.isdigit())
        if normalized_digits.startswith("00"):
            normalized_digits = normalized_digits[2:]
        else:
            dial_code = _COUNTRY_DIAL_CODES.get(default_country_code.upper())
            if dial_code is None:
                raise ValueError(
                    f"unsupported profile.default_country_code: {default_country_code}"
                )
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
