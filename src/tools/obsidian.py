"""Obsidian vault integration via Local REST API."""

import httpx
from typing import List, Dict, Any
import logging

from config import settings

logger = logging.getLogger(__name__)


class ObsidianClient:
    """Client for Obsidian Local REST API."""
    
    def __init__(self):
        self.base_url = settings.obsidian_url
        self.headers = {
            "Authorization": f"Bearer {settings.obsidian_api_key}",
            "Content-Type": "application/json"
        }
    
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search vault for notes matching query.

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            List of matching notes with metadata
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use query parameter instead of JSON body
                response = await client.post(
                    f"{self.base_url}/search/simple/",
                    headers=self.headers,
                    params={"query": query},
                )
                response.raise_for_status()
                results = response.json()
                return results[:limit] if isinstance(results, list) else results
        except httpx.HTTPStatusError as e:
            logger.error(f"Obsidian search failed: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Obsidian connection error: {e}")
            raise
    
    async def get_note(self, path: str) -> str:
        """Get content of a specific note.

        Args:
            path: Path to note within vault

        Returns:
            Note content as string
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/vault/{path}",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Note not found: {path}")
                raise FileNotFoundError(f"Note not found: {path}")
            logger.error(f"Obsidian get_note failed: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Obsidian connection error: {e}")
            raise
    
    async def create_note(self, path: str, content: str) -> Dict[str, Any]:
        """Create a new note.

        Args:
            path: Path for new note (should end in .md)
            content: Note content in markdown format

        Returns:
            Created note metadata
        """
        # Ensure path ends with .md
        if not path.endswith(".md"):
            path = f"{path}.md"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use text/markdown content type for note creation
                headers = {**self.headers, "Content-Type": "text/markdown"}
                response = await client.put(
                    f"{self.base_url}/vault/{path}",
                    headers=headers,
                    content=content
                )
                response.raise_for_status()
                logger.info(f"Created note: {path}")
                return {"path": path, "status": "created"}
        except httpx.HTTPStatusError as e:
            logger.error(f"Obsidian create_note failed: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Obsidian connection error: {e}")
            raise
    
    async def append_to_note(self, path: str, content: str) -> Dict[str, Any]:
        """Append content to existing note.

        Args:
            path: Path to note
            content: Content to append

        Returns:
            Updated note metadata
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {**self.headers, "Content-Type": "text/markdown"}
                response = await client.post(
                    f"{self.base_url}/vault/{path}",
                    headers=headers,
                    content=content
                )
                response.raise_for_status()
                logger.info(f"Appended to note: {path}")
                return {"path": path, "status": "appended"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Note not found for append: {path}")
                raise FileNotFoundError(f"Note not found: {path}")
            logger.error(f"Obsidian append_to_note failed: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Obsidian connection error: {e}")
            raise

    async def note_exists(self, path: str) -> bool:
        """Check if a note exists.

        Args:
            path: Path to note

        Returns:
            True if note exists, False otherwise
        """
        try:
            await self.get_note(path)
            return True
        except FileNotFoundError:
            return False
