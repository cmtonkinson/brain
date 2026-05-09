"""Default Relay implementation composing inbound + outbound paths."""

from __future__ import annotations

from lib.shared.envelope import Envelope, EnvelopeMeta, success, validate_meta, failure
from lib.shared.inbound_message import InboundMessage
from lib.shared.errors import codes, validation_error
from lib.shared.logging import get_logger, public_api_instrumented
from services.effect.relay._outbound.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    ConsoleResponseMessage,
    RouteNotificationResult,
)
from services.effect.relay._outbound.implementation import (
    DefaultRelayOutboundService,
)
from services.effect.relay._inbound.domain import (
    IngestResult,
    RegisterInboundCallbacksResult,
)
from services.effect.relay._inbound.implementation import DefaultRelayInboundService
from services.effect.relay.component import SERVICE_COMPONENT_ID
from services.effect.relay.domain import RelayHealthStatus
from services.effect.relay.service import RelayService
from services.reason.recall.service import ConversationalMemoryContext

_LOGGER = get_logger(__name__)


class DefaultRelayService(RelayService):
    """Bidirectional Relay composing one inbound and one outbound delegate."""

    def __init__(
        self,
        *,
        inbound: DefaultRelayInboundService,
        outbound: DefaultRelayOutboundService,
    ) -> None:
        self._inbound = inbound
        self._outbound = outbound

    # --- Inbound delegation ---

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def ingest_inbound_message(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> Envelope[IngestResult]:
        return self._inbound.ingest_inbound_message(meta=meta, message=message)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def register_inbound_callbacks(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[RegisterInboundCallbacksResult]:
        return self._inbound.register_inbound_callbacks(meta=meta)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def poll_operator_instruction(
        self, *, meta: EnvelopeMeta, wait_timeout_seconds: float = 0.0
    ) -> Envelope[InboundMessage | None]:
        return self._inbound.poll_operator_instruction(
            meta=meta, wait_timeout_seconds=wait_timeout_seconds
        )

    # --- Outbound delegation ---

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
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
        return self._outbound.route_notification(
            meta=meta,
            actor=actor,
            channel=channel,
            title=title,
            message=message,
            dedupe_key=dedupe_key,
            batch_key=batch_key,
            force=force,
            conversational_memory=conversational_memory,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def route_approval_notification(
        self,
        *,
        meta: EnvelopeMeta,
        approval: ApprovalNotificationPayload,
    ) -> Envelope[RouteNotificationResult]:
        return self._outbound.route_approval_notification(meta=meta, approval=approval)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def flush_batch(
        self,
        *,
        meta: EnvelopeMeta,
        batch_key: str,
        actor: str = "operator",
        channel: str = "",
        title: str = "",
    ) -> Envelope[RouteNotificationResult]:
        return self._outbound.flush_batch(
            meta=meta,
            batch_key=batch_key,
            actor=actor,
            channel=channel,
            title=title,
        )

    # --- Approval correlation delegation ---

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
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
        return self._outbound.correlate_approval_response(
            meta=meta,
            actor=actor,
            channel=channel,
            message_text=message_text,
            approval_token=approval_token,
            reply_to_proposal_token=reply_to_proposal_token,
            reaction_to_proposal_token=reaction_to_proposal_token,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def resolve_approval_notification_proposal_token(
        self,
        *,
        meta: EnvelopeMeta,
        channel: str,
        target_timestamp_ms: int,
    ) -> Envelope[str | None]:
        return self._outbound.resolve_approval_notification_proposal_token(
            meta=meta,
            channel=channel,
            target_timestamp_ms=target_timestamp_ms,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def poll_console_response(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[ConsoleResponseMessage | None]:
        return self._outbound.poll_console_response(
            meta=meta,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    # --- Aggregated health ---

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[RelayHealthStatus]:
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )
        inbound = self._inbound.health(meta=meta).payload
        outbound = self._outbound.health(meta=meta).payload
        inbound_ready = (
            bool(inbound.value.service_ready) if inbound is not None else False
        )
        outbound_ready = (
            bool(outbound.value.service_ready) if outbound is not None else False
        )
        adapter_ready = (
            bool(outbound.value.adapter_ready) if outbound is not None else False
        )
        return success(
            meta=meta,
            payload=RelayHealthStatus(
                service_ready=inbound_ready and outbound_ready,
                inbound_ready=inbound_ready,
                outbound_ready=outbound_ready,
                adapter_ready=adapter_ready,
                detail="ok" if (inbound_ready and outbound_ready) else "degraded",
            ),
        )
