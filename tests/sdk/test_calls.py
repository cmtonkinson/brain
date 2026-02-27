"""Unit tests for Brain SDK call wrappers."""

from __future__ import annotations

from datetime import UTC, datetime

import grpc
import pytest


class _FakeRpcError(grpc.RpcError):
    def __init__(self, *, status: grpc.StatusCode, details: str) -> None:
        self._status = status
        self._details = details

    def code(self) -> grpc.StatusCode:
        return self._status

    def details(self) -> str:
        return self._details


def _meta() -> object:
    from packages.brain_sdk.meta import build_envelope_meta

    return build_envelope_meta(source="tests", principal="operator")


def _timestamp() -> object:
    from packages.brain_sdk._generated import vault_pb2

    ts = datetime(2026, 2, 26, 16, 0, 0, tzinfo=UTC)
    msg = vault_pb2.VaultEntry().created_at
    msg.FromDatetime(ts)
    return msg


def test_call_core_health_success() -> None:
    """Core health wrapper should return mapped component dictionaries."""
    from packages.brain_sdk._generated import core_health_pb2
    from packages.brain_sdk.calls import call_core_health

    def _rpc(*_: object, **__: object) -> object:
        return core_health_pb2.CoreHealthResponse(
            payload=core_health_pb2.CoreHealthStatus(
                ready=True,
                services={
                    "svc": core_health_pb2.CoreComponentHealthStatus(
                        ready=True,
                        detail="ok",
                    )
                },
                resources={
                    "res": core_health_pb2.CoreComponentHealthStatus(
                        ready=False,
                        detail="degraded",
                    )
                },
            )
        )

    result = call_core_health(
        rpc=_rpc,
        metadata=_meta(),
        timeout_seconds=1.0,
        wait_for_ready=False,
    )

    assert result.ready is True
    assert result.services["svc"].detail == "ok"
    assert result.resources["res"].ready is False


def test_call_lms_chat_success() -> None:
    """Chat wrapper should return simple chat payload dataclass."""
    from packages.brain_sdk._generated import language_model_pb2
    from packages.brain_sdk.calls import call_lms_chat

    def _rpc(*_: object, **__: object) -> object:
        return language_model_pb2.ChatResponse(
            payload=language_model_pb2.ChatResult(
                text="hello",
                provider="local",
                model="model-a",
            )
        )

    result = call_lms_chat(
        rpc=_rpc,
        metadata=_meta(),
        prompt="hi",
        profile="standard",
        timeout_seconds=1.0,
        wait_for_ready=False,
    )

    assert result.text == "hello"
    assert result.provider == "local"
    assert result.model == "model-a"


def test_call_vault_get_list_search_success() -> None:
    """Vault wrappers should map file/list/search payloads to dataclasses."""
    from packages.brain_sdk._generated import vault_pb2
    from packages.brain_sdk.calls import (
        call_vault_get,
        call_vault_list,
        call_vault_search,
    )

    updated_at = _timestamp()

    def _get(*_: object, **__: object) -> object:
        return vault_pb2.GetFileResponse(
            payload=vault_pb2.VaultFileRecord(
                path="notes/today.md",
                content="content",
                size_bytes=7,
                created_at=updated_at,
                updated_at=updated_at,
                revision="r1",
            )
        )

    def _list(*_: object, **__: object) -> object:
        return vault_pb2.ListDirectoryResponse(
            payload=[
                vault_pb2.VaultEntry(
                    path="notes/today.md",
                    name="today.md",
                    entry_type=vault_pb2.VAULT_ENTRY_TYPE_FILE,
                    size_bytes=7,
                    created_at=updated_at,
                    updated_at=updated_at,
                    revision="r1",
                )
            ]
        )

    def _search(*_: object, **__: object) -> object:
        return vault_pb2.SearchFilesResponse(
            payload=[
                vault_pb2.SearchFileMatch(
                    path="notes/today.md",
                    score=0.9,
                    snippets=["today"],
                    updated_at=updated_at,
                    revision="r1",
                )
            ]
        )

    file_record = call_vault_get(
        rpc=_get,
        metadata=_meta(),
        file_path="notes/today.md",
        timeout_seconds=1.0,
        wait_for_ready=False,
    )
    entries = call_vault_list(
        rpc=_list,
        metadata=_meta(),
        directory_path="notes",
        timeout_seconds=1.0,
        wait_for_ready=False,
    )
    matches = call_vault_search(
        rpc=_search,
        metadata=_meta(),
        query="today",
        directory_scope="notes",
        limit=5,
        timeout_seconds=1.0,
        wait_for_ready=False,
    )

    assert file_record.path == "notes/today.md"
    assert entries[0].entry_type == "file"
    assert matches[0].snippets == ("today",)


def test_call_wrappers_raise_domain_and_transport_errors() -> None:
    """Wrappers should raise typed domain and transport failures."""
    from packages.brain_sdk._generated import envelope_pb2, language_model_pb2
    from packages.brain_sdk.calls import call_lms_chat, call_vault_get
    from packages.brain_sdk.errors import BrainTransportError, BrainValidationError

    def _domain_error(*_: object, **__: object) -> object:
        return language_model_pb2.ChatResponse(
            errors=[
                envelope_pb2.ErrorDetail(
                    code="INVALID_ARGUMENT",
                    message="prompt required",
                    category=envelope_pb2.ERROR_CATEGORY_VALIDATION,
                    retryable=False,
                )
            ]
        )

    with pytest.raises(BrainValidationError):
        call_lms_chat(
            rpc=_domain_error,
            metadata=_meta(),
            prompt="",
            profile="standard",
            timeout_seconds=1.0,
            wait_for_ready=False,
        )

    def _transport_error(*_: object, **__: object) -> object:
        raise _FakeRpcError(status=grpc.StatusCode.UNAVAILABLE, details="offline")

    with pytest.raises(BrainTransportError):
        call_vault_get(
            rpc=_transport_error,
            metadata=_meta(),
            file_path="notes/today.md",
            timeout_seconds=1.0,
            wait_for_ready=False,
        )
