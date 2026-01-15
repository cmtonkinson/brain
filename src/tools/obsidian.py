"""Obsidian vault integration via Local REST API."""

import httpx
from typing import List, Dict, Any
import logging

from config import settings

logger = logging.getLogger(__name__)


class ObsidianClient:
    """Client for Obsidian Local REST API."""
    
    def __init__(self):
        # Normalize to avoid accidental double slashes in request URLs.
        self.base_url = settings.obsidian.url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.obsidian.api_key}",
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
        logger.info("Obsidian search: query_chars=%s limit=%s", len(query), limit)
        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                # Use query parameter instead of JSON body
                response = await client.post(
                    f"{self.base_url}/search/simple/",
                    headers=self.headers,
                    params={"query": query},
                )
                response.raise_for_status()
                results = response.json()
                if isinstance(results, dict):
                    for key in ("results", "files", "items"):
                        value = results.get(key)
                        if isinstance(value, list):
                            results = value
                            break
                count = len(results) if isinstance(results, list) else 1
                logger.info("Obsidian search results: %s", count)
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
        logger.info("Obsidian get_note: %s", path)
        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/vault/{path}",
                    headers=self.headers
                )
                response.raise_for_status()
                logger.info("Obsidian get_note OK: %s chars=%s", path, len(response.text))
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

        logger.info("Obsidian create_note: %s chars=%s", path, len(content))
        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                # Use text/markdown content type for note creation
                headers = {**self.headers, "Content-Type": "text/markdown"}
                response = await client.put(
                    f"{self.base_url}/vault/{path}",
                    headers=headers,
                    content=content
                )
                response.raise_for_status()
                logger.info("Created note: %s", path)
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
        logger.info("Obsidian append_to_note: %s chars=%s", path, len(content))
        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                headers = {**self.headers, "Content-Type": "text/markdown"}
                response = await client.post(
                    f"{self.base_url}/vault/{path}",
                    headers=headers,
                    content=content
                )
                response.raise_for_status()
                logger.info("Appended to note: %s", path)
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

    async def list_dir(self, path: str = "") -> list[str]:
        """List entries in a vault directory.

        Args:
            path: Vault-relative directory path (default: vault root)

        Returns:
            List of entry names or paths
        """
        normalized = path.strip("/")
        if normalized:
            url = f"{self.base_url}/vault/{normalized}/"
        else:
            url = f"{self.base_url}/vault/"
        logger.info("Obsidian list_dir: %s", normalized or "/")
        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ValueError("Obsidian list_dir returned non-JSON response.") from exc
            entries = None
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                for key in ("files", "items", "children", "entries", "data"):
                    value = data.get(key)
                    if isinstance(value, list):
                        entries = value
                        break
            if entries is None:
                raise ValueError("Obsidian list_dir returned unexpected response shape.")

            names: list[str] = []
            for entry in entries:
                if isinstance(entry, str):
                    names.append(entry)
                elif isinstance(entry, dict):
                    name = entry.get("path") or entry.get("name") or entry.get("file")
                    if name is not None:
                        names.append(str(name))
                else:
                    names.append(str(entry))
            logger.info("Obsidian list_dir OK: %s entries", len(names))
            return names
        except httpx.HTTPStatusError as e:
            logger.error(f"Obsidian list_dir failed: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Obsidian connection error: {e}")
            raise
