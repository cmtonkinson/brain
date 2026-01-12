"""Main agent daemon for Brain assistant."""

import asyncio
import logging
from datetime import datetime

from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/app/logs/agent.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main agent loop."""
    logger.info("Brain assistant starting...")
    logger.info(f"Obsidian URL: {settings.obsidian_url}")
    logger.info(f"Qdrant URL: {settings.qdrant_url}")
    logger.info(f"Signal API URL: {settings.signal_api_url}")
    
    # TODO: Initialize components
    # - Qdrant client
    # - Pydantic AI agent
    # - Signal message handler
    # - Background task scheduler
    
    logger.info("Agent initialized successfully")
    
    # Keep alive
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
