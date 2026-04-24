"""Concrete Execution Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from lib.shared.config import (
    CoreRuntimeSettings,
    component_settings_for,
    runtime_config_directory,
)
from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
    new_meta,
    EnvelopeKind,
)
from lib.shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    internal_error,
    not_found_error,
    validation_error,
)
from services.effect.execution.op_handler_bridge import OpHandlerBridgeError
from lib.shared.ids import generate_ulid_str
from lib.shared.logging import get_logger, public_api_instrumented
from lib.shared.manifest import get_registry
from services.effect.execution.mcp_op_handler_bridge import (
    is_mcp_call_target,
    parse_mcp_call_target,
)
from services.effect.execution.component import SERVICE_COMPONENT_ID
from services.effect.execution.config import ExecutionSettings
from services.effect.execution.domain import (
    DynamicOpClassificationRow,
    NativeOpManifest,
    OpDescriptor,
    ExecutionHealthStatus,
    OpExecutionResponse,
    OpDiscoveryStateRow,
    OpInvocationAuditRow,
    OpInvocationMetadata,
    OpInvokeResult,
    OpManifest,
    OpPolicySummary,
    OpSearchHit,
    ToolSystemHint,
)
from services.effect.execution.data.repository import (
    InMemoryDynamicOpClassificationRepository,
    InMemoryOpDiscoveryStateRepository,
    InMemoryOpInvocationAuditRepository,
)
from services.effect.execution.interfaces import (
    DynamicOpClassificationRepository,
    OpDiscoveryStateRepository,
    OpInvocationAuditRepository,
)
from services.effect.execution.registry import (
    OpRegistry,
    OpRuntime,
)
from services.effect.language.service import LanguageService
from services.effect.execution.service import ExecutionService
from services.reason.policy.domain import (
    OpInvocationRequest,
    OpPolicyInput,
    InvocationPolicyInput,
    PolicyDecision,
    PolicyExecutionResult,
    UNKNOWN_CALL_TARGET_REASON,
)
from services.reason.policy.service import PolicyService
from services.state.embedding.service import EmbeddingService

_LOGGER = get_logger(__name__)
_REASON_DYNAMIC_OP_UNCLASSIFIED = "dynamic_op_unclassified"
_REASON_DEPENDENCY_ERROR = "dependency_error"
_REASON_NOT_FOUND = "not_found"
_OP_DISCOVERY_SOURCE_REFERENCE = "op-engine:discovery"
_OP_DISCOVERY_SOURCE_TYPE = "op_catalog"
_OP_DISCOVERY_PRINCIPAL = "system"
_OP_EMBEDDING_VERSION = "op_embedding"
_OP_EMBEDDING_PROFILE = "op_embedding"
_PREPOLICY_DENY_ID = "prepolicy-deny"
_PLACEHOLDER_DECISION_ID = "placeholder"


@dataclass(frozen=True)
class _InvokeInternalResult:
    """Internal invocation result used by both public and nested invoke paths."""

    allowed: bool
    output: dict[str, Any] | None
    errors: tuple[ErrorDetail, ...]
    policy: OpPolicySummary
    proposal_token: str
    op_version: str


@dataclass(frozen=True)
class _OpDiscoveryDocument:
    """Stable derived discovery document content and digest for one op."""

    text: str
    content_digest: str


@dataclass(frozen=True)
class _NestedRuntime(OpRuntime):
    """Runtime helper passed to handlers for nested op invocation."""

    engine: "DefaultExecutionService"
    parent_request: OpInvocationRequest

    def invoke_nested(
        self,
        *,
        op_id: str,
        input_payload: dict[str, Any],
    ) -> OpExecutionResponse:
        child_meta = self.parent_request.metadata.model_copy(
            update={
                "parent_id": self.parent_request.metadata.envelope_id,
                "envelope_id": generate_ulid_str(),
            }
        )
        child_invocation = InvocationPolicyInput(
            actor=self.parent_request.invocation.actor,
            source=self.parent_request.invocation.source,
            channel=self.parent_request.invocation.channel,
            invocation_id=generate_ulid_str(),
            parent_invocation_id=self.parent_request.invocation.invocation_id,
        )

        nested = self.engine._invoke_internal(
            meta=child_meta,
            op_id=op_id,
            input_payload=input_payload,
            invocation=child_invocation,
        )
        if not nested.allowed:
            return OpExecutionResponse(output=None)
        return OpExecutionResponse(output=nested.output)


class DefaultExecutionService(ExecutionService):
    """Default Execution implementation enforcing policy-gated op execution."""

    def __init__(
        self,
        *,
        settings: ExecutionSettings,
        policy_service: PolicyService,
        language_service: LanguageService | None = None,
        embedding_service: EmbeddingService | None = None,
        registry: OpRegistry,
        mcp_adapter: object | None = None,
        mcp_overrides: dict[str, dict[str, object]] | None = None,
        audit_repository: OpInvocationAuditRepository | None = None,
        discovery_state_repository: OpDiscoveryStateRepository | None = None,
        dynamic_op_classification_repository: DynamicOpClassificationRepository
        | None = None,
        op_embedding_profile_fingerprint: str = "",
    ) -> None:
        self._settings = settings
        self._policy_service = policy_service
        self._language_service = language_service
        self._embedding_service = embedding_service
        self._registry = registry
        self._mcp_adapter = mcp_adapter
        self._mcp_overrides = dict(mcp_overrides or {})
        self._audit_repository = (
            audit_repository or InMemoryOpInvocationAuditRepository()
        )
        self._discovery_state_repository = (
            discovery_state_repository or InMemoryOpDiscoveryStateRepository()
        )
        self._dynamic_op_classification_repository = (
            dynamic_op_classification_repository
            or InMemoryDynamicOpClassificationRepository()
        )
        self._op_embedding_profile_fingerprint = op_embedding_profile_fingerprint

    def _load_ops(self) -> None:
        """Discover op manifests across configured roots and the user overlay."""
        self._registry.discover(roots=self._effective_discovery_roots())

    def _effective_discovery_roots(self) -> tuple[Path, ...]:
        """Return ordered discovery roots: configured roots + user overlay.

        Later roots overlay earlier ones, so the user overlay (located at
        ``runtime_config_directory()/ops``) always takes precedence over
        built-in roots when an op_id collides.
        """
        configured = tuple(
            Path(root).expanduser() for root in self._settings.discovery_roots
        )
        return configured + (runtime_config_directory() / "ops",)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[ExecutionHealthStatus]:
        """Return service readiness and local registry/audit counters."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        return success(
            meta=meta,
            payload=ExecutionHealthStatus(
                service_ready=True,
                policy_ready=True,
                discovered_ops=self._registry.count(),
                invocation_audit_rows=self._audit_repository.count(),
                detail="ok",
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def describe_ops(self, *, meta: EnvelopeMeta) -> Envelope[tuple[OpDescriptor, ...]]:
        """Return descriptors for all registered ops."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        descriptors = tuple(
            self._descriptor_from_manifest(manifest)
            for manifest in self._registry.list_manifests()
        )
        return success(meta=meta, payload=descriptors)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def list_always_on_ops(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[OpDescriptor, ...]]:
        """Return full descriptors for the configured always-on ops."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        descriptors: list[OpDescriptor] = []
        for op_id in self._settings.always_on_op_ids:
            manifest = self._registry.resolve_manifest(op_id=op_id)
            if manifest is None:
                continue
            descriptors.append(self._descriptor_from_manifest(manifest))
        return success(meta=meta, payload=tuple(descriptors))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def search_ops(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        limit: int | None = None,
    ) -> Envelope[tuple[OpSearchHit, ...]]:
        """Return compact top-k semantic op search results."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
                payload=(),
            )

        normalized_query = query.strip()
        if normalized_query == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error("query is required", code=codes.INVALID_ARGUMENT)
                ],
                payload=(),
            )

        if self._language_service is None or self._embedding_service is None:
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "op discovery dependencies are not configured",
                        code=codes.INTERNAL_ERROR,
                    )
                ],
                payload=(),
            )

        effective_limit = max(
            1,
            min(
                limit or self._settings.op_search_top_k, self._settings.op_search_top_k
            ),
        )
        try:
            self._sync_op_discovery_index(meta=meta)
            results = self._search_ops_internal(
                meta=meta,
                query=normalized_query,
                limit=effective_limit,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("op discovery search failed", exc_info=exc)
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "op discovery search failed",
                        code=codes.INTERNAL_ERROR,
                    )
                ],
                payload=(),
            )
        return success(meta=meta, payload=tuple(results))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def list_tool_system_hints(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[ToolSystemHint, ...]]:
        """Return compact orientation hints for systems reachable through tools."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
                payload=(),
            )

        self._sync_mcp_tools_quietly()
        hints = [*_service_tool_system_hints()]
        list_servers = getattr(self._mcp_adapter, "list_servers", None)
        if callable(list_servers):
            active_by_server = self._registered_mcp_counts_by_server()
            pending_by_server = self._unclassified_mcp_counts_by_server()
            for server in list_servers():
                summary = str(getattr(server, "instruction_summary", "")).strip()
                server_id = str(getattr(server, "server_id", "")).strip()
                if server_id == "":
                    continue
                hints.append(
                    ToolSystemHint(
                        system_id=server_id,
                        label=server_id,
                        summary=summary or "MCP server",
                        kind="mcp",
                        ready=bool(getattr(server, "connected", False)),
                        tool_count=active_by_server.get(server_id, 0),
                        pending_tool_count=pending_by_server.get(server_id, 0),
                    )
                )

        return success(
            meta=meta,
            payload=tuple(
                sorted(
                    hints,
                    key=lambda item: (
                        0 if item.kind == "core" else 1,
                        item.system_id,
                    ),
                )
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def describe_op(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
    ) -> Envelope[OpDescriptor]:
        """Return one full descriptor by op id."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        manifest = self._registry.resolve_manifest(op_id=op_id.strip())
        if manifest is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        "op not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata={"op_id": op_id},
                    )
                ],
            )
        return success(meta=meta, payload=self._descriptor_from_manifest(manifest))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def resolve_slash_command(
        self,
        *,
        meta: EnvelopeMeta,
        name: str,
    ) -> Envelope[OpDescriptor | None]:
        """Return the descriptor for a slash command by name or alias."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        manifest = self._registry.resolve_slash_command(name=name.strip().lower())
        if manifest is None:
            return success(meta=meta, payload=None)
        return success(meta=meta, payload=self._descriptor_from_manifest(manifest))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def list_dynamic_op_classifications(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[tuple[DynamicOpClassificationRow, ...]]:
        """Return observed dynamic op definitions and persisted classifications."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )
        return success(
            meta=meta,
            payload=self._dynamic_op_classification_repository.list_rows(),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def classify_dynamic_op(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
        effect: str | None = None,
        approval: str | None = None,
    ) -> Envelope[DynamicOpClassificationRow]:
        """Persist one operator-supplied classification for a dynamic op.

        Either ``effect`` or ``approval`` may be omitted to leave the existing
        persisted value unchanged. Once both effect and approval are set on the
        row, the corresponding op manifest is registered (if not already) so
        the op becomes invokable without restart.
        """
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )
        if effect is None and approval is None:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "classify_dynamic_op requires at least one of effect or approval",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )
        existing = self._dynamic_op_classification_repository.get(op_id=op_id)
        if existing is None:
            self._sync_mcp_tools_quietly()
            existing = self._dynamic_op_classification_repository.get(op_id=op_id)
        if existing is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        "dynamic op classification target not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata={"op_id": op_id},
                    )
                ],
            )
        try:
            row = self._dynamic_op_classification_repository.classify(
                op_id=op_id,
                definition_digest=existing.definition_digest,
                effect=effect,
                approval=approval,
            )
        except KeyError:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        "dynamic op classification target not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata={"op_id": op_id},
                    )
                ],
            )
        if (
            row.effect is not None
            and row.approval is not None
            and self._registry.resolve_manifest(op_id=op_id) is None
        ):
            self._register_classified_dynamic_op(row=row)
        return success(meta=meta, payload=row)

    def _register_classified_dynamic_op(
        self, *, row: DynamicOpClassificationRow
    ) -> None:
        """Register manifest+handler for one newly-classified dynamic op."""
        from services.effect.execution.mcp_op_handler_bridge import (
            build_mcp_op_handler,
        )

        if row.effect is None or row.approval is None:
            return
        if row.source_kind != "mcp":
            return
        if not isinstance(self._mcp_adapter, object) or self._mcp_adapter is None:
            return
        try:
            server_id, tool_name = row.source_ref.split(":", 1)
        except ValueError:
            return
        manifest = NativeOpManifest(
            op_id=row.op_id,
            kind="mcp",
            version="1.0.0",
            summary=row.summary,
            call_target=f"mcp:{server_id}:{tool_name}",
            input_schema=row.input_schema,
            output_schema=row.output_schema,
            effect=row.effect,
            approval=row.approval,
        )
        self._registry.register_manifest(manifest=manifest)
        handler = build_mcp_op_handler(
            server_id=server_id,
            tool_name=tool_name,
            adapter=self._mcp_adapter,
        )
        self._registry.register_handler(op_id=row.op_id, handler=handler)
        _LOGGER.info(
            "mcp tool activated via runtime classification: %s "
            "(source_ref=%s, effect=%s, approval=%s)",
            row.op_id,
            row.source_ref,
            row.effect,
            row.approval,
        )

    def sync_op_discovery_index(self) -> None:
        """Refresh the derived op discovery index against enabled manifests."""
        if self._language_service is None or self._embedding_service is None:
            return
        meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=_OP_DISCOVERY_PRINCIPAL,
        )
        try:
            self._sync_op_discovery_index(meta=meta)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "op discovery index sync skipped",
                extra={codes.EXCEPTION_TYPE_KEY: type(exc).__name__},
                exc_info=exc,
            )

    def _sync_op_discovery_index(self, *, meta: EnvelopeMeta) -> None:
        """Incrementally synchronize Execution op discovery documents and embeddings."""
        source = self._ensure_op_discovery_source(meta=meta)
        current_documents = self._op_discovery_documents()
        existing_rows = {
            row.op_id: row for row in self._discovery_state_repository.list_rows()
        }
        chunks_by_ordinal = {
            chunk.chunk_ordinal: chunk
            for chunk in self._embedding_service.list_chunks_by_source(
                meta=meta,
                source_id=source.id,
                limit=max(1, len(existing_rows) + len(current_documents) + 16),
            ).payload.value
        }

        removed_op_ids = sorted(set(existing_rows) - set(current_documents))
        for op_id in removed_op_ids:
            row = existing_rows[op_id]
            chunk = chunks_by_ordinal.get(row.chunk_ordinal)
            if chunk is not None:
                self._embedding_service.delete_chunk(
                    meta=meta,
                    chunk_id=chunk.id,
                )
            self._discovery_state_repository.delete(op_id=op_id)

        next_chunk_ordinal = (
            max(
                (row.chunk_ordinal for row in existing_rows.values()),
                default=-1,
            )
            + 1
        )
        pending_documents: list[tuple[str, OpDiscoveryStateRow, str]] = []
        for op_id, document in current_documents.items():
            existing = existing_rows.get(op_id)
            if existing is None:
                row = OpDiscoveryStateRow(
                    op_id=op_id,
                    content_digest=document.content_digest,
                    chunk_ordinal=next_chunk_ordinal,
                )
                next_chunk_ordinal += 1
                pending_documents.append((op_id, row, document.text))
                continue

            chunk = chunks_by_ordinal.get(existing.chunk_ordinal)
            chunk_missing = chunk is None
            content_changed = existing.content_digest != document.content_digest
            if chunk_missing or content_changed:
                row = OpDiscoveryStateRow(
                    op_id=op_id,
                    content_digest=document.content_digest,
                    chunk_ordinal=existing.chunk_ordinal,
                )
                pending_documents.append((op_id, row, document.text))

        chunk_records_by_op: dict[str, object] = {}
        for op_id, row, text in pending_documents:
            chunk = self._embedding_service.upsert_chunk(
                meta=meta,
                source_id=source.id,
                chunk_ordinal=row.chunk_ordinal,
                reference_range=op_id,
                content_hash=row.content_digest,
                text=text,
                metadata={"op_id": op_id},
            ).payload.value
            chunk_records_by_op[op_id] = chunk
            self._discovery_state_repository.upsert(row=row)

        all_chunks = {
            chunk.chunk_ordinal: chunk
            for chunk in self._embedding_service.list_chunks_by_source(
                meta=meta,
                source_id=source.id,
                limit=max(1, len(current_documents) + 16),
            ).payload.value
        }
        current_rows = {
            row.op_id: row
            for row in self._discovery_state_repository.list_rows()
            if row.op_id in current_documents
        }
        if len(current_rows) == 0:
            return

        active_spec = self._find_op_embedding_spec(meta=meta)
        indexed_embeddings_by_chunk_id: dict[str, object] = {}
        if active_spec is not None:
            indexed_embeddings = self._embedding_service.list_embeddings_by_source(
                meta=meta,
                source_id=source.id,
                spec_id=active_spec.id,
                limit=max(1, len(current_rows) + 16),
            )
            if indexed_embeddings.payload is not None:
                indexed_embeddings_by_chunk_id = {
                    row.chunk_id: row for row in indexed_embeddings.payload.value
                }

        changed_op_ids = {item[0] for item in pending_documents}
        embeddings_to_refresh: list[tuple[str, str, object]] = []
        for op_id, row in sorted(current_rows.items()):
            chunk = all_chunks.get(row.chunk_ordinal)
            if chunk is None:
                continue
            embedding = indexed_embeddings_by_chunk_id.get(chunk.id)
            if (
                active_spec is not None
                and op_id not in changed_op_ids
                and embedding is not None
                and embedding.content_hash == row.content_digest
            ):
                continue
            embeddings_to_refresh.append((op_id, current_documents[op_id].text, chunk))

        if len(embeddings_to_refresh) == 0:
            return

        embedding_results = self._language_service.embed_batch(
            meta=meta,
            texts=[item[1] for item in embeddings_to_refresh],
            profile=_OP_EMBEDDING_PROFILE,
        )
        if embedding_results.payload is None:
            raise RuntimeError("op embedding batch returned no payload")
        vectors = embedding_results.payload.value
        if len(vectors) != len(embeddings_to_refresh):
            raise RuntimeError("op embedding batch size mismatch")
        first_vector = vectors[0]
        spec = self._embedding_service.upsert_spec(
            meta=meta,
            provider=first_vector.provider,
            name=first_vector.model,
            version=_OP_EMBEDDING_VERSION,
            dimensions=len(first_vector.values),
        )
        if spec.payload is None:
            raise RuntimeError("op embedding spec upsert returned no payload")
        spec_id = spec.payload.value.id

        self._embedding_service.upsert_embedding_vectors(
            meta=meta,
            items=[
                {
                    "chunk_id": item[2].id,
                    "spec_id": spec_id,
                    "vector": tuple(vectors[index].values),
                }
                for index, item in enumerate(embeddings_to_refresh)
            ],
        )

    def _find_op_embedding_spec(self, *, meta: EnvelopeMeta):
        """Return the current op-embedding spec when already materialized."""
        provider, model, dimensions = _parse_op_embedding_profile_fingerprint(
            self._op_embedding_profile_fingerprint
        )
        specs = self._embedding_service.list_specs(meta=meta, limit=1000)
        if specs.payload is None:
            return None
        for spec in specs.payload.value:
            if (
                spec.provider == provider
                and spec.name == model
                and spec.version == _OP_EMBEDDING_VERSION
                and spec.dimensions == dimensions
            ):
                return spec
        return None

    def _ensure_op_discovery_source(self, *, meta: EnvelopeMeta):
        """Create or return the dedicated Embedding source for op discovery."""
        source_result = self._embedding_service.upsert_source(
            meta=meta,
            canonical_reference=_OP_DISCOVERY_SOURCE_REFERENCE,
            source_type=_OP_DISCOVERY_SOURCE_TYPE,
            service=str(SERVICE_COMPONENT_ID),
            principal=_OP_DISCOVERY_PRINCIPAL,
            metadata={"component_id": str(SERVICE_COMPONENT_ID)},
        )
        if source_result.payload is None:
            raise RuntimeError("op discovery source upsert returned no payload")
        return source_result.payload.value

    def _search_ops_internal(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        limit: int,
    ) -> list[OpSearchHit]:
        """Run one semantic op search over the derived discovery index."""
        source = self._ensure_op_discovery_source(meta=meta)
        chunks = self._embedding_service.list_chunks_by_source(
            meta=meta,
            source_id=source.id,
            limit=max(1, self._registry.count() + 16),
        )
        if chunks.payload is None or len(chunks.payload.value) == 0:
            return []

        query_result = self._language_service.embed(
            meta=meta,
            text=query,
            profile=_OP_EMBEDDING_PROFILE,
        )
        if query_result.payload is None:
            raise RuntimeError("op discovery embed returned no payload")
        query_vector = query_result.payload.value
        spec = self._embedding_service.upsert_spec(
            meta=meta,
            provider=query_vector.provider,
            name=query_vector.model,
            version=_OP_EMBEDDING_VERSION,
            dimensions=len(query_vector.values),
        )
        if spec.payload is None:
            raise RuntimeError("op discovery spec upsert returned no payload")
        search = self._embedding_service.search_embeddings(
            meta=meta,
            query_vector=query_vector.values,
            source_id=source.id,
            spec_id=spec.payload.value.id,
            limit=limit,
        )
        if search.payload is None:
            return []

        hits: list[OpSearchHit] = []
        for match in search.payload.value:
            chunk = self._embedding_service.get_chunk(
                meta=meta,
                chunk_id=match.chunk_id,
            )
            if chunk.payload is None:
                continue
            op_id = chunk.payload.value.metadata.get("op_id", "").strip()
            if op_id == "":
                continue
            manifest = self._registry.resolve_manifest(op_id=op_id)
            if manifest is None:
                continue
            hits.append(
                OpSearchHit(
                    op_id=op_id,
                    required_params=self._required_params(manifest.input_schema),
                    summary=manifest.summary,
                )
            )
        return hits

    def _op_discovery_documents(
        self,
    ) -> dict[str, "_OpDiscoveryDocument"]:
        """Build stable per-op discovery documents for semantic indexing."""
        documents: dict[str, _OpDiscoveryDocument] = {}
        for manifest in self._registry.list_manifests():
            required_params = self._required_params(manifest.input_schema)
            lines = [
                f"op_id: {manifest.op_id}",
                f"summary: {manifest.summary}",
                f"required_params: {', '.join(required_params)}",
            ]
            mcp_server_id = ""
            mcp_tool_name = ""
            if getattr(manifest, "kind", "") == "mcp" and is_mcp_call_target(
                manifest.call_target
            ):
                mcp_server_id, mcp_tool_name = parse_mcp_call_target(
                    manifest.call_target
                )
                lines.extend(
                    (
                        f"server_id: {mcp_server_id}",
                        f"tool_name: {mcp_tool_name}",
                    )
                )
            text = "\n".join(lines)
            digest_payload = {
                "op_id": manifest.op_id,
                "summary": manifest.summary,
                "required_params": list(required_params),
                "mcp_server_id": mcp_server_id,
                "mcp_tool_name": mcp_tool_name,
                "embedding_profile": self._op_embedding_profile_fingerprint,
            }
            documents[manifest.op_id] = _OpDiscoveryDocument(
                text=text,
                content_digest=hashlib.sha256(
                    json.dumps(digest_payload, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )
        return documents

    def _descriptor_from_manifest(self, manifest: OpManifest) -> OpDescriptor:
        """Project one registered manifest into the agent-facing descriptor shape."""
        sc = manifest.slash_command
        return OpDescriptor(
            op_id=manifest.op_id,
            kind=manifest.kind,
            version=manifest.version,
            summary=manifest.summary,
            input_schema=manifest.input_schema,
            output_schema=manifest.output_schema,
            simple_output_path=manifest.simple_output_path,
            effect=manifest.effect,
            approval=manifest.approval,
            required_ops=manifest.required_ops,
            slash_command_name=(sc.name or manifest.op_id if sc is not None else None),
            slash_command_aliases=(sc.aliases if sc is not None else ()),
            slash_command_description=(
                sc.description or manifest.summary if sc is not None else None
            ),
        )

    def sync_mcp_tools(self) -> None:
        """Pull current MCP tool list from the adapter and reconcile state.

        For each tool the adapter advertises:
        - upserts an observed-definition row (creating it if missing,
          preserving operator-set effect/approval if already classified);
        - registers a manifest+handler when both effect and approval are set
          and no manifest is registered yet.

        Idempotent. Tolerant of repeat invocation; safe to call from
        `list_tool_system_hints` for lazy reconciliation when sidecar
        connectivity changes after process boot.
        """
        import hashlib
        import json

        from resources.adapters.mcp.adapter import McpAdapter
        from services.effect.execution.mcp_op_handler_bridge import (
            build_mcp_op_handler,
            mcp_op_id,
        )
        from services.effect.execution.mcp_schema_loader import (
            resolve_mcp_override,
        )

        adapter = self._mcp_adapter
        if not isinstance(adapter, McpAdapter):
            return
        for tool_info in adapter.list_tools():
            op_id = mcp_op_id(tool_info.server_id, tool_info.tool_name)
            override = resolve_mcp_override(
                self._mcp_overrides, tool_info.server_id, tool_info.tool_name
            )
            output_schema = override.output_schema if override is not None else None
            definition_digest = hashlib.sha256(
                json.dumps(
                    {
                        "source_kind": "mcp",
                        "source_ref": f"{tool_info.server_id}:{tool_info.tool_name}",
                        "summary": tool_info.description,
                        "input_schema": tool_info.input_schema,
                        "output_schema": output_schema,
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            existing = self._dynamic_op_classification_repository.get(op_id=op_id)
            digest_matches = (
                existing is not None and existing.definition_digest == definition_digest
            )
            override_effect = override.effect if override is not None else None
            override_approval = override.approval if override is not None else None
            seed_effect = (
                existing.effect
                if digest_matches
                and existing is not None
                and existing.effect is not None
                else override_effect
            )
            seed_approval = (
                existing.approval
                if digest_matches
                and existing is not None
                and existing.approval is not None
                else override_approval
            )
            observed = self._dynamic_op_classification_repository.upsert_observed(
                row=DynamicOpClassificationRow(
                    op_id=op_id,
                    source_kind="mcp",
                    source_ref=f"{tool_info.server_id}:{tool_info.tool_name}",
                    definition_digest=definition_digest,
                    summary=tool_info.description
                    or f"{tool_info.server_id} {tool_info.tool_name}",
                    input_schema=tool_info.input_schema,
                    output_schema=output_schema,
                    effect=seed_effect,
                    approval=seed_approval,
                )
            )
            if observed.effect is None or observed.approval is None:
                continue
            if self._registry.resolve_manifest(op_id=op_id) is not None:
                continue
            manifest = NativeOpManifest(
                op_id=op_id,
                kind="mcp",
                version="1.0.0",
                summary=observed.summary,
                call_target=f"mcp:{tool_info.server_id}:{tool_info.tool_name}",
                input_schema=tool_info.input_schema,
                output_schema=output_schema,
                effect=observed.effect,
                approval=observed.approval,
            )
            self._registry.register_manifest(manifest=manifest)
            self._registry.register_handler(
                op_id=op_id,
                handler=build_mcp_op_handler(
                    server_id=tool_info.server_id,
                    tool_name=tool_info.tool_name,
                    adapter=adapter,
                ),
            )
            _LOGGER.info(
                "mcp tool activated via discovery sync: %s "
                "(source_ref=%s:%s, effect=%s, approval=%s)",
                op_id,
                tool_info.server_id,
                tool_info.tool_name,
                observed.effect,
                observed.approval,
            )

    def _sync_mcp_tools_quietly(self) -> None:
        """Best-effort MCP tool sync; swallow only sidecar transport errors.

        Programming errors must surface so they can be fixed; only
        ``McpAdapterError`` (raised by the sidecar adapter on connection
        or call failures) is treated as recoverable.
        """
        from resources.adapters.mcp.adapter import McpAdapterError

        try:
            self.sync_mcp_tools()
        except McpAdapterError as exc:
            _LOGGER.warning("mcp tool sync skipped: %s: %s", type(exc).__name__, exc)

    def _registered_mcp_counts_by_server(self) -> dict[str, int]:
        """Return per-server count of MCP manifests already in the op registry."""
        counts: dict[str, int] = {}
        for manifest in self._registry.list_manifests():
            if manifest.kind != "mcp":
                continue
            server_id, sep, _ = manifest.op_id.partition("--")
            if sep == "" or server_id == "":
                continue
            counts[server_id] = counts.get(server_id, 0) + 1
        return counts

    def _unclassified_mcp_counts_by_server(self) -> dict[str, int]:
        """Return per-server count of dynamic-op rows missing effect/approval.

        Reads from the classification repository so the figure tracks operator
        state directly, independent of the MCP sidecar's transient tool cache.
        """
        counts: dict[str, int] = {}
        for row in self._dynamic_op_classification_repository.list_rows():
            if row.source_kind != "mcp":
                continue
            if row.effect is not None and row.approval is not None:
                continue
            server_id = row.source_ref.split(":", 1)[0] if row.source_ref else ""
            if server_id == "":
                continue
            counts[server_id] = counts.get(server_id, 0) + 1
        return counts

    def _required_params(self, input_schema: dict[str, Any] | None) -> tuple[str, ...]:
        """Extract required input parameter names from one canonical input schema."""
        if not isinstance(input_schema, dict):
            return ()
        required = input_schema.get("required")
        if not isinstance(required, list):
            return ()
        result = [str(item).strip() for item in required if str(item).strip() != ""]
        return tuple(result)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=(),
    )
    def invoke_op(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
        input_payload: dict[str, object],
        invocation: OpInvocationMetadata,
    ) -> Envelope[OpInvokeResult]:
        """Invoke one op package by ``op_id`` through Policy Service."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        result = self._invoke_internal(
            meta=meta,
            op_id=op_id,
            input_payload=dict(input_payload),
            invocation=InvocationPolicyInput.model_validate(
                invocation.model_dump(mode="python")
            ),
        )
        self._append_audit_row(
            meta=meta,
            op_id=op_id,
            op_version=result.op_version,
            summary=result.policy,
            proposal_token=result.proposal_token,
            invocation=invocation,
        )

        if not result.allowed:
            return failure(meta=meta, errors=result.errors)

        return success(
            meta=meta,
            payload=OpInvokeResult(
                op_id=op_id,
                op_version=result.op_version,
                output=result.output,
                policy_decision_id=result.policy.decision_id,
                policy_regime_id=result.policy.policy_regime_id,
                policy_allowed=result.policy.allowed,
                policy_reason_codes=result.policy.reason_codes,
                policy_obligations=result.policy.obligations,
                proposal_token=result.proposal_token,
            ),
        )

    def _invoke_internal(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
        input_payload: dict[str, Any],
        invocation: InvocationPolicyInput,
    ) -> _InvokeInternalResult:
        manifest = self._registry.resolve_manifest(op_id=op_id)
        if manifest is None:
            errors = (
                not_found_error(
                    "op not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"op_id": op_id},
                ),
            )
            return self._denied_internal(
                op_version="unknown",
                errors=errors,
                reason_codes=(codes.RESOURCE_NOT_FOUND,),
            )

        request = OpInvocationRequest(
            metadata=meta,
            op_policy=OpPolicyInput(
                op_id=manifest.op_id,
                kind=manifest.kind,
                version=manifest.version,
                effect=manifest.effect,
                approval=manifest.approval,
                required_ops=manifest.required_ops,
            ),
            invocation=invocation,
            input_payload=input_payload,
        )
        policy_result = self._invoke_with_policy(request=request)

        proposal_token = ""
        if policy_result.proposal is not None:
            proposal_token = policy_result.proposal.proposal_token
        summary = OpPolicySummary(
            decision_id=policy_result.decision.decision_id,
            policy_regime_id=policy_result.decision.policy_regime_id,
            allowed=policy_result.decision.allowed,
            reason_codes=policy_result.decision.reason_codes,
            obligations=policy_result.decision.obligations,
            proposal_token=proposal_token,
        )

        return _InvokeInternalResult(
            allowed=policy_result.allowed,
            output=policy_result.output,
            errors=policy_result.errors,
            policy=summary,
            proposal_token=proposal_token,
            op_version=manifest.version,
        )

    def _invoke_with_policy(
        self, *, request: OpInvocationRequest
    ) -> PolicyExecutionResult:
        handler = self._registry.resolve_handler(op_id=request.op_policy.op_id)
        runtime = _NestedRuntime(engine=self, parent_request=request)

        if handler is None:
            return self._policy_service.authorize_and_execute(
                request=request,
                execute=lambda _: self._missing_handler_result(request=request),
            )

        def _execute(
            allowed_request: OpInvocationRequest,
        ) -> PolicyExecutionResult:
            try:
                result = handler(allowed_request, runtime)
            except OpHandlerBridgeError as exc:
                reason_codes = tuple(
                    _error_category_to_reason_code(e.category) for e in exc.errors
                )
                return PolicyExecutionResult(
                    allowed=False,
                    output=None,
                    errors=exc.errors,
                    decision=self._placeholder_allow_decision().model_copy(
                        update={"allowed": False, "reason_codes": reason_codes}
                    ),
                    proposal=None,
                )
            except ValueError as exc:
                return PolicyExecutionResult(
                    allowed=False,
                    output=None,
                    errors=(
                        validation_error(
                            str(exc),
                            code=codes.INVALID_ARGUMENT,
                        ),
                    ),
                    decision=self._placeholder_allow_decision(),
                    proposal=None,
                )
            except Exception as exc:
                return PolicyExecutionResult(
                    allowed=False,
                    output=None,
                    errors=(
                        internal_error(
                            str(exc),
                            code=codes.INTERNAL_ERROR,
                        ),
                    ),
                    decision=self._placeholder_allow_decision(),
                    proposal=None,
                )
            return PolicyExecutionResult(
                allowed=True,
                output=result.output,
                errors=(),
                decision=self._placeholder_allow_decision(),
                proposal=None,
            )

        return self._policy_service.authorize_and_execute(
            request=request,
            execute=_execute,
        )

    def _append_audit_row(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
        op_version: str,
        summary: OpPolicySummary,
        proposal_token: str,
        invocation: OpInvocationMetadata,
    ) -> None:
        self._audit_repository.append(
            row=OpInvocationAuditRow(
                audit_id=generate_ulid_str(),
                envelope_id=meta.envelope_id,
                trace_id=meta.trace_id,
                parent_id=meta.parent_id,
                invocation_id=invocation.invocation_id,
                parent_invocation_id=invocation.parent_invocation_id,
                actor=invocation.actor,
                source=invocation.source,
                channel=invocation.channel,
                op_id=op_id,
                op_version=op_version,
                policy_decision_id=summary.decision_id,
                policy_regime_id=summary.policy_regime_id,
                allowed=summary.allowed,
                reason_codes=summary.reason_codes,
                proposal_token=proposal_token,
                created_at=datetime.now(UTC),
            ),
        )

    def _denied_internal(
        self,
        *,
        op_version: str,
        errors: tuple[ErrorDetail, ...],
        reason_codes: tuple[str, ...],
    ) -> _InvokeInternalResult:
        summary = OpPolicySummary(
            decision_id=_PREPOLICY_DENY_ID,
            policy_regime_id=_PREPOLICY_DENY_ID,
            allowed=False,
            reason_codes=reason_codes,
            obligations=(),
        )
        return _InvokeInternalResult(
            allowed=False,
            output=None,
            errors=errors,
            policy=summary,
            proposal_token="",
            op_version=op_version,
        )

    @staticmethod
    def _placeholder_allow_decision() -> PolicyDecision:
        return PolicyDecision(
            decision_id=_PLACEHOLDER_DECISION_ID,
            policy_regime_id=_PLACEHOLDER_DECISION_ID,
            policy_regime_hash=_PLACEHOLDER_DECISION_ID,
            allowed=True,
            reason_codes=(),
            obligations=(),
            policy_metadata={},
            decided_at=datetime.now(UTC),
            policy_name=_PLACEHOLDER_DECISION_ID,
            policy_version="1",
        )

    def _missing_handler_result(
        self, *, request: OpInvocationRequest
    ) -> PolicyExecutionResult:
        return PolicyExecutionResult(
            allowed=False,
            output=None,
            errors=(
                not_found_error(
                    "op handler not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"op_id": request.op_policy.op_id},
                ),
            ),
            decision=self._placeholder_allow_decision().model_copy(
                update={"allowed": False, "reason_codes": (UNKNOWN_CALL_TARGET_REASON,)}
            ),
            proposal=None,
        )


_ERROR_CATEGORY_REASON_MAP: dict[ErrorCategory, str] = {
    ErrorCategory.NOT_FOUND: _REASON_NOT_FOUND,
    ErrorCategory.DEPENDENCY: _REASON_DEPENDENCY_ERROR,
    ErrorCategory.CONFLICT: "conflict",
    ErrorCategory.VALIDATION: "validation_error",
    ErrorCategory.INTERNAL: "internal_error",
    ErrorCategory.POLICY: "policy_error",
}


def _error_category_to_reason_code(category: ErrorCategory) -> str:
    """Map an ErrorCategory to an op-engine reason code."""
    return _ERROR_CATEGORY_REASON_MAP.get(category, "internal_error")


def _service_tool_system_hints() -> tuple[ToolSystemHint, ...]:
    """Return service-owned tool-system hints from registered service manifests."""
    hints: list[ToolSystemHint] = []
    for service in get_registry().list_services():
        summary = service.tool_system_summary.strip()
        if not service.exposes_ops or summary == "":
            continue
        service_id = str(service.id)
        label = service.tool_system_label.strip() or service_id
        hints.append(
            ToolSystemHint(
                system_id=service_id,
                label=label,
                summary=summary,
                kind="core",
                ready=None,
                tool_count=None,
            )
        )
    return tuple(hints)


def _resolve_op_embedding_profile_fingerprint(
    settings: CoreRuntimeSettings,
) -> str:
    """Read the op-embedding profile fingerprint from root settings only."""
    language_settings = component_settings_for(settings, component_name="language")
    op_embedding = language_settings.get("op_embedding", {})
    if not isinstance(op_embedding, dict):
        return ""
    provider = str(op_embedding.get("provider", "")).strip()
    model = str(op_embedding.get("model", "")).strip()
    dimensions = int(op_embedding.get("dimensions", 0) or 0)
    return json.dumps(
        {
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
        },
        sort_keys=True,
    )


def _parse_op_embedding_profile_fingerprint(
    fingerprint: str,
) -> tuple[str, str, int]:
    """Parse the configured op-embedding fingerprint into lookup fields."""
    if fingerprint.strip() == "":
        return "", "", 0
    try:
        payload = json.loads(fingerprint)
    except json.JSONDecodeError:
        return "", "", 0
    if not isinstance(payload, dict):
        return "", "", 0
    provider = str(payload.get("provider", "")).strip()
    model = str(payload.get("model", "")).strip()
    dimensions = int(payload.get("dimensions", 0) or 0)
    return provider, model, dimensions
