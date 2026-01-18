"""Contract tests for the Obsidian REST client."""

from __future__ import annotations

import pytest
import respx

from config import settings
from tools.obsidian import ObsidianClient


@pytest.mark.asyncio
async def test_search_sends_query_params(monkeypatch) -> None:
    """Search sends the expected query parameters and auth headers."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    monkeypatch.setattr(settings.obsidian, "api_key", "secret", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://obsidian.test/search/simple/").respond(
            200, json=[{"path": "note.md"}]
        )

        client = ObsidianClient()
        data = await client.search("hello", limit=5)

    assert data == [{"path": "note.md"}]
    assert route.called
    request = route.calls[0].request
    assert request.url.params.get("query") == "hello"
    assert request.headers["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_get_note_uses_vault_path(monkeypatch) -> None:
    """Get note targets the vault path and returns raw text."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    monkeypatch.setattr(settings.obsidian, "api_key", "secret", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://obsidian.test/vault/Notes/hello.md").respond(
            200, text="hello world"
        )

        client = ObsidianClient()
        content = await client.get_note("Notes/hello.md")

    assert content == "hello world"
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_get_note_404_raises(monkeypatch) -> None:
    """Get note raises FileNotFoundError on a 404 response."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    monkeypatch.setattr(settings.obsidian, "api_key", "secret", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://obsidian.test/vault/Notes/missing.md").respond(404, text="nope")

        client = ObsidianClient()
        with pytest.raises(FileNotFoundError, match="Note not found"):
            await client.get_note("Notes/missing.md")

    assert route.called


@pytest.mark.asyncio
async def test_create_note_uses_markdown_content_type(monkeypatch) -> None:
    """Create note sends markdown content and normalizes file extension."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    monkeypatch.setattr(settings.obsidian, "api_key", "secret", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.put("http://obsidian.test/vault/Notes/hello.md").respond(
            200, json={"ok": True}
        )

        client = ObsidianClient()
        await client.create_note("Notes/hello", "# Hello")

    assert route.called
    request = route.calls[0].request
    assert request.headers["Content-Type"] == "text/markdown"
    assert request.content == b"# Hello"


@pytest.mark.asyncio
async def test_append_note_uses_markdown_content_type(monkeypatch) -> None:
    """Append note posts markdown content to the note path."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    monkeypatch.setattr(settings.obsidian, "api_key", "secret", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://obsidian.test/vault/Notes/hello.md").respond(
            200, json={"ok": True}
        )

        client = ObsidianClient()
        await client.append_to_note("Notes/hello.md", "more")

    assert route.called
    request = route.calls[0].request
    assert request.headers["Content-Type"] == "text/markdown"
    assert request.content == b"more"


@pytest.mark.asyncio
async def test_list_dir_targets_directory(monkeypatch) -> None:
    """List dir uses the normalized vault directory path."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    monkeypatch.setattr(settings.obsidian, "api_key", "secret", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://obsidian.test/vault/Notes/").respond(200, json=["A.md", "B.md"])

        client = ObsidianClient()
        entries = await client.list_dir("Notes")

    assert entries == ["A.md", "B.md"]
    assert route.called
