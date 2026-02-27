"""Thin typed wrappers for Brain Core SDK HTTP operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from packages.brain_sdk.errors import (
    BrainTransportError,
    map_transport_error,
    raise_for_domain_errors,
)
from packages.brain_shared.http.errors import HttpRequestError, HttpStatusError


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
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> CoreHealthResult:
    """Execute one Core health request and map response payload."""
    data = _post_json(
        operation="core.health",
        http=http,
        url="/health",
        body=metadata,
        timeout_seconds=timeout_seconds,
        method="get",
    )
    services = {
        k: CoreComponentHealth(
            ready=bool(v.get("ready")), detail=str(v.get("detail", ""))
        )
        for k, v in data.get("services", {}).items()
    }
    resources = {
        k: CoreComponentHealth(
            ready=bool(v.get("ready")), detail=str(v.get("detail", ""))
        )
        for k, v in data.get("resources", {}).items()
    }
    return CoreHealthResult(
        ready=bool(data.get("ready")),
        services=services,
        resources=resources,
    )


def call_lms_chat(
    *,
    http: object,
    metadata: dict[str, object],
    prompt: str,
    profile: str,
    timeout_seconds: float,
) -> LmsChatResult:
    """Execute one LMS chat request and map response payload."""
    data = _post_json(
        operation="lms.chat",
        http=http,
        url="/lms/chat",
        body={**metadata, "prompt": prompt, "profile": _reasoning_level(profile)},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(operation="lms.chat", errors=data.get("errors", []))
    payload = data.get("payload", {})
    return LmsChatResult(
        text=str(payload.get("text", "")),
        provider=str(payload.get("provider", "")),
        model=str(payload.get("model", "")),
    )


def call_vault_get(
    *,
    http: object,
    metadata: dict[str, object],
    file_path: str,
    timeout_seconds: float,
) -> VaultFile:
    """Execute one VAS get-file request and map response payload."""
    data = _post_json(
        operation="vault.get",
        http=http,
        url="/vault/files/get",
        body={**metadata, "file_path": file_path},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(operation="vault.get", errors=data.get("errors", []))
    payload = data.get("payload", {})
    return VaultFile(
        path=str(payload.get("path", "")),
        content=str(payload.get("content", "")),
        size_bytes=int(payload.get("size_bytes", 0)),
        created_at=_parse_datetime(payload.get("created_at")),
        updated_at=_parse_datetime(payload.get("updated_at")),
        revision=str(payload.get("revision", "")),
    )


def call_vault_list(
    *,
    http: object,
    metadata: dict[str, object],
    directory_path: str,
    timeout_seconds: float,
) -> list[VaultEntry]:
    """Execute one VAS list-directory request and map response payload."""
    data = _post_json(
        operation="vault.list",
        http=http,
        url="/vault/directories/list",
        body={**metadata, "directory_path": directory_path},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(operation="vault.list", errors=data.get("errors", []))
    return [_vault_entry(item) for item in data.get("payload", [])]


def call_vault_search(
    *,
    http: object,
    metadata: dict[str, object],
    query: str,
    directory_scope: str,
    limit: int,
    timeout_seconds: float,
) -> list[VaultSearchMatch]:
    """Execute one VAS search-files request and map response payload."""
    data = _post_json(
        operation="vault.search",
        http=http,
        url="/vault/files/search",
        body={
            **metadata,
            "query": query,
            "directory_scope": directory_scope,
            "limit": limit,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(operation="vault.search", errors=data.get("errors", []))
    return [_vault_search_match(item) for item in data.get("payload", [])]


def _post_json(
    *,
    operation: str,
    http: object,
    url: str,
    body: dict[str, object],
    timeout_seconds: float,
    method: str = "post",
) -> dict[str, Any]:
    """Issue one HTTP request and return the JSON response dict."""
    try:
        if method == "get":
            return http.get_json(url, timeout=timeout_seconds)  # type: ignore[union-attr]
        return http.post_json(url, json=body, timeout=timeout_seconds)  # type: ignore[union-attr]
    except HttpStatusError as exc:
        retryable = exc.status_code >= 500 or exc.status_code == 429
        raise map_transport_error(
            operation=operation,
            status_code=exc.status_code,
            message=exc.response_body or str(exc),
            retryable=retryable,
        ) from exc
    except HttpRequestError as exc:
        raise BrainTransportError(
            message=f"{operation} transport failure: {exc}",
            operation=operation,
            status_code=0,
            retryable=True,
        ) from exc


def _reasoning_level(profile: str) -> str:
    """Validate and normalize reasoning profile name."""
    normalized = profile.strip().lower()
    if normalized not in {"quick", "standard", "deep"}:
        raise ValueError("profile must be one of: quick, standard, deep")
    return normalized


def _vault_entry(value: dict[str, Any]) -> VaultEntry:
    return VaultEntry(
        path=str(value.get("path", "")),
        name=str(value.get("name", "")),
        entry_type=str(value.get("entry_type", "unspecified")),
        size_bytes=int(value.get("size_bytes", 0)),
        created_at=_parse_datetime(value.get("created_at")),
        updated_at=_parse_datetime(value.get("updated_at")),
        revision=str(value.get("revision", "")),
    )


def _vault_search_match(value: dict[str, Any]) -> VaultSearchMatch:
    return VaultSearchMatch(
        path=str(value.get("path", "")),
        score=float(value.get("score", 0.0)),
        snippets=tuple(value.get("snippets", [])),
        updated_at=_parse_datetime(value.get("updated_at")),
        revision=str(value.get("revision", "")),
    )


def _parse_datetime(value: object) -> datetime:
    """Parse ISO datetime string or return epoch UTC on failure."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime(1970, 1, 1, tzinfo=UTC)


def core_health(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> CoreHealthResult:
    """High-level SDK wrapper for Core health checks."""
    return client.core_health(  # type: ignore[union-attr]
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
    return client.lms_chat(  # type: ignore[union-attr]
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
    return client.vault_get(  # type: ignore[union-attr]
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
    return client.vault_list(  # type: ignore[union-attr]
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
    return client.vault_search(  # type: ignore[union-attr]
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
) -> object:
    """Build metadata overrides only when call-site values are provided."""
    from packages.brain_sdk.meta import MetaOverrides

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
