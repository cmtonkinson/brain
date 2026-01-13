"""Main agent daemon for Brain assistant."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic_ai import Agent, RunContext

from config import settings
from models import SignalMessage
from services.code_mode import CodeModeManager, create_code_mode_manager
from services.database import init_db, get_session, log_action
from services.signal import SignalClient
from prompts import render_prompt
from tools.obsidian import ObsidianClient
from tools.memory import ConversationMemory

# Observability imports (conditional to allow running without OTEL)
try:
    from observability import (
        setup_observability,
        setup_json_logging,
        get_metrics,
        get_tracer,
        traced,
        BrainMetrics,
    )
    from observability_litellm import setup_litellm_observability

    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False

# Configure logging - use JSON if observability available, otherwise basic
log_dir = Path("/app/logs") if Path("/app/logs").exists() else Path("logs")
log_dir.mkdir(exist_ok=True)

# Basic logging setup (may be replaced by JSON logging if observability is enabled)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "agent.log"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

# Global metrics reference (set in main if observability enabled)
_brain_metrics: BrainMetrics | None = None
_summary_agent: Agent[None, str] | None = None


# --- Dependency Injection ---


@dataclass
class AgentDeps:
    """Dependencies injected into the agent at runtime."""

    user: str
    obsidian: ObsidianClient
    memory: ConversationMemory
    code_mode: CodeModeManager
    signal_sender: str | None = None  # Phone number of current message sender


def _get_summary_agent() -> Agent[None, str]:
    global _summary_agent
    if _summary_agent is None:
        _summary_agent = Agent(
            "anthropic:claude-sonnet-4-20250514",
            result_type=str,
            system_prompt=render_prompt("system/summary"),
        )
    return _summary_agent


# --- Agent Definition ---


def create_agent() -> Agent[AgentDeps, str]:
    """Create and configure the Pydantic AI agent."""
    agent: Agent[AgentDeps, str] = Agent(
        "anthropic:claude-sonnet-4-20250514",
        deps_type=AgentDeps,
        result_type=str,
        system_prompt=render_prompt("system/assistant", {"user": settings.user}),
    )

    # --- Tool Definitions ---

    @agent.tool
    async def search_notes(
        ctx: RunContext[AgentDeps], query: str, limit: int = 10
    ) -> str:
        """Search the Obsidian knowledge base for notes matching a query.

        Use this tool when the user asks about topics, people, projects, or concepts
        that might be documented in their notes. Returns note titles and relevant snippets.

        Args:
            query: Search terms to find in notes
            limit: Maximum number of results to return (default 10)
        """
        logger.info(f"Tool: search_notes(query={query!r}, limit={limit})")

        try:
            results = await ctx.deps.obsidian.search(query, limit=limit)

            if not results:
                return f"No notes found matching '{query}'."

            # Format results for the LLM
            formatted = []
            for i, result in enumerate(results, 1):
                if isinstance(result, dict):
                    filename = (
                        result.get("filename")
                        or result.get("path")
                        or result.get("file")
                        or "Unknown"
                    )
                    matches = result.get("matches", [])
                else:
                    filename = str(result)
                    matches = []

                snippet = ""
                if isinstance(matches, list) and matches:
                    first = matches[0]
                    if isinstance(first, dict):
                        snippet_value = (
                            first.get("match")
                            or first.get("context")
                            or first.get("snippet")
                            or ""
                        )
                    else:
                        snippet_value = first
                    snippet = str(snippet_value)[:200]

                formatted.append(f"{i}. **{filename}**")
                if snippet:
                    formatted.append(f"   {snippet}...")

            return f"Found {len(results)} note(s):\n\n" + "\n".join(formatted)

        except Exception as e:
            logger.error(f"search_notes failed: {e}")
            return f"Error searching notes: {e}"

    @agent.tool
    async def read_note(ctx: RunContext[AgentDeps], path: str) -> str:
        """Read the full content of a specific note from Obsidian.

        Use this after searching to get complete context from a note.
        The path should match a result from search_notes.

        Args:
            path: The path to the note (e.g., "Projects/MyProject.md")
        """
        logger.info(f"Tool: read_note(path={path!r})")

        try:
            content = await ctx.deps.obsidian.get_note(path)

            # Truncate very long notes
            if len(content) > 8000:
                content = content[:8000] + "\n\n... (note truncated)"

            return f"Content of **{path}**:\n\n{content}"

        except FileNotFoundError:
            return f"Note not found: {path}"
        except Exception as e:
            logger.error(f"read_note failed: {e}")
            return f"Error reading note: {e}"

    @agent.tool
    async def create_note(
        ctx: RunContext[AgentDeps], path: str, content: str
    ) -> str:
        """Create a new note in the Obsidian vault.

        Use this when the user wants to save new information, create a new document,
        or capture an idea. The note will be created at the specified path.

        Args:
            path: Where to create the note (e.g., "Ideas/NewIdea.md")
            content: The markdown content for the note
        """
        logger.info(f"Tool: create_note(path={path!r})")

        try:
            result = await ctx.deps.obsidian.create_note(path, content)
            return f"Created note: {result.get('path', path)}"

        except Exception as e:
            logger.error(f"create_note failed: {e}")
            return f"Error creating note: {e}"

    @agent.tool
    async def append_to_note(
        ctx: RunContext[AgentDeps], path: str, content: str
    ) -> str:
        """Append content to an existing note in Obsidian.

        Use this to add information to existing notes like journals, logs,
        or ongoing documents. The content will be added at the end.

        Args:
            path: The note to append to (e.g., "Journal/2026-01.md")
            content: The markdown content to append
        """
        logger.info(f"Tool: append_to_note(path={path!r})")

        try:
            result = await ctx.deps.obsidian.append_to_note(path, content)
            return f"Appended to note: {result.get('path', path)}"

        except FileNotFoundError:
            return f"Note not found: {path}. Use create_note to create it first."
        except Exception as e:
            logger.error(f"append_to_note failed: {e}")
            return f"Error appending to note: {e}"

    @agent.tool
    async def code_mode_search_tools(
        ctx: RunContext[AgentDeps], query: str
    ) -> str:
        """Search Code-Mode/UTCP tools for relevant external capabilities."""
        logger.info(f"Tool: code_mode_search_tools(query={query!r})")
        return await ctx.deps.code_mode.search_tools(query)

    @agent.tool
    async def code_mode_call_tool_chain(
        ctx: RunContext[AgentDeps],
        code: str,
        confirm_destructive: bool = False,
        timeout: int | None = None,
    ) -> str:
        """Execute a Code-Mode Python tool chain against MCP servers."""
        logger.info("Tool: code_mode_call_tool_chain")
        return await ctx.deps.code_mode.call_tool_chain(
            code,
            confirm_destructive=confirm_destructive,
            timeout=timeout,
        )

    return agent


# --- Message Processing ---


async def process_message(
    agent: Agent[AgentDeps, str],
    message: str,
    deps: AgentDeps,
) -> str:
    """Process a user message and return the response.

    Args:
        agent: The Pydantic AI agent
        message: The user's message
        deps: Runtime dependencies

    Returns:
        The agent's response text
    """
    logger.info(f"Processing message: {message[:100]}...")
    start_time = time.perf_counter()
    status = "success"

    try:
        prompt = message
        if deps.signal_sender:
            try:
                recent = await deps.memory.get_recent_context(deps.signal_sender)
            except Exception as e:
                recent = None
                logger.warning(f"Failed to load recent context: {e}")
            if recent:
                prompt = render_prompt(
                    "user/recent_context",
                    {"recent": recent, "message": message},
                )

        result = await agent.run(prompt, deps=deps)
        response = _extract_agent_response(result)
        if _brain_metrics:
            _record_llm_metrics(result, agent, start_time)
        logger.info(f"Response generated: {response[:100]}...")
        if deps.signal_sender and deps.memory.should_write_summary(
            deps.signal_sender, settings.summary_every_turns
        ):
            try:
                summary_prompt = render_prompt(
                    "user/summary_input",
                    {"message": message, "response": response},
                )
                summary_agent = _get_summary_agent()
                summary_result = await summary_agent.run(summary_prompt)
                summary_text = _extract_agent_response(summary_result).strip()
                if summary_text:
                    summary_path = await deps.memory.log_summary(
                        deps.signal_sender, summary_text
                    )
                    await deps.memory.log_summary_marker(
                        deps.signal_sender, summary_path
                    )
            except Exception as e:
                logger.warning(f"Failed to write summary: {e}")

        return response

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        status = "error"
        return f"I encountered an error: {e}"

    finally:
        # Record metrics if available
        if _brain_metrics:
            duration_ms = (time.perf_counter() - start_time) * 1000
            channel = "signal" if deps.signal_sender else "test"
            _brain_metrics.messages_processed.add(1, {"channel": channel, "status": status})
            _brain_metrics.message_processing_duration.record(duration_ms, {"channel": channel})


def _extract_agent_response(result: object) -> str:
    """Normalize agent result across pydantic-ai versions."""
    for attr in ("output", "data", "result"):
        if hasattr(result, attr):
            value = getattr(result, attr)
            if isinstance(value, str):
                return value
            return str(value)
    return str(result)


def _render_signal_message(markdown: str) -> str:
    """Convert Markdown to Signal-friendly formatting without mutating stored logs."""
    if not markdown:
        return markdown

    def _render_inline(text: str) -> str:
        # Images: ![alt](url) -> "alt (url)" or "url"
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 (\2)", text)
        # Links: [text](url) -> "text (url)" to preserve previews.
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
        # Strikethrough: ~~text~~ -> ~text~
        text = re.sub(r"~~(.+?)~~", r"~\1~", text)
        # Bold: __text__ -> **text** (Signal uses ** for bold).
        text = re.sub(r"__(.+?)__", r"**\1**", text)
        # Italic: _text_ -> *text* (Signal uses * for italic).
        text = re.sub(r"_(.+?)_", r"*\1*", text)
        return text

    def _render_block(text: str) -> str:
        # Headings: convert to bold line (Signal has no heading style).
        text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"**\1**", text)
        # Blockquotes: keep prefix for readability.
        text = re.sub(r"(?m)^>\s?", r"> ", text)

        # Protect inline code segments from other substitutions.
        code_spans = {}
        def _stash_code(match: re.Match[str]) -> str:
            key = f"__CODE_SPAN_{len(code_spans)}__"
            code_spans[key] = match.group(0)
            return key

        text = re.sub(r"`[^`]+`", _stash_code, text)
        text = _render_inline(text)

        for key, value in code_spans.items():
            text = text.replace(key, value)

        return text

    # Preserve fenced code blocks (```...```) but map to Signal monospace.
    parts = re.split(r"(```[\s\S]*?```)", markdown)
    rendered = []
    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            inner = part[3:-3]
            if inner.startswith("\n"):
                inner = inner[1:]
            elif "\n" in inner:
                inner = inner.split("\n", 1)[1]
            if inner.endswith("\n"):
                inner = inner[:-1]
            rendered.append(f"`{inner}`")
        else:
            rendered.append(_render_block(part))

    return "".join(rendered)


def _record_llm_metrics(result: object, agent: Agent[AgentDeps, str], start_time: float) -> None:
    """Record LLM usage metrics when available."""
    usage = None
    if hasattr(result, "usage"):
        usage_attr = getattr(result, "usage")
        usage = usage_attr() if callable(usage_attr) else usage_attr
    if usage is None:
        return

    model = getattr(agent, "model", None)
    model_label = getattr(model, "model_name", None) or str(model or "unknown")
    base_attrs = {"model": model_label}

    if getattr(usage, "request_tokens", None) is not None:
        _brain_metrics.llm_tokens_input.add(usage.request_tokens, base_attrs)
    if getattr(usage, "response_tokens", None) is not None:
        _brain_metrics.llm_tokens_output.add(usage.response_tokens, base_attrs)

    requests = getattr(usage, "requests", 0) or 1
    _brain_metrics.llm_requests.add(requests, {"model": model_label, "status": "success"})
    _brain_metrics.llm_cost.add(0.0, base_attrs)

    latency_ms = (time.perf_counter() - start_time) * 1000
    _brain_metrics.llm_latency.record(latency_ms, base_attrs)


async def handle_signal_message(
    agent: Agent[AgentDeps, str],
    signal_msg: SignalMessage,
    obsidian: ObsidianClient,
    memory: ConversationMemory,
    code_mode: CodeModeManager,
    signal_client: SignalClient,
    phone_number: str,
) -> None:
    """Handle an incoming Signal message.

    Args:
        agent: The Pydantic AI agent
        signal_msg: The incoming Signal message
        obsidian: Obsidian client
        memory: Conversation memory manager
        signal_client: Signal client for sending replies
        phone_number: The agent's phone number
    """
    sender = signal_msg.sender
    message = signal_msg.message

    # Record message received metric
    if _brain_metrics:
        _brain_metrics.messages_received.add(1, {"channel": "signal"})

    # Check allowed senders if configured
    if settings.allowed_senders and sender not in settings.allowed_senders:
        logger.warning(f"Ignoring message from unauthorized sender: {sender}")
        return

    logger.info(f"Handling message from {sender}: {message[:50]}...")

    # Create tracing span if available
    tracer = None
    if OBSERVABILITY_AVAILABLE:
        try:
            tracer = get_tracer()
        except RuntimeError:
            tracer = None
    span_context = tracer.start_as_current_span(
        "signal.handle_message",
        attributes={
            "signal.sender": sender,
            "signal.message_length": len(message),
        },
    ) if tracer else None

    try:
        if span_context:
            span_context.__enter__()

        # Log incoming message to conversation
        await memory.log_message(sender, "user", message, signal_msg.timestamp)

        # Create dependencies with sender context
        deps = AgentDeps(
            user=settings.user,
            obsidian=obsidian,
            memory=memory,
            code_mode=code_mode,
            signal_sender=sender,
        )

        # Process message
        response = await process_message(agent, message, deps)

        # Log response to conversation
        await memory.log_message(sender, "assistant", response)

        # Send reply via Signal
        send_start = time.perf_counter()
        await signal_client.send_message(
            phone_number, sender, _render_signal_message(response)
        )

        if _brain_metrics:
            send_duration = (time.perf_counter() - send_start) * 1000
            _brain_metrics.signal_messages_sent.add(1, {"status": "success"})
            _brain_metrics.signal_latency.record(send_duration, {"operation": "send"})

        # Log action to database
        async with get_session() as session:
            await log_action(
                session,
                action_type="signal_conversation",
                description=f"Conversation with {sender}",
                result=f"User: {message[:100]}... | Brain: {response[:100]}...",
            )
    finally:
        if span_context:
            span_context.__exit__(None, None, None)


# --- Main Loop ---


async def run_signal_loop(
    agent: Agent[AgentDeps, str],
    obsidian: ObsidianClient,
    memory: ConversationMemory,
    code_mode: CodeModeManager,
    poll_interval: float = 2.0,
) -> None:
    """Main loop for polling Signal messages.

    Args:
        agent: The Pydantic AI agent
        obsidian: Obsidian client
        memory: Conversation memory manager
        poll_interval: Seconds between polls
    """
    phone_number = settings.signal_phone_number
    if not phone_number:
        logger.error("SIGNAL_PHONE_NUMBER not configured")
        return

    signal_client = SignalClient()

    # Check Signal API connection
    if not await signal_client.check_connection():
        logger.error("Cannot connect to Signal API")
        return

    logger.info(f"Starting Signal polling for {phone_number}")

    while True:
        poll_start = time.perf_counter()
        try:
            messages = await signal_client.poll_messages(phone_number)

            # Record poll metrics
            if _brain_metrics:
                poll_duration = (time.perf_counter() - poll_start) * 1000
                _brain_metrics.signal_polls.add(1, {"status": "success"})
                _brain_metrics.signal_latency.record(poll_duration, {"operation": "poll"})

            for msg in messages:
                await handle_signal_message(
                    agent, msg, obsidian, memory, code_mode, signal_client, phone_number
                )

        except Exception as e:
            logger.error(f"Error in Signal loop: {e}")
            if _brain_metrics:
                _brain_metrics.signal_poll_errors.add(1, {"error_type": type(e).__name__})

        await asyncio.sleep(poll_interval)


async def run_test_mode(
    agent: Agent[AgentDeps, str],
    message: str,
    code_mode: CodeModeManager,
) -> None:
    """Run a single message in test mode.

    Args:
        agent: The Pydantic AI agent
        message: The test message to process
    """
    obsidian = ObsidianClient()
    memory = ConversationMemory(obsidian)

    deps = AgentDeps(
        user=settings.user,
        obsidian=obsidian,
        memory=memory,
        code_mode=code_mode,
        signal_sender="test",
    )

    print(f"\n[User]: {message}\n")
    response = await process_message(agent, message, deps)
    print(f"[Brain]: {response}\n")


async def main() -> None:
    """Main entry point."""
    global _brain_metrics

    parser = argparse.ArgumentParser(description="Brain AI Assistant")
    parser.add_argument(
        "--test",
        type=str,
        help="Run a single test message and exit",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Signal polling interval in seconds",
    )
    parser.add_argument(
        "--no-otel",
        action="store_true",
        help="Disable OpenTelemetry observability",
    )
    args = parser.parse_args()

    # Initialize observability if available and not disabled
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if OBSERVABILITY_AVAILABLE and not args.no_otel and otel_endpoint:
        logger.info(f"Initializing observability: endpoint={otel_endpoint}")
        try:
            _, _, _brain_metrics = setup_observability(
                service_name="brain-agent",
                service_version="1.0.0",
                otlp_endpoint=otel_endpoint,
            )
            setup_json_logging(logging.INFO)
            setup_litellm_observability(_brain_metrics)
            logger.info("Observability initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize observability: {e}")
    elif not OBSERVABILITY_AVAILABLE:
        logger.info("Observability modules not available (install opentelemetry packages)")
    elif args.no_otel:
        logger.info("Observability disabled via --no-otel flag")
    else:
        logger.info("Observability disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")

    logger.info("Brain assistant starting...")
    logger.info(f"User: {settings.user}")
    logger.info(f"Obsidian URL: {settings.obsidian_url}")
    logger.info(f"Signal API URL: {settings.signal_api_url}")

    # Initialize database
    try:
        await init_db()
    except Exception as e:
        logger.warning(f"Database init failed (may not be available): {e}")

    code_mode = await create_code_mode_manager(
        settings.utcp_config_path,
        settings.code_mode_timeout,
    )

    # Create agent
    agent = create_agent()
    logger.info("Agent initialized")

    # Test mode
    if args.test:
        await run_test_mode(agent, args.test, code_mode)
        return

    # Signal mode
    obsidian = ObsidianClient()
    memory = ConversationMemory(obsidian)

    logger.info("Starting Signal message loop...")
    try:
        await run_signal_loop(
            agent,
            obsidian,
            memory,
            code_mode,
            poll_interval=args.poll_interval,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
