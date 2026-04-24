"""Integration-style tests for SeaweedFS substrate request semantics."""

from __future__ import annotations

import httpx

from resources.substrates.seaweedfs import (
    SeaweedFSBlobSubstrate,
    SeaweedFSSubstrateSettings,
)


def test_provider_request_cycle_uses_configured_endpoint_and_bucket() -> None:
    """Substrate should issue a complete object lifecycle against the provider API."""
    seen: list[tuple[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.method == "HEAD":
            return httpx.Response(404)
        return httpx.Response(200, content=b"hello")

    substrate = SeaweedFSBlobSubstrate(
        settings=SeaweedFSSubstrateSettings(
            endpoint_url="http://seaweedfs:8333",
            bucket="brain-oas",
            access_key_id="test-key",
            secret_access_key="test-secret",
        ),
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    assert substrate.write_blob(digest_hex=digest, extension="bin", content=b"hello")
    assert substrate.read_blob(digest_hex=digest, extension="bin") == b"hello"

    assert seen == [
        ("HEAD", f"http://seaweedfs:8333/brain-oas/objects/aa/aa/{digest}.bin"),
        ("PUT", f"http://seaweedfs:8333/brain-oas/objects/aa/aa/{digest}.bin"),
        ("GET", f"http://seaweedfs:8333/brain-oas/objects/aa/aa/{digest}.bin"),
    ]
