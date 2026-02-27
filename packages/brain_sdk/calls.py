"""Thin typed wrappers for Brain Core SDK gRPC operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

import grpc

from packages.brain_sdk._generated import core_health_pb2, language_model_pb2, vault_pb2
from packages.brain_sdk.errors import map_transport_error, raise_for_domain_errors
from packages.brain_sdk.meta import MetaOverrides, timestamp_to_datetime


@dataclass(frozen=True, slots=True)
class CoreComponentHealth:
    """Aggregate readiness for one Core component."""

    ready: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CoreHealthResult:
    """Aggregate Core health status."""

    ready: bool
    services: dict[str, CoreComponentHealth]
    resources: dict[str, CoreComponentHealth]


@dataclass(frozen=True, slots=True)
class LmsChatResult:
    """Language model chat completion payload."""

    text: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class VaultEntry:
    """One vault directory entry."""

    path: str
    name: str
    entry_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime
    revision: str


@dataclass(frozen=True, slots=True)
class VaultFile:
    """One vault file payload."""

    path: str
    content: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime
    revision: str


@dataclass(frozen=True, slots=True)
class VaultSearchMatch:
    """One vault search match payload."""

    path: str
    score: float
    snippets: tuple[str, ...]
    updated_at: datetime
    revision: str


def call_core_health(
    *,
    rpc: Callable[..., object],
    metadata: object,
    timeout_seconds: float,
    wait_for_ready: bool,
) -> CoreHealthResult:
    """Execute one Core health RPC and map envelope payload/errors."""
    response = _call_rpc(
        operation="core.health",
        rpc=rpc,
        request=core_health_pb2.CoreHealthRequest(
            metadata=metadata,
            payload=core_health_pb2.CoreHealthPayload(),
        ),
        timeout_seconds=timeout_seconds,
        wait_for_ready=wait_for_ready,
    )
    payload = response.payload
    services = {
        key: CoreComponentHealth(ready=value.ready, detail=value.detail)
        for key, value in payload.services.items()
    }
    resources = {
        key: CoreComponentHealth(ready=value.ready, detail=value.detail)
        for key, value in payload.resources.items()
    }
    return CoreHealthResult(ready=payload.ready, services=services, resources=resources)


def call_lms_chat(
    *,
    rpc: Callable[..., object],
    metadata: object,
    prompt: str,
    profile: str,
    timeout_seconds: float,
    wait_for_ready: bool,
) -> LmsChatResult:
    """Execute one LMS chat RPC and map envelope payload/errors."""
    response = _call_rpc(
        operation="lms.chat",
        rpc=rpc,
        request=language_model_pb2.ChatRequest(
            metadata=metadata,
            payload=language_model_pb2.ChatPayload(
                prompt=prompt,
                profile=_reasoning_level(profile),
            ),
        ),
        timeout_seconds=timeout_seconds,
        wait_for_ready=wait_for_ready,
    )
    return LmsChatResult(
        text=response.payload.text,
        provider=response.payload.provider,
        model=response.payload.model,
    )


def call_vault_get(
    *,
    rpc: Callable[..., object],
    metadata: object,
    file_path: str,
    timeout_seconds: float,
    wait_for_ready: bool,
) -> VaultFile:
    """Execute one VAS get-file RPC and map envelope payload/errors."""
    response = _call_rpc(
        operation="vault.get",
        rpc=rpc,
        request=vault_pb2.GetFileRequest(
            metadata=metadata,
            payload=vault_pb2.GetFilePayload(file_path=file_path),
        ),
        timeout_seconds=timeout_seconds,
        wait_for_ready=wait_for_ready,
    )
    return _vault_file(response.payload)


def call_vault_list(
    *,
    rpc: Callable[..., object],
    metadata: object,
    directory_path: str,
    timeout_seconds: float,
    wait_for_ready: bool,
) -> list[VaultEntry]:
    """Execute one VAS list-directory RPC and map envelope payload/errors."""
    response = _call_rpc(
        operation="vault.list",
        rpc=rpc,
        request=vault_pb2.ListDirectoryRequest(
            metadata=metadata,
            payload=vault_pb2.ListDirectoryPayload(directory_path=directory_path),
        ),
        timeout_seconds=timeout_seconds,
        wait_for_ready=wait_for_ready,
    )
    return [_vault_entry(item) for item in response.payload]


def call_vault_search(
    *,
    rpc: Callable[..., object],
    metadata: object,
    query: str,
    directory_scope: str,
    limit: int,
    timeout_seconds: float,
    wait_for_ready: bool,
) -> list[VaultSearchMatch]:
    """Execute one VAS search-files RPC and map envelope payload/errors."""
    response = _call_rpc(
        operation="vault.search",
        rpc=rpc,
        request=vault_pb2.SearchFilesRequest(
            metadata=metadata,
            payload=vault_pb2.SearchFilesPayload(
                query=query,
                directory_scope=directory_scope,
                limit=limit,
            ),
        ),
        timeout_seconds=timeout_seconds,
        wait_for_ready=wait_for_ready,
    )
    return [_vault_search_match(item) for item in response.payload]


def _call_rpc(
    *,
    operation: str,
    rpc: Callable[..., object],
    request: object,
    timeout_seconds: float,
    wait_for_ready: bool,
) -> object:
    """Invoke one RPC call and normalize transport/domain failures."""
    try:
        response = rpc(
            request,
            timeout=timeout_seconds,
            wait_for_ready=wait_for_ready,
        )
    except grpc.RpcError as error:
        raise map_transport_error(operation=operation, error=error) from error

    raise_for_domain_errors(operation=operation, errors=_response_errors(response))
    return response


def _response_errors(response: object) -> Sequence[object]:
    """Return envelope errors from a response-like protobuf object."""
    return tuple(getattr(response, "errors", ()))


def _reasoning_level(profile: str) -> int:
    """Map CLI-friendly reasoning profile names to protobuf enum values."""
    mapping = {
        "quick": language_model_pb2.REASONING_LEVEL_QUICK,
        "standard": language_model_pb2.REASONING_LEVEL_STANDARD,
        "deep": language_model_pb2.REASONING_LEVEL_DEEP,
    }
    normalized = profile.strip().lower()
    if normalized not in mapping:
        raise ValueError("profile must be one of: quick, standard, deep")
    return mapping[normalized]


def _vault_entry(value: object) -> VaultEntry:
    """Convert protobuf ``VaultEntry`` payload to SDK dataclass."""
    entry_type = {
        vault_pb2.VAULT_ENTRY_TYPE_DIRECTORY: "directory",
        vault_pb2.VAULT_ENTRY_TYPE_FILE: "file",
    }.get(int(value.entry_type), "unspecified")
    return VaultEntry(
        path=value.path,
        name=value.name,
        entry_type=entry_type,
        size_bytes=int(value.size_bytes),
        created_at=timestamp_to_datetime(value.created_at),
        updated_at=timestamp_to_datetime(value.updated_at),
        revision=value.revision,
    )


def _vault_file(value: object) -> VaultFile:
    """Convert protobuf ``VaultFileRecord`` payload to SDK dataclass."""
    return VaultFile(
        path=value.path,
        content=value.content,
        size_bytes=int(value.size_bytes),
        created_at=timestamp_to_datetime(value.created_at),
        updated_at=timestamp_to_datetime(value.updated_at),
        revision=value.revision,
    )


def _vault_search_match(value: object) -> VaultSearchMatch:
    """Convert protobuf ``SearchFileMatch`` payload to SDK dataclass."""
    return VaultSearchMatch(
        path=value.path,
        score=float(value.score),
        snippets=tuple(value.snippets),
        updated_at=timestamp_to_datetime(value.updated_at),
        revision=value.revision,
    )


def core_health(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> CoreHealthResult:
    """High-level SDK wrapper for Core health checks."""
    return client.core_health(
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def lms_chat(
    *,
    client: object,
    prompt: str = "",
    message: str = "",
    profile: str = "standard",
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> LmsChatResult:
    """High-level SDK wrapper for LMS chat calls."""
    input_prompt = prompt if prompt != "" else message
    if input_prompt == "":
        raise ValueError("prompt is required")
    return client.lms_chat(
        input_prompt,
        profile=profile,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def vault_get(
    *,
    client: object,
    file_path: str = "",
    path: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> VaultFile:
    """High-level SDK wrapper for vault get-file calls."""
    target_path = file_path if file_path != "" else path
    if target_path == "":
        raise ValueError("file_path is required")
    return client.vault_get(
        target_path,
        meta=_meta_overrides(trace_id=trace_id, parent_id=parent_id),
    )


def vault_list(
    *,
    client: object,
    directory_path: str = "",
    path: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> list[VaultEntry]:
    """High-level SDK wrapper for vault directory listings."""
    target_path = directory_path if directory_path != "" else path
    return client.vault_list(
        target_path,
        meta=_meta_overrides(trace_id=trace_id, parent_id=parent_id),
    )


def vault_search(
    *,
    client: object,
    query: str,
    directory_scope: str = "",
    limit: int = 20,
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> list[VaultSearchMatch]:
    """High-level SDK wrapper for vault search calls."""
    return client.vault_search(
        query,
        directory_scope=directory_scope,
        limit=limit,
        meta=_meta_overrides(trace_id=trace_id, parent_id=parent_id),
    )


def _meta_overrides(
    *,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MetaOverrides | None:
    """Build metadata overrides only when call-site values are provided."""
    has_values = any(
        (
            principal != "",
            source != "",
            trace_id is not None,
            parent_id is not None,
        )
    )
    if not has_values:
        return None
    return MetaOverrides(
        principal=principal or None,
        source=source or None,
        trace_id=trace_id,
        parent_id="" if parent_id is None else parent_id,
    )
