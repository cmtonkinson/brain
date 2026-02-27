"""Phase-1 Brain CLI actor implemented with Typer."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import typer
from packages.brain_sdk import (
    BrainSdkClient,
    DomainError,
    TransportError,
    core_health,
    lms_chat,
    vault_get,
    vault_list,
    vault_search,
)
from packages.brain_sdk.config import resolve_timeout_seconds

_DEFAULT_HOST_SOCKET_PATH = str(
    Path.home() / ".config" / "brain" / "generated" / "brain.sock"
)

SUCCESS_EXIT_CODE = 0
DOMAIN_ERROR_EXIT_CODE = 3
TRANSPORT_ERROR_EXIT_CODE = 4


class ReasoningProfile(str, Enum):
    """Supported LMS reasoning profiles for chat."""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True)
class CliConfig:
    """Global CLI runtime options propagated to SDK calls."""

    socket: str
    principal: str
    source: str
    timeout: float
    as_json: bool
    trace_id: str | None
    parent_id: str | None


def _serialize(value: Any) -> Any:
    """Convert result objects to JSON-serializable structures."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, Decimal, Path)):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _serialize(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    if hasattr(value, "model_dump"):
        return _serialize(value.model_dump(mode="python"))
    if hasattr(value, "dict"):
        return _serialize(value.dict())
    if hasattr(value, "__dict__"):
        return _serialize(
            {k: v for k, v in vars(value).items() if not k.startswith("_")}
        )
    return str(value)


def _emit_output(result: Any, as_json: bool) -> None:
    """Render command output in requested format."""

    data = _serialize(result)
    if as_json:
        typer.echo(json.dumps(data, sort_keys=True, separators=(",", ":")))
        return
    rendered = _render_human(data)
    if rendered is not None:
        typer.echo(rendered)
        return
    if data is None:
        typer.echo("ok")
        return
    typer.echo(str(data))


def _emit_error(exc: Exception, as_json: bool) -> None:
    """Render mapped SDK errors to stderr."""

    if as_json:
        typer.echo(json.dumps({"error": str(exc)}), err=True)
        return
    typer.echo(f"error: {exc}", err=True)


def _render_human(data: Any) -> str | None:
    """Return human-oriented rendering for recognized response shapes."""
    if isinstance(data, dict):
        if _looks_like_core_health(data):
            return _render_core_health(data)
        if _looks_like_lms_chat(data):
            return _render_lms_chat(data)
        if _looks_like_vault_file(data):
            return _render_vault_file(data)
    if isinstance(data, list):
        if _looks_like_vault_search(data):
            return _render_vault_search(data)
        if _looks_like_vault_list(data):
            return _render_vault_list(data)
    if isinstance(data, (dict, list)):
        return json.dumps(data, indent=2, sort_keys=True)
    return None


def _looks_like_core_health(value: dict[str, Any]) -> bool:
    """Return True for core health payloads."""
    return (
        isinstance(value.get("ready"), bool)
        and isinstance(value.get("services"), dict)
        and isinstance(value.get("resources"), dict)
    )


def _looks_like_lms_chat(value: dict[str, Any]) -> bool:
    """Return True for LMS chat payloads."""
    return "text" in value or "reply" in value


def _looks_like_vault_file(value: dict[str, Any]) -> bool:
    """Return True for vault get payloads."""
    return "path" in value and "content" in value


def _looks_like_vault_search(items: list[Any]) -> bool:
    """Return True for vault search payloads."""
    return len(items) == 0 or all(
        isinstance(item, dict) and "path" in item and "score" in item for item in items
    )


def _looks_like_vault_list(items: list[Any]) -> bool:
    """Return True for vault list payloads."""
    return len(items) == 0 or all(
        isinstance(item, (str, dict)) and not isinstance(item, bool) for item in items
    )


def _render_core_health(data: dict[str, Any]) -> str:
    """Render core health data for human scanning."""
    ready = bool(data.get("ready", False))
    lines = [f"Core: {_status_icon(ready)} {_status_label(ready)}"]
    lines.append(
        f"Services: {_status_icon(_all_ready(data.get('services', {})))} "
        f"{_status_label(_all_ready(data.get('services', {})))}"
    )
    lines.extend(_render_component_group(data.get("services", {}), indent=2))
    lines.append(
        f"Resources: {_status_icon(_all_ready(data.get('resources', {})))} "
        f"{_status_label(_all_ready(data.get('resources', {})))}"
    )
    lines.extend(_render_component_group(data.get("resources", {}), indent=2))
    return "\n".join(lines)


def _render_component_group(components: dict[str, Any], indent: int) -> list[str]:
    """Render one grouped list of component readiness rows."""
    lines: list[str] = []
    padding = " " * indent
    for key in sorted(components.keys()):
        value = components[key]
        ready = bool(value.get("ready", False)) if isinstance(value, dict) else False
        detail = value.get("detail", "") if isinstance(value, dict) else ""
        line = f"{padding}{_humanize_component_name(key)}: {_status_icon(ready)} {_status_label(ready)}"
        if isinstance(detail, str) and detail.strip() != "":
            line = f"{line} ({detail})"
        lines.append(line)
    return lines


def _all_ready(components: dict[str, Any]) -> bool:
    """Return True when every component readiness entry is healthy."""
    if not isinstance(components, dict):
        return False
    return all(
        bool(value.get("ready", False)) if isinstance(value, dict) else False
        for value in components.values()
    )


def _status_icon(ready: bool) -> str:
    """Return status icon for one readiness value."""
    return "✅" if ready else "⚠️"


def _status_label(ready: bool) -> str:
    """Return status label for one readiness value."""
    return "healthy" if ready else "degraded"


def _humanize_component_name(name: str) -> str:
    """Convert canonical ids into user-facing component names."""
    normalized = name.strip()
    for prefix in ("service_", "resource_", "substrate_", "adapter_"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.replace("_", " ").title()


def _render_lms_chat(data: dict[str, Any]) -> str:
    """Render LMS chat result."""
    text = str(data.get("text", data.get("reply", ""))).strip()
    provider = str(data.get("provider", "")).strip()
    model = str(data.get("model", "")).strip()
    lines = [text]
    if provider != "" or model != "":
        lines.append(f"[{provider}:{model}]".strip(":"))
    return "\n".join(line for line in lines if line != "")


def _render_vault_file(data: dict[str, Any]) -> str:
    """Render vault file payload."""
    path = str(data.get("path", "")).strip()
    content = str(data.get("content", ""))
    heading = f"File: {path}" if path != "" else "File"
    return f"{heading}\n\n{content}".rstrip()


def _render_vault_list(items: list[Any]) -> str:
    """Render vault list payload."""
    if len(items) == 0:
        return "No entries found."
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            lines.append(f"- {item}")
            continue
        if isinstance(item, dict):
            path = str(item.get("path", item.get("name", ""))).strip()
            entry_type = str(item.get("entry_type", "")).strip()
            if path == "":
                path = "<unknown>"
            if entry_type != "":
                lines.append(f"- {path} ({entry_type})")
            else:
                lines.append(f"- {path}")
    return "\n".join(lines)


def _render_vault_search(items: list[Any]) -> str:
    """Render vault search payload."""
    if len(items) == 0:
        return "No matches found."
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "<unknown>"))
        score = item.get("score")
        snippets = item.get("snippets", [])
        line = f"- {path}"
        if isinstance(score, (int, float)):
            line = f"{line} (score: {score:.3f})"
        lines.append(line)
        if isinstance(snippets, list):
            for snippet in snippets[:2]:
                lines.append(f"  {snippet}")
    return "\n".join(lines)


def _with_client(cfg: CliConfig) -> BrainSdkClient:
    """Return one SDK client built from global CLI settings."""
    return BrainSdkClient(
        socket=cfg.socket,
        timeout=cfg.timeout,
        source=cfg.source,
        principal=cfg.principal,
    )


def _run_command(cfg: CliConfig, invoke: Callable[[BrainSdkClient], Any]) -> None:
    """Execute one SDK call and map outputs/errors to process semantics."""
    try:
        with _with_client(cfg) as client:
            result = invoke(client)
    except DomainError as exc:
        _emit_error(exc, cfg.as_json)
        raise typer.Exit(code=DOMAIN_ERROR_EXIT_CODE) from exc
    except TransportError as exc:
        _emit_error(exc, cfg.as_json)
        raise typer.Exit(code=TRANSPORT_ERROR_EXIT_CODE) from exc

    _emit_output(result, cfg.as_json)
    raise typer.Exit(code=SUCCESS_EXIT_CODE)


def _require_config(ctx: typer.Context) -> CliConfig:
    """Return required CLI config from Typer context."""

    config = ctx.obj
    if not isinstance(config, CliConfig):
        raise RuntimeError("CLI configuration not initialized")
    return config


app = typer.Typer(no_args_is_help=True, help="Brain command-line interface")
health_app = typer.Typer(help="Core domain commands")
lms_app = typer.Typer(help="Language model service commands")
vault_app = typer.Typer(help="Vault authority commands")


@app.callback()
def main(
    ctx: typer.Context,
    socket: str = typer.Option(
        _DEFAULT_HOST_SOCKET_PATH,
        envvar="BRAIN_SOCKET_PATH",
        help="Brain Core Unix socket path",
    ),
    principal: str = typer.Option("operator", help="Envelope principal"),
    source: str = typer.Option("cli", help="Envelope source"),
    timeout: float = typer.Option(
        resolve_timeout_seconds(),
        min=0.001,
        help="Request timeout in seconds",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
    trace_id: str | None = typer.Option(None, help="Optional trace id"),
    parent_id: str | None = typer.Option(None, help="Optional parent envelope id"),
) -> None:
    """Store global options for all domain/action commands."""

    ctx.obj = CliConfig(
        socket=socket,
        principal=principal,
        source=source,
        timeout=timeout,
        as_json=as_json,
        trace_id=trace_id,
        parent_id=parent_id,
    )


@health_app.command("core")
def health_core(ctx: typer.Context) -> None:
    """Call core health."""
    cfg = _require_config(ctx)
    _run_command(
        cfg,
        lambda client: core_health(
            client=client,
            source=cfg.source,
            principal=cfg.principal,
            trace_id=cfg.trace_id,
            parent_id=cfg.parent_id,
        ),
    )


@lms_app.command("chat")
def lms_chat_command(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Chat prompt"),
    profile: ReasoningProfile = typer.Option(
        ReasoningProfile.STANDARD,
        help="Reasoning profile",
        case_sensitive=False,
        show_choices=True,
    ),
) -> None:
    """Call LMS chat."""
    cfg = _require_config(ctx)
    _run_command(
        cfg,
        lambda client: lms_chat(
            client=client,
            prompt=prompt,
            profile=profile.value,
            source=cfg.source,
            principal=cfg.principal,
            trace_id=cfg.trace_id,
            parent_id=cfg.parent_id,
        ),
    )


@vault_app.command("get")
def vault_get_command(
    ctx: typer.Context, path: str = typer.Argument(..., help="Vault file path")
) -> None:
    """Call vault get."""
    cfg = _require_config(ctx)
    _run_command(
        cfg,
        lambda client: vault_get(
            client=client,
            file_path=path,
            trace_id=cfg.trace_id,
            parent_id=cfg.parent_id,
        ),
    )


@vault_app.command("list")
def vault_list_command(
    ctx: typer.Context,
    path: str = typer.Argument("", help="Vault directory path"),
) -> None:
    """Call vault list."""
    cfg = _require_config(ctx)
    _run_command(
        cfg,
        lambda client: vault_list(
            client=client,
            directory_path=path,
            trace_id=cfg.trace_id,
            parent_id=cfg.parent_id,
        ),
    )


@vault_app.command("search")
def vault_search_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Vault search query"),
    directory_scope: str = typer.Option("", help="Optional directory scope"),
    limit: int = typer.Option(20, min=1, help="Maximum number of search results"),
) -> None:
    """Call vault search."""
    cfg = _require_config(ctx)
    _run_command(
        cfg,
        lambda client: vault_search(
            client=client,
            query=query,
            directory_scope=directory_scope,
            limit=limit,
            trace_id=cfg.trace_id,
            parent_id=cfg.parent_id,
        ),
    )


app.add_typer(health_app, name="health")
app.add_typer(lms_app, name="lms")
app.add_typer(vault_app, name="vault")


if __name__ == "__main__":
    app()
