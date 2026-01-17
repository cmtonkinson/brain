"""Main agent daemon for Brain assistant."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent, RunContext

from config import settings
from models import SignalMessage
from services.code_mode import CodeModeManager, create_code_mode_manager
from services.database import init_db, get_session, log_action
from access_control import is_sender_allowed
from services.signal import SignalClient
from services.letta import LettaService
from prompts import render_prompt
from tools.obsidian import ObsidianClient
from tools.memory import ConversationMemory
from indexer import index_vault as run_indexer
from services.vector_search import search_vault as search_vault_vectors
from qdrant_client import QdrantClient
from self_diagnostic_utils import (
    contains_expected_name,
    extract_allowed_directories,
    extract_allowed_directories_from_text,
    extract_code_mode_result,
    extract_content_text,
    parse_code_mode_payload,
)
from skills.adapters.op_adapter import MCPOpAdapter, NativeOpAdapter
from skills.adapters.python_adapter import PythonSkillAdapter
from skills.context import SkillContext
from skills.op_runtime import OpRuntime
from skills.policy import DefaultPolicy
from skills.registry import OpRegistryLoader, SkillRegistryLoader
from skills.errors import SkillPolicyError, SkillRuntimeError
from skills.runtime import SkillRuntime
from skills.registry_schema import AutonomyLevel, SkillStatus
from skills.services import SkillServices, set_services

# Observability imports (conditional to allow running without OTEL)
try:
    from observability import (
        setup_observability,
        setup_json_logging,
        get_tracer,
        BrainMetrics,
    )
    from observability_litellm import setup_litellm_observability

    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False

# Configure logging - use JSON if observability available, otherwise basic (stdout only).
# Use force=True to override any handlers set by imported modules (e.g., indexer.py).
# Explicitly use sys.stdout (not stderr) for Docker log capture reliability.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)

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
    signal_sender: str | None = None  # Phone number of current message sender
    channel: str = "signal"


def _preview(text: str, limit: int = 160) -> str:
    """Return a single-line preview of text for logging."""
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        return cleaned[:limit] + "..."
    return cleaned


def _ensure_logging() -> None:
    """Force logging to stdout at INFO in case another lib muted it."""
    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setLevel(logging.INFO)
        handler.flush()  # Ensure any buffered output is written
    logger.setLevel(logging.INFO)
    logger.propagate = True
    logger.info("Logging configured (handlers=%s)", len(root.handlers))
    # Flush again after logging to ensure immediate output
    for handler in root.handlers:
        handler.flush()


def _stdout(msg: str) -> None:
    """Write a message to stdout and flush immediately."""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _ensure_llm_env() -> None:
    """Bridge config secrets into env for SDKs that only read env vars."""
    if settings.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key


def _get_summary_agent() -> Agent[None, str]:
    """Lazy-initialize the summary agent used for conversation summaries."""
    global _summary_agent
    if _summary_agent is None:
        _summary_agent = Agent(
            settings.llm.model,
            result_type=str,
            system_prompt=render_prompt("system/summary"),
        )
    return _summary_agent


async def _run_code_mode_diagnostics(ctx: RunContext[AgentDeps]) -> list[str]:
    """Run Code-Mode/MCP checks for self-diagnostic only."""
    results: list[str] = []
    code_mode_enabled = ctx.deps.code_mode.client is not None

    def _has_non_empty_listing(raw: str | None) -> bool:
        if raw is None:
            return False
        if raw in ("", "None", "null", "[]", "{}"):
            return False
        parsed = parse_code_mode_payload(raw)
        text = extract_content_text(parsed)
        if text is not None:
            return bool(text.strip())
        if isinstance(parsed, (list, tuple, set, dict)):
            return bool(parsed)
        return parsed is not None

    def _has_tool_results(raw: str) -> bool:
        return bool(re.search(r"^- \S+:", raw, re.MULTILINE))

    if not code_mode_enabled:
        logger.info("self_diagnostic: code-mode search_tools skipped (not configured)")
        _stdout("AGENT: self_diagnostic code-mode search_tools skipped (not configured)")
        results.append("- code-mode: skipped (not configured)")
        results.append("- mcp/filesystem: skipped (not configured)")
        results.append("- mcp/calendar: skipped (not configured)")
        results.append("- mcp/reminders: skipped (not configured)")
        results.append("- mcp/github: skipped (not configured)")
        return results

    # Code-Mode: search tools to confirm UTCP is available.
    try:
        logger.info("self_diagnostic: code-mode search_tools")
        _stdout("AGENT: self_diagnostic code-mode search_tools")
        response = await ctx.deps.code_mode.search_tools("list tools")
        if response.startswith("Code-Mode is not configured"):
            logger.warning("self_diagnostic: code-mode not configured")
            _stdout("AGENT: self_diagnostic code-mode not configured")
            results.append("- code-mode: error (not configured)")
        elif _has_tool_results(response):
            logger.info("self_diagnostic: code-mode ok (search_tools)")
            _stdout("AGENT: self_diagnostic code-mode ok (search_tools)")
            results.append("- code-mode: ok (search_tools)")
        else:
            logger.warning("self_diagnostic: code-mode empty search_tools result")
            _stdout("AGENT: self_diagnostic code-mode empty search_tools result")
            results.append("- code-mode: error (empty tool search)")
    except Exception as exc:
        logger.error(f"self_diagnostic code-mode failed: {exc}")
        _stdout(f"AGENT: self_diagnostic code-mode failed ({exc})")
        results.append(f"- code-mode: error ({exc})")

    # MCP filesystem: list base directory.
    try:
        logger.info("self_diagnostic: mcp filesystem list_directory")
        _stdout("AGENT: self_diagnostic mcp filesystem list_directory")
        allowed_code = "result = filesystem.list_allowed_directories({})\nreturn result"
        allowed_output = await ctx.deps.code_mode.call_tool_chain(allowed_code)
        allowed_raw = extract_code_mode_result(allowed_output)
        allowed_parsed = parse_code_mode_payload(allowed_raw)
        allowed_dirs = extract_allowed_directories(allowed_parsed)
        if not allowed_dirs:
            allowed_dirs = extract_allowed_directories_from_text(allowed_output)
        if not allowed_dirs:
            logger.warning("self_diagnostic: mcp filesystem no allowed directories")
            _stdout("AGENT: self_diagnostic mcp filesystem no allowed directories")
            results.append("- mcp/filesystem: error (no allowed directories)")
        else:
            base_path = Path(os.path.expanduser(allowed_dirs[0])).resolve()
            code = (
                f"result = filesystem.list_directory({{'path': {str(base_path)!r}}})\nreturn result"
            )
            output = await ctx.deps.code_mode.call_tool_chain(code)
            raw = extract_code_mode_result(output)
            if _has_non_empty_listing(raw):
                logger.info("self_diagnostic: mcp filesystem ok")
                _stdout("AGENT: self_diagnostic mcp filesystem ok")
                results.append("- mcp/filesystem: ok (base directory listed)")
            else:
                logger.warning("self_diagnostic: mcp filesystem empty listing")
                _stdout("AGENT: self_diagnostic mcp filesystem empty listing")
                results.append("- mcp/filesystem: error (empty directory listing)")
    except Exception as exc:
        logger.error(f"self_diagnostic mcp filesystem failed: {exc}")
        _stdout(f"AGENT: self_diagnostic mcp filesystem failed ({exc})")
        results.append(f"- mcp/filesystem: error ({exc})")

    # MCP calendar: list event calendars.
    try:
        logger.info("self_diagnostic: mcp calendar list_event_calendars")
        _stdout("AGENT: self_diagnostic mcp calendar list_event_calendars")
        code = "result = eventkit.list_event_calendars({})\nreturn result"
        output = await ctx.deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        expected_calendar = settings.user.test_calendar_name
        if _has_non_empty_listing(raw) and contains_expected_name(raw, expected_calendar):
            logger.info("self_diagnostic: mcp calendar ok")
            _stdout("AGENT: self_diagnostic mcp calendar ok")
            results.append("- mcp/calendar: ok (calendars listed)")
        else:
            if _has_non_empty_listing(raw):
                logger.warning(
                    "self_diagnostic: mcp calendar missing expected name (%s)",
                    expected_calendar,
                )
                _stdout("AGENT: self_diagnostic mcp calendar missing expected name")
                results.append(
                    f"- mcp/calendar: error (missing expected calendar: {expected_calendar})"
                )
            else:
                logger.warning("self_diagnostic: mcp calendar empty list")
                _stdout("AGENT: self_diagnostic mcp calendar empty list")
                results.append("- mcp/calendar: error (no calendars)")
    except Exception as exc:
        logger.error(f"self_diagnostic mcp calendar failed: {exc}")
        _stdout(f"AGENT: self_diagnostic mcp calendar failed ({exc})")
        results.append(f"- mcp/calendar: error ({exc})")

    # MCP reminders: list reminder lists.
    try:
        logger.info("self_diagnostic: mcp reminders list_calendars")
        _stdout("AGENT: self_diagnostic mcp reminders list_calendars")
        code = "result = eventkit.list_calendars({})\nreturn result"
        output = await ctx.deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        expected_reminders = settings.user.test_reminder_list_name
        if _has_non_empty_listing(raw) and contains_expected_name(raw, expected_reminders):
            logger.info("self_diagnostic: mcp reminders ok")
            _stdout("AGENT: self_diagnostic mcp reminders ok")
            results.append("- mcp/reminders: ok (reminder lists listed)")
        else:
            if _has_non_empty_listing(raw):
                logger.warning(
                    "self_diagnostic: mcp reminders missing expected name (%s)",
                    expected_reminders,
                )
                _stdout("AGENT: self_diagnostic mcp reminders missing expected name")
                results.append(
                    f"- mcp/reminders: error (missing expected reminder list: {expected_reminders})"
                )
            else:
                logger.warning("self_diagnostic: mcp reminders empty list")
                _stdout("AGENT: self_diagnostic mcp reminders empty list")
                results.append("- mcp/reminders: error (no reminder lists)")
    except Exception as exc:
        logger.error(f"self_diagnostic mcp reminders failed: {exc}")
        _stdout(f"AGENT: self_diagnostic mcp reminders failed ({exc})")
        results.append(f"- mcp/reminders: error ({exc})")

    # MCP github: fetch authenticated user.
    try:
        logger.info("self_diagnostic: mcp github get_authenticated_user")
        _stdout("AGENT: self_diagnostic mcp github get_authenticated_user")
        code = "result = github.get_me({})\nreturn result"
        output = await ctx.deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        if _has_non_empty_listing(raw):
            logger.info("self_diagnostic: mcp github ok")
            _stdout("AGENT: self_diagnostic mcp github ok")
            results.append("- mcp/github: ok (authenticated user)")
        else:
            logger.warning("self_diagnostic: mcp github empty response")
            _stdout("AGENT: self_diagnostic mcp github empty response")
            results.append("- mcp/github: error (empty response)")
    except Exception as exc:
        logger.error(f"self_diagnostic mcp github failed: {exc}")
        _stdout(f"AGENT: self_diagnostic mcp github failed ({exc})")
        results.append(f"- mcp/github: error ({exc})")

    return results


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
    context = SkillContext(
        allowed_capabilities=allowed,
        actor=deps.signal_sender,
        channel=deps.channel,
        max_autonomy=AutonomyLevel.L1,
        confirmed=confirmed,
    )
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
        ),
    )
    set_services(
        SkillServices(
            obsidian=deps.obsidian,
            code_mode=deps.code_mode,
            signal=None,
        )
    )
    result = await runtime.execute(name, inputs, context, version=version)
    return result.output


# --- Agent Definition ---


def create_agent() -> Agent[AgentDeps, str]:
    """Create and configure the Pydantic AI agent."""
    agent: Agent[AgentDeps, str] = Agent(
        settings.llm.model,
        deps_type=AgentDeps,
        result_type=str,
        system_prompt=render_prompt("system/assistant", {"user": settings.user.name}),
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
        """Run a lightweight self-diagnostic across core subsystems."""
        logger.info("Tool: self_diagnostic")
        _stdout("AGENT: self_diagnostic started")
        results: list[str] = []

        # Obsidian: list base vault directory.
        try:
            logger.info("self_diagnostic: obsidian list_dir")
            _stdout("AGENT: self_diagnostic obsidian list_dir")
            entries = await ctx.deps.obsidian.list_dir("")
            if entries:
                logger.info("self_diagnostic: obsidian ok (%s entries)", len(entries))
                _stdout(f"AGENT: self_diagnostic obsidian ok ({len(entries)} entries)")
                results.append(f"- obsidian: ok ({len(entries)} entries)")
            else:
                logger.warning("self_diagnostic: obsidian empty directory listing")
                _stdout("AGENT: self_diagnostic obsidian empty directory listing")
                results.append("- obsidian: error (empty directory listing)")
        except Exception as exc:
            logger.error(f"self_diagnostic obsidian failed: {exc}")
            _stdout(f"AGENT: self_diagnostic obsidian failed ({exc})")
            results.append(f"- obsidian: error ({exc})")

        # Letta: check enabled then read-only search.
        letta = LettaService()
        if not letta.enabled:
            logger.info("self_diagnostic: letta skipped (not configured)")
            _stdout("AGENT: self_diagnostic letta skipped (not configured)")
            results.append("- letta: skipped (not configured)")
        else:
            try:
                logger.info("self_diagnostic: letta archival search")
                _stdout("AGENT: self_diagnostic letta archival search")
                await asyncio.to_thread(letta.search_archival_memory, "smoke test")
                logger.info("self_diagnostic: letta ok (archival search)")
                _stdout("AGENT: self_diagnostic letta ok (archival search)")
                results.append("- letta: ok (archival search)")
            except Exception as exc:
                logger.error(f"self_diagnostic letta failed: {exc}")
                _stdout(f"AGENT: self_diagnostic letta failed ({exc})")
                results.append(f"- letta: error ({exc})")

        # Signal: check connection then fetch accounts.
        try:
            signal_client = SignalClient()
            logger.info("self_diagnostic: signal check_connection")
            _stdout("AGENT: self_diagnostic signal check_connection")
            connected = await signal_client.check_connection()
            if not connected:
                logger.warning("self_diagnostic: signal connection failed")
                _stdout("AGENT: self_diagnostic signal connection failed")
                results.append("- signal: error (connection failed)")
            else:
                logger.info("self_diagnostic: signal get_accounts")
                _stdout("AGENT: self_diagnostic signal get_accounts")
                accounts = await signal_client.get_accounts()
                if accounts:
                    logger.info("self_diagnostic: signal ok (%s account(s))", len(accounts))
                    _stdout(f"AGENT: self_diagnostic signal ok ({len(accounts)} account(s))")
                    results.append(f"- signal: ok ({len(accounts)} account(s))")
                else:
                    logger.warning("self_diagnostic: signal no accounts returned")
                    _stdout("AGENT: self_diagnostic signal no accounts returned")
                    results.append("- signal: error (no accounts returned)")
        except Exception as exc:
            logger.error(f"self_diagnostic signal failed: {exc}")
            _stdout(f"AGENT: self_diagnostic signal failed ({exc})")
            results.append(f"- signal: error ({exc})")

        # Qdrant: list collections to confirm service is reachable.
        try:
            logger.info("self_diagnostic: qdrant get_collections")
            _stdout("AGENT: self_diagnostic qdrant get_collections")
            qdrant = QdrantClient(url=settings.qdrant.url)
            collections = qdrant.get_collections()
            count = len(collections.collections or [])
            logger.info("self_diagnostic: qdrant ok (%s collection(s))", count)
            _stdout(f"AGENT: self_diagnostic qdrant ok ({count} collection(s))")
            results.append(f"- qdrant: ok ({count} collection(s))")
        except Exception as exc:
            logger.error(f"self_diagnostic qdrant failed: {exc}")
            _stdout(f"AGENT: self_diagnostic qdrant failed ({exc})")
            results.append(f"- qdrant: error ({exc})")

        results.extend(await _run_code_mode_diagnostics(ctx))

        return "\n".join(results)

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

    _ensure_logging()
    _stdout("AGENT: message received")
    logger.info("Incoming message from %s: %s", sender, _preview(message))

    # Record message received metric
    if _brain_metrics:
        _brain_metrics.messages_received.add(1, {"channel": "signal"})

    if not is_sender_allowed("signal", sender):
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

        # Create dependencies with sender context
        deps = AgentDeps(
            user=settings.user.name,
            obsidian=obsidian,
            memory=memory,
            code_mode=code_mode,
            signal_sender=sender,
            channel="signal",
        )

        # Process message
        response = await process_message(agent, message, deps)

        # Log response to conversation
        await memory.log_message(
            sender,
            "assistant",
            response,
            channel="signal",
        )
        logger.info("Outgoing message to %s: %s", sender, _preview(response))

        # Send reply via Signal
        send_start = time.perf_counter()
        await signal_client.send_message(phone_number, sender, _render_signal_message(response))

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
    phone_number = settings.signal.phone_number
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
        _ensure_logging()
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
        user=settings.user.name,
        obsidian=obsidian,
        memory=memory,
        code_mode=code_mode,
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

    _ensure_logging()
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
    if args.test:
        await run_test_mode(agent, args.test, code_mode)
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
            poll_interval=args.poll_interval,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
