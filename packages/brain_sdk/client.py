"""Synchronous Brain Core SDK client for CLI/agent callers."""

from __future__ import annotations

from packages.brain_sdk.calls import (
    CapabilityDescriptor,
    CapabilityInvokeResult,
    CapabilitySearchHit,
    CoreHealthResult,
    LmsChatResult,
    LmsChatMessage,
    LmsChatToolDefinition,
    LmsToolChatResult,
    MemoryContextBlock,
    MemorySessionRef,
    SwitchboardOperatorInstruction,
    call_capabilities_describe,
    call_capabilities_list_always_on,
    call_capabilities_search,
    call_capability_describe,
    call_capability_invoke,
    call_core_health,
    call_lms_chat,
    call_lms_chat_with_tools,
    call_memory_assemble_context,
    call_memory_create_session,
    call_memory_get_latest_or_create_session,
    call_memory_record_response,
    call_switchboard_poll_operator_instruction,
)
from packages.brain_sdk.config import (
    BrainSdkConfig,
    resolve_host,
    resolve_port,
    resolve_timeout_seconds,
)
from packages.brain_sdk.meta import MetaOverrides, build_envelope_meta
from packages.brain_shared.http.client import HttpClient


class BrainClient:
    """Thin HTTP client for selected Core operations."""

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

    def describe_capabilities(
        self, *, meta: MetaOverrides | None = None
    ) -> tuple[CapabilityDescriptor, ...]:
        """Return all active Capability descriptors."""
        return call_capabilities_describe(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def list_always_on_capabilities(
        self, *, meta: MetaOverrides | None = None
    ) -> tuple[CapabilityDescriptor, ...]:
        """Return full descriptors for configured always-on capabilities."""
        return call_capabilities_list_always_on(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def search_capabilities(
        self,
        *,
        query: str,
        limit: int | None = None,
        meta: MetaOverrides | None = None,
    ) -> tuple[CapabilitySearchHit, ...]:
        """Search the CES capability catalog."""
        return call_capabilities_search(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            query=query,
            limit=limit,
        )

    def describe_capability(
        self,
        *,
        capability_id: str,
        meta: MetaOverrides | None = None,
    ) -> CapabilityDescriptor:
        """Return one full capability descriptor by id."""
        return call_capability_describe(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            capability_id=capability_id,
        )

    def invoke_capability(
        self,
        *,
        capability_id: str,
        input_payload: dict[str, object] | None = None,
        actor: str = "",
        channel: str = "",
        invocation_id: str = "",
        parent_invocation_id: str = "",
        confirmed: bool = False,
        approval_token: str = "",
        meta: MetaOverrides | None = None,
    ) -> CapabilityInvokeResult:
        """Invoke one Capability via the CES route surface."""
        return call_capability_invoke(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            capability_id=capability_id,
            input_payload=input_payload,
            actor=actor,
            channel=channel,
            invocation_id=invocation_id,
            parent_invocation_id=parent_invocation_id,
            confirmed=confirmed,
            approval_token=approval_token,
        )

    def lms_chat(
        self,
        *,
        prompt: str,
        profile: str = "standard",
        meta: MetaOverrides | None = None,
    ) -> LmsChatResult:
        """Execute one direct LMS chat request."""
        return call_lms_chat(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            prompt=prompt,
            profile=profile,
        )

    def lms_chat_with_tools(
        self,
        *,
        messages: tuple[LmsChatMessage, ...],
        tools: tuple[LmsChatToolDefinition, ...] = (),
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
        allow_text_output: bool = True,
        profile: str = "standard",
        meta: MetaOverrides | None = None,
    ) -> LmsToolChatResult:
        """Execute one tool-capable LMS chat request."""
        return call_lms_chat_with_tools(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            allow_text_output=allow_text_output,
            profile=profile,
        )

    def memory_assemble_context(
        self,
        *,
        session_id: str,
        message: str,
        meta: MetaOverrides | None = None,
    ) -> MemoryContextBlock:
        """Append one inbound turn and return the assembled MAS context."""
        return call_memory_assemble_context(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            message=message,
        )

    def memory_create_session(
        self,
        *,
        meta: MetaOverrides | None = None,
    ) -> MemorySessionRef:
        """Create one MAS session and return the new session identifier."""
        return call_memory_create_session(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def memory_get_latest_or_create_session(
        self,
        *,
        meta: MetaOverrides | None = None,
    ) -> MemorySessionRef:
        """Return the latest MAS session id or create one when none exist."""
        return call_memory_get_latest_or_create_session(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def memory_record_response(
        self,
        *,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
        meta: MetaOverrides | None = None,
    ) -> bool:
        """Append one outbound MAS response turn."""
        return call_memory_record_response(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            content=content,
            model=model,
            provider=provider,
            token_count=token_count,
            reasoning_level=reasoning_level,
        )

    def switchboard_poll_operator_instruction(
        self,
        *,
        wait_timeout_seconds: float = 0.0,
        meta: MetaOverrides | None = None,
    ) -> SwitchboardOperatorInstruction | None:
        """Poll Switchboard for the next queued operator instruction."""
        return call_switchboard_poll_operator_instruction(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
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
        """Create one HttpClient over TCP from SDK runtime configuration."""
        return HttpClient(
            base_url=f"http://{self._config.host}:{self._config.port}",
            timeout_seconds=self._config.timeout_seconds,
        )


class BrainSdkClient(BrainClient):
    """CLI-friendly SDK client with constructor aliases for host/port args."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
        *,
        timeout_seconds: float | None = None,
        source: str = "cli",
        principal: str = "operator",
        http: HttpClient | None = None,
    ) -> None:
        """Create one SDK client from direct constructor fields."""
        resolved_timeout = resolve_timeout_seconds(
            timeout if timeout is not None else timeout_seconds
        )
        super().__init__(
            config=BrainSdkConfig(
                host=resolve_host(host),
                port=resolve_port(port),
                timeout_seconds=resolved_timeout,
                source=source,
                principal=principal,
            ),
            http=http,
        )
