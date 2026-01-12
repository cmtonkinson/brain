"""Main agent daemon for Brain assistant."""

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic_ai import Agent, RunContext

from config import settings
from models import SignalMessage
from services.database import init_db, get_session, log_action
from services.signal import SignalClient
from tools.obsidian import ObsidianClient
from tools.memory import ConversationMemory

# Configure logging
log_dir = Path("/app/logs") if Path("/app/logs").exists() else Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "agent.log"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


# --- Dependency Injection ---


@dataclass
class AgentDeps:
    """Dependencies injected into the agent at runtime."""

    user: str
    obsidian: ObsidianClient
    memory: ConversationMemory
    signal_sender: str | None = None  # Phone number of current message sender


# --- System Prompt ---

SYSTEM_PROMPT = """You are Brain, a personal AI assistant for {user}. You have access to their Obsidian knowledge base and can help with:

- Searching and retrieving information from notes
- Creating new notes and capturing ideas
- Answering questions based on stored knowledge

Guidelines:
- Be concise but thorough
- When searching notes, summarize relevant findings
- Always confirm before creating or modifying notes unless the user explicitly asks
- If you don't find information in the knowledge base, say so clearly
- Format responses for readability (use markdown when helpful)

You are communicating via Signal messenger, so keep responses appropriately sized for mobile reading."""


# --- Agent Definition ---


def create_agent() -> Agent[AgentDeps, str]:
    """Create and configure the Pydantic AI agent."""
    agent: Agent[AgentDeps, str] = Agent(
        "anthropic:claude-sonnet-4-20250514",
        deps_type=AgentDeps,
        result_type=str,
        system_prompt=SYSTEM_PROMPT.format(user=settings.user),
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
                filename = result.get("filename", "Unknown")
                # Handle different response formats from the API
                matches = result.get("matches", [])
                snippet = ""
                if matches and isinstance(matches, list):
                    snippet = matches[0].get("match", "")[:200] if matches else ""

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

    try:
        result = await agent.run(message, deps=deps)
        response = result.output
        logger.info(f"Response generated: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return f"I encountered an error: {e}"


async def handle_signal_message(
    agent: Agent[AgentDeps, str],
    signal_msg: SignalMessage,
    obsidian: ObsidianClient,
    memory: ConversationMemory,
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

    # Check allowed senders if configured
    if settings.allowed_senders and sender not in settings.allowed_senders:
        logger.warning(f"Ignoring message from unauthorized sender: {sender}")
        return

    logger.info(f"Handling message from {sender}: {message[:50]}...")

    # Log incoming message to conversation
    await memory.log_message(sender, "user", message, signal_msg.timestamp)

    # Create dependencies with sender context
    deps = AgentDeps(
        user=settings.user,
        obsidian=obsidian,
        memory=memory,
        signal_sender=sender,
    )

    # Process message
    response = await process_message(agent, message, deps)

    # Log response to conversation
    await memory.log_message(sender, "assistant", response)

    # Send reply via Signal
    await signal_client.send_message(phone_number, sender, response)

    # Log action to database
    async with get_session() as session:
        await log_action(
            session,
            action_type="signal_conversation",
            description=f"Conversation with {sender}",
            result=f"User: {message[:100]}... | Brain: {response[:100]}...",
        )


# --- Main Loop ---


async def run_signal_loop(
    agent: Agent[AgentDeps, str],
    obsidian: ObsidianClient,
    memory: ConversationMemory,
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
        try:
            messages = await signal_client.poll_messages(phone_number)

            for msg in messages:
                await handle_signal_message(
                    agent, msg, obsidian, memory, signal_client, phone_number
                )

        except Exception as e:
            logger.error(f"Error in Signal loop: {e}")

        await asyncio.sleep(poll_interval)


async def run_test_mode(agent: Agent[AgentDeps, str], message: str) -> None:
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
        signal_sender="test",
    )

    print(f"\n[User]: {message}\n")
    response = await process_message(agent, message, deps)
    print(f"[Brain]: {response}\n")


async def main() -> None:
    """Main entry point."""
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
    args = parser.parse_args()

    logger.info("Brain assistant starting...")
    logger.info(f"User: {settings.user}")
    logger.info(f"Obsidian URL: {settings.obsidian_url}")
    logger.info(f"Signal API URL: {settings.signal_api_url}")

    # Initialize database
    try:
        await init_db()
    except Exception as e:
        logger.warning(f"Database init failed (may not be available): {e}")

    # Create agent
    agent = create_agent()
    logger.info("Agent initialized")

    # Test mode
    if args.test:
        await run_test_mode(agent, args.test)
        return

    # Signal mode
    obsidian = ObsidianClient()
    memory = ConversationMemory(obsidian)

    logger.info("Starting Signal message loop...")
    try:
        await run_signal_loop(
            agent, obsidian, memory, poll_interval=args.poll_interval
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
