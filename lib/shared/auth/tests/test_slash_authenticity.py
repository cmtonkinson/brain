"""Tests for the slash authenticity HMAC primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.shared.auth.slash_authenticity import (
    SlashAuthenticityError,
    SlashAuthenticityProof,
    default_secret_path,
    delete_secret,
    generate_and_write_secret,
    mint_proof,
    new_nonce,
    read_secret,
    verify_proof,
)


_SAMPLE_CHANNEL = "console"
_SAMPLE_TEXT = "/workspace-register --path /tmp/foo"
_VALIDITY_SECONDS = 60


def test_secret_roundtrip(tmp_path: Path) -> None:
    """Generated secret is readable, exactly 32 bytes, and 0600-permissioned."""
    path = tmp_path / "secret"
    written = generate_and_write_secret(path)
    assert len(written) == 32
    assert read_secret(path) == written
    assert path.stat().st_mode & 0o777 == 0o600


def test_generate_overwrites_existing(tmp_path: Path) -> None:
    """A second generate replaces the prior file content."""
    path = tmp_path / "secret"
    first = generate_and_write_secret(path)
    second = generate_and_write_secret(path)
    assert first != second
    assert read_secret(path) == second


def test_delete_removes_file_and_tolerates_missing(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    generate_and_write_secret(path)
    assert path.exists()
    delete_secret(path)
    assert not path.exists()
    delete_secret(path)


def test_read_secret_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(SlashAuthenticityError):
        read_secret(tmp_path / "nope")


def test_read_secret_wrong_size_raises(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    path.write_bytes(b"too short")
    with pytest.raises(SlashAuthenticityError):
        read_secret(path)


def test_valid_proof_verifies() -> None:
    secret = b"\x01" * 32
    proof = mint_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        now_ms=1_000_000,
        nonce=new_nonce(),
    )
    assert verify_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        proof=proof,
        now_ms=1_000_001,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_tampered_message_text_fails() -> None:
    secret = b"\x01" * 32
    proof = mint_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        now_ms=1_000_000,
        nonce=new_nonce(),
    )
    assert not verify_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text="/workspace-register --path /tmp/elsewhere",
        proof=proof,
        now_ms=1_000_000,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_tampered_channel_fails() -> None:
    """A proof minted for one channel does not verify on another."""
    secret = b"\x01" * 32
    proof = mint_proof(
        secret,
        channel="console",
        message_text=_SAMPLE_TEXT,
        now_ms=1_000_000,
        nonce=new_nonce(),
    )
    assert not verify_proof(
        secret,
        channel="signal",
        message_text=_SAMPLE_TEXT,
        proof=proof,
        now_ms=1_000_000,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_expired_timestamp_fails() -> None:
    secret = b"\x01" * 32
    proof = mint_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        now_ms=1_000_000,
        nonce=new_nonce(),
    )
    assert not verify_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        proof=proof,
        now_ms=1_000_000 + (_VALIDITY_SECONDS + 1) * 1000,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_future_timestamp_fails() -> None:
    """Proof minted ahead of the verifier's clock is rejected."""
    secret = b"\x01" * 32
    proof = mint_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        now_ms=2_000_000,
        nonce=new_nonce(),
    )
    assert not verify_proof(
        secret,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        proof=proof,
        now_ms=1_000_000,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_wrong_secret_fails() -> None:
    minted = mint_proof(
        b"\x01" * 32,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        now_ms=1_000_000,
        nonce=new_nonce(),
    )
    assert not verify_proof(
        b"\x02" * 32,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        proof=minted,
        now_ms=1_000_000,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_garbled_hmac_fails() -> None:
    minted = mint_proof(
        b"\x01" * 32,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        now_ms=1_000_000,
        nonce=new_nonce(),
    )
    bad = SlashAuthenticityProof(
        hmac_b64="not-base64-!!!",
        timestamp_ms=minted.timestamp_ms,
        nonce=minted.nonce,
    )
    assert not verify_proof(
        b"\x01" * 32,
        channel=_SAMPLE_CHANNEL,
        message_text=_SAMPLE_TEXT,
        proof=bad,
        now_ms=1_000_000,
        validity_seconds=_VALIDITY_SECONDS,
    )


def test_new_nonce_returns_unique_strings() -> None:
    seen = {new_nonce() for _ in range(100)}
    assert len(seen) == 100


def test_default_secret_path_honors_xdg_state_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert default_secret_path() == tmp_path / "brain" / "slash_authenticity_secret"


def test_default_secret_path_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        default_secret_path()
        == tmp_path / ".local" / "state" / "brain" / "slash_authenticity_secret"
    )
