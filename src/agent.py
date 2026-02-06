"""Main agent daemon for Brain assistant."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from pydantic_ai import Agent, RunContext

from config import settings
from models import SignalMessage
from services.code_mode import CodeModeManager, create_code_mode_manager
from services.database import init_db, get_session, log_action
from services.database import get_sync_session
from access_control import is_sender_allowed
from services.signal import SignalClient
from attention.router import AttentionRouter
from attention.routing_envelope import build_signal_reply_envelope
from attention.routing_hooks import (
    build_approval_router,
    build_op_routing_hook,
    build_skill_routing_hook,
)
from services.letta import LettaService
from services.object_store import ObjectStore
from prompts import render_prompt
from tools.obsidian import ObsidianClient
from tools.memory import ConversationMemory
from indexer import index_vault as run_indexer
from services.vector_search import search_vault as search_vault_vectors
from diagnostics.self_test import (
    SelfTestDependencies,
    format_self_test_report,
    run_full_self_test,
)
from skills.adapters.op_adapter import MCPOpAdapter, NativeOpAdapter
from skills.adapters.python_adapter import PythonSkillAdapter
from entrypoints import EntrypointContext, require_entrypoint_context
from skills.context import SkillContext
from skills.op_runtime import OpRuntime
from skills.policy import DefaultPolicy
from skills.registry import OpRegistryLoader, SkillRegistryLoader
from skills.errors import SkillPolicyError, SkillRuntimeError
from skills.runtime import SkillRuntime
from skills.registry_schema import AutonomyLevel, SkillStatus
from skills.services import SkillServices
from commitments.review_delivery import maybe_record_review_engagement

# Observability imports (conditional to allow running without OTEL)
try:
    from observability import (
        setup_observability,
        configure_logging,
        get_tracer,
        BrainMetrics,
    )
    from observability_litellm import setup_litellm_observability

    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global metrics reference (set in main if observability enabled)
_brain_metrics: BrainMetrics | None = None
_summary_agent: Agent[None, str] | None = None
_indexer_lock = asyncio.Lock()
_skill_registry_loader: SkillRegistryLoader | None = None
_skill_policy: DefaultPolicy | None = None
_op_registry_loader: OpRegistryLoader | None = None
_DEFAULT_ALLOWED_CAPABILITIES = {
    "obsidian.read",
    "vault.search",
}


# --- Dependency Injection ---


@dataclass
class AgentDeps:
    """Dependencies injected into the agent at runtime."""

    user: str
    obsidian: ObsidianClient
    memory: ConversationMemory
    code_mode: CodeModeManager
    object_store: ObjectStore
    signal_sender: str | None = None  # Phone number of current message sender
    channel: str = "signal"


def _generate_loop_closure_confirmation(result: object) -> str:
    """Generate a confirmation message for a loop-closure action.

    Args:
        result: LoopClosureActionResult from the handler

    Returns:
        Confirmation message string
    """
    status = result.status
    if status == "completed":
        return "✓ Marked as complete."
    elif status == "canceled":
        return "✓ Commitment canceled."
    elif status == "renegotiated":
        if result.new_due_by:
            return f"✓ Rescheduled to {result.new_due_by.strftime('%Y-%m-%d')}."
        return "✓ Commitment updated."
    elif status == "reviewed":
        return "✓ Marked for review."
    elif status == "noop":
        return "This commitment is already resolved."
    return "✓ Updated."


def _preview(text: str, limit: int = 160) -> str:
    """Return a single-line preview of text for logging."""
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        return cleaned[:limit] + "..."
    return cleaned


def _ensure_llm_env() -> None:
    """Bridge config secrets into env for SDKs that only read env vars."""
    if settings.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key


def _agent_init_kwargs(system_prompt: str, deps_type: type | None = None) -> dict[str, object]:
    """Build Agent constructor kwargs compatible with installed pydantic_ai."""
    signature = inspect.signature(Agent)
    kwargs: dict[str, object] = {"system_prompt": system_prompt}
    if deps_type is not None:
        kwargs["deps_type"] = deps_type
    if "output_type" in signature.parameters:
        kwargs["output_type"] = str
    else:
        kwargs["result_type"] = str
    return kwargs


def _get_summary_agent() -> Agent[None, str]:
    """Lazy-initialize the summary agent used for conversation summaries."""
    global _summary_agent
    if _summary_agent is None:
        _summary_agent = Agent(
            settings.llm.model,
            **_agent_init_kwargs(render_prompt("system/summary")),
        )
    return _summary_agent


def _get_skill_registry() -> SkillRegistryLoader:
    """Return the cached skill registry loader."""
    global _skill_registry_loader
    if _skill_registry_loader is None:
        _skill_registry_loader = SkillRegistryLoader()
        _skill_registry_loader.load()
    return _skill_registry_loader


def _get_skill_policy() -> DefaultPolicy:
    """Return the cached default skill policy."""
    global _skill_policy
    if _skill_policy is None:
        _skill_policy = DefaultPolicy()
    return _skill_policy


def _get_op_registry() -> OpRegistryLoader:
    """Return the cached op registry loader."""
    global _op_registry_loader
    if _op_registry_loader is None:
        _op_registry_loader = OpRegistryLoader()
        _op_registry_loader.load()
    return _op_registry_loader


async def _execute_skill(
    deps: AgentDeps,
    name: str,
    inputs: dict,
    version: str | None = None,
    allow_capabilities: list[str] | None = None,
    confirmed: bool = False,
) -> dict:
    """Execute a skill through the runtime with policy enforcement."""
    registry = _get_skill_registry()
    op_registry = _get_op_registry()
    policy = _get_skill_policy()
    allowed = set(_DEFAULT_ALLOWED_CAPABILITIES)
    if allow_capabilities and confirmed:
        allowed.update(allow_capabilities)
    require_entrypoint_context(
        EntrypointContext(
            entrypoint="agent",
            actor=deps.signal_sender,
            channel=deps.channel,
        )
    )
    context = SkillContext(
        allowed_capabilities=allowed,
        actor=deps.signal_sender,
        channel=deps.channel,
        max_autonomy=AutonomyLevel.L3,
        confirmed=confirmed,
        services=SkillServices(
            obsidian=deps.obsidian,
            code_mode=deps.code_mode,
            signal=None,
            object_store=deps.object_store,
        ),
    )
    router = AttentionRouter(signal_client=SignalClient())
    skill_routing_hook = build_skill_routing_hook(router)
    op_routing_hook = build_op_routing_hook(router)
    approval_router = build_approval_router(router)
    runtime = SkillRuntime(
        registry=registry,
        policy=policy,
        adapters={
            "python": PythonSkillAdapter(),
        },
        op_runtime=OpRuntime(
            registry=op_registry,
            policy=policy,
            adapters={
                "native": NativeOpAdapter(),
                "mcp": MCPOpAdapter(deps.code_mode),
            },
            routing_hook=op_routing_hook,
            approval_router=approval_router,
        ),
        routing_hook=skill_routing_hook,
        approval_router=approval_router,
    )
    result = await runtime.execute(name, inputs, context, version=version)
    return result.output


# --- Agent Definition ---


def create_agent() -> Agent[AgentDeps, str]:
    """Create and configure the Pydantic AI agent."""
    agent = cast(
        Agent[AgentDeps, str],
        Agent(
            settings.llm.model,
            **_agent_init_kwargs(
                render_prompt("system/assistant", {"user": settings.user.name}),
                deps_type=AgentDeps,
            ),
        ),
    )

    # --- Tool Definitions ---

    @agent.tool
    async def index_vault(ctx: RunContext[AgentDeps], full_reindex: bool = False) -> str:
        """Trigger a vault indexing run into Qdrant.

        Use this when the user asks to refresh embeddings, reindex the vault,
        or repair missing vectors.
        """
        logger.info(f"Tool: index_vault(full_reindex={full_reindex})")
        return await run_indexer_task(full_reindex=full_reindex)

    @agent.tool
    async def search_notes(ctx: RunContext[AgentDeps], query: str, limit: int = 10) -> str:
        """Search the Obsidian knowledge base for notes matching a query.

        Use this tool when the user asks about topics, people, projects, or concepts
        that might be documented in their notes. Returns note titles and relevant snippets.

        Args:
            query: Search terms to find in notes
            limit: Maximum number of results to return (default 10)
        """
        logger.info(f"Tool: search_notes(query={query!r}, limit={limit})")

        try:
            output = await _execute_skill(
                ctx.deps,
                "search_notes",
                {"query": query, "limit": limit},
            )
            results = output.get("results", [])
            if not results:
                logger.info("search_notes: no results")
                return f"No notes found matching '{query}'."

            logger.info("search_notes: %s result(s)", len(results))
            formatted = [f"{i}. {item}" for i, item in enumerate(results, 1)]
            return f"Found {len(results)} note(s):\n\n" + "\n".join(formatted)

        except SkillRuntimeError as e:
            logger.error(f"search_notes failed: {e}")
            return f"Error searching notes: {e}"

    @agent.tool
    async def search_vault_embeddings(
        ctx: RunContext[AgentDeps], query: str, limit: int = 8
    ) -> str:
        """Semantic search over indexed vault embeddings in Qdrant."""
        logger.info(f"Tool: search_vault_embeddings(query={query!r}, limit={limit})")

        try:
            results = await asyncio.to_thread(
                search_vault_vectors,
                query=query,
                limit=limit,
            )
            if not results:
                logger.info("search_vault_embeddings: no results")
                return f"No embedding matches found for '{query}'."

            formatted = []
            for i, result in enumerate(results, 1):
                path = result.get("path") or "Unknown"
                score = result.get("score")
                text = (result.get("text") or "").strip()
                snippet = " ".join(text.split())
                if len(snippet) > 240:
                    snippet = snippet[:240] + "..."
                score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
                formatted.append(f"{i}. **{path}** (score {score_text})")
                if snippet:
                    formatted.append(f"   {snippet}")

            logger.info("search_vault_embeddings: %s result(s)", len(results))
            return "Embedding matches:\n\n" + "\n".join(formatted)

        except Exception as e:
            logger.error(f"search_vault_embeddings failed: {e}")
            return f"Error searching embeddings: {e}"

    @agent.tool
    async def search_memory(ctx: RunContext[AgentDeps], query: str) -> str:
        """Search Letta archival memory for past context or stored facts."""
        logger.info(f"Tool: search_memory(query={query!r})")
        letta = LettaService()
        if not letta.enabled:
            return "Letta memory is not configured."
        try:
            result = await asyncio.to_thread(letta.search_archival_memory, query)
            logger.info("search_memory: %s chars", len(result))
            return result
        except Exception as e:
            logger.error(f"search_memory failed: {e}")
            return f"Error searching memory: {e}"

    @agent.tool
    async def save_to_memory(ctx: RunContext[AgentDeps], fact: str) -> str:
        """Save important facts into Letta archival memory."""
        logger.info("Tool: save_to_memory")
        letta = LettaService()
        if not letta.enabled:
            return "Letta memory is not configured."
        try:
            result = await asyncio.to_thread(letta.insert_to_archival, fact)
            logger.info("save_to_memory: %s", result)
            return result
        except Exception as e:
            logger.error(f"save_to_memory failed: {e}")
            return f"Error saving to memory: {e}"

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
            output = await _execute_skill(ctx.deps, "read_note", {"path": path})
            content = output.get("content", "")

            if len(content) > 8000:
                content = content[:8000] + "\n\n... (note truncated)"

            logger.info("read_note: %s chars from %s", len(content), path)
            return f"Content of **{path}**:\n\n{content}"

        except FileNotFoundError:
            return f"Note not found: {path}"
        except SkillRuntimeError as e:
            logger.error(f"read_note failed: {e}")
            return f"Error reading note: {e}"

    @agent.tool
    async def create_note(
        ctx: RunContext[AgentDeps], path: str, content: str, confirm: bool = False
    ) -> str:
        """Create a new note in the Obsidian vault.

        Use this when the user wants to save new information, create a new document,
        or capture an idea. The note will be created at the specified path.

        Args:
            path: Where to create the note (e.g., "Ideas/NewIdea.md")
            content: The markdown content for the note
        """
        logger.info(f"Tool: create_note(path={path!r})")

        if not confirm:
            return (
                "Confirmation required to create notes. Ask the user, then retry with confirm=True."
            )

        try:
            output = await _execute_skill(
                ctx.deps,
                "create_note",
                {"path": path, "content": content},
                allow_capabilities=["obsidian.write"],
                confirmed=confirm,
            )
            logger.info("create_note: %s chars to %s", len(content), output.get("path", path))
            return f"Created note: {output.get('path', path)}"

        except SkillRuntimeError as e:
            logger.error(f"create_note failed: {e}")
            return f"Error creating note: {e}"

    @agent.tool
    async def append_to_note(
        ctx: RunContext[AgentDeps], path: str, content: str, confirm: bool = False
    ) -> str:
        """Append content to an existing note in Obsidian.

        Use this to add information to existing notes like journals, logs,
        or ongoing documents. The content will be added at the end.

        Args:
            path: The note to append to (e.g., "Journal/2026-01.md")
            content: The markdown content to append
        """
        logger.info(f"Tool: append_to_note(path={path!r})")

        if not confirm:
            return (
                "Confirmation required to append notes. Ask the user, then retry with confirm=True."
            )

        try:
            output = await _execute_skill(
                ctx.deps,
                "append_note",
                {"path": path, "content": content},
                allow_capabilities=["obsidian.write"],
                confirmed=confirm,
            )
            logger.info("append_to_note: %s chars to %s", len(content), output.get("path", path))
            return f"Appended to note: {output.get('path', path)}"

        except FileNotFoundError:
            return f"Note not found: {path}. Use create_note to create it first."
        except SkillRuntimeError as e:
            logger.error(f"append_to_note failed: {e}")
            return f"Error appending to note: {e}"

    @agent.tool
    async def self_diagnostic(ctx: RunContext[AgentDeps]) -> str:
        """Run the full self-test diagnostic across core subsystems."""
        logger.info("Tool: self_diagnostic")
        report = await run_full_self_test(
            SelfTestDependencies(
                obsidian=ctx.deps.obsidian,
                code_mode=ctx.deps.code_mode,
            )
        )
        return format_self_test_report(report)

    @agent.tool
    async def list_skills(
        ctx: RunContext[AgentDeps],
        status: str | None = None,
        capability: str | None = None,
    ) -> str:
        """List skills from the registry, optionally filtered by status/capability."""
        registry = _get_skill_registry()
        try:
            skill_status = SkillStatus(status) if status else None
        except ValueError:
            return f"Unknown status: {status}"
        skills = registry.list_skills(status=skill_status, capability=capability)
        if not skills:
            return "No skills matched the filter."
        lines = []
        for skill in skills:
            caps = ", ".join(skill.definition.capabilities)
            lines.append(
                f"- {skill.definition.name}@{skill.definition.version} "
                f"({skill.status.value}, caps: {caps})"
            )
        return "Skills:\n" + "\n".join(lines)

    @agent.tool
    async def run_skill(
        ctx: RunContext[AgentDeps],
        name: str,
        inputs: dict,
        version: str | None = None,
        allow_capabilities: list[str] | None = None,
        confirm: bool = False,
    ) -> str:
        """Run a skill by name/version through the skill runtime."""
        if allow_capabilities and not confirm:
            return (
                "Confirmation required to grant extra capabilities. "
                "Ask the user, then retry with confirm=True."
            )
        try:
            result = await _execute_skill(
                ctx.deps,
                name,
                inputs,
                version=version,
                allow_capabilities=allow_capabilities,
                confirmed=confirm,
            )
        except SkillPolicyError as exc:
            return f"Skill denied by policy: {exc.details.get('reasons', [])}"
        except SkillRuntimeError as exc:
            return f"Skill failed ({exc.code}): {exc}"
        except Exception as exc:
            return f"Skill execution error: {exc}"

        return json.dumps(result, indent=2)

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
    logger.info("Processing message (%s chars): %s", len(message), _preview(message, 120))
    start_time = time.perf_counter()
    status = "success"
    llm_start = None

    try:
        prompt = message
        if deps.signal_sender:
            try:
                recent = await deps.memory.get_recent_context(
                    deps.signal_sender,
                    channel=deps.channel,
                )
            except Exception as e:
                recent = None
                logger.warning(f"Failed to load recent context: {e}")
            if recent:
                logger.info(
                    "Recent context loaded (%s chars) for %s",
                    len(recent),
                    deps.signal_sender,
                )
                prompt = render_prompt(
                    "user/recent_context",
                    {"recent": recent, "message": message},
                )

        logger.info("LLM request start (prompt_chars=%s)", len(prompt))
        llm_start = time.perf_counter()
        result = await agent.run(prompt, deps=deps)
        response = _extract_agent_response(result)
        if _brain_metrics:
            _record_llm_metrics(result, agent, start_time)
        if llm_start is not None:
            llm_ms = (time.perf_counter() - llm_start) * 1000
            logger.info("LLM response received (duration_ms=%.1f)", llm_ms)
        logger.info("Response generated (%s chars): %s", len(response), _preview(response, 120))
        if deps.signal_sender and deps.memory.should_write_summary(
            deps.signal_sender,
            settings.conversation.summary_every_turns,
            channel=deps.channel,
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
                        deps.signal_sender, summary_text, channel=deps.channel
                    )
                    await deps.memory.log_summary_marker(
                        deps.signal_sender, summary_path, channel=deps.channel
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


async def run_indexer_task(full_reindex: bool = False) -> str:
    """Run a single vault indexing task under a shared lock."""
    async with _indexer_lock:
        try:
            logger.info("Starting indexer run (full_reindex=%s)", full_reindex)
            await asyncio.to_thread(
                run_indexer,
                vault_path=settings.obsidian.vault_path,
                collection=settings.indexer.collection,
                embed_model=settings.llm.embed_model,
                max_tokens=settings.indexer.chunk_tokens,
                full_reindex=full_reindex,
                run_migrations=False,
            )
            logger.info("Indexer run completed")
            return "Indexing complete."
        except Exception as exc:
            logger.warning(f"Indexer run failed: {exc}")
            return f"Indexing failed: {exc}"


async def indexer_loop(interval_seconds: int) -> None:
    """Continuously run the indexer on a fixed interval."""
    while True:
        await run_indexer_task(full_reindex=False)
        await asyncio.sleep(interval_seconds)


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
            # Use a placeholder that won't be altered by markdown substitutions.
            # Avoid underscores/tildes/asterisks which trigger italic/bold/strikethrough.
            key = f"--CODESPAN{len(code_spans)}--"
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

    if getattr(usage, "input_tokens", None) is not None:
        _brain_metrics.llm_tokens_input.add(usage.input_tokens, base_attrs)
    if getattr(usage, "output_tokens", None) is not None:
        _brain_metrics.llm_tokens_output.add(usage.output_tokens, base_attrs)

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
    object_store: ObjectStore,
    router: AttentionRouter,
    phone_number: str,
    signal_commitment_extractor: Callable | None = None,
    loop_closure_handler: object | None = None,
) -> None:
    """Handle an incoming Signal message.

    Args:
        agent: The Pydantic AI agent
        signal_msg: The incoming Signal message
        obsidian: Obsidian client
        memory: Conversation memory manager
        object_store: Object store for blob persistence
        router: Attention router for outbound replies
        phone_number: The agent's phone number
        signal_commitment_extractor: Optional extractor for creating commitments from messages
        loop_closure_handler: Optional handler for loop-closure replies
    """
    sender = signal_msg.sender
    message = signal_msg.message

    logger.info("Incoming message from %s: %s", sender, _preview(message))

    # Record message received metric
    if _brain_metrics:
        _brain_metrics.messages_received.add(1, {"channel": "signal"})

    if not is_sender_allowed("signal", sender):
        logger.warning(f"Ignoring message from unauthorized sender: {sender}")
        return

    logger.info(f"Handling message from {sender}: {message[:50]}...")
    try:
        maybe_record_review_engagement(
            sender,
            session_factory=get_sync_session,
            engaged_at=signal_msg.timestamp,
            window_minutes=settings.commitments.review_engagement_window_minutes,
        )
    except Exception:
        logger.exception("Failed to record review engagement for %s.", sender)

    # Create tracing span if available
    tracer = None
    if OBSERVABILITY_AVAILABLE:
        try:
            tracer = get_tracer()
        except RuntimeError:
            tracer = None
    span_context = (
        tracer.start_as_current_span(
            "signal.handle_message",
            attributes={
                "signal.sender": sender,
                "signal.message_length": len(message),
            },
        )
        if tracer
        else None
    )

    try:
        if span_context:
            span_context.__enter__()

        # Log incoming message to conversation
        await memory.log_message(
            sender,
            "user",
            message,
            signal_msg.timestamp,
            channel="signal",
        )

        # Check if this is a loop-closure reply first
        loop_closure_result = None
        if loop_closure_handler:
            try:
                loop_closure_result = await asyncio.to_thread(
                    loop_closure_handler.try_handle_reply,
                    sender,
                    message,
                    signal_msg.timestamp,
                )
                if loop_closure_result:
                    logger.info(
                        "Handled loop-closure reply from %s: %s",
                        sender,
                        loop_closure_result.status,
                    )
            except Exception:
                logger.exception("Failed to process potential loop-closure reply")

        # Create dependencies with sender context
        deps = AgentDeps(
            user=settings.user.name,
            obsidian=obsidian,
            memory=memory,
            code_mode=code_mode,
            object_store=object_store,
            signal_sender=sender,
            channel="signal",
        )

        # Process message (or generate acknowledgment if loop-closure was handled)
        if loop_closure_result:
            # Generate a confirmation response based on the action taken
            response = _generate_loop_closure_confirmation(loop_closure_result)
        else:
            response = await process_message(agent, message, deps)

        # Log response to conversation
        await memory.log_message(
            sender,
            "assistant",
            response,
            channel="signal",
        )
        logger.info("Outgoing message to %s: %s", sender, _preview(response))

        # Extract commitments from message exchange
        if signal_commitment_extractor:
            try:
                await asyncio.to_thread(
                    signal_commitment_extractor,
                    message,
                    response,
                    sender,
                    signal_msg.timestamp,
                )
            except Exception:
                logger.exception("Failed to extract commitments from Signal message")

        # Send reply via Attention Router
        send_start = time.perf_counter()
        outbound = build_signal_reply_envelope(
            from_number=phone_number,
            to_number=sender,
            message=_render_signal_message(response),
            source_component="agent",
        )
        await router.route_envelope(outbound)

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
    object_store: ObjectStore,
    poll_interval: float = 2.0,
    signal_commitment_extractor: Callable | None = None,
    loop_closure_handler: object | None = None,
) -> None:
    """Main loop for polling Signal messages.

    Args:
        agent: The Pydantic AI agent
        obsidian: Obsidian client
        memory: Conversation memory manager
        object_store: Object store for blob persistence
        poll_interval: Seconds between polls
        signal_commitment_extractor: Optional extractor for creating commitments from messages
        loop_closure_handler: Optional handler for loop-closure replies
    """
    phone_number = settings.signal.phone_number
    if not phone_number:
        logger.error("SIGNAL_PHONE_NUMBER not configured")
        return

    signal_client = SignalClient()
    router = AttentionRouter(signal_client)

    # Check Signal API connection
    if not await signal_client.check_connection():
        logger.error("Cannot connect to Signal API")
        return

    logger.info(f"Starting Signal polling for {phone_number}")

    while True:
        poll_start = time.perf_counter()
        try:
            logger.info("Polling Signal for %s", phone_number)
            messages = await signal_client.poll_messages(phone_number)
            logger.info("Signal poll returned %s message(s)", len(messages))

            # Record poll metrics
            if _brain_metrics:
                poll_duration = (time.perf_counter() - poll_start) * 1000
                _brain_metrics.signal_polls.add(1, {"status": "success"})
                _brain_metrics.signal_latency.record(poll_duration, {"operation": "poll"})

            for msg in messages:
                await handle_signal_message(
                    agent,
                    msg,
                    obsidian,
                    memory,
                    code_mode,
                    object_store,
                    router,
                    phone_number,
                    signal_commitment_extractor=signal_commitment_extractor,
                    loop_closure_handler=loop_closure_handler,
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
    object_store: ObjectStore,
) -> None:
    """Run a single message in test mode.

    Args:
        agent: The Pydantic AI agent
        message: The test message to process
        object_store: Object store for blob persistence
    """
    obsidian = ObsidianClient()
    memory = ConversationMemory(obsidian)

    deps = AgentDeps(
        user=settings.user.name,
        obsidian=obsidian,
        memory=memory,
        code_mode=code_mode,
        object_store=object_store,
        signal_sender="test",
        channel="test",
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

    # Determine OTLP endpoint
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if args.no_otel:
        otel_endpoint = None

    # Configure logging and observability
    if OBSERVABILITY_AVAILABLE:
        try:
            _, _, _brain_metrics = setup_observability(
                service_name="brain-agent",
                service_version="1.0.0",
                otlp_endpoint=otel_endpoint,
            )
            configure_logging(settings.log_level, settings.log_level_otel)
            if otel_endpoint:
                setup_litellm_observability(_brain_metrics)
        except Exception as e:
            logging.warning(f"Failed to initialize observability: {e}", exc_info=True)
    else:
        # Fallback to basic logging if observability packages are not installed
        log_level_numeric = getattr(logging, settings.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=log_level_numeric,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
            force=True,
        )
        logger.info("Observability modules not available, using basic logging.")

    _ensure_llm_env()

    logger.info("Brain assistant starting...")
    logger.info(f"User: {settings.user.name}")
    logger.info(f"Obsidian URL: {settings.obsidian.url}")
    logger.info(f"Signal API URL: {settings.signal.url}")

    # Initialize database
    try:
        await init_db()
    except Exception as e:
        logger.warning(f"Database init failed (may not be available): {e}")

    if settings.letta.bootstrap_on_start:
        try:
            from letta_bootstrap import bootstrap_letta

            bootstrap_letta()
        except Exception as e:
            logger.warning(f"Letta bootstrap failed: {e}")

    logger.info("Initializing Code-Mode/UTCP...")
    try:
        code_mode = await asyncio.wait_for(
            create_code_mode_manager(
                settings.utcp.config_path,
                settings.utcp.code_mode_timeout,
            ),
            timeout=settings.utcp.code_mode_timeout,
        )
        logger.info(
            "Code-Mode initialized (enabled=%s)",
            bool(code_mode.client),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Code-Mode init timed out after %s seconds; continuing without it",
            settings.utcp.code_mode_timeout,
        )
        code_mode = CodeModeManager(
            client=None,
            config_path=Path(os.path.expanduser(settings.utcp.config_path)).resolve(),
            timeout=settings.utcp.code_mode_timeout,
        )

    # Create agent
    agent = create_agent()
    logger.info("Agent initialized")

    # Test mode
    object_store = ObjectStore(settings.objects.root_dir)

    # Initialize agent hooks and services
    # IMPORTANT: Initialization failures are fatal - the agent cannot operate without these hooks
    try:
        from agent_init import initialize_agent_hooks
        from llm import LLMClient

        llm_client = LLMClient()
        agent_services = initialize_agent_hooks(
            session_factory=get_sync_session,
            object_store=object_store,
            llm_client=llm_client,
        )
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize agent hooks: {e}", exc_info=True)
        raise RuntimeError(f"Agent initialization failed: {e}") from e

    if args.test:
        await run_test_mode(agent, args.test, code_mode, object_store)
        return

    # Signal mode
    obsidian = ObsidianClient()
    memory = ConversationMemory(obsidian)

    if settings.indexer.interval_seconds > 0:
        logger.info(
            "Starting scheduled indexing every %s seconds",
            settings.indexer.interval_seconds,
        )
        asyncio.create_task(indexer_loop(settings.indexer.interval_seconds))

    logger.info("Starting Signal message loop...")
    try:
        await run_signal_loop(
            agent,
            obsidian,
            memory,
            code_mode,
            object_store,
            poll_interval=args.poll_interval,
            signal_commitment_extractor=agent_services.get("signal_commitment_extractor"),
            loop_closure_handler=agent_services.get("loop_closure_handler"),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
