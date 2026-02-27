"""CLI tests for phase-1 Brain Typer commands."""

from __future__ import annotations

import importlib
import json
import sys
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
            grpc_target: str,
            timeout: float,
            source: str = "cli",
            principal: str = "operator",
        ) -> None:
            self.grpc_target = grpc_target
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
                client.grpc_target,
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
                client.grpc_target,
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
        module.calls.append(("vault_get", client.grpc_target, file_path))
        return {"path": file_path, "content": "hello"}

    def vault_list(
        *,
        client: BrainSdkClient,
        directory_path: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> list[str]:
        module.calls.append(("vault_list", client.grpc_target, directory_path))
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
        module.calls.append(("vault_search", client.grpc_target, query))
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
    config_module.resolve_target = lambda value=None: (
        "127.0.0.1:50051" if value is None else value
    )
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
        "--grpc-target",
        "127.0.0.1:50051",
        "--timeout",
        "1.5",
    ]


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
