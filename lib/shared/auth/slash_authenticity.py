"""HMAC proof-of-authenticity for operator-typed slash commands.

A *SlashAuthenticityProof* lets Policy distinguish a slash command minted by
a trusted operator channel (Console on the host, Signal Adapter inside Brain
Core after the operator-identity check) from any other ``invoke_op`` call.
Mint and verify both bind to the inbound channel, the raw message text, a
wall-clock timestamp, and a nonce; replay protection is the caller's
responsibility.
"""

from __future__ import annotations

import base64
import hmac
import os
import secrets
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


_SECRET_BYTES = 32
_HMAC_DIGEST_BYTES = 32  # sha256 output


class SlashAuthenticityError(Exception):
    """Raised when secret reading fails or its on-disk shape is invalid."""


class SlashAuthenticityProof(BaseModel):
    """One signed authenticity proof carried alongside a slash invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hmac_b64: str = Field(min_length=1)
    timestamp_ms: int = Field(gt=0)
    nonce: str = Field(min_length=1)


def default_secret_path() -> Path:
    """Resolve the conventional secret path: ``$XDG_STATE_HOME/brain/slash_authenticity_secret``.

    Falls back to ``~/.local/state`` when ``XDG_STATE_HOME`` is unset, per the
    XDG Base Directory specification. Containers can override the location by
    setting ``XDG_STATE_HOME`` in their environment.
    """
    xdg = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "brain" / "slash_authenticity_secret"


def generate_and_write_secret(path: Path) -> bytes:
    """Generate 32 random bytes, atomically write to ``path`` with mode 0600.

    Overwrites any prior file. Returns the new secret.
    """
    secret = secrets.token_bytes(_SECRET_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, secret)
    finally:
        os.close(fd)
    tmp_path.replace(path)
    return secret


def delete_secret(path: Path) -> None:
    """Best-effort unlink of the secret file; tolerates a missing file."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def read_secret(path: Path) -> bytes:
    """Return the raw secret bytes from ``path``.

    Raises ``SlashAuthenticityError`` if the file is missing or its size is
    not the expected secret length.
    """
    try:
        secret = path.read_bytes()
    except FileNotFoundError as exc:
        raise SlashAuthenticityError(
            f"slash authenticity secret not found at {path}"
        ) from exc
    if len(secret) != _SECRET_BYTES:
        raise SlashAuthenticityError(
            f"slash authenticity secret at {path} has unexpected size {len(secret)}"
        )
    return secret


def mint_proof(
    secret: bytes,
    *,
    channel: str,
    message_text: str,
    now_ms: int,
    nonce: str,
) -> SlashAuthenticityProof:
    """Sign one slash invocation with HMAC-SHA256.

    Binding is deterministic over (channel, message text, timestamp, nonce).
    Two callers using the same secret and identical inputs produce identical
    proofs. ``channel`` and ``message_text`` are the same fields Policy
    surfaces on ``InvocationPolicyInput`` for verification.
    """
    digest = hmac.new(
        secret,
        _bound_payload(
            channel=channel,
            message_text=message_text,
            timestamp_ms=now_ms,
            nonce=nonce,
        ),
        sha256,
    ).digest()
    return SlashAuthenticityProof(
        hmac_b64=_b64encode(digest),
        timestamp_ms=now_ms,
        nonce=nonce,
    )


def verify_proof(
    secret: bytes,
    *,
    channel: str,
    message_text: str,
    proof: SlashAuthenticityProof,
    now_ms: int,
    validity_seconds: int,
) -> bool:
    """Return True iff the HMAC matches and the timestamp is within the window.

    Replay protection (nonce uniqueness) is intentionally outside this
    function; callers must check the nonce against a ledger before relying
    on a True return.
    """
    age_ms = now_ms - proof.timestamp_ms
    if age_ms < 0:
        return False
    if age_ms > validity_seconds * 1000:
        return False
    try:
        actual = _b64decode(proof.hmac_b64)
    except ValueError:
        return False
    if len(actual) != _HMAC_DIGEST_BYTES:
        return False
    expected = hmac.new(
        secret,
        _bound_payload(
            channel=channel,
            message_text=message_text,
            timestamp_ms=proof.timestamp_ms,
            nonce=proof.nonce,
        ),
        sha256,
    ).digest()
    return hmac.compare_digest(expected, actual)


def new_nonce() -> str:
    """Return a fresh URL-safe nonce suitable for inclusion in a proof."""
    return secrets.token_urlsafe(16)


def _bound_payload(
    *,
    channel: str,
    message_text: str,
    timestamp_ms: int,
    nonce: str,
) -> bytes:
    """Compose the deterministic byte string the HMAC signs.

    Newline separators isolate fields so a value containing one separator
    does not collide with another shape across the join.
    """
    return f"{channel}\n{message_text}\n{timestamp_ms}\n{nonce}".encode()


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)
