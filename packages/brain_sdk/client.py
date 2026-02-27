"""Synchronous Brain Core SDK client for CLI/agent callers."""

from __future__ import annotations

import httpx

from packages.brain_sdk.calls import (
    CoreHealthResult,
    LmsChatResult,
    VaultEntry,
    VaultFile,
    VaultSearchMatch,
    call_core_health,
    call_lms_chat,
    call_vault_get,
    call_vault_list,
    call_vault_search,
)
from packages.brain_sdk.config import BrainSdkConfig
from packages.brain_sdk.config import resolve_socket_path, resolve_timeout_seconds
from packages.brain_sdk.meta import MetaOverrides, build_envelope_meta
from packages.brain_shared.http.client import HttpClient


class BrainClient:
    """Thin HTTP client for selected Core/LMS/Vault operations."""

    def __init__(
        self,
        *,
        config: BrainSdkConfig | None = None,
        http: HttpClient | None = None,
    ) -> None:
        """Create one SDK client with injected HttpClient or config-built client."""
        self._config = BrainSdkConfig() if config is None else config
        self._owns_http = http is None
        self._http = http if http is not None else self._new_http_client()

    def close(self) -> None:
        """Close underlying HTTP client when owned."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> BrainClient:
        """Enter context manager scope."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit context manager scope and close client resources."""
        self.close()

    def core_health(self, *, meta: MetaOverrides | None = None) -> CoreHealthResult:
        """Return aggregate Core health status."""
        return call_core_health(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def lms_chat(
        self,
        prompt: str,
        *,
        profile: str = "standard",
        meta: MetaOverrides | None = None,
    ) -> LmsChatResult:
        """Return one language model chat completion."""
        return call_lms_chat(
            http=self._http,
            metadata=self._meta(meta),
            prompt=prompt,
            profile=profile,
            timeout_seconds=self._config.timeout_seconds,
        )

    def vault_get(
        self, file_path: str, *, meta: MetaOverrides | None = None
    ) -> VaultFile:
        """Return one vault file by path."""
        return call_vault_get(
            http=self._http,
            metadata=self._meta(meta),
            file_path=file_path,
            timeout_seconds=self._config.timeout_seconds,
        )

    def vault_list(
        self,
        directory_path: str,
        *,
        meta: MetaOverrides | None = None,
    ) -> list[VaultEntry]:
        """Return one directory listing from vault."""
        return call_vault_list(
            http=self._http,
            metadata=self._meta(meta),
            directory_path=directory_path,
            timeout_seconds=self._config.timeout_seconds,
        )

    def vault_search(
        self,
        query: str,
        *,
        directory_scope: str = "",
        limit: int = 20,
        meta: MetaOverrides | None = None,
    ) -> list[VaultSearchMatch]:
        """Return vault file matches for one search query."""
        return call_vault_search(
            http=self._http,
            metadata=self._meta(meta),
            query=query,
            directory_scope=directory_scope,
            limit=limit,
            timeout_seconds=self._config.timeout_seconds,
        )

    def _meta(self, overrides: MetaOverrides | None) -> dict[str, object]:
        """Build one request metadata dict for an outbound call."""
        value = MetaOverrides() if overrides is None else overrides
        return build_envelope_meta(
            source=self._config.source if value.source is None else value.source,
            principal=(
                self._config.principal if value.principal is None else value.principal
            ),
            trace_id=value.trace_id,
            parent_id=value.parent_id,
            envelope_id=value.envelope_id,
            timestamp=value.timestamp,
        )

    def _new_http_client(self) -> HttpClient:
        """Create one HttpClient over UDS from SDK runtime configuration."""
        transport = httpx.HTTPTransport(uds=self._config.socket_path)
        return HttpClient(
            base_url="http://localhost",
            timeout_seconds=self._config.timeout_seconds,
            transport=transport,
        )


class BrainSdkClient(BrainClient):
    """CLI-friendly SDK client with constructor aliases for socket/timeout args."""

    def __init__(
        self,
        socket: str | None = None,
        timeout: float | None = None,
        *,
        socket_path: str | None = None,
        target: str | None = None,
        address: str | None = None,
        timeout_seconds: float | None = None,
        source: str = "cli",
        principal: str = "operator",
        http: HttpClient | None = None,
    ) -> None:
        """Create one SDK client from direct constructor fields."""
        resolved_socket = (
            socket
            if socket is not None
            else socket_path
            if socket_path is not None
            else target
            if target is not None
            else address
        )
        resolved_timeout = resolve_timeout_seconds(
            timeout if timeout is not None else timeout_seconds
        )
        super().__init__(
            config=BrainSdkConfig(
                socket_path=resolve_socket_path(resolved_socket),
                timeout_seconds=resolved_timeout,
                source=source,
                principal=principal,
            ),
            http=http,
        )
