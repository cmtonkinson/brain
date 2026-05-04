"""Tests for the Console client's slash authenticity signing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from actors.console.client import ConsoleClient
from lib.shared.auth.slash_authenticity import (
    generate_and_write_secret,
    verify_proof,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> ConsoleClient:
    """A ConsoleClient with its underlying SDK replaced by a mock."""
    instance = ConsoleClient.__new__(ConsoleClient)
    instance._sdk = MagicMock()  # type: ignore[attr-defined]
    return instance


def test_non_slash_message_is_not_signed(
    monkeypatch: pytest.MonkeyPatch, tmp_path, client: ConsoleClient
) -> None:
    """Plain operator messages should not carry an authenticity proof."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    generate_and_write_secret(tmp_path / "brain" / "slash_authenticity_secret")

    client.ingest("hello brain, how are you?")

    call_kwargs = client._sdk.relay_enqueue_console.call_args.kwargs  # type: ignore[attr-defined]
    assert call_kwargs["message_text"] == "hello brain, how are you?"
    assert call_kwargs["slash_authenticity"] is None


def test_slash_message_is_signed_and_verifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path, client: ConsoleClient
) -> None:
    """A slash command should carry a proof that verifies under the on-disk secret."""
    import time as _time

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    secret = generate_and_write_secret(tmp_path / "brain" / "slash_authenticity_secret")

    text = "/workspace-register --path /tmp/foo"
    client.ingest(text)

    call_kwargs = client._sdk.relay_enqueue_console.call_args.kwargs  # type: ignore[attr-defined]
    assert call_kwargs["message_text"] == text
    proof = call_kwargs["slash_authenticity"]
    assert proof is not None
    assert verify_proof(
        secret,
        channel="console",
        message_text=text,
        proof=proof,
        now_ms=int(_time.time() * 1000),
        validity_seconds=60,
    )


def test_slash_message_with_missing_secret_returns_none_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path, client: ConsoleClient
) -> None:
    """If the secret file is absent, the proof is None and Policy will deny."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    client.ingest("/workspace-register --path /tmp/foo")

    call_kwargs = client._sdk.relay_enqueue_console.call_args.kwargs  # type: ignore[attr-defined]
    assert call_kwargs["slash_authenticity"] is None
