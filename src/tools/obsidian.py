"""Obsidian vault integration via Local REST API."""

import httpx
from typing import List, Dict, Any

from config import settings


class ObsidianClient:
    """Client for Obsidian Local REST API."""
    
    def __init__(self):
        self.base_url = settings.obsidian_url
        self.headers = {
            "Authorization": f"Bearer {settings.obsidian_api_key}",
            "Content-Type": "application/json"
        }
    
    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search vault for notes matching query.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching notes with metadata
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/search/simple/",
                headers=self.headers,
                json={"query": query}
            )
            response.raise_for_status()
            return response.json()
    
    async def get_note(self, path: str) -> str:
        """Get content of a specific note.
        
        Args:
            path: Path to note within vault
            
        Returns:
            Note content as string
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/vault/{path}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.text
    
    async def create_note(self, path: str, content: str) -> Dict[str, Any]:
        """Create a new note.
        
        Args:
            path: Path for new note
            content: Note content
            
        Returns:
            Created note metadata
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/vault/{path}",
                headers=self.headers,
                data=content
            )
            response.raise_for_status()
            return response.json()
    
    async def append_to_note(self, path: str, content: str) -> Dict[str, Any]:
        """Append content to existing note.
        
        Args:
            path: Path to note
            content: Content to append
            
        Returns:
            Updated note metadata
        """
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}/vault/{path}",
                headers=self.headers,
                data=content
            )
            response.raise_for_status()
            return response.json()
