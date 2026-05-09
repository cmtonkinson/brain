"""Thin wrapper around BrainSdkClient for console TUI operations."""

from __future__ import annotations

import time

from lib.sdk import (
    BrainSdkClient,
    ConsoleResponseMessage,
    MemoryContextBlock,
    MemorySessionRef,
    RelayInboundIngestResult,
)
from lib.shared.auth.slash_authenticity import (
    SlashAuthenticityError,
    SlashAuthenticityProof,
    default_secret_path,
    mint_proof,
    new_nonce,
    read_secret,
)
from lib.shared.inbound_message import InboundMessage, InboundSender
from lib.shared.inbound_text import (
    parse_links,
    parse_slash_command,
    parse_text_approval,
)


class ConsoleClient:
    """Synchronous Brain SDK client pre-configured for console channel operations."""

    def __init__(self, *, host: str, port: int, timeout_seconds: float) -> None:
        self._sdk = BrainSdkClient(
            host=host,
            port=port,
            timeout_seconds=timeout_seconds,
            source="console",
            principal="operator",
        )

    def ingest(self, text: str) -> RelayInboundIngestResult:
        """Submit one operator message to Brain via the console channel.

        Slash-prefixed messages are signed with the host-side authenticity
        secret so Policy can recognize them as operator-typed and bypass the
        approval gate for ``approval: always`` ops.
        """
        proof = self._mint_slash_proof(text) if text.startswith("/") else None
        message = InboundMessage(
            channel="console",
            sender=InboundSender(id="operator"),
            message_text=text,
            timestamp_ms=int(time.time() * 1000),
            links=parse_links(text),
            approval=parse_text_approval(text),
            slash_command=parse_slash_command(text),
            slash_authenticity=proof,
        )
        return self._sdk.relay_ingest_inbound_message(
            message=message,
        )

    def _mint_slash_proof(self, text: str) -> SlashAuthenticityProof | None:
        """Read the secret and sign one outbound slash command.

        Returns ``None`` when the secret file is unavailable (Brain Core not
        running, or the runtime directory is unreadable). Policy will deny
        the resulting invocation through the standard approval gate; this
        keeps a missing secret a visible failure mode rather than a silent
        bypass.
        """
        try:
            secret = read_secret(default_secret_path())
        except SlashAuthenticityError:
            return None
        return mint_proof(
            secret,
            channel="console",
            message_text=text,
            now_ms=int(time.time() * 1000),
            nonce=new_nonce(),
        )

    def poll_response(
        self, *, wait_timeout_seconds: float
    ) -> ConsoleResponseMessage | None:
        """Long-poll for the next Brain response on the console channel."""
        return self._sdk.relay_poll_console_response(
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def load_history(
        self,
    ) -> tuple[list[tuple[str, str, int | None]], bool]:
        """Load recent conversation history as (role, content, timestamp_ms) tuples.

        Returns a ``(turns, had_summaries_filtered)`` pair. ``turns`` contains
        non-summary turns from the shared memory session; ``role`` is ``"user"``
        for operator messages and ``"assistant"`` for Brain responses.
        ``had_summaries_filtered`` is ``True`` when the session contained turns
        but all were summary entries — indicating history has rolled over.
        """
        session: MemorySessionRef = self._sdk.memory_get_latest_or_create_session()
        snapshot: MemoryContextBlock = self._sdk.memory_assemble_snapshot(
            session_id=session.session_id,
            exclude_latest=False,
        )
        turns = [
            (turn.role, turn.content, turn.timestamp_ms)
            for turn in snapshot.recent_turns
            if not turn.is_summary
        ]
        had_summaries_filtered = bool(snapshot.recent_turns) and not turns
        return turns, had_summaries_filtered

    def close(self) -> None:
        """Release underlying HTTP resources."""
        self._sdk.close()
