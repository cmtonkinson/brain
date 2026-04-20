"""Concrete Capability Engine Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
    new_meta,
    EnvelopeKind,
)
from packages.brain_shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    internal_error,
    not_found_error,
    validation_error,
)
from services.action.capability_engine.op_handler_bridge import OpHandlerBridgeError
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.utcp_code_mode import (
    LocalFileUtcpCodeModeAdapter,
    UtcpCodeModeAdapter,
    UtcpCodeModeLoadResult,
    resolve_utcp_code_mode_adapter_settings,
)
from services.action.capability_engine.component import SERVICE_COMPONENT_ID
from services.action.capability_engine.config import (
    CapabilityEngineSettings,
    resolve_capability_engine_settings,
)
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityEngineHealthStatus,
    CapabilityExecutionResponse,
    CapabilityDiscoveryStateRow,
    CapabilityInvocationAuditRow,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
    CapabilityPolicySummary,
    CapabilitySearchHit,
)
from services.action.capability_engine.data.repository import (
    InMemoryCapabilityDiscoveryStateRepository,
    InMemoryCapabilityInvocationAuditRepository,
    PostgresCapabilityDiscoveryStateRepository,
    PostgresCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.data.runtime import (
    CapabilityEnginePostgresRuntime,
)
from services.action.capability_engine.interfaces import (
    CapabilityDiscoveryStateRepository,
    CapabilityInvocationAuditRepository,
)
from services.action.capability_engine.registry import (
    CapabilityRegistry,
    CapabilityRuntime,
)
from services.action.language_model.service import LanguageModelService
from services.action.capability_engine.service import CapabilityEngineService
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    CapabilityPolicyInput,
    InvocationPolicyInput,
    PolicyDecision,
    PolicyExecutionResult,
    UNKNOWN_CALL_TARGET_REASON,
    utc_now,
)
from services.action.policy_service.service import PolicyService
from services.state.embedding_authority.service import EmbeddingAuthorityService

_LOGGER = get_logger(__name__)
_REASON_AUTONOMY_EXCEEDS_ENGINE_LIMIT = "autonomy_exceeds_engine_limit"
_REASON_DEPENDENCY_ERROR = "dependency_error"
_REASON_NOT_FOUND = "not_found"
_CAPABILITY_DISCOVERY_SOURCE_REFERENCE = "capability-engine:discovery"
_CAPABILITY_DISCOVERY_SOURCE_TYPE = "capability_catalog"
_CAPABILITY_DISCOVERY_PRINCIPAL = "system"
_CAPABILITY_EMBEDDING_VERSION = "capability_embedding"
_CAPABILITY_EMBEDDING_PROFILE = "capability_embedding"


@dataclass(frozen=True)
class _InvokeInternalResult:
    """Internal invocation result used by both public and nested invoke paths."""

    allowed: bool
    output: dict[str, Any] | None
    errors: tuple[ErrorDetail, ...]
    policy: CapabilityPolicySummary
    proposal_token: str
    capability_version: str


@dataclass(frozen=True)
class _CapabilityDiscoveryDocument:
    """Stable derived discovery document content and digest for one capability."""

    text: str
    content_digest: str


@dataclass(frozen=True)
class _NestedRuntime(CapabilityRuntime):
    """Runtime helper passed to handlers for nested capability invocation."""

    engine: "DefaultCapabilityEngineService"
    parent_request: CapabilityInvocationRequest

    def invoke_nested(
        self,
        *,
        capability_id: str,
        input_payload: dict[str, Any],
    ) -> CapabilityExecutionResponse:
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
            capability_id=capability_id,
            input_payload=input_payload,
            invocation=child_invocation,
        )
        if not nested.allowed:
            return CapabilityExecutionResponse(output=None)
        return CapabilityExecutionResponse(output=nested.output)


class DefaultCapabilityEngineService(CapabilityEngineService):
    """Default CES implementation enforcing policy-gated capability execution."""

    def __init__(
        self,
        *,
        settings: CapabilityEngineSettings,
        policy_service: PolicyService,
        language_model_service: LanguageModelService | None = None,
        embedding_authority_service: EmbeddingAuthorityService | None = None,
        registry: CapabilityRegistry,
        code_mode_adapter: UtcpCodeModeAdapter | None = None,
        code_mode_config: UtcpCodeModeLoadResult | None = None,
        audit_repository: CapabilityInvocationAuditRepository | None = None,
        discovery_state_repository: CapabilityDiscoveryStateRepository | None = None,
        capability_embedding_profile_fingerprint: str = "",
    ) -> None:
        self._settings = settings
        self._policy_service = policy_service
        self._language_model_service = language_model_service
        self._embedding_authority_service = embedding_authority_service
        self._registry = registry
        self._code_mode_adapter = code_mode_adapter
        self._code_mode_config = code_mode_config
        self._audit_repository = (
            audit_repository or InMemoryCapabilityInvocationAuditRepository()
        )
        self._discovery_state_repository = (
            discovery_state_repository or InMemoryCapabilityDiscoveryStateRepository()
        )
        self._capability_embedding_profile_fingerprint = (
            capability_embedding_profile_fingerprint
        )

    def _load_capabilities(self) -> None:
        """Discover capability manifests from configured discovery root."""
        self._registry.discover(root=Path(self._settings.discovery_root))

    @classmethod
    def from_settings(
        cls,
        settings: CoreRuntimeSettings,
        *,
        policy_service: PolicyService,
        language_model_service: LanguageModelService | None = None,
        embedding_authority_service: EmbeddingAuthorityService | None = None,
        registry: CapabilityRegistry | None = None,
    ) -> "DefaultCapabilityEngineService":
        """Build CES from typed settings and injected Policy Service dependency."""
        resolved = resolve_capability_engine_settings(settings)
        active_registry = registry or CapabilityRegistry()
        active_registry.discover(root=Path(resolved.discovery_root))
        code_mode_adapter_settings = resolve_utcp_code_mode_adapter_settings(settings)
        code_mode_adapter = LocalFileUtcpCodeModeAdapter(
            settings=code_mode_adapter_settings
        )
        code_mode_config = code_mode_adapter.load()
        runtime = CapabilityEnginePostgresRuntime.from_settings(settings)
        return cls(
            settings=resolved,
            policy_service=policy_service,
            language_model_service=language_model_service,
            embedding_authority_service=embedding_authority_service,
            registry=active_registry,
            code_mode_adapter=code_mode_adapter,
            code_mode_config=code_mode_config,
            audit_repository=PostgresCapabilityInvocationAuditRepository(
                runtime.schema_sessions
            ),
            discovery_state_repository=PostgresCapabilityDiscoveryStateRepository(
                runtime.schema_sessions
            ),
            capability_embedding_profile_fingerprint=_resolve_capability_embedding_profile_fingerprint(
                settings
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]:
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
            payload=CapabilityEngineHealthStatus(
                service_ready=True,
                policy_ready=True,
                discovered_capabilities=self._registry.count(),
                invocation_audit_rows=self._audit_repository.count(),
                detail="ok",
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def describe_capabilities(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[CapabilityDescriptor, ...]]:
        """Return descriptors for all registered capabilities."""
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
    def list_always_on_capabilities(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[CapabilityDescriptor, ...]]:
        """Return full descriptors for the configured always-on capabilities."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        descriptors: list[CapabilityDescriptor] = []
        for capability_id in self._settings.always_on_capability_ids:
            manifest = self._registry.resolve_manifest(capability_id=capability_id)
            if manifest is None:
                continue
            descriptors.append(self._descriptor_from_manifest(manifest))
        return success(meta=meta, payload=tuple(descriptors))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def search_capabilities(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        limit: int | None = None,
    ) -> Envelope[tuple[CapabilitySearchHit, ...]]:
        """Return compact top-k semantic capability search results."""
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

        if (
            self._language_model_service is None
            or self._embedding_authority_service is None
        ):
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "capability discovery dependencies are not configured",
                        code=codes.INTERNAL_ERROR,
                    )
                ],
                payload=(),
            )

        effective_limit = (
            self._settings.capability_search_top_k if limit is None else limit
        )
        effective_limit = max(
            1, min(effective_limit, self._settings.capability_search_top_k)
        )
        try:
            self._sync_capability_discovery_index(meta=meta)
            results = self._search_capabilities_internal(
                meta=meta,
                query=normalized_query,
                limit=effective_limit,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("capability discovery search failed", exc_info=exc)
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "capability discovery search failed",
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
    def describe_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
    ) -> Envelope[CapabilityDescriptor]:
        """Return one full descriptor by capability id."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        manifest = self._registry.resolve_manifest(capability_id=capability_id.strip())
        if manifest is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        "capability not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata={"capability_id": capability_id},
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
    ) -> Envelope[CapabilityDescriptor | None]:
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

    def sync_capability_discovery_index(self) -> None:
        """Refresh the derived capability discovery index against enabled manifests."""
        if (
            self._language_model_service is None
            or self._embedding_authority_service is None
        ):
            return
        meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=_CAPABILITY_DISCOVERY_PRINCIPAL,
        )
        try:
            self._sync_capability_discovery_index(meta=meta)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "capability discovery index sync skipped",
                extra={"exception_type": type(exc).__name__},
                exc_info=exc,
            )

    def _sync_capability_discovery_index(self, *, meta: EnvelopeMeta) -> None:
        """Incrementally synchronize CES capability discovery documents and embeddings."""
        source = self._ensure_capability_discovery_source(meta=meta)
        current_documents = self._capability_discovery_documents()
        existing_rows = {
            row.capability_id: row
            for row in self._discovery_state_repository.list_rows()
        }
        chunks_by_ordinal = {
            chunk.chunk_ordinal: chunk
            for chunk in self._embedding_authority_service.list_chunks_by_source(
                meta=meta,
                source_id=source.id,
                limit=max(1, len(existing_rows) + len(current_documents) + 16),
            ).payload.value
        }

        removed_capability_ids = sorted(set(existing_rows) - set(current_documents))
        for capability_id in removed_capability_ids:
            row = existing_rows[capability_id]
            chunk = chunks_by_ordinal.get(row.chunk_ordinal)
            if chunk is not None:
                self._embedding_authority_service.delete_chunk(
                    meta=meta,
                    chunk_id=chunk.id,
                )
            self._discovery_state_repository.delete(capability_id=capability_id)

        next_chunk_ordinal = (
            max(
                (row.chunk_ordinal for row in existing_rows.values()),
                default=-1,
            )
            + 1
        )
        pending_documents: list[tuple[str, CapabilityDiscoveryStateRow, str]] = []
        for capability_id, document in current_documents.items():
            existing = existing_rows.get(capability_id)
            if existing is None:
                row = CapabilityDiscoveryStateRow(
                    capability_id=capability_id,
                    content_digest=document.content_digest,
                    chunk_ordinal=next_chunk_ordinal,
                )
                next_chunk_ordinal += 1
                pending_documents.append((capability_id, row, document.text))
                continue

            chunk = chunks_by_ordinal.get(existing.chunk_ordinal)
            chunk_missing = chunk is None
            content_changed = existing.content_digest != document.content_digest
            if chunk_missing or content_changed:
                row = CapabilityDiscoveryStateRow(
                    capability_id=capability_id,
                    content_digest=document.content_digest,
                    chunk_ordinal=existing.chunk_ordinal,
                )
                pending_documents.append((capability_id, row, document.text))

        chunk_records_by_capability: dict[str, object] = {}
        for capability_id, row, text in pending_documents:
            chunk = self._embedding_authority_service.upsert_chunk(
                meta=meta,
                source_id=source.id,
                chunk_ordinal=row.chunk_ordinal,
                reference_range=capability_id,
                content_hash=row.content_digest,
                text=text,
                metadata={"capability_id": capability_id},
            ).payload.value
            chunk_records_by_capability[capability_id] = chunk
            self._discovery_state_repository.upsert(row=row)

        all_chunks = {
            chunk.chunk_ordinal: chunk
            for chunk in self._embedding_authority_service.list_chunks_by_source(
                meta=meta,
                source_id=source.id,
                limit=max(1, len(current_documents) + 16),
            ).payload.value
        }
        current_rows = {
            row.capability_id: row
            for row in self._discovery_state_repository.list_rows()
            if row.capability_id in current_documents
        }
        if len(current_rows) == 0:
            return

        active_spec = self._find_capability_embedding_spec(meta=meta)
        indexed_embeddings_by_chunk_id: dict[str, object] = {}
        if active_spec is not None:
            indexed_embeddings = (
                self._embedding_authority_service.list_embeddings_by_source(
                    meta=meta,
                    source_id=source.id,
                    spec_id=active_spec.id,
                    limit=max(1, len(current_rows) + 16),
                )
            )
            if indexed_embeddings.payload is not None:
                indexed_embeddings_by_chunk_id = {
                    row.chunk_id: row for row in indexed_embeddings.payload.value
                }

        changed_capability_ids = {item[0] for item in pending_documents}
        embeddings_to_refresh: list[tuple[str, str, object]] = []
        for capability_id, row in sorted(current_rows.items()):
            chunk = all_chunks.get(row.chunk_ordinal)
            if chunk is None:
                continue
            embedding = indexed_embeddings_by_chunk_id.get(chunk.id)
            if (
                active_spec is not None
                and capability_id not in changed_capability_ids
                and embedding is not None
                and embedding.content_hash == row.content_digest
            ):
                continue
            embeddings_to_refresh.append(
                (capability_id, current_documents[capability_id].text, chunk)
            )

        if len(embeddings_to_refresh) == 0:
            return

        embedding_results = self._language_model_service.embed_batch(
            meta=meta,
            texts=[item[1] for item in embeddings_to_refresh],
            profile=_CAPABILITY_EMBEDDING_PROFILE,
        )
        if embedding_results.payload is None:
            raise RuntimeError("capability embedding batch returned no payload")
        vectors = embedding_results.payload.value
        if len(vectors) != len(embeddings_to_refresh):
            raise RuntimeError("capability embedding batch size mismatch")
        first_vector = vectors[0]
        spec = self._embedding_authority_service.upsert_spec(
            meta=meta,
            provider=first_vector.provider,
            name=first_vector.model,
            version=_CAPABILITY_EMBEDDING_VERSION,
            dimensions=len(first_vector.values),
        )
        if spec.payload is None:
            raise RuntimeError("capability embedding spec upsert returned no payload")
        spec_id = spec.payload.value.id

        self._embedding_authority_service.upsert_embedding_vectors(
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

    def _find_capability_embedding_spec(self, *, meta: EnvelopeMeta):
        """Return the current capability-embedding spec when already materialized."""
        provider, model, dimensions = _parse_capability_embedding_profile_fingerprint(
            self._capability_embedding_profile_fingerprint
        )
        specs = self._embedding_authority_service.list_specs(meta=meta, limit=1000)
        if specs.payload is None:
            return None
        for spec in specs.payload.value:
            if (
                spec.provider == provider
                and spec.name == model
                and spec.version == _CAPABILITY_EMBEDDING_VERSION
                and spec.dimensions == dimensions
            ):
                return spec
        return None

    def _ensure_capability_discovery_source(self, *, meta: EnvelopeMeta):
        """Create or return the dedicated EAS source for capability discovery."""
        source_result = self._embedding_authority_service.upsert_source(
            meta=meta,
            canonical_reference=_CAPABILITY_DISCOVERY_SOURCE_REFERENCE,
            source_type=_CAPABILITY_DISCOVERY_SOURCE_TYPE,
            service=str(SERVICE_COMPONENT_ID),
            principal=_CAPABILITY_DISCOVERY_PRINCIPAL,
            metadata={"component_id": str(SERVICE_COMPONENT_ID)},
        )
        if source_result.payload is None:
            raise RuntimeError("capability discovery source upsert returned no payload")
        return source_result.payload.value

    def _search_capabilities_internal(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        limit: int,
    ) -> list[CapabilitySearchHit]:
        """Run one semantic capability search over the derived discovery index."""
        source = self._ensure_capability_discovery_source(meta=meta)
        chunks = self._embedding_authority_service.list_chunks_by_source(
            meta=meta,
            source_id=source.id,
            limit=max(1, self._registry.count() + 16),
        )
        if chunks.payload is None or len(chunks.payload.value) == 0:
            return []

        query_result = self._language_model_service.embed(
            meta=meta,
            text=query,
            profile=_CAPABILITY_EMBEDDING_PROFILE,
        )
        if query_result.payload is None:
            raise RuntimeError("capability discovery embed returned no payload")
        query_vector = query_result.payload.value
        spec = self._embedding_authority_service.upsert_spec(
            meta=meta,
            provider=query_vector.provider,
            name=query_vector.model,
            version=_CAPABILITY_EMBEDDING_VERSION,
            dimensions=len(query_vector.values),
        )
        if spec.payload is None:
            raise RuntimeError("capability discovery spec upsert returned no payload")
        search = self._embedding_authority_service.search_embeddings(
            meta=meta,
            query_vector=query_vector.values,
            source_id=source.id,
            spec_id=spec.payload.value.id,
            limit=limit,
        )
        if search.payload is None:
            return []

        hits: list[CapabilitySearchHit] = []
        for match in search.payload.value:
            chunk = self._embedding_authority_service.get_chunk(
                meta=meta,
                chunk_id=match.chunk_id,
            )
            if chunk.payload is None:
                continue
            capability_id = chunk.payload.value.metadata.get(
                "capability_id", ""
            ).strip()
            if capability_id == "":
                continue
            manifest = self._registry.resolve_manifest(capability_id=capability_id)
            if manifest is None:
                continue
            hits.append(
                CapabilitySearchHit(
                    capability_id=capability_id,
                    required_params=self._required_params(manifest.input_schema),
                    summary=manifest.summary,
                )
            )
        return hits

    def _capability_discovery_documents(
        self,
    ) -> dict[str, "_CapabilityDiscoveryDocument"]:
        """Build stable per-capability discovery documents for semantic indexing."""
        documents: dict[str, _CapabilityDiscoveryDocument] = {}
        for manifest in self._registry.list_manifests():
            required_params = self._required_params(manifest.input_schema)
            text = "\n".join(
                (
                    f"capability_id: {manifest.capability_id}",
                    f"summary: {manifest.summary}",
                    f"required_params: {', '.join(required_params)}",
                )
            )
            digest_payload = {
                "capability_id": manifest.capability_id,
                "summary": manifest.summary,
                "required_params": list(required_params),
                "embedding_profile": self._capability_embedding_profile_fingerprint,
            }
            documents[manifest.capability_id] = _CapabilityDiscoveryDocument(
                text=text,
                content_digest=hashlib.sha256(
                    json.dumps(digest_payload, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )
        return documents

    def _descriptor_from_manifest(self, manifest: object) -> CapabilityDescriptor:
        """Project one registered manifest into the agent-facing descriptor shape."""
        sc = manifest.slash_command
        return CapabilityDescriptor(
            capability_id=manifest.capability_id,
            kind=manifest.kind,
            version=manifest.version,
            summary=manifest.summary,
            input_schema=manifest.input_schema,
            output_schema=manifest.output_schema,
            simple_output_path=manifest.simple_output_path,
            autonomy=manifest.autonomy,
            requires_approval=manifest.requires_approval,
            side_effects=manifest.side_effects,
            required_capabilities=manifest.required_capabilities,
            slash_command_name=(
                sc.name or manifest.capability_id if sc is not None else None
            ),
            slash_command_aliases=(sc.aliases if sc is not None else ()),
            slash_command_description=(
                sc.description or manifest.summary if sc is not None else None
            ),
        )

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
    def invoke_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
        input_payload: dict[str, object],
        invocation: CapabilityInvocationMetadata,
    ) -> Envelope[CapabilityInvokeResult]:
        """Invoke one capability package by ``capability_id`` through Policy Service."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        result = self._invoke_internal(
            meta=meta,
            capability_id=capability_id,
            input_payload={key: value for key, value in input_payload.items()},
            invocation=InvocationPolicyInput.model_validate(
                invocation.model_dump(mode="python")
            ),
        )
        self._append_audit_row(
            meta=meta,
            capability_id=capability_id,
            capability_version=result.capability_version,
            summary=result.policy,
            proposal_token=result.proposal_token,
            invocation=invocation,
        )

        if not result.allowed:
            return failure(meta=meta, errors=result.errors)

        return success(
            meta=meta,
            payload=CapabilityInvokeResult(
                capability_id=capability_id,
                capability_version=result.capability_version,
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
        capability_id: str,
        input_payload: dict[str, Any],
        invocation: InvocationPolicyInput,
    ) -> _InvokeInternalResult:
        manifest = self._registry.resolve_manifest(capability_id=capability_id)
        if manifest is None:
            errors = (
                not_found_error(
                    "capability not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"capability_id": capability_id},
                ),
            )
            return self._denied_internal(
                capability_version="unknown",
                errors=errors,
                reason_codes=(codes.RESOURCE_NOT_FOUND,),
            )

        if manifest.autonomy > self._settings.default_max_autonomy:
            errors = (
                validation_error(
                    "capability autonomy exceeds engine ceiling",
                    code=codes.PERMISSION_DENIED,
                    metadata={
                        "capability_id": capability_id,
                        "capability_autonomy": str(manifest.autonomy),
                        "engine_max_autonomy": str(self._settings.default_max_autonomy),
                    },
                ),
            )
            return self._denied_internal(
                capability_version=manifest.version,
                errors=errors,
                reason_codes=(_REASON_AUTONOMY_EXCEEDS_ENGINE_LIMIT,),
            )

        request = CapabilityInvocationRequest(
            metadata=meta,
            capability=CapabilityPolicyInput(
                capability_id=manifest.capability_id,
                kind=manifest.kind,
                version=manifest.version,
                autonomy=manifest.autonomy,
                requires_approval=manifest.requires_approval,
                side_effects=manifest.side_effects,
                required_capabilities=manifest.required_capabilities,
            ),
            invocation=invocation,
            input_payload=input_payload,
        )
        policy_result = self._invoke_with_policy(request=request)

        proposal_token = ""
        if policy_result.proposal is not None:
            proposal_token = policy_result.proposal.proposal_token
        summary = CapabilityPolicySummary(
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
            capability_version=manifest.version,
        )

    def _invoke_with_policy(
        self, *, request: CapabilityInvocationRequest
    ) -> PolicyExecutionResult:
        handler = self._registry.resolve_handler(
            capability_id=request.capability.capability_id
        )
        runtime = _NestedRuntime(engine=self, parent_request=request)

        if handler is None:
            return self._policy_service.authorize_and_execute(
                request=request,
                execute=lambda _: self._missing_handler_result(request=request),
            )

        def _execute(
            allowed_request: CapabilityInvocationRequest,
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
        capability_id: str,
        capability_version: str,
        summary: CapabilityPolicySummary,
        proposal_token: str,
        invocation: CapabilityInvocationMetadata,
    ) -> None:
        self._audit_repository.append(
            row=CapabilityInvocationAuditRow(
                audit_id=generate_ulid_str(),
                envelope_id=meta.envelope_id,
                trace_id=meta.trace_id,
                parent_id=meta.parent_id,
                invocation_id=invocation.invocation_id,
                parent_invocation_id=invocation.parent_invocation_id,
                actor=invocation.actor,
                source=invocation.source,
                channel=invocation.channel,
                capability_id=capability_id,
                capability_version=capability_version,
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
        capability_version: str,
        errors: tuple[ErrorDetail, ...],
        reason_codes: tuple[str, ...],
    ) -> _InvokeInternalResult:
        summary = CapabilityPolicySummary(
            decision_id="prepolicy-deny",
            policy_regime_id="prepolicy-deny",
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
            capability_version=capability_version,
        )

    @staticmethod
    def _placeholder_allow_decision() -> PolicyDecision:
        return PolicyDecision(
            decision_id="placeholder",
            policy_regime_id="placeholder",
            policy_regime_hash="placeholder",
            allowed=True,
            reason_codes=(),
            obligations=(),
            policy_metadata={},
            decided_at=utc_now(),
            policy_name="placeholder",
            policy_version="1",
        )

    def _missing_handler_result(
        self, *, request: CapabilityInvocationRequest
    ) -> PolicyExecutionResult:
        return PolicyExecutionResult(
            allowed=False,
            output=None,
            errors=(
                not_found_error(
                    "capability handler not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"capability_id": request.capability.capability_id},
                ),
            ),
            decision=self._placeholder_allow_decision().model_copy(
                update={"allowed": False, "reason_codes": (UNKNOWN_CALL_TARGET_REASON,)}
            ),
            proposal=None,
        )


def _error_category_to_reason_code(category: ErrorCategory) -> str:
    """Map an ErrorCategory to a capability-engine reason code."""
    _MAP = {
        ErrorCategory.NOT_FOUND: _REASON_NOT_FOUND,
        ErrorCategory.DEPENDENCY: _REASON_DEPENDENCY_ERROR,
        ErrorCategory.CONFLICT: "conflict",
        ErrorCategory.VALIDATION: "validation_error",
        ErrorCategory.INTERNAL: "internal_error",
        ErrorCategory.POLICY: "policy_error",
    }
    return _MAP.get(category, "internal_error")


def _resolve_capability_embedding_profile_fingerprint(
    settings: CoreRuntimeSettings,
) -> str:
    """Read the capability-embedding profile fingerprint from root settings only."""
    service_settings = settings.core.service.model_dump(mode="python")
    language_model = service_settings.get("language_model", {})
    if not isinstance(language_model, dict):
        return ""
    capability_embedding = language_model.get("capability_embedding", {})
    if not isinstance(capability_embedding, dict):
        return ""
    provider = str(capability_embedding.get("provider", "")).strip()
    model = str(capability_embedding.get("model", "")).strip()
    dimensions = int(capability_embedding.get("dimensions", 0) or 0)
    return json.dumps(
        {
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
        },
        sort_keys=True,
    )


def _parse_capability_embedding_profile_fingerprint(
    fingerprint: str,
) -> tuple[str, str, int]:
    """Parse the configured capability-embedding fingerprint into lookup fields."""
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
