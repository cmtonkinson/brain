"""Synchronous Brain Core SDK client for CLI/agent callers."""

from __future__ import annotations

import grpc

from packages.brain_sdk._generated import (
    core_health_pb2_grpc,
    language_model_pb2_grpc,
    vault_pb2_grpc,
)
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
from packages.brain_sdk.config import resolve_target, resolve_timeout_seconds
from packages.brain_sdk.meta import MetaOverrides, build_envelope_meta


class BrainClient:
    """Thin gRPC client for selected Core/LMS/Vault operations."""

    def __init__(
        self,
        *,
        config: BrainSdkConfig | None = None,
        channel: grpc.Channel | None = None,
    ) -> None:
        """Create one SDK client with injected channel or config-built channel."""
        self._config = BrainSdkConfig() if config is None else config
        self._owns_channel = channel is None
        self._channel = self._new_channel() if channel is None else channel
        self._core = core_health_pb2_grpc.CoreHealthServiceStub(self._channel)
        self._lms = language_model_pb2_grpc.LanguageModelServiceStub(self._channel)
        self._vault = vault_pb2_grpc.VaultAuthorityServiceStub(self._channel)

    def close(self) -> None:
        """Close underlying gRPC channel when the channel supports closing."""
        close = getattr(self._channel, "close", None)
        if self._owns_channel and callable(close):
            close()

    def __enter__(self) -> BrainClient:
        """Enter context manager scope."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit context manager scope and close channel resources."""
        self.close()

    def core_health(self, *, meta: MetaOverrides | None = None) -> CoreHealthResult:
        """Return aggregate Core health status."""
        return call_core_health(
            rpc=self._core.Health,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            wait_for_ready=self._config.wait_for_ready,
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
            rpc=self._lms.Chat,
            metadata=self._meta(meta),
            prompt=prompt,
            profile=profile,
            timeout_seconds=self._config.timeout_seconds,
            wait_for_ready=self._config.wait_for_ready,
        )

    def vault_get(
        self, file_path: str, *, meta: MetaOverrides | None = None
    ) -> VaultFile:
        """Return one vault file by path."""
        return call_vault_get(
            rpc=self._vault.GetFile,
            metadata=self._meta(meta),
            file_path=file_path,
            timeout_seconds=self._config.timeout_seconds,
            wait_for_ready=self._config.wait_for_ready,
        )

    def vault_list(
        self,
        directory_path: str,
        *,
        meta: MetaOverrides | None = None,
    ) -> list[VaultEntry]:
        """Return one directory listing from vault."""
        return call_vault_list(
            rpc=self._vault.ListDirectory,
            metadata=self._meta(meta),
            directory_path=directory_path,
            timeout_seconds=self._config.timeout_seconds,
            wait_for_ready=self._config.wait_for_ready,
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
            rpc=self._vault.SearchFiles,
            metadata=self._meta(meta),
            query=query,
            directory_scope=directory_scope,
            limit=limit,
            timeout_seconds=self._config.timeout_seconds,
            wait_for_ready=self._config.wait_for_ready,
        )

    def _meta(self, overrides: MetaOverrides | None) -> object:
        """Build one request metadata envelope for an outbound call."""
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

    def _new_channel(self) -> grpc.Channel:
        """Create one gRPC channel from SDK runtime configuration."""
        options = list(self._config.channel_options)
        if self._config.use_tls:
            credentials = grpc.ssl_channel_credentials()
            return grpc.secure_channel(
                self._config.target,
                credentials=credentials,
                options=options,
            )
        return grpc.insecure_channel(self._config.target, options=options)


class BrainSdkClient(BrainClient):
    """CLI-friendly SDK client with constructor aliases for target/timeout args."""

    def __init__(
        self,
        grpc_target: str | None = None,
        timeout: float | None = None,
        *,
        target: str | None = None,
        address: str | None = None,
        timeout_seconds: float | None = None,
        source: str = "cli",
        principal: str = "operator",
        use_tls: bool = False,
        wait_for_ready: bool = False,
        channel_options: tuple[tuple[str, str | int], ...] = (),
        channel: grpc.Channel | None = None,
    ) -> None:
        """Create one SDK client from direct constructor fields."""
        resolved_target = (
            grpc_target
            if grpc_target is not None
            else target
            if target is not None
            else address
        )
        resolved_timeout = resolve_timeout_seconds(
            timeout if timeout is not None else timeout_seconds
        )
        super().__init__(
            config=BrainSdkConfig(
                target=resolve_target(resolved_target),
                timeout_seconds=resolved_timeout,
                source=source,
                principal=principal,
                use_tls=use_tls,
                wait_for_ready=wait_for_ready,
                channel_options=channel_options,
            ),
            channel=channel,
        )
