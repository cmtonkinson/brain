"""CLI tests for phase-1 Brain Typer commands."""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from typer.testing import CliRunner


def _install_fake_sdk(monkeypatch: Any) -> ModuleType:
    """Install a fake `packages.brain_sdk` module for CLI tests."""

    module = ModuleType("packages.brain_sdk")
    module.calls = []

    class DomainError(Exception):
        """Fake domain-level typed error."""

    class TransportError(Exception):
        """Fake transport-level typed error."""

    class BrainSdkClient:
        """Fake SDK client recording constructor inputs."""

        def __init__(
            self,
            socket: str,
            timeout: float,
            source: str = "cli",
            principal: str = "operator",
        ) -> None:
            self.socket = socket
            self.timeout = timeout
            self.source = source
            self.principal = principal

        def __enter__(self) -> BrainSdkClient:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def core_health(
        *,
        client: BrainSdkClient,
        principal: str,
        source: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        module.calls.append(
            (
                "core_health",
                client.socket,
                client.timeout,
                principal,
                source,
                trace_id,
                parent_id,
            )
        )
        return {
            "ready": False,
            "services": {
                "service_attention_router": {"ready": True, "detail": "ok"},
                "service_vault_authority": {"ready": False, "detail": "obsidian down"},
            },
            "resources": {
                "substrate_obsidian": {"ready": False, "detail": "connection refused"}
            },
        }

    def lms_chat(
        *,
        client: BrainSdkClient,
        prompt: str,
        principal: str,
        source: str,
        profile: str = "standard",
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        module.calls.append(
            (
                "lms_chat",
                client.socket,
                prompt,
                profile,
                principal,
                source,
                trace_id,
                parent_id,
            )
        )
        return {"reply": f"echo:{prompt}"}

    def vault_get(
        *,
        client: BrainSdkClient,
        file_path: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        module.calls.append(("vault_get", client.socket, file_path))
        return {"path": file_path, "content": "hello"}

    def vault_list(
        *,
        client: BrainSdkClient,
        directory_path: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> list[str]:
        module.calls.append(("vault_list", client.socket, directory_path))
        return ["a.md", "b.md"]

    def vault_search(
        *,
        client: BrainSdkClient,
        query: str,
        directory_scope: str = "",
        limit: int = 20,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        module.calls.append(
            ("vault_search", client.socket, query, directory_scope, limit)
        )
        return [{"path": "notes/a.md", "score": 0.9}]

    module.BrainSdkClient = BrainSdkClient
    module.DomainError = DomainError
    module.TransportError = TransportError
    module.core_health = core_health
    module.lms_chat = lms_chat
    module.vault_get = vault_get
    module.vault_list = vault_list
    module.vault_search = vault_search

    config_module = ModuleType("packages.brain_sdk.config")
    config_module.resolve_timeout_seconds = lambda value=None: (
        10.0 if value is None else value
    )

    monkeypatch.setitem(sys.modules, "packages.brain_sdk", module)
    monkeypatch.setitem(sys.modules, "packages.brain_sdk.config", config_module)
    return module


def _load_cli_app(monkeypatch: Any) -> tuple[Any, ModuleType, Any]:
    """Load CLI app with fake SDK module installed."""

    sdk_module = _install_fake_sdk(monkeypatch)
    if "actors.cli.main" in sys.modules:
        del sys.modules["actors.cli.main"]
    cli_module = importlib.import_module("actors.cli.main")
    cli_module = importlib.reload(cli_module)
    return cli_module.app, sdk_module, cli_module


def _base_args() -> list[str]:
    """Return required global flag arguments."""

    return [
        "--socket",
        "/tmp/brain.sock",
        "--timeout",
        "1.5",
    ]


# ---------------------------------------------------------------------------
# Original command-dispatch tests
# ---------------------------------------------------------------------------


def test_cli_parses_domain_action_and_executes(monkeypatch: Any) -> None:
    """Command shape `brain <domain> <action>` should execute successfully."""

    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "health", "core"])

    assert result.exit_code == 0
    assert "Services:" in result.stdout
    assert "Attention Router: ✅ healthy" in result.stdout
    assert "Vault Authority: ⚠️ degraded" in result.stdout
    assert "Resources:" in result.stdout
    assert sdk.calls[0][0] == "core_health"


def test_cli_human_output_for_success(monkeypatch: Any) -> None:
    """Successful non-JSON output should be human readable."""

    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "vault", "get", "notes/today.md"])

    assert result.exit_code == 0
    assert "notes/today.md" in result.stdout
    assert "hello" in result.stdout


def test_cli_json_output_for_success(monkeypatch: Any) -> None:
    """`--json` should emit compact JSON output."""

    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "--json", "lms", "chat", "hello"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"reply": "echo:hello"}


def test_domain_error_maps_to_exit_code_3(monkeypatch: Any) -> None:
    """Domain errors should map to exit code 3."""

    app, sdk, cli_module = _load_cli_app(monkeypatch)
    runner = CliRunner()

    def fail_domain(*, client: Any, **_: Any) -> Any:
        raise sdk.DomainError("domain failed")

    monkeypatch.setattr(cli_module, "core_health", fail_domain)
    result = runner.invoke(app, [*_base_args(), "health", "core"])

    assert result.exit_code == 3
    assert "domain failed" in result.stderr


def test_transport_error_maps_to_exit_code_4(monkeypatch: Any) -> None:
    """Transport/dependency errors should map to exit code 4."""

    app, sdk, cli_module = _load_cli_app(monkeypatch)
    runner = CliRunner()

    def fail_transport(*, client: Any, **_: Any) -> Any:
        raise sdk.TransportError("transport failed")

    monkeypatch.setattr(cli_module, "vault_search", fail_transport)
    result = runner.invoke(app, [*_base_args(), "vault", "search", "topic"])

    assert result.exit_code == 4
    assert "transport failed" in result.stderr


def test_typer_usage_errors_are_unchanged(monkeypatch: Any) -> None:
    """Typer validation/usage behavior should remain default."""

    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "vault", "get"])

    assert result.exit_code == 2
    assert "Missing argument" in result.stderr


# ---------------------------------------------------------------------------
# _serialize — pure unit tests
# ---------------------------------------------------------------------------


def _get_serialize(monkeypatch: Any) -> Any:
    """Return the _serialize function from the CLI module."""
    _, _, cli_module = _load_cli_app(monkeypatch)
    return cli_module._serialize


def test_serialize_primitives(monkeypatch: Any) -> None:
    """None, bool, int, float, str pass through unchanged."""
    serialize = _get_serialize(monkeypatch)
    assert serialize(None) is None
    assert serialize(True) is True
    assert serialize(42) == 42
    assert serialize(3.14) == 3.14
    assert serialize("hello") == "hello"


def test_serialize_datetime_and_decimal(monkeypatch: Any) -> None:
    """datetime, date, Decimal, and Path are converted to strings."""
    serialize = _get_serialize(monkeypatch)
    dt = datetime(2024, 1, 15, 12, 0, 0)
    d = date(2024, 1, 15)
    dec = Decimal("3.14")
    p = Path("/tmp/file.txt")
    assert serialize(dt) == str(dt)
    assert serialize(d) == str(d)
    assert serialize(dec) == str(dec)
    assert serialize(p) == str(p)


def test_serialize_dataclass(monkeypatch: Any) -> None:
    """Dataclass instances are serialized to dicts recursively."""
    serialize = _get_serialize(monkeypatch)

    @dataclass
    class Inner:
        value: int

    @dataclass
    class Outer:
        name: str
        inner: Inner

    result = serialize(Outer(name="x", inner=Inner(value=7)))
    assert result == {"name": "x", "inner": {"value": 7}}


def test_serialize_pydantic_model(monkeypatch: Any) -> None:
    """Objects with model_dump() are serialized via that method."""
    serialize = _get_serialize(monkeypatch)

    class FakeModel:
        def model_dump(self, mode: str = "python") -> dict[str, Any]:
            return {"key": "val", "num": 1}

    result = serialize(FakeModel())
    assert result == {"key": "val", "num": 1}


# ---------------------------------------------------------------------------
# Rendering helpers — pure unit tests
# ---------------------------------------------------------------------------


def _get_render_helpers(monkeypatch: Any) -> Any:
    """Return a namespace with all rendering helpers from the CLI module."""
    _, _, cli_module = _load_cli_app(monkeypatch)
    return cli_module


def test_render_core_health_healthy(monkeypatch: Any) -> None:
    """All-ready payload produces healthy icons and labels."""
    m = _get_render_helpers(monkeypatch)
    data = {
        "ready": True,
        "services": {"service_lms": {"ready": True, "detail": "ok"}},
        "resources": {"substrate_db": {"ready": True, "detail": "ok"}},
    }
    output = m._render_core_health(data)
    assert "✅" in output
    assert "healthy" in output
    assert "⚠️" not in output


def test_render_core_health_degraded(monkeypatch: Any) -> None:
    """Mixed-ready payload produces degraded label with detail."""
    m = _get_render_helpers(monkeypatch)
    data = {
        "ready": False,
        "services": {"service_lms": {"ready": False, "detail": "model unavailable"}},
        "resources": {},
    }
    output = m._render_core_health(data)
    assert "⚠️" in output
    assert "degraded" in output
    assert "model unavailable" in output


def test_humanize_component_name(monkeypatch: Any) -> None:
    """Prefixes are stripped and names are title-cased."""
    m = _get_render_helpers(monkeypatch)
    assert m._humanize_component_name("service_attention_router") == "Attention Router"
    assert m._humanize_component_name("resource_vault") == "Vault"
    assert m._humanize_component_name("substrate_obsidian") == "Obsidian"
    assert m._humanize_component_name("adapter_litellm") == "Litellm"
    assert m._humanize_component_name("plain_name") == "Plain Name"


def test_render_lms_chat_with_provider(monkeypatch: Any) -> None:
    """Provider and model are appended in brackets."""
    m = _get_render_helpers(monkeypatch)
    data = {"text": "Hello!", "provider": "openai", "model": "gpt-4"}
    output = m._render_lms_chat(data)
    assert "Hello!" in output
    assert "[openai:gpt-4]" in output


def test_render_lms_chat_text_only(monkeypatch: Any) -> None:
    """No provider/model bracket when both are absent."""
    m = _get_render_helpers(monkeypatch)
    data = {"reply": "Just a reply"}
    output = m._render_lms_chat(data)
    assert "Just a reply" in output
    assert "[" not in output


def test_render_vault_file(monkeypatch: Any) -> None:
    """Path heading and content are both present in output."""
    m = _get_render_helpers(monkeypatch)
    data = {"path": "notes/ideas.md", "content": "Some content here."}
    output = m._render_vault_file(data)
    assert "File: notes/ideas.md" in output
    assert "Some content here." in output


def test_render_vault_list_empty(monkeypatch: Any) -> None:
    """Empty list renders 'No entries found.'"""
    m = _get_render_helpers(monkeypatch)
    assert m._render_vault_list([]) == "No entries found."


def test_render_vault_list_items(monkeypatch: Any) -> None:
    """String items are prefixed with dashes."""
    m = _get_render_helpers(monkeypatch)
    output = m._render_vault_list(["a.md", "b.md"])
    assert "- a.md" in output
    assert "- b.md" in output


def test_render_vault_search_empty(monkeypatch: Any) -> None:
    """Empty list renders 'No matches found.'"""
    m = _get_render_helpers(monkeypatch)
    assert m._render_vault_search([]) == "No matches found."


def test_render_vault_search_with_score(monkeypatch: Any) -> None:
    """Score is formatted to 3 decimal places."""
    m = _get_render_helpers(monkeypatch)
    items = [{"path": "notes/a.md", "score": 0.9123456}]
    output = m._render_vault_search(items)
    assert "notes/a.md" in output
    assert "0.912" in output


# ---------------------------------------------------------------------------
# Additional command coverage via CliRunner
# ---------------------------------------------------------------------------


def test_lms_chat_with_profile_option(monkeypatch: Any) -> None:
    """`--profile deep` is propagated to the SDK call."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app, [*_base_args(), "lms", "chat", "--profile", "deep", "my question"]
    )

    assert result.exit_code == 0
    call = next(c for c in sdk.calls if c[0] == "lms_chat")
    assert call[3] == "deep"


def test_vault_list_with_path(monkeypatch: Any) -> None:
    """Non-empty directory_path argument is forwarded to the SDK."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "vault", "list", "notes/"])

    assert result.exit_code == 0
    call = next(c for c in sdk.calls if c[0] == "vault_list")
    assert call[2] == "notes/"


def test_vault_search_with_scope_and_limit(monkeypatch: Any) -> None:
    """`--directory-scope` and `--limit` are forwarded to the SDK."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            *_base_args(),
            "vault",
            "search",
            "--directory-scope",
            "notes/",
            "--limit",
            "5",
            "query text",
        ],
    )

    assert result.exit_code == 0
    call = next(c for c in sdk.calls if c[0] == "vault_search")
    assert call[3] == "notes/"
    assert call[4] == 5


def test_json_output_for_domain_error(monkeypatch: Any) -> None:
    """`--json` flag produces JSON-wrapped error on stderr."""
    app, sdk, cli_module = _load_cli_app(monkeypatch)
    runner = CliRunner()

    def fail_domain(*, client: Any, **_: Any) -> Any:
        raise sdk.DomainError("json domain error")

    monkeypatch.setattr(cli_module, "core_health", fail_domain)
    result = runner.invoke(app, [*_base_args(), "--json", "health", "core"])

    assert result.exit_code == 3
    error_payload = json.loads(result.stderr)
    assert error_payload["error"] == "json domain error"


def test_trace_and_parent_ids_propagated(monkeypatch: Any) -> None:
    """`--trace-id` and `--parent-id` are forwarded to the SDK call."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            *_base_args(),
            "--trace-id",
            "trace-abc",
            "--parent-id",
            "parent-xyz",
            "health",
            "core",
        ],
    )

    assert result.exit_code == 0
    call = next(c for c in sdk.calls if c[0] == "core_health")
    assert call[5] == "trace-abc"
    assert call[6] == "parent-xyz"


def test_vault_list_empty_result_human(monkeypatch: Any) -> None:
    """Empty vault list falls through _looks_like_vault_search and renders 'No matches found.'"""
    app, sdk, cli_module = _load_cli_app(monkeypatch)
    runner = CliRunner()

    def empty_vault_list(*, client: Any, **_: Any) -> list[Any]:
        sdk.calls.append(("vault_list", client.socket, ""))
        return []

    monkeypatch.setattr(cli_module, "vault_list", empty_vault_list)
    result = runner.invoke(app, [*_base_args(), "vault", "list"])

    assert result.exit_code == 0
    # Empty list satisfies _looks_like_vault_search (checked first), so renders
    # "No matches found." rather than "No entries found."
    assert "No matches found." in result.stdout


def test_vault_search_empty_result_human(monkeypatch: Any) -> None:
    """Empty vault search renders 'No matches found.' in human mode."""
    app, sdk, cli_module = _load_cli_app(monkeypatch)
    runner = CliRunner()

    def empty_vault_search(*, client: Any, **_: Any) -> list[Any]:
        sdk.calls.append(("vault_search", client.socket, ""))
        return []

    monkeypatch.setattr(cli_module, "vault_search", empty_vault_search)
    result = runner.invoke(app, [*_base_args(), "vault", "search", "nothing"])

    assert result.exit_code == 0
    assert "No matches found." in result.stdout
