"""Smoke tests for the agent message flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent import AgentDeps, handle_signal_message
from attention.envelope_schema import RoutingEnvelope
from attention.router import RoutingResult
from models import SignalMessage
from services.object_store import ObjectStore
from tools.memory import ConversationMemory


@dataclass
class FakeAgent:
    """Stub agent that returns a fixed response without LLM calls."""

    response: str

    async def run(self, prompt: str, deps: AgentDeps) -> SimpleNamespace:
        """Return a lightweight response object compatible with agent parsing."""
        return SimpleNamespace(output=self.response)


@dataclass
class FakeObsidianClient:
    """In-memory Obsidian client for smoke tests."""

    notes: dict[str, str] = field(default_factory=dict)

    async def note_exists(self, path: str) -> bool:
        """Return True when the note path is already stored."""
        return path in self.notes

    async def create_note(self, path: str, content: str) -> None:
        """Persist a new note in the in-memory store."""
        self.notes[path] = content

    async def append_to_note(self, path: str, content: str) -> None:
        """Append content to an existing note, creating it if missing."""
        self.notes[path] = self.notes.get(path, "") + content

    async def get_note(self, path: str) -> str:
        """Return a stored note or raise FileNotFoundError."""
        if path not in self.notes:
            raise FileNotFoundError(path)
        return self.notes[path]


@dataclass
class FakeRouter:
    """Capture outbound router signals for inspection."""

    sent: list[RoutingEnvelope] = field(default_factory=list)

    async def route_envelope(self, envelope: RoutingEnvelope) -> RoutingResult:
        """Record the outbound routing request."""
        self.sent.append(envelope)
        return RoutingResult(decision="DELIVERED", channel=envelope.channel_hint)


@dataclass
class FakeCodeModeManager:
    """Stub Code-Mode manager placeholder for dependency injection."""

    client: object | None = None


@dataclass
class DummySessionContext:
    """Async context manager that yields a dummy session."""

    session: object = field(default_factory=object)

    async def __aenter__(self) -> object:
        """Return a placeholder session object."""
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """No-op async context exit."""
        return None


@pytest.mark.asyncio
async def test_agent_flow_smoke_logs_and_formats_signal(monkeypatch, tmp_path) -> None:
    """Exercise the agent flow from Signal intake to formatted reply."""
    obsidian = FakeObsidianClient()
    memory = ConversationMemory(obsidian)
    code_mode = FakeCodeModeManager()
    object_store = ObjectStore(tmp_path)
    router = FakeRouter()
    agent = FakeAgent(response="# Greeting\nSee [link](https://example.com) and _italic_.")

    async def _fake_log_action(*args, **kwargs) -> None:
        """Stub database log action handler."""
        return None

    def _fake_get_session() -> DummySessionContext:
        """Return an async context manager for database logging."""
        return DummySessionContext()

    monkeypatch.setattr("agent.is_sender_allowed", lambda *args, **kwargs: True)
    monkeypatch.setattr("agent.log_action", _fake_log_action)
    monkeypatch.setattr("agent.get_session", _fake_get_session)

    message = SignalMessage(
        sender="+15551234567",
        message="Summarize my note.",
        timestamp=datetime.now(timezone.utc),
    )

    await handle_signal_message(
        agent=agent,
        signal_msg=message,
        obsidian=obsidian,
        memory=memory,
        code_mode=code_mode,
        object_store=object_store,
        router=router,
        phone_number="+15550000000",
    )

    assert len(obsidian.notes) == 1
    note_content = next(iter(obsidian.notes.values()))
    assert "Summarize my note." in note_content
    assert "# Greeting" in note_content

    assert len(router.sent) == 1
    payload = router.sent[0].signal_payload
    assert payload is not None
    rendered = payload.message
    assert "**Greeting**" in rendered
    assert "link (https://example.com)" in rendered
    assert "*italic*" in rendered
