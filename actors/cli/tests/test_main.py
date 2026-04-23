"""CLI tests for phase-1 Brain Typer commands."""

from __future__ import annotations

import importlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from typing import Any

from typer.testing import CliRunner


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _normalized_help_text(text: str) -> str:
    """Return help output normalized for stable assertions across Typer versions."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _install_fake_sdk(monkeypatch: Any) -> ModuleType:
    """Install a fake `lib.sdk` module for CLI tests."""

    module = ModuleType("lib.sdk")
    module.calls = []

    class DomainError(Exception):
        """Fake domain-level typed error."""

    class TransportError(Exception):
        """Fake transport-level typed error."""

    class BrainSdkClient:
        """Fake SDK client recording constructor inputs."""

        def __init__(
            self,
            host: str,
            port: int,
            timeout: float,
            source: str = "cli",
            principal: str = "operator",
        ) -> None:
            self.host = host
            self.port = port
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
                client.host,
                client.port,
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

    def describe_capabilities(
        *,
        client: BrainSdkClient,
        principal: str,
        source: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        module.calls.append(
            (
                "describe_capabilities",
                client.host,
                client.port,
                principal,
                source,
                trace_id,
                parent_id,
            )
        )
        return (
            {
                "capability_id": "vault-get-file",
                "summary": "Read one vault file.",
                "simple_output_path": ".content",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "include_metadata": {"type": "boolean"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "capability_id": "podcast-update",
                "summary": "Update one podcast record.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "feed_url": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["feed_url"],
                },
            },
        )

    def describe_capability(
        *,
        client: BrainSdkClient,
        capability_id: str,
        principal: str,
        source: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        module.calls.append(
            (
                "describe_capability",
                client.host,
                client.port,
                capability_id,
                principal,
                source,
                trace_id,
                parent_id,
            )
        )
        return next(
            item
            for item in describe_capabilities(
                client=client,
                principal=principal,
                source=source,
                trace_id=trace_id,
                parent_id=parent_id,
            )
            if item["capability_id"] == capability_id
        )

    class CapabilityInvokeResult:
        """Fake invoke result carrying a decoded output payload."""

        def __init__(self, output: Any) -> None:
            self.output = output

    def invoke_capability(
        *,
        client: BrainSdkClient,
        capability_id: str,
        input_payload: dict[str, Any] | None = None,
        actor: str = "",
        channel: str = "",
        principal: str = "",
        source: str = "",
        trace_id: str | None = None,
        parent_id: str | None = None,
        **_: Any,
    ) -> CapabilityInvokeResult:
        module.calls.append(
            (
                "invoke_capability",
                client.host,
                client.port,
                capability_id,
                input_payload,
                actor,
                channel,
                principal,
                source,
                trace_id,
                parent_id,
            )
        )
        output = {
            "capability_id": capability_id,
            "input_payload": input_payload or {},
        }
        if capability_id == "vault-get-file":
            output["content"] = "file body"
        return CapabilityInvokeResult(output)

    module.BrainSdkClient = BrainSdkClient
    module.DomainError = DomainError
    module.TransportError = TransportError
    module.core_health = core_health
    module.describe_capabilities = describe_capabilities
    module.describe_capability = describe_capability
    module.invoke_capability = invoke_capability

    config_module = ModuleType("lib.sdk.config")
    config_module.resolve_timeout_seconds = lambda value=None: (
        10.0 if value is None else value
    )

    monkeypatch.setitem(sys.modules, "lib.sdk", module)
    monkeypatch.setitem(sys.modules, "lib.sdk.config", config_module)
    return module


def _load_cli_app(monkeypatch: Any) -> tuple[Any, ModuleType, Any]:
    """Load CLI app with fake SDK module installed."""

    sdk_module = _install_fake_sdk(monkeypatch)
    if "actors.cli.main" in sys.modules:
        del sys.modules["actors.cli.main"]
    cli_module = importlib.import_module("actors.cli.main")
    cli_module = importlib.reload(cli_module)
    monkeypatch.setattr(
        cli_module,
        "load_actor_settings",
        lambda: SimpleNamespace(
            core=SimpleNamespace(host="127.0.0.1", port=8898, timeout_seconds=1.5),
            cli=SimpleNamespace(principal="operator", source="cli"),
        ),
    )
    sdk_module.calls.clear()
    return cli_module.build_app(), sdk_module, cli_module


def _base_args() -> list[str]:
    """Return required global flag arguments."""

    return [
        "--host",
        "127.0.0.1",
        "--port",
        "8898",
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
    assert sdk.calls[0][0] == "describe_capabilities"
    assert sdk.calls[1][0] == "core_health"


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

    monkeypatch.setattr(cli_module, "core_health", fail_transport)
    result = runner.invoke(app, [*_base_args(), "health", "core"])

    assert result.exit_code == 4
    assert "transport failed" in result.stderr


def test_typer_usage_errors_are_unchanged(monkeypatch: Any) -> None:
    """Typer validation/usage behavior should remain default."""

    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "health"])

    assert result.exit_code == 2
    assert "No such command" in result.stderr or "Missing command" in result.stderr


def test_capability_command_path_splits_first_hyphen(monkeypatch: Any) -> None:
    """Capability ids map to CLI command groups by first-hyphen split."""
    _, _, cli_module = _load_cli_app(monkeypatch)

    assert cli_module._capability_command_path("vault-get-file") == (
        "vault",
        "get-file",
    )
    assert cli_module._capability_command_path("podcast-update") == (
        "podcast",
        "update",
    )


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
    assert m._humanize_component_name("adapter_llm") == "Llm"
    assert m._humanize_component_name("plain_name") == "Plain Name"


# ---------------------------------------------------------------------------
# Additional command coverage via CliRunner
# ---------------------------------------------------------------------------


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


def test_capability_list_shows_command_paths(monkeypatch: Any) -> None:
    """Capability list should expose the resolved CLI command form."""
    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "capability", "list"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["command"] == "vault get-file"
    assert payload[1]["command"] == "podcast update"


def test_capability_describe_calls_sdk(monkeypatch: Any) -> None:
    """Capability describe should call the CES SDK describe wrapper."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [*_base_args(), "--json", "capability", "describe", "vault-get-file"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["capability_id"] == "vault-get-file"
    call = next(c for c in sdk.calls if c[0] == "describe_capability")
    assert call[3] == "vault-get-file"


def test_service_command_invokes_capability_with_parsed_flags(monkeypatch: Any) -> None:
    """Known service command should resolve and invoke the matching capability."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            *_base_args(),
            "--json",
            "vault",
            "get-file",
            "--file-path",
            "notes/today.md",
            "--include-metadata",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["capability_id"] == "vault-get-file"
    assert payload["input_payload"] == {
        "file_path": "notes/today.md",
        "include_metadata": True,
    }
    call = next(c for c in sdk.calls if c[0] == "invoke_capability")
    assert call[3] == "vault-get-file"
    assert call[4] == {
        "file_path": "notes/today.md",
        "include_metadata": True,
    }


def test_generated_help_lists_live_capability_commands(monkeypatch: Any) -> None:
    """Service-group help should list commands discovered from the live catalog."""
    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "vault", "--help"])

    assert result.exit_code == 0
    assert "Capability Metadata: live Core connection" in result.stdout
    assert "get-file" in result.stdout


def test_generated_help_lists_command_options(monkeypatch: Any) -> None:
    """Capability-command help should expose generated options despite style changes."""
    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "vault", "get-file", "--help"])
    help_text = _normalized_help_text(result.stdout)

    assert result.exit_code == 0
    assert "--file-path" in help_text
    assert "--include-metadata" in help_text


def test_json_pretty_outputs_indented_json(monkeypatch: Any) -> None:
    """`--json-pretty` should emit indented JSON output."""
    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            *_base_args(),
            "--json-pretty",
            "vault",
            "get-file",
            "--file-path",
            "notes/today.md",
        ],
    )

    assert result.exit_code == 0
    assert '"capability_id": "vault-get-file"' in result.stdout
    assert "\n  " in result.stdout


def test_simple_output_uses_configured_projection(monkeypatch: Any) -> None:
    """`--simple` should emit the configured simple projection only."""
    app, _, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            *_base_args(),
            "--simple",
            "vault",
            "get-file",
            "--file-path",
            "notes/today.md",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "file body"


def test_capability_invoke_supports_unknown_prefix_capability(monkeypatch: Any) -> None:
    """Unknown prefixes stay on the generic invoke path instead of being split."""
    app, sdk, _ = _load_cli_app(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            *_base_args(),
            "--json",
            "capability",
            "invoke",
            "podcast-update",
            "--feed-url",
            "https://example.com/feed.xml",
            "--limit",
            "3",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["capability_id"] == "podcast-update"
    assert payload["input_payload"] == {
        "feed_url": "https://example.com/feed.xml",
        "limit": 3,
    }
    call = next(c for c in sdk.calls if c[0] == "invoke_capability")
    assert call[3] == "podcast-update"


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
    assert call[6] == "trace-abc"
    assert call[7] == "parent-xyz"


def test_startup_capabilities_cached_on_context(monkeypatch: Any) -> None:
    """CLI startup should cache the published CES capability list on config."""
    _, _, cli_module = _load_cli_app(monkeypatch)
    cfg = cli_module.CliConfig(
        host="127.0.0.1",
        port=8898,
        principal="operator",
        source="cli",
        timeout=1.5,
        as_json=False,
        trace_id=None,
        parent_id=None,
        capabilities=(),
    )

    capabilities = cli_module._load_capabilities(cfg)

    assert len(capabilities) == 2
    assert capabilities[0]["capability_id"] == "vault-get-file"


def test_build_app_uses_cached_catalog_when_core_unavailable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Cached catalog should back generated help when live Core is unavailable."""
    _, sdk_module, cli_module = _load_cli_app(monkeypatch)
    cli_module._write_capability_cache(
        tmp_path / "cli-capabilities.json",
        capabilities=(
            {
                "capability_id": "vault-list-directory",
                "summary": "List directory entries.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory_path": {
                            "type": "string",
                            "description": "Vault-relative directory path.",
                        }
                    },
                    "required": ["directory_path"],
                },
            },
        ),
    )

    def fail_transport(*, client: Any, **_: Any) -> Any:
        raise sdk_module.TransportError("core down")

    monkeypatch.setattr(cli_module, "describe_capabilities", fail_transport)
    app = cli_module.build_app(tmp_path / "cli-capabilities.json")
    runner = CliRunner()

    result = runner.invoke(app, [*_base_args(), "vault", "--help"])

    assert result.exit_code == 0
    assert "Capability Metadata: cached catalog" in result.stdout
    assert "list-directory" in result.stdout
