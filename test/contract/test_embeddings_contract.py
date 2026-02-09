"""Contract tests for embedding HTTP calls."""

from __future__ import annotations

import json

import pytest
import respx

from config import settings
from indexer import embed_text
from services import vector_search


def test_vector_search_embed_query_contract(monkeypatch) -> None:
    """Embed query posts to the embeddings endpoint with expected payload."""
    monkeypatch.setattr(settings.llm, "embed_base_url", "http://embeddings.test", raising=False)
    monkeypatch.setattr(settings.llm, "embed_model", "mxbai-embed-large", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://embeddings.test/api/embeddings").respond(
            200, json={"embedding": [0.1, 0.2]}
        )

        embedding = vector_search._embed_query("hello")

    assert embedding == [0.1, 0.2]
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode("utf-8"))
    assert payload == {"model": "mxbai-embed-large", "prompt": "hello"}


def test_indexer_embed_text_contract(monkeypatch) -> None:
    """Indexer embed_text posts to the embeddings endpoint via HTTP wrapper."""
    monkeypatch.setattr(settings.llm, "embed_base_url", "http://embeddings.test", raising=False)
    monkeypatch.setattr(settings.llm, "embed_model", "mxbai-embed-large", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://embeddings.test/api/embeddings").respond(
            200, json={"embedding": [0.9]}
        )

        embedding = embed_text("hello", "mxbai-embed-large")

    assert embedding == [0.9]
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode("utf-8"))
    assert payload == {"model": "mxbai-embed-large", "prompt": "hello"}


def test_indexer_embed_text_raises_on_missing_embedding(monkeypatch) -> None:
    """Indexer embed_text raises when the embeddings response is missing."""
    monkeypatch.setattr(settings.llm, "embed_base_url", "http://embeddings.test", raising=False)

    with respx.mock(assert_all_called=True) as router:
        router.post("http://embeddings.test/api/embeddings").respond(200, json={"unexpected": []})

        with pytest.raises(ValueError, match="missing 'embedding'"):
            embed_text("hello", "mxbai-embed-large")
