"""Mock Obsidian client for skill tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockObsidianClient:
    """In-memory Obsidian client for unit tests."""

    notes: dict[str, str] = field(default_factory=dict)

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Return matching notes by query string."""
        results = []
        for path, content in self.notes.items():
            if query.lower() in content.lower() or query.lower() in path.lower():
                results.append(
                    {
                        "path": path,
                        "matches": [{"match": content[:200]}],
                    }
                )
            if len(results) >= limit:
                break
        return results

    async def get_note(self, path: str) -> str:
        """Return note content or raise if missing."""
        if path not in self.notes:
            raise FileNotFoundError(path)
        return self.notes[path]

    async def create_note(self, path: str, content: str) -> dict[str, str]:
        """Create a note in memory."""
        self.notes[path] = content
        return {"path": path}

    async def append_to_note(self, path: str, content: str) -> dict[str, str]:
        """Append content to an existing note."""
        if path not in self.notes:
            raise FileNotFoundError(path)
        self.notes[path] = self.notes[path] + content
        return {"path": path}
