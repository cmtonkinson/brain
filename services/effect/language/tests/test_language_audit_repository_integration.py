"""Integration tests for Language provider call audit persistence."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from lib.shared.envelope import EnvelopeKind, new_meta
from resources.adapters.llm import (
    AdapterChatToolCall,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterProviderCallAudit,
    AdapterToolChatResult,
    LlmAdapter,
)
from services.effect.language.config import (
    LanguageEmbeddingProfileSettings,
    LanguageProfileSettings,
    LanguageServiceSettings,
)
from services.effect.language.data.repository import (
    PostgresLanguageModelCallAuditRepository,
    PostgresLanguageModelTurnCacheHopRepository,
)
from services.effect.language.data.runtime import LanguagePostgresRuntime
from services.effect.language.data.schema import call_audits, turn_cache_hops
from services.effect.language.implementation import DefaultLanguageService
from tests.integration.helpers import real_provider_tests_enabled
from tests.helpers.inference_request import make_inference_request

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


class _AuditAdapter(LlmAdapter):
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
        inference_request,
    ) -> AdapterToolChatResult:
        # The audit repository treats `request_body` as opaque JSONB, so the
        # exact shape here is not load-bearing for these tests. We mimic the
        # canonical Anthropic Messages API body that `HttpLlmAdapter` emits
        # so readers don't infer that audits store IR-shaped bodies.
        operator_message_text = (
            inference_request.current_turn.operator_message.message_text
        )
        system_text = "".join(
            f"<{block.kind}>\n{block.text}\n</{block.kind}>"
            for block in inference_request.system.blocks
        )
        raw_call = AdapterProviderCallAudit(
            request_api_base="https://api.example.test",
            request_headers={
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "x-api-key": "***",
            },
            request_body={
                "model": model,
                "system": [{"type": "text", "text": system_text}],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "<operator_message>\n<body>\n"
                                    f"{operator_message_text}"
                                    "\n</body>\n</operator_message>"
                                ),
                            }
                        ],
                    }
                ],
                "tools": [],
                "max_tokens": 1024,
                "tool_choice": {"type": "auto"},
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

    def embed(
        self,
        *,
        provider: str,
        model: str,
        text: str,
        dimensions: int | None = None,
    ) -> AdapterEmbeddingResult:
        del provider, model, text, dimensions
        raise NotImplementedError

    def embed_batch(
        self,
        *,
        provider: str,
        model: str,
        texts: Sequence[str],
        dimensions: int | None = None,
    ) -> list[AdapterEmbeddingResult]:
        del provider, model, texts, dimensions
        raise NotImplementedError

    def health(self) -> AdapterHealthResult:
        return AdapterHealthResult(adapter_ready=True, detail="ok")


def _settings() -> LanguageServiceSettings:
    return LanguageServiceSettings(
        document_embedding=LanguageEmbeddingProfileSettings(
            provider="ollama", model="embed", dimensions=1024
        ),
        op_embedding=LanguageEmbeddingProfileSettings(
            provider="ollama", model="embed-cap", dimensions=1024
        ),
        quick=LanguageProfileSettings(provider="unit", model="quick"),
        standard=LanguageProfileSettings(provider="unit", model="standard"),
        deep=LanguageProfileSettings(provider="unit", model="deep"),
    )


def _meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_chat_with_tools_persists_postgres_audit_rows(
    migrated_integration_settings,
) -> None:
    """Successful tool chat should append one durable Language audit row."""
    runtime = LanguagePostgresRuntime.from_settings(migrated_integration_settings)
    service = DefaultLanguageService(
        settings=_settings(),
        adapter=_AuditAdapter(),
        audit_repository=PostgresLanguageModelCallAuditRepository(
            runtime.schema_sessions
        ),
        turn_cache_hop_repository=PostgresLanguageModelTurnCacheHopRepository(
            runtime.schema_sessions
        ),
    )

    result = service.chat_with_tools(
        meta=_meta(),
        inference_request=make_inference_request(),
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
    assert "hello" in row.request_json["body"]["messages"][0]["content"][0]["text"]
    assert row.response_json["body"]["id"] == "resp_123"
    with runtime.schema_sessions.session() as session:
        hop_rows = session.execute(
            select(
                turn_cache_hops.c.trace_id,
                turn_cache_hops.c.hop_ordinal,
                turn_cache_hops.c.call_index,
                turn_cache_hops.c.active_cachepoint_count,
                turn_cache_hops.c.cache_creation_input_tokens,
                turn_cache_hops.c.cache_read_input_tokens,
            )
        ).all()
        view_row = (
            session.execute(
                sa.text(
                    "SELECT hop_count, total_cache_creation_input_tokens, "
                    "total_cache_read_input_tokens "
                    "FROM service_language.turn_cache_traces_v "
                    "WHERE trace_id = :trace_id"
                ),
                {"trace_id": row.trace_id},
            )
            .mappings()
            .one()
        )
    assert hop_rows
    hop_row = hop_rows[-1]
    assert hop_row.hop_ordinal == 1
    assert hop_row.call_index == 1
    assert hop_row.active_cachepoint_count == 0
    assert view_row["hop_count"] == 1
    assert view_row["total_cache_creation_input_tokens"] == 0
    assert view_row["total_cache_read_input_tokens"] == 0


def test_chat_with_tools_failure_persists_non_empty_postgres_audit_rows(
    migrated_integration_settings,
) -> None:
    """Dependency failures should still persist useful raw request and error data."""
    runtime = LanguagePostgresRuntime.from_settings(migrated_integration_settings)
    service = DefaultLanguageService(
        settings=_settings(),
        adapter=_AuditAdapter(fail=True),
        audit_repository=PostgresLanguageModelCallAuditRepository(
            runtime.schema_sessions
        ),
        turn_cache_hop_repository=PostgresLanguageModelTurnCacheHopRepository(
            runtime.schema_sessions
        ),
    )

    result = service.chat_with_tools(
        meta=_meta(),
        inference_request=make_inference_request(),
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
    assert "You are Brain." in row.request_json["body"]["system"][0]["text"]
    assert row.response_json["body"]["id"] == "resp_123"


def test_sum_token_usage_by_trace_aggregates_jsonb(
    migrated_integration_settings,
) -> None:
    """JSONB-extracted token totals aggregate across all matching trace rows."""
    from datetime import UTC, datetime

    from services.effect.language.data.runtime import LanguagePostgresRuntime
    from services.effect.language.domain import LanguageModelCallAuditRow

    runtime = LanguagePostgresRuntime.from_settings(migrated_integration_settings)
    repository = PostgresLanguageModelCallAuditRepository(runtime.schema_sessions)

    trace = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    other = "01YYYYYYYYYYYYYYYYYYYYYYYY"

    def _row(
        *,
        trace_id: str,
        outcome: str,
        usage: dict[str, object],
    ) -> LanguageModelCallAuditRow:
        return LanguageModelCallAuditRow(
            envelope_id="01HEEEEEEEEEEEEEEEEEEEEEEE",
            trace_id=trace_id,
            parent_id="",
            source="test",
            principal="operator",
            provider="anthropic",
            model="claude",
            profile="standard",
            operation="chat_with_tools",
            request_phase="initial",
            outcome_kind=outcome,
            call_index=repository.next_call_index(trace_id=trace_id),
            duration_ms=1.0,
            finish_reason="stop",
            error_message="",
            request_json={"body": {}},
            response_json={"usage": usage},
            created_at=datetime.now(UTC),
        )

    repository.append(
        row=_row(
            trace_id=trace,
            outcome="final",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    repository.append(
        row=_row(
            trace_id=trace,
            outcome="tool_call",
            usage={
                "input_tokens": 60,
                "output_tokens": 30,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 20,
            },
        )
    )
    # Different trace id; must not contribute.
    repository.append(
        row=_row(
            trace_id=other,
            outcome="final",
            usage={"input_tokens": 9999, "output_tokens": 9999},
        )
    )
    # Same trace, but outcome=error; must not contribute either.
    repository.append(
        row=_row(
            trace_id=trace,
            outcome="error",
            usage={"input_tokens": 9999, "output_tokens": 9999},
        )
    )

    totals = repository.sum_token_usage_by_trace(trace_id=trace)
    assert totals.input_tokens == 160
    assert totals.output_tokens == 80
    assert totals.cache_creation_input_tokens == 10
    assert totals.cache_read_input_tokens == 20
    assert totals.call_count == 2
