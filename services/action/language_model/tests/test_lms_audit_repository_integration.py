"""Integration tests for LMS provider call audit persistence."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import select

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from resources.adapters.litellm import (
    AdapterChatMessage,
    AdapterChatToolCall,
    AdapterChatToolDefinition,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterProviderCallAudit,
    AdapterToolChatResult,
    LiteLlmAdapter,
)
from services.action.language_model.config import (
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
)
from services.action.language_model.data.repository import (
    PostgresLanguageModelCallAuditRepository,
)
from services.action.language_model.data.runtime import LanguageModelPostgresRuntime
from services.action.language_model.data.schema import call_audits
from services.action.language_model.domain import ChatMessage, ChatToolDefinition
from services.action.language_model.implementation import DefaultLanguageModelService
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


class _AuditAdapter(LiteLlmAdapter):
    """Deterministic adapter fake that records one tool-chat success or failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def chat(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str = "",
        prompt: str,
    ):
        del system_prompt
        raise NotImplementedError

    def chat_batch(self, *, provider: str, model: str, prompts: Sequence[str]):
        raise NotImplementedError

    def chat_with_tools(
        self,
        *,
        provider: str,
        model: str,
        messages: Sequence[AdapterChatMessage],
        tools: Sequence[AdapterChatToolDefinition],
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> AdapterToolChatResult:
        del tool_choice, parallel_tool_calls
        raw_call = AdapterProviderCallAudit(
            request_api_base="https://api.example.test/v1/messages",
            request_headers={"x-trace": "test"},
            request_body={
                "provider": provider,
                "model": model,
                "messages": [
                    {"role": item.role, "content": item.content} for item in messages
                ],
                "tools": [item.name for item in tools],
            },
            response_body={"id": "resp_123", "stop_reason": "tool_use"},
        )
        if self._fail:
            raise AdapterDependencyError("rate limited", raw_call=raw_call)
        return AdapterToolChatResult(
            text=None,
            tool_calls=(
                AdapterChatToolCall(
                    tool_name="demo-tool",
                    args_json='{"value":"x"}',
                    tool_call_id="call-1",
                ),
            ),
            provider=provider,
            model=model,
            finish_reason="tool_call",
            raw_call=raw_call,
        )

    def embed(self, *, provider: str, model: str, text: str) -> AdapterEmbeddingResult:
        raise NotImplementedError

    def embed_batch(
        self, *, provider: str, model: str, texts: Sequence[str]
    ) -> list[AdapterEmbeddingResult]:
        raise NotImplementedError

    def health(self) -> AdapterHealthResult:
        return AdapterHealthResult(adapter_ready=True, detail="ok")


def _settings() -> LanguageModelServiceSettings:
    return LanguageModelServiceSettings(
        document_embedding=LanguageModelProfileSettings(
            provider="ollama", model="embed"
        ),
        capability_embedding=LanguageModelProfileSettings(
            provider="ollama", model="embed-cap"
        ),
        quick=LanguageModelProfileSettings(provider="unit", model="quick"),
        standard=LanguageModelProfileSettings(provider="unit", model="standard"),
        deep=LanguageModelProfileSettings(provider="unit", model="deep"),
    )


def _meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_chat_with_tools_persists_postgres_audit_rows(
    migrated_integration_settings,
) -> None:
    """Successful tool chat should append one durable LMS audit row."""
    runtime = LanguageModelPostgresRuntime.from_settings(migrated_integration_settings)
    service = DefaultLanguageModelService(
        settings=_settings(),
        adapter=_AuditAdapter(),
        audit_repository=PostgresLanguageModelCallAuditRepository(
            runtime.schema_sessions
        ),
    )

    result = service.chat_with_tools(
        meta=_meta(),
        messages=[ChatMessage(role="user", content="find the resume")],
        tools=[
            ChatToolDefinition(
                name="demo-tool", parameters_json_schema={"type": "object"}
            )
        ],
    )

    assert result.ok is True
    with runtime.schema_sessions.session() as session:
        rows = session.execute(
            select(
                call_audits.c.trace_id,
                call_audits.c.call_index,
                call_audits.c.request_phase,
                call_audits.c.outcome_kind,
                call_audits.c.request_json,
                call_audits.c.response_json,
            )
        ).all()
    assert rows
    row = rows[-1]
    assert row.call_index == 1
    assert row.request_phase == "initial"
    assert row.outcome_kind == "tool_call"
    assert row.request_json["body"]["messages"][0]["content"] == "find the resume"
    assert row.response_json["body"]["id"] == "resp_123"


def test_chat_with_tools_failure_persists_non_empty_postgres_audit_rows(
    migrated_integration_settings,
) -> None:
    """Dependency failures should still persist useful raw request and error data."""
    runtime = LanguageModelPostgresRuntime.from_settings(migrated_integration_settings)
    service = DefaultLanguageModelService(
        settings=_settings(),
        adapter=_AuditAdapter(fail=True),
        audit_repository=PostgresLanguageModelCallAuditRepository(
            runtime.schema_sessions
        ),
    )

    result = service.chat_with_tools(
        meta=_meta(),
        messages=[ChatMessage(role="user", content="find the resume")],
        tools=[
            ChatToolDefinition(
                name="demo-tool", parameters_json_schema={"type": "object"}
            )
        ],
    )

    assert result.ok is False
    with runtime.schema_sessions.session() as session:
        rows = session.execute(
            select(
                call_audits.c.outcome_kind,
                call_audits.c.error_message,
                call_audits.c.request_json,
                call_audits.c.response_json,
            )
        ).all()
    error_rows = [row for row in rows if row.outcome_kind == "error"]
    assert error_rows
    row = error_rows[-1]
    assert row.error_message == "rate limited"
    assert row.request_json["body"]["tools"] == ["demo-tool"]
    assert row.response_json["body"]["id"] == "resp_123"
