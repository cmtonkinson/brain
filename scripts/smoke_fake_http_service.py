"""Tiny internal-only fake HTTP services for Docker smoke tests."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from aiohttp import web


class _StateStore:
    """Persist small fake-service captures to one mounted state directory."""

    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def append(self, *, name: str, value: object) -> None:
        """Append one JSON-serializable record to the named capture file."""
        async with self._lock:
            values = self.read(name=name)
            values.append(value)
            self._write(name=name, values=values)

    def read(self, *, name: str) -> list[object]:
        """Read one named capture file, returning an empty list when absent."""
        path = self._path(name=name)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        return payload

    async def pop_all(self, *, name: str) -> list[object]:
        """Atomically drain one named capture file and return its prior contents."""
        async with self._lock:
            values = self.read(name=name)
            self._write(name=name, values=[])
            return values

    def _write(self, *, name: str, values: list[object]) -> None:
        """Atomically replace one named capture file with the provided array."""
        path = self._path(name=name)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(values, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _path(self, *, name: str) -> Path:
        """Resolve one capture file path under the configured root directory."""
        return self._root / f"{name}.json"


async def _signal_health(_request: web.Request) -> web.Response:
    """Return a minimal ready response for Signal health checks."""
    return web.json_response({"status": "ok"})


async def _signal_send(request: web.Request) -> web.Response:
    """Capture one outbound send payload and acknowledge it."""
    store: _StateStore = request.app["state_store"]
    payload = await request.json()
    await store.append(name="sent_messages", value=payload)
    return web.json_response({"ok": True, "timestamp": 1730000000000})


async def _signal_receive(request: web.Request) -> web.StreamResponse:
    """Accept and hold a websocket receive session open, emitting queued payloads."""
    store: _StateStore = request.app["state_store"]
    websocket = web.WebSocketResponse(heartbeat=30.0, autoping=True)
    await websocket.prepare(request)
    await store.append(
        name="receive_sessions",
        value={"path": request.path, "connected": True},
    )
    try:
        while True:
            queued = await store.pop_all(name="queued_receive_payloads")
            for item in queued:
                await websocket.send_json(item)
            try:
                message = await websocket.receive(timeout=0.5)
            except TimeoutError:
                continue
            if message.type in {
                web.WSMsgType.CLOSE,
                web.WSMsgType.CLOSED,
                web.WSMsgType.CLOSING,
                web.WSMsgType.ERROR,
            }:
                break
            if message.type in {web.WSMsgType.PING, web.WSMsgType.PONG}:
                continue
    finally:
        await websocket.close()
    return websocket


async def _signal_inject_receive(request: web.Request) -> web.Response:
    """Queue one inbound receive payload for the next connected websocket session."""
    store: _StateStore = request.app["state_store"]
    payload = await request.json()
    await store.append(name="queued_receive_payloads", value=payload)
    return web.json_response({"queued": True})


async def _obsidian_health(_request: web.Request) -> web.Response:
    """Return a generic health response for the fake Obsidian service."""
    return web.json_response({"ready": True})


async def _obsidian_list(_request: web.Request) -> web.Response:
    """Return an empty vault listing, enough for substrate health checks."""
    return web.json_response({"files": []})


async def _openai_health(_request: web.Request) -> web.Response:
    """Return a generic health response for the fake OpenAI service."""
    return web.json_response({"ready": True})


async def _openai_chat_completions(request: web.Request) -> web.Response:
    """Capture one chat-completions request and return a fixed final reply."""
    store: _StateStore = request.app["state_store"]
    payload = await request.json()
    await store.append(name="chat_completions", value=payload)
    return web.json_response(
        {
            "id": "chatcmpl-smoke",
            "object": "chat.completion",
            "created": 1730000000,
            "model": payload.get("model", "gpt-4o-mini"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "assistant reply",
                    },
                }
            ],
        }
    )


async def _openai_embeddings(request: web.Request) -> web.Response:
    """Capture one embeddings request and return simple deterministic vectors."""
    store: _StateStore = request.app["state_store"]
    payload = await request.json()
    await store.append(name="embeddings", value=payload)
    raw_input = payload.get("input", [])
    items = raw_input if isinstance(raw_input, list) else [raw_input]
    return web.json_response(
        {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": [float(index), 0.1, 0.2],
                }
                for index, _ in enumerate(items)
            ],
            "model": payload.get("model", "text-embedding-3-small"),
        }
    )


def _build_app(*, role: str, state_dir: Path) -> web.Application:
    """Construct the fake service app for the selected role."""
    app = web.Application()
    app["state_store"] = _StateStore(root=state_dir)

    if role == "signal":
        app.router.add_get("/v1/health", _signal_health)
        app.router.add_post("/v2/send", _signal_send)
        app.router.add_get("/v1/receive/{number}", _signal_receive)
        app.router.add_post("/testing/inject-receive", _signal_inject_receive)
        return app

    if role == "obsidian":
        app.router.add_get("/health", _obsidian_health)
        app.router.add_get("/vault/", _obsidian_list)
        app.router.add_get("/vault/{tail:.*}", _obsidian_list)
        return app

    if role == "openai":
        app.router.add_get("/health", _openai_health)
        app.router.add_post("/v1/chat/completions", _openai_chat_completions)
        app.router.add_post("/v1/embeddings", _openai_embeddings)
        return app

    raise ValueError(f"unsupported fake service role: {role}")


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for one fake smoke service process."""
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("signal", "obsidian", "openai"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Run one configured fake service until interrupted."""
    args = _parse_args()
    app = _build_app(role=args.role, state_dir=args.state_dir)
    web.run_app(app, host=args.host, port=args.port, handle_signals=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
