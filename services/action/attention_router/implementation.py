"""Concrete Attention Router Service implementation."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from lib.shared.config import CoreRuntimeSettings
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
    ErrorDetail,
    codes,
    dependency_error,
    internal_error,
    validation_error,
)
from lib.shared.logging import get_logger, public_api_instrumented
from resources.adapters.signal import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterInternalError,
    SignalRestApiAdapter,
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
    ConsoleResponseMessage,
    HealthStatus,
    RouteNotificationResult,
    RoutedNotification,
)
from services.action.attention_router.service import AttentionRouterService
from services.state.cache_authority.service import CacheAuthorityService
from services.state.memory_authority.service import (
    ConversationalMemoryContext,
    MemoryAuthorityService,
)
from services.action.attention_router.validation import (
    CorrelateApprovalRequest,
    FlushBatchRequest,
    PollConsoleResponseRequest,
    RouteNotificationRequest,
)

_LOGGER = get_logger(__name__)
_POLL_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class _DeliveryResult:
    """Channel-agnostic delivery outcome returned by all delivery paths."""

    sent_timestamp_ms: int


@dataclass(frozen=True, slots=True)
class _PendingBatchItem:
    """One batched outbound plus optional conversational-memory metadata."""

    rendered_message: str
    conversational_memory: ConversationalMemoryContext | None = None


class DefaultAttentionRouterService(AttentionRouterService):
    """Attention Router implementation with dedupe, batching, and rate limits."""

    def __init__(
        self,
        *,
        settings: AttentionRouterServiceSettings,
        signal_adapter: SignalAdapter,
        operator_signal_contact_e164: str,
        signal_receive_e164: str,
        console_response_queue_name: str,
        cache_authority_service: CacheAuthorityService | None = None,
        memory_authority_service: MemoryAuthorityService | None = None,
    ) -> None:
        self._settings = settings
        self._signal_adapter = signal_adapter
        self._operator_signal_contact_e164 = operator_signal_contact_e164.strip()
        self._signal_receive_e164 = signal_receive_e164.strip()
        self._console_response_queue_name = console_response_queue_name
        self._cache_authority_service = cache_authority_service
        self._memory_authority_service = memory_authority_service
        self._recent_dedupe: dict[str, datetime] = {}
        self._recent_by_channel_recipient: dict[tuple[str, str], deque[datetime]] = (
            defaultdict(deque)
        )
        self._batched_messages: dict[str, list[_PendingBatchItem]] = defaultdict(list)

    @classmethod
    def from_settings(
        cls, *, settings: CoreRuntimeSettings
    ) -> "DefaultAttentionRouterService":
        """Build Attention Router + owned Signal adapter from typed settings."""
        service_settings = resolve_attention_router_service_settings(settings)
        adapter_settings = resolve_signal_adapter_settings(settings)
        switchboard_raw = settings.core.service.model_dump(mode="python").get(
            "switchboard", {}
        )
        console_queue = str(
            switchboard_raw.get("console_response_queue_name", "console_outbound")
        )
        return cls(
            settings=service_settings,
            signal_adapter=SignalRestApiAdapter(settings=adapter_settings),
            operator_signal_contact_e164=settings.core.profile.operator.signal_contact_e164,
            signal_receive_e164=adapter_settings.receive_e164,
            console_response_queue_name=console_queue,
            memory_authority_service=None,
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
        dedupe_key: str = "",
        batch_key: str = "",
        force: bool = False,
        conversational_memory: ConversationalMemoryContext | None = None,
    ) -> Envelope[RouteNotificationResult]:
        """Route one outbound notification and apply policy-neutral constraints."""
        normalized_conversational_memory = self._normalize_conversational_memory(
            conversational_memory=conversational_memory
        )
        request, errors = self._validate_request(
            meta=meta,
            model=RouteNotificationRequest,
            payload={
                "actor": actor,
                "channel": channel,
                "title": title,
                "message": message,
                "dedupe_key": dedupe_key,
                "batch_key": batch_key,
                "force": force,
                "conversational_memory": (
                    None
                    if normalized_conversational_memory is None
                    else normalized_conversational_memory.model_dump(mode="python")
                ),
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
                conversational_memory=request.conversational_memory,
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

        delivery, delivery_error = self._deliver(notification=resolved)
        if delivery is None:
            assert delivery_error is not None
            return failure(meta=meta, errors=[delivery_error])

        self._mark_delivered(
            dedupe_key=resolved.dedupe_key,
            channel=resolved.channel,
            recipient=resolved.recipient,
            now=now,
        )
        persistence_error = self._persist_conversational_outbound(
            meta=meta,
            notification=resolved,
            rendered_message=self._render_message(resolved),
            conversational_memory=request.conversational_memory,
            delivered_at_ms=delivery.sent_timestamp_ms,
        )
        if persistence_error is not None:
            return failure(meta=meta, errors=[persistence_error])
        return success(
            meta=meta,
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="delivered",
                delivery_timestamp_ms=delivery.sent_timestamp_ms,
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
        result = self.route_notification(
            meta=meta,
            actor=approval.actor,
            channel=approval.channel,
            title="Policy approval required",
            message="\n".join(lines),
            dedupe_key=f"approval:{approval.proposal_token}",
        )
        if (
            result.ok
            and result.payload is not None
            and result.payload.value.delivery_timestamp_ms is not None
        ):
            persist_error = self._persist_approval_timestamp_correlation(
                meta=meta,
                approval=approval,
                delivery_timestamp_ms=result.payload.value.delivery_timestamp_ms,
            )
            if persist_error is not None:
                return failure(meta=meta, errors=[persist_error])
        return result

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

        rendered = self._render_batch_message(
            batch_key=request.batch_key,
            items=[item.rendered_message for item in items],
        )
        conversational_memory = self._batch_conversational_memory(items=items)
        result = self.route_notification(
            meta=meta,
            actor=request.actor,
            channel=request.channel,
            title=request.title or f"Batch: {request.batch_key}",
            message=rendered,
            dedupe_key=f"batch:{request.batch_key}:{len(items)}",
            force=True,
            conversational_memory=conversational_memory,
        )
        return result

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Attention Router self-readiness state."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=True,
                detail="ok",
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def poll_console_response(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[ConsoleResponseMessage | None]:
        """Pop the next queued console response, optionally long-polling."""
        request, errors = self._validate_request(
            meta=meta,
            model=PollConsoleResponseRequest,
            payload={"wait_timeout_seconds": wait_timeout_seconds},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        if self._cache_authority_service is None:
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "cache authority unavailable for console response polling",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                    )
                ],
            )

        deadline = time.monotonic() + request.wait_timeout_seconds
        while True:
            popped = self._cache_authority_service.pop_queue(
                meta=meta,
                component_id="service_switchboard",
                queue=self._console_response_queue_name,
            )
            if not popped.ok:
                return failure(meta=meta, errors=popped.errors)

            if popped.payload is not None and popped.payload.value is not None:
                entry = popped.payload.value
                try:
                    response = ConsoleResponseMessage.model_validate(entry.value)
                except ValidationError:
                    return failure(
                        meta=meta,
                        errors=[
                            internal_error(
                                "queued console response payload is invalid",
                                code=codes.INTERNAL_ERROR,
                            )
                        ],
                    )
                return success(meta=meta, payload=response)

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

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def resolve_approval_notification_proposal_token(
        self,
        *,
        meta: EnvelopeMeta,
        channel: str,
        target_timestamp_ms: int,
    ) -> Envelope[str | None]:
        """Resolve one approval-notification Signal timestamp to a proposal token."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        resolved_channel = channel.strip()
        if resolved_channel == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error("channel is required", code=codes.INVALID_ARGUMENT)
                ],
            )

        lookup_meta = new_meta(
            kind=meta.kind,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )
        token = self._load_approval_timestamp_correlation(
            meta=lookup_meta,
            channel=resolved_channel,
            target_timestamp_ms=target_timestamp_ms,
        )
        if isinstance(token, ErrorDetail):
            return failure(meta=meta, errors=[token])
        return success(meta=meta, payload=token)

    def _resolve_notification(
        self,
        *,
        request: RouteNotificationRequest,
    ) -> RoutedNotification:
        """Resolve defaults and clamp message payload before delivery."""
        resolved_channel = request.channel or self._settings.default_channel
        if resolved_channel == "console":
            recipient = "console"
            sender = "brain"
        else:
            recipient = self._operator_signal_contact_e164
            sender = self._signal_receive_e164

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

    @staticmethod
    def _normalize_conversational_memory(
        *,
        conversational_memory: object,
    ) -> ConversationalMemoryContext | None:
        """Normalize one optional conversational-memory payload into MAS-owned shape."""
        if conversational_memory is None:
            return None
        if isinstance(conversational_memory, ConversationalMemoryContext):
            return conversational_memory
        return ConversationalMemoryContext.model_validate(conversational_memory)

    def _persist_approval_timestamp_correlation(
        self,
        *,
        meta: EnvelopeMeta,
        approval: ApprovalNotificationPayload,
        delivery_timestamp_ms: int,
    ) -> ErrorDetail | None:
        """Persist one delivery timestamp -> proposal token mapping with approval TTL."""
        if self._cache_authority_service is None:
            return None

        ttl_seconds = max(
            1,
            int((approval.expires_at - datetime.now(UTC)).total_seconds()),
        )
        result = self._cache_authority_service.set_value(
            meta=meta,
            component_id=str(SERVICE_COMPONENT_ID),
            key=self._approval_timestamp_cache_key(
                channel=approval.channel,
                timestamp_ms=delivery_timestamp_ms,
            ),
            value={"proposal_token": approval.proposal_token},
            ttl_seconds=ttl_seconds,
        )
        if result.ok:
            return None
        return dependency_error(
            "approval timestamp correlation persistence failed",
            metadata={
                "channel": approval.channel,
                "proposal_token": approval.proposal_token,
                "timestamp_ms": str(delivery_timestamp_ms),
            },
        )

    def _load_approval_timestamp_correlation(
        self,
        *,
        meta: EnvelopeMeta,
        channel: str,
        target_timestamp_ms: int,
    ) -> str | None | ErrorDetail:
        """Load one persisted delivery timestamp -> proposal token mapping."""
        if self._cache_authority_service is None:
            return None

        result = self._cache_authority_service.get_value(
            meta=meta,
            component_id=str(SERVICE_COMPONENT_ID),
            key=self._approval_timestamp_cache_key(
                channel=channel,
                timestamp_ms=target_timestamp_ms,
            ),
        )
        if not result.ok:
            return dependency_error(
                "approval timestamp correlation lookup failed",
                metadata={
                    "channel": channel,
                    "timestamp_ms": str(target_timestamp_ms),
                },
            )
        if result.payload is None:
            return None
        payload_value = result.payload.value
        if payload_value is None:
            return None
        value = payload_value.value
        if not isinstance(value, Mapping):
            return None
        token = str(value.get("proposal_token", "")).strip()
        return token or None

    def _persist_conversational_outbound(
        self,
        *,
        meta: EnvelopeMeta,
        notification: RoutedNotification,
        rendered_message: str,
        conversational_memory: ConversationalMemoryContext | None,
        delivered_at_ms: int | None,
    ) -> ErrorDetail | None:
        """Persist one actually sent conversational outbound into MAS."""
        if conversational_memory is None:
            return None
        if not self._is_conversational_channel(channel=notification.channel):
            return None
        if self._memory_authority_service is None:
            return None
        candidate_meta = new_meta(
            kind=meta.kind,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )
        candidate = self._memory_authority_service.record_outbound_candidate(
            meta=candidate_meta,
            session_id=conversational_memory.session_id,
            content=rendered_message,
            model=conversational_memory.model,
            provider=conversational_memory.provider,
            token_count=conversational_memory.token_count,
            reasoning_level=conversational_memory.reasoning_level,
        )
        if not candidate.ok or candidate.payload is None:
            return dependency_error(
                "memory persistence failed for conversational outbound",
                metadata={"channel": notification.channel},
            )
        delivery = self._memory_authority_service.record_outbound_delivery(
            meta=candidate_meta,
            session_id=conversational_memory.session_id,
            turn_id=candidate.payload.value.id,
            delivered=True,
        )
        if delivery.ok:
            return None
        return dependency_error(
            "memory delivery persistence failed for conversational outbound",
            metadata={
                "channel": notification.channel,
                "timestamp_ms": "" if delivered_at_ms is None else str(delivered_at_ms),
            },
        )

    @staticmethod
    def _approval_timestamp_cache_key(*, channel: str, timestamp_ms: int) -> str:
        """Return the component-local cache key for one approval delivery timestamp."""
        return f"approval-timestamp:{channel}:{timestamp_ms}"

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
        self._batched_messages[batch_key].append(
            _PendingBatchItem(rendered_message=message)
        )
        return len(self._batched_messages[batch_key])

    def _enqueue_batch(
        self,
        *,
        batch_key: str,
        message: str,
        conversational_memory: ConversationalMemoryContext | None,
    ) -> int:
        """Append one routed message to the pending batch queue and return depth."""
        self._batched_messages[batch_key].append(
            _PendingBatchItem(
                rendered_message=message,
                conversational_memory=conversational_memory,
            )
        )
        return len(self._batched_messages[batch_key])

    def _batch_conversational_memory(
        self, *, items: list[_PendingBatchItem]
    ) -> ConversationalMemoryContext | None:
        """Return one stable conversational context for a flushed batch when possible."""
        contexts = [
            item.conversational_memory
            for item in items
            if item.conversational_memory is not None
        ]
        if len(contexts) == 0:
            return None
        first = contexts[0]
        if any(item != first for item in contexts[1:]):
            return None
        return first

    def _is_conversational_channel(self, *, channel: str) -> bool:
        """Return True when one channel participates in unified assistant dialogue."""
        return channel in self._settings.conversational_channels

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

    def _deliver(
        self,
        *,
        notification: RoutedNotification,
    ) -> tuple[_DeliveryResult | None, ErrorDetail | None]:
        """Deliver one normalized notification via the appropriate channel."""
        if notification.channel == "signal":
            return self._deliver_via_signal(notification=notification)
        if notification.channel == "console":
            return self._deliver_via_console(notification=notification)
        return None, validation_error(
            f"unsupported channel: {notification.channel}",
            code=codes.INVALID_ARGUMENT,
        )

    def _deliver_via_signal(
        self,
        *,
        notification: RoutedNotification,
    ) -> tuple[_DeliveryResult | None, ErrorDetail | None]:
        """Deliver one normalized notification over Signal adapter."""
        try:
            delivery = self._signal_adapter.send_message(
                sender_e164=notification.sender,
                recipient_e164=notification.recipient,
                message=self._render_message(notification),
            )
        except SignalAdapterDependencyError as exc:
            return None, dependency_error(
                str(exc) or "signal adapter unavailable",
                code=codes.DEPENDENCY_UNAVAILABLE,
                metadata={"adapter": "adapter_signal"},
            )
        except SignalAdapterInternalError as exc:
            return None, internal_error(
                str(exc) or "signal adapter internal failure",
                metadata={"adapter": "adapter_signal"},
            )

        return _DeliveryResult(sent_timestamp_ms=delivery.sent_timestamp_ms), None

    def _deliver_via_console(
        self,
        *,
        notification: RoutedNotification,
    ) -> tuple[_DeliveryResult | None, ErrorDetail | None]:
        """Deliver one normalized notification to the console outbound queue."""
        if self._cache_authority_service is None:
            return None, dependency_error(
                "cache authority unavailable for console delivery",
                code=codes.DEPENDENCY_UNAVAILABLE,
            )

        timestamp_ms = int(time.time() * 1000)
        result = self._cache_authority_service.push_queue(
            meta=new_meta(
                kind=EnvelopeKind.EVENT,
                source=str(SERVICE_COMPONENT_ID),
                principal="system",
            ),
            component_id="service_switchboard",
            queue=self._console_response_queue_name,
            value={
                "message": self._render_message(notification),
                "timestamp_ms": timestamp_ms,
            },
        )
        if not result.ok:
            return None, dependency_error(
                "console response queue push failed",
                code=codes.DEPENDENCY_UNAVAILABLE,
            )

        return _DeliveryResult(sent_timestamp_ms=timestamp_ms), None

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
