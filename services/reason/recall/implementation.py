"""Concrete Recall Service implementation."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
    validate_service_request,
)
from lib.shared.errors import (
    codes,
    dependency_error,
    not_found_error,
    validation_error,
)
from lib.shared.ids import ulid_str_to_bytes
from lib.shared.logging import get_logger, public_api_instrumented
from resources.substrates.postgres.errors import (
    is_postgres_error,
    normalize_postgres_error,
)
from services.effect.language.service import LanguageService
from services.reason.recall.assembler import ContextAssembler
from services.reason.recall.component import SERVICE_COMPONENT_ID
from services.reason.recall.config import (
    RecallSettings,
    resolve_recall_settings,
)
from services.reason.recall.data import (
    MemoryRepository,
    MemoryPostgresRuntime,
    PostgresMemoryRepository,
)
from services.reason.recall.dialogue import DialogueModule
from services.reason.recall.domain import (
    ContextBlock,
    FocusRecord,
    HealthStatus,
    InboundInstructionRecord,
    SessionRecord,
    TurnContext,
    TurnRecord,
)
from services.reason.recall.focus import FocusCompactionError, FocusModule
from services.reason.recall.service import RecallService

_LOGGER = get_logger(__name__)


class _SessionRequest(BaseModel):
    """Validate one request carrying a required session id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        """Require canonical ULID format for session id."""
        ulid_str_to_bytes(value)
        return value


class _AssembleRequest(_SessionRequest):
    """Validate assemble-context request payload."""

    message: str

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        """Require non-empty inbound message content."""
        if value.strip() == "":
            raise ValueError("message is required")
        return value


class _RecordResponseRequest(_SessionRequest):
    """Validate outbound response-record request payload."""

    content: str
    model: str
    provider: str
    token_count: int
    reasoning_level: str

    @field_validator("content", "model", "provider", "reasoning_level")
    @classmethod
    def _validate_text_fields(cls, value: str, info: object) -> str:
        """Require non-empty text fields on response recording."""
        normalized = value.strip()
        if normalized == "":
            field_name = getattr(info, "field_name", "field")
            raise ValueError(f"{field_name} is required")
        return normalized

    @field_validator("token_count")
    @classmethod
    def _validate_token_count(cls, value: int) -> int:
        """Require non-negative token_count metadata."""
        if value < 0:
            raise ValueError("token_count must be >= 0")
        return value


class _OutboundDeliveryRequest(_SessionRequest):
    """Validate outbound delivery recording payload."""

    turn_id: str
    delivered: bool

    @field_validator("turn_id")
    @classmethod
    def _validate_turn_id(cls, value: str) -> str:
        """Require canonical ULID format for turn id."""
        ulid_str_to_bytes(value)
        return value


class _UpdateFocusRequest(_SessionRequest):
    """Validate explicit focus update payload."""

    content: str


class DefaultRecallService(RecallService):
    """Default Recall implementation with Postgres-backed state and Language side effects."""

    def __init__(
        self,
        *,
        settings: RecallSettings,
        runtime: MemoryPostgresRuntime,
        language_model: LanguageService,
        repository: MemoryRepository | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        self._repository = (
            PostgresMemoryRepository(runtime.schema_sessions)
            if repository is None
            else repository
        )
        self._dialogue = DialogueModule(
            repository=self._repository,
            language_model=language_model,
            settings=settings,
        )
        self._focus = FocusModule(
            repository=self._repository,
            language_model=language_model,
            settings=settings,
        )
        self._assembler = ContextAssembler(
            focus=self._focus,
            dialogue=self._dialogue,
        )

    @classmethod
    def from_settings(
        cls,
        *,
        settings: CoreRuntimeSettings,
        language_model: LanguageService,
    ) -> "DefaultRecallService":
        """Build Recall from typed settings and injected Language public API dependency."""
        service_settings = resolve_recall_settings(settings)
        runtime = MemoryPostgresRuntime.from_settings(settings)
        return cls(
            settings=service_settings,
            runtime=runtime,
            language_model=language_model,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def record_inbound_turn(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        message: str,
        instruction: InboundInstructionRecord | None = None,
    ) -> Envelope[TurnRecord]:
        """Persist one inbound turn and return the recorded turn row."""
        request, errors = validate_service_request(
            meta=meta,
            model=_AssembleRequest,
            payload={"session_id": session_id, "message": message},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            session = self._repository.get_session(session_id=request.session_id)
            if session is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)

            inbound_at = _inbound_at(instruction)
            episode_id = self._repository.resolve_conversation_episode(
                session_id=request.session_id,
                inbound_at=inbound_at,
                idle_seconds=self._settings.conversation_episode_idle_seconds,
            )
            if episode_id is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)

            turn = self._dialogue.append_inbound(
                session_id=request.session_id,
                content=request.message,
                trace_id=meta.trace_id,
                conversation_episode_id=episode_id,
                principal=meta.principal,
                instruction=instruction,
            )
            return success(meta=meta, payload=turn)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="record_inbound_turn", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def assemble_snapshot(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        exclude_latest: bool = True,
    ) -> Envelope[ContextBlock]:
        """Return the historical Recall context snapshot for one session."""
        request, errors = validate_service_request(
            meta=meta,
            model=_SessionRequest,
            payload={"session_id": session_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            session = self._repository.get_session(session_id=request.session_id)
            if session is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)

            exclude_turn_id: str | None = None
            if exclude_latest:
                latest = self._repository.get_latest_turn(session_id=request.session_id)
                if latest is not None:
                    exclude_turn_id = latest.id
            context = self._assembler.assemble(
                meta=meta,
                session_id=request.session_id,
                exclude_turn_id=exclude_turn_id,
            )
            return success(meta=meta, payload=context)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="assemble_snapshot", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def record_outbound_candidate(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ) -> Envelope[TurnRecord]:
        """Persist one outbound candidate turn and return the recorded row."""
        request, errors = validate_service_request(
            meta=meta,
            model=_RecordResponseRequest,
            payload={
                "session_id": session_id,
                "content": content,
                "model": model,
                "provider": provider,
                "token_count": token_count,
                "reasoning_level": reasoning_level,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            session = self._repository.get_session(session_id=request.session_id)
            if session is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)

            episode_id = session.current_conversation_episode_id or ""
            turn = self._dialogue.append_outbound(
                session_id=request.session_id,
                content=request.content,
                model=request.model,
                provider=request.provider,
                token_count=request.token_count,
                reasoning_level=request.reasoning_level,
                trace_id=meta.trace_id,
                conversation_episode_id=episode_id,
                principal=meta.principal,
            )
            return success(meta=meta, payload=turn)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="record_outbound_candidate", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id", "turn_id"),
    )
    def record_outbound_delivery(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        turn_id: str,
        delivered: bool,
    ) -> Envelope[bool]:
        """Record delivery status for one outbound turn."""
        request, errors = validate_service_request(
            meta=meta,
            model=_OutboundDeliveryRequest,
            payload={
                "session_id": session_id,
                "turn_id": turn_id,
                "delivered": delivered,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            session = self._repository.get_session(
                session_id=request.session_id,
            )
            if session is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)
            _ = self._repository.get_latest_turn(session_id=request.session_id)
            return success(meta=meta, payload=request.delivered)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="record_outbound_delivery", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def assemble_context(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        message: str,
        instruction: InboundInstructionRecord | None = None,
    ) -> Envelope[TurnContext]:
        """Resolve active session, record inbound turn, and return assembled context."""
        resolved_session = self._repository.get_latest_session()
        if resolved_session is None:
            resolved_session = self._repository.create_session()
        resolved_session_id = resolved_session.id
        inbound = self.record_inbound_turn(
            meta=meta,
            session_id=resolved_session_id,
            message=message,
            instruction=instruction,
        )
        if not inbound.ok:
            return failure(meta=meta, errors=inbound.errors)
        assert inbound.payload is not None
        snapshot = self.assemble_snapshot(meta=meta, session_id=resolved_session_id)
        if not snapshot.ok:
            return failure(meta=meta, errors=snapshot.errors)
        assert snapshot.payload is not None
        return success(
            meta=meta,
            payload=TurnContext(
                session_id=resolved_session_id,
                inbound_turn=inbound.payload.value,
                context=snapshot.payload.value,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def record_response(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ) -> Envelope[bool]:
        """Persist one outbound response turn and mark it delivered."""
        candidate = self.record_outbound_candidate(
            meta=meta,
            session_id=session_id,
            content=content,
            model=model,
            provider=provider,
            token_count=token_count,
            reasoning_level=reasoning_level,
        )
        if not candidate.ok:
            return failure(meta=meta, errors=candidate.errors)
        return success(meta=meta, payload=True)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def update_focus(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        content: str,
    ) -> Envelope[FocusRecord]:
        """Update focus content and enforce configured token budget."""
        request, errors = validate_service_request(
            meta=meta,
            model=_UpdateFocusRequest,
            payload={"session_id": session_id, "content": content},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._focus.update(
                meta=meta,
                session_id=request.session_id,
                content=request.content,
            )
            return success(meta=meta, payload=record)
        except KeyError:
            return self._session_not_found(meta=meta, session_id=request.session_id)
        except FocusCompactionError as exc:
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc),
                        code=codes.DEPENDENCY_FAILURE,
                        metadata={"dependency": "service_language"},
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="update_focus", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def clear_session(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[bool]:
        """Advance dialogue pointer to latest turn and clear focus state."""
        request, errors = validate_service_request(
            meta=meta,
            model=_SessionRequest,
            payload={"session_id": session_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            latest = self._repository.get_latest_turn(session_id=request.session_id)
            updated = self._repository.clear_session(
                session_id=request.session_id,
                dialogue_start_turn_id=None if latest is None else latest.id,
            )
            if updated is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)
            return success(meta=meta, payload=True)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="clear_session", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def compact_dialogue(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[SessionRecord]:
        """Force-summarize all visible turns and advance dialogue frontier."""
        request, errors = validate_service_request(
            meta=meta,
            model=_SessionRequest,
            payload={"session_id": session_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            focus = self._focus.read(session_id=request.session_id)
            updated = self._dialogue.compact(
                meta=meta,
                session_id=request.session_id,
                focus=focus,
            )
            if updated is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)
            return success(meta=meta, payload=updated)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="compact_dialogue", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def create_session(self, *, meta: EnvelopeMeta) -> Envelope[SessionRecord]:
        """Create and return one new session."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        try:
            record = self._repository.create_session()
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="create_session", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def get_latest_or_create_session(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[SessionRecord]:
        """Return latest session when present, otherwise create one new session."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        try:
            record = self._repository.get_latest_session()
            if record is None:
                record = self._repository.create_session()
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="get_latest_or_create_session", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("session_id",),
    )
    def get_session(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[SessionRecord]:
        """Read one session by id."""
        request, errors = validate_service_request(
            meta=meta,
            model=_SessionRequest,
            payload={"session_id": session_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._repository.get_session(session_id=request.session_id)
            if record is None:
                return self._session_not_found(meta=meta, session_id=request.session_id)
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="get_session", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def list_inbound_turns_after(
        self,
        *,
        meta: EnvelopeMeta,
        after_id: str | None,
        limit: int = 100,
    ) -> Envelope[tuple[TurnRecord, ...]]:
        """List inbound turns across all sessions created after a given turn id."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        clamped_limit = max(1, min(limit, 500))

        try:
            records = self._repository.list_inbound_turns_after(
                after_id=after_id,
                limit=clamped_limit,
            )
            return success(meta=meta, payload=tuple(records))
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="list_inbound_turns_after", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Recall and Postgres substrate readiness."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        try:
            substrate_ready = self._runtime.is_healthy()
            return success(
                meta=meta,
                payload=HealthStatus(
                    service_ready=True,
                    substrate_ready=substrate_ready,
                    detail="ok" if substrate_ready else "postgres ping returned false",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return success(
                meta=meta,
                payload=HealthStatus(
                    service_ready=True,
                    substrate_ready=False,
                    detail=str(exc) or "postgres ping failed",
                ),
            )

    def _session_not_found(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[object]:
        """Build canonical not-found envelope for session lookups."""
        return failure(
            meta=meta,
            errors=[
                not_found_error(
                    "session not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"session_id": session_id},
                )
            ],
        )

    def _handle_exception(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        exc: Exception,
    ) -> Envelope[object]:
        """Normalize repository and runtime exceptions to envelope errors."""
        if is_postgres_error(exc):
            return failure(meta=meta, errors=[normalize_postgres_error(exc)])

        _LOGGER.warning(
            "Recall operation failed due to dependency error: operation=%s exception_type=%s",
            operation,
            type(exc).__name__,
            exc_info=exc,
        )
        return failure(
            meta=meta,
            errors=[
                dependency_error(
                    f"{operation} failed",
                    code=codes.DEPENDENCY_FAILURE,
                    metadata={codes.EXCEPTION_TYPE_KEY: type(exc).__name__},
                )
            ],
        )


def _inbound_at(instruction: InboundInstructionRecord | None) -> datetime:
    """Return the operator-message timestamp used for episode rotation."""
    if instruction is None or instruction.timestamp_ms is None:
        return datetime.now(UTC)
    try:
        return datetime.fromtimestamp(instruction.timestamp_ms / 1000, tz=UTC)
    except OSError, OverflowError, ValueError:
        return datetime.now(UTC)
