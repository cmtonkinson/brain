"""Concrete Attention Router Service implementation."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    dependency_error,
    internal_error,
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
from services.action.attention_router.component import SERVICE_COMPONENT_ID
from services.action.attention_router.config import (
    AttentionRouterServiceSettings,
    resolve_attention_router_service_settings,
)
from services.action.attention_router.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    HealthStatus,
    RouteNotificationResult,
    RoutedNotification,
)
from services.action.attention_router.service import AttentionRouterService
from services.action.attention_router.validation import (
    CorrelateApprovalRequest,
    FlushBatchRequest,
    RouteNotificationRequest,
)

_LOGGER = get_logger(__name__)


class DefaultAttentionRouterService(AttentionRouterService):
    """Attention Router implementation with dedupe, batching, and rate limits."""

    def __init__(
        self,
        *,
        settings: AttentionRouterServiceSettings,
        signal_adapter: SignalAdapter,
    ) -> None:
        self._settings = settings
        self._signal_adapter = signal_adapter
        self._recent_dedupe: dict[str, datetime] = {}
        self._recent_by_channel_recipient: dict[tuple[str, str], deque[datetime]] = (
            defaultdict(deque)
        )
        self._batched_messages: dict[str, list[str]] = defaultdict(list)

    @classmethod
    def from_settings(
        cls, *, settings: BrainSettings
    ) -> "DefaultAttentionRouterService":
        """Build Attention Router + owned Signal adapter from typed settings."""
        service_settings = resolve_attention_router_service_settings(settings)
        adapter_settings = resolve_signal_adapter_settings(settings)
        return cls(
            settings=service_settings,
            signal_adapter=HttpSignalAdapter(settings=adapter_settings),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def route_notification(
        self,
        *,
        meta: EnvelopeMeta,
        actor: str = "operator",
        channel: str = "",
        title: str = "",
        message: str,
        recipient_e164: str = "",
        sender_e164: str = "",
        dedupe_key: str = "",
        batch_key: str = "",
        force: bool = False,
    ) -> Envelope[RouteNotificationResult]:
        """Route one outbound notification and apply policy-neutral constraints."""
        request, errors = self._validate_request(
            meta=meta,
            model=RouteNotificationRequest,
            payload={
                "actor": actor,
                "channel": channel,
                "title": title,
                "message": message,
                "recipient_e164": recipient_e164,
                "sender_e164": sender_e164,
                "dedupe_key": dedupe_key,
                "batch_key": batch_key,
                "force": force,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        now = datetime.now(UTC)
        resolved = self._resolve_notification(request=request)

        if not request.force and self._should_suppress_dedupe(
            dedupe_key=resolved.dedupe_key, now=now
        ):
            return success(
                meta=meta,
                payload=RouteNotificationResult(
                    decision="suppressed",
                    delivered=False,
                    detail="duplicate notification suppressed",
                    suppressed_reason="dedupe_window",
                    notification=resolved,
                ),
            )

        if not request.force and resolved.batch_key != "":
            batched_count = self._enqueue_batch(
                batch_key=resolved.batch_key,
                message=self._render_message(resolved),
            )
            return success(
                meta=meta,
                payload=RouteNotificationResult(
                    decision="batched",
                    delivered=False,
                    detail="queued for later batch flush",
                    batched_count=batched_count,
                    notification=resolved,
                ),
            )

        if not request.force and self._is_rate_limited(
            channel=resolved.channel,
            recipient=resolved.recipient,
            now=now,
        ):
            return success(
                meta=meta,
                payload=RouteNotificationResult(
                    decision="suppressed",
                    delivered=False,
                    detail="rate limit exceeded",
                    suppressed_reason="rate_limited",
                    notification=resolved,
                ),
            )

        delivered, delivery_error = self._deliver_signal(notification=resolved)
        if not delivered:
            assert delivery_error is not None
            return failure(meta=meta, errors=[delivery_error])

        self._mark_delivered(
            dedupe_key=resolved.dedupe_key,
            channel=resolved.channel,
            recipient=resolved.recipient,
            now=now,
        )
        return success(
            meta=meta,
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="delivered",
                notification=resolved,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def route_approval_notification(
        self,
        *,
        meta: EnvelopeMeta,
        approval: ApprovalNotificationPayload,
    ) -> Envelope[RouteNotificationResult]:
        """Route one Policy approval proposal as an outbound notification."""
        lines = [
            f"Approval required: {approval.capability_id}@{approval.capability_version}",
            approval.summary,
            f"Token: {approval.proposal_token}",
            f"Trace: {approval.trace_id}",
            f"Invocation: {approval.invocation_id}",
            f"Expires: {approval.expires_at.isoformat()}",
        ]
        return self.route_notification(
            meta=meta,
            actor=approval.actor,
            channel=approval.channel,
            title="Policy approval required",
            message="\n".join(lines),
            dedupe_key=f"approval:{approval.proposal_token}",
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def flush_batch(
        self,
        *,
        meta: EnvelopeMeta,
        batch_key: str,
        actor: str = "operator",
        channel: str = "",
        recipient_e164: str = "",
        sender_e164: str = "",
        title: str = "",
    ) -> Envelope[RouteNotificationResult]:
        """Flush one pending batch and deliver consolidated summary message."""
        request, errors = self._validate_request(
            meta=meta,
            model=FlushBatchRequest,
            payload={
                "batch_key": batch_key,
                "actor": actor,
                "channel": channel,
                "recipient_e164": recipient_e164,
                "sender_e164": sender_e164,
                "title": title,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        items = self._batched_messages.pop(request.batch_key, [])
        if len(items) == 0:
            return success(
                meta=meta,
                payload=RouteNotificationResult(
                    decision="suppressed",
                    delivered=False,
                    detail="no pending batched notifications",
                    suppressed_reason="empty_batch",
                ),
            )

        rendered = self._render_batch_message(batch_key=request.batch_key, items=items)
        return self.route_notification(
            meta=meta,
            actor=request.actor,
            channel=request.channel,
            title=request.title or f"Batch: {request.batch_key}",
            message=rendered,
            recipient_e164=request.recipient_e164,
            sender_e164=request.sender_e164,
            dedupe_key=f"batch:{request.batch_key}:{len(items)}",
            force=True,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Attention Router and Signal adapter readiness state."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        try:
            adapter_health = self._signal_adapter.health()
        except SignalAdapterDependencyError as exc:
            return success(
                meta=meta,
                payload=HealthStatus(
                    service_ready=True,
                    adapter_ready=False,
                    detail=str(exc) or "signal adapter unavailable",
                ),
            )
        except SignalAdapterInternalError as exc:
            return success(
                meta=meta,
                payload=HealthStatus(
                    service_ready=True,
                    adapter_ready=False,
                    detail=str(exc) or "signal adapter internal failure",
                ),
            )

        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=adapter_health.adapter_ready,
                detail=adapter_health.detail,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def correlate_approval_response(
        self,
        *,
        meta: EnvelopeMeta,
        actor: str,
        channel: str,
        message_text: str = "",
        approval_token: str = "",
        reply_to_proposal_token: str = "",
        reaction_to_proposal_token: str = "",
    ) -> Envelope[ApprovalCorrelationPayload]:
        """Normalize deterministic approval-correlation fields for Policy Service."""
        request, errors = self._validate_request(
            meta=meta,
            model=CorrelateApprovalRequest,
            payload={
                "actor": actor,
                "channel": channel,
                "message_text": message_text,
                "approval_token": approval_token,
                "reply_to_proposal_token": reply_to_proposal_token,
                "reaction_to_proposal_token": reaction_to_proposal_token,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        normalized = ApprovalCorrelationPayload(
            actor=request.actor,
            channel=request.channel,
            message_text=request.message_text,
            approval_token=request.approval_token,
            reply_to_proposal_token=request.reply_to_proposal_token,
            reaction_to_proposal_token=request.reaction_to_proposal_token,
        )
        if (
            normalized.approval_token == ""
            and normalized.reply_to_proposal_token == ""
            and normalized.reaction_to_proposal_token == ""
            and normalized.message_text == ""
        ):
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "at least one approval correlator or message_text is required",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )
        return success(meta=meta, payload=normalized)

    def _resolve_notification(
        self, *, request: RouteNotificationRequest
    ) -> RoutedNotification:
        """Resolve defaults and clamp message payload before delivery."""
        resolved_channel = request.channel or self._settings.default_channel
        recipient = (
            request.recipient_e164 or self._settings.default_signal_recipient_e164
        )
        sender = request.sender_e164 or self._settings.default_signal_sender_e164

        message = request.message.strip()
        if len(message) > self._settings.max_message_chars:
            message = message[: self._settings.max_message_chars]

        return RoutedNotification(
            actor=request.actor,
            channel=resolved_channel,
            recipient=recipient,
            sender=sender,
            title=request.title,
            message=message,
            dedupe_key=request.dedupe_key,
            batch_key=request.batch_key,
        )

    def _should_suppress_dedupe(self, *, dedupe_key: str, now: datetime) -> bool:
        """Return True when dedupe key was recently delivered within window."""
        if dedupe_key == "" or self._settings.dedupe_window_seconds == 0:
            return False
        seen = self._recent_dedupe.get(dedupe_key)
        if seen is None:
            return False
        age_seconds = (now - seen).total_seconds()
        return age_seconds <= self._settings.dedupe_window_seconds

    def _enqueue_batch(self, *, batch_key: str, message: str) -> int:
        """Append one message to in-memory batch queue and return queue depth."""
        self._batched_messages[batch_key].append(message)
        return len(self._batched_messages[batch_key])

    def _is_rate_limited(self, *, channel: str, recipient: str, now: datetime) -> bool:
        """Return True when channel/recipient exceeds configured send rate."""
        window = self._settings.rate_limit_window_seconds
        if window == 0:
            return False

        key = (channel, recipient)
        entries = self._recent_by_channel_recipient[key]
        while len(entries) > 0 and (now - entries[0]).total_seconds() > window:
            entries.popleft()

        return len(entries) >= self._settings.rate_limit_max_per_window

    def _mark_delivered(
        self,
        *,
        dedupe_key: str,
        channel: str,
        recipient: str,
        now: datetime,
    ) -> None:
        """Record delivery metadata for dedupe and rate-limiting windows."""
        if dedupe_key != "":
            self._recent_dedupe[dedupe_key] = now
        self._recent_by_channel_recipient[(channel, recipient)].append(now)

    def _deliver_signal(
        self,
        *,
        notification: RoutedNotification,
    ) -> tuple[bool, ErrorDetail | None]:
        """Deliver one normalized notification over Signal adapter."""
        if notification.channel != "signal":
            return False, validation_error(
                f"unsupported channel: {notification.channel}",
                code=codes.INVALID_ARGUMENT,
            )

        try:
            self._signal_adapter.send_message(
                sender_e164=notification.sender,
                recipient_e164=notification.recipient,
                message=self._render_message(notification),
            )
        except SignalAdapterDependencyError as exc:
            return False, dependency_error(
                str(exc) or "signal adapter unavailable",
                code=codes.DEPENDENCY_UNAVAILABLE,
                metadata={"adapter": "adapter_signal"},
            )
        except SignalAdapterInternalError as exc:
            return False, internal_error(
                str(exc) or "signal adapter internal failure",
                metadata={"adapter": "adapter_signal"},
            )

        return True, None

    def _render_message(self, notification: RoutedNotification) -> str:
        """Render title/body into final outbound message text payload."""
        if notification.title.strip() == "":
            return notification.message
        return f"{notification.title}\n\n{notification.message}"

    def _render_batch_message(self, *, batch_key: str, items: list[str]) -> str:
        """Render one compact summary payload for a pending batch key."""
        total = len(items)
        kept = items[: self._settings.batch_summary_max_items]
        lines = [f"{index + 1}. {item}" for index, item in enumerate(kept)]
        if total > len(kept):
            lines.append(f"... and {total - len(kept)} more")
        summary = "\n".join(lines)
        return f"Batch {batch_key}: {total} notifications\n\n{summary}"

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, Any],
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate envelope metadata and operation payload fields."""
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


def map_policy_approval_payload(
    *,
    proposal_token: str,
    capability_id: str,
    capability_version: str,
    summary: str,
    actor: str,
    channel: str,
    trace_id: str,
    invocation_id: str,
    expires_at: datetime,
    metadata: Mapping[str, str] | None = None,
) -> ApprovalNotificationPayload:
    """Build one typed policy approval payload from primitive API fields."""
    del metadata
    return ApprovalNotificationPayload(
        proposal_token=proposal_token,
        capability_id=capability_id,
        capability_version=capability_version,
        summary=summary,
        actor=actor,
        channel=channel,
        trace_id=trace_id,
        invocation_id=invocation_id,
        expires_at=expires_at,
    )
