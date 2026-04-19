"""Textual application for the Brain Console TUI."""

from __future__ import annotations

import logging
import time
import threading
from datetime import UTC, datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Rule, Static

from actors.console.client import ConsoleClient
from actors.console.config import ConsoleConfig, load_console_config
from actors.console.widgets.message_input import MessageInput
from actors.console.widgets.message_view import MessageView

logger = logging.getLogger(__name__)


class BrainResponse(Message):
    """Posted by the background poller when Brain sends a response."""

    def __init__(self, text: str, timestamp: datetime) -> None:
        super().__init__()
        self.text = text
        self.timestamp = timestamp


class ConsoleApp(App[None]):
    """Interactive conversational interface to Brain."""

    CSS = """
    Screen { layout: vertical; }
    #root { layout: vertical; height: 100%; }
    #header { height: 1; padding: 0 1; background: $boost; color: $text; }
    #header-rule { height: 1; margin: 0; }
    #input-rule { height: 1; margin: 0; }
    MessageView { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(self, *, config: ConsoleConfig | None = None) -> None:
        super().__init__()
        self._config = config or load_console_config()
        self._client = ConsoleClient(
            host=self._config.host,
            port=self._config.port,
            timeout_seconds=self._config.timeout_seconds,
        )
        self._polling = True

    def compose(self) -> ComposeResult:
        """Build the console layout."""
        yield Container(
            Static("Brain Console", id="header"),
            Rule(id="header-rule"),
            MessageView(id="messages"),
            Rule(id="input-rule"),
            MessageInput(id="input", editor=self._config.editor),
            id="root",
        )

    def on_mount(self) -> None:
        """Focus input and start background workers."""
        self.query_one("#input-field").focus()
        self.run_worker(self._load_history, thread=True)
        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

    def _load_history(self) -> None:
        """Load conversation history from MAS and post as messages."""
        try:
            turns = self._client.load_history()
        except Exception as exc:
            logger.error("Failed to load history: %s", exc)
            self.call_from_thread(
                self.notify,
                "Could not load conversation history",
                severity="warning",
            )
            return
        for role, content in turns:
            direction = "brain" if role == "assistant" else "operator"
            self.call_from_thread(
                self._append_history_bubble,
                direction=direction,
                text=content,
            )

    def _append_history_bubble(self, direction: str, text: str) -> None:
        """Append one history bubble on the main thread."""
        view = self.query_one("#messages", MessageView)
        view.append_message(direction=direction, text=text, timestamp=None)

    async def action_quit(self) -> None:
        """Shut down the poll loop and exit."""
        self._stop_polling()
        self.exit()

    def on_unmount(self) -> None:
        """Stop polling and release resources."""
        self._stop_polling()

    def _stop_polling(self) -> None:
        """Signal the poll thread to stop and release HTTP resources."""
        self._polling = False
        try:
            self._client.close()
        except Exception as exc:
            logger.warning("Error closing HTTP client: %s", exc)

    def _poll_loop(self) -> None:
        """Background worker: short-poll for Brain responses.

        Uses a short wait timeout so the thread checks ``_polling`` frequently
        and exits promptly on shutdown.
        """
        while self._polling:
            try:
                response = self._client.poll_response(
                    wait_timeout_seconds=self._config.poll_timeout_seconds,
                )
                if response is not None:
                    self.post_message(
                        BrainResponse(
                            text=response.message,
                            timestamp=datetime.fromtimestamp(
                                response.timestamp_ms / 1000.0, tz=UTC
                            ),
                        )
                    )
            except Exception as exc:
                logger.warning("Poll error: %s", exc)
                if not self._polling:
                    break
                time.sleep(1.0)

    def on_brain_response(self, event: BrainResponse) -> None:
        """Append a Brain bubble when a response arrives."""
        view = self.query_one("#messages", MessageView)
        view.append_message(
            direction="brain",
            text=event.text,
            timestamp=event.timestamp,
        )

    def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        """Handle operator message submission."""
        view = self.query_one("#messages", MessageView)
        view.append_message(
            direction="operator",
            text=event.text,
            timestamp=datetime.now(tz=UTC),
        )
        self.run_worker(
            lambda: self._ingest_message(event.text),
            thread=True,
        )

    def _ingest_message(self, text: str) -> None:
        """Send message to Brain; log and notify on failure."""
        try:
            self._client.ingest(text)
        except Exception as exc:
            logger.error("Failed to send message: %s", exc)
            self.call_from_thread(
                self.notify,
                f"Failed to send message: {exc}",
                severity="error",
            )
