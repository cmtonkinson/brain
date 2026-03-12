"""Phase-1 Brain CLI actor implemented with Typer."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import typer
from packages.brain_sdk import (
    BrainSdkClient,
    DomainError,
    TransportError,
    core_health,
    describe_capability,
    describe_capabilities,
    invoke_capability,
)
from packages.brain_shared.config import load_actor_settings

SUCCESS_EXIT_CODE = 0
DOMAIN_ERROR_EXIT_CODE = 3
TRANSPORT_ERROR_EXIT_CODE = 4
KNOWN_SERVICE_PREFIXES = frozenset(
    {
        "attention",
        "cache",
        "embedding",
        "memory",
        "object",
        "utility",
        "vault",
    }
)
_DYNAMIC_COMMAND_CONTEXT_SETTINGS = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
}


@dataclass(frozen=True)
class CliConfig:
    """Global CLI runtime options propagated to SDK calls."""

    host: str
    port: int
    principal: str
    source: str
    timeout: float
    as_json: bool
    trace_id: str | None
    parent_id: str | None
    capabilities: tuple[Any, ...]


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


def _with_client(cfg: CliConfig) -> BrainSdkClient:
    """Return one SDK client built from global CLI settings."""
    return BrainSdkClient(
        host=cfg.host,
        port=cfg.port,
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


def _load_capabilities(cfg: CliConfig) -> tuple[Any, ...]:
    """Load the published CES capability list during CLI startup."""
    try:
        with _with_client(cfg) as client:
            capabilities = describe_capabilities(
                client=client,
                source=cfg.source,
                principal=cfg.principal,
                trace_id=cfg.trace_id,
                parent_id=cfg.parent_id,
            )
    except DomainError as exc:
        _emit_error(exc, cfg.as_json)
        raise typer.Exit(code=DOMAIN_ERROR_EXIT_CODE) from exc
    except TransportError as exc:
        _emit_error(exc, cfg.as_json)
        raise typer.Exit(code=TRANSPORT_ERROR_EXIT_CODE) from exc
    return tuple(capabilities)


def _require_config(ctx: typer.Context) -> CliConfig:
    """Return required CLI config from Typer context."""

    config = ctx.obj
    if not isinstance(config, CliConfig):
        raise RuntimeError("CLI configuration not initialized")
    return config


def _capability_field(descriptor: Any, field_name: str, default: Any = None) -> Any:
    """Read one capability descriptor field from dicts or typed objects."""
    if isinstance(descriptor, dict):
        return descriptor.get(field_name, default)
    return getattr(descriptor, field_name, default)


def _capability_id(descriptor: Any) -> str:
    """Return the canonical capability identifier for one descriptor."""
    return str(_capability_field(descriptor, "capability_id", "")).strip()


def _capability_summary(descriptor: Any) -> str:
    """Return the summary text for one descriptor."""
    return str(_capability_field(descriptor, "summary", "")).strip()


def _capability_input_schema(descriptor: Any) -> dict[str, Any] | None:
    """Return the input schema object for one descriptor when available."""
    value = _capability_field(descriptor, "input_schema")
    return dict(value) if isinstance(value, dict) else None


def _capability_command_path(capability_id: str) -> tuple[str, ...]:
    """Split one capability id only when it uses a known service prefix."""
    prefix, separator, remainder = capability_id.partition("-")
    if separator != "" and prefix in KNOWN_SERVICE_PREFIXES:
        return prefix, remainder
    return (capability_id,)


def _capability_lookup(cfg: CliConfig) -> dict[str, Any]:
    """Index loaded capability descriptors by canonical identifier."""
    return {_capability_id(item): item for item in cfg.capabilities}


def _require_capability(cfg: CliConfig, capability_id: str) -> Any:
    """Return one loaded capability descriptor or raise a usage error."""
    descriptor = _capability_lookup(cfg).get(capability_id)
    if descriptor is None:
        raise typer.BadParameter(f"unknown capability: {capability_id}")
    return descriptor


def _command_label_for_capability(capability_id: str) -> str:
    """Return the user-facing CLI command form for one capability id."""
    path = _capability_command_path(capability_id)
    if len(path) == 2:
        return " ".join(path)
    return f"capability invoke {capability_id}"


def _json_object(text: str) -> dict[str, Any]:
    """Parse one JSON object payload from CLI text."""
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise typer.BadParameter("`--input-json` must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("`--input-json` must decode to a JSON object")
    return payload


def _coerce_capability_value(name: str, schema: dict[str, Any], value: str) -> Any:
    """Coerce one CLI token into the JSON-schema-declared scalar type."""
    schema_type = schema.get("type")
    if schema_type == "string":
        return value
    if schema_type == "integer":
        try:
            return int(value)
        except ValueError as exc:
            raise typer.BadParameter(f"`{name}` must be an integer") from exc
    if schema_type == "number":
        try:
            return float(value)
        except ValueError as exc:
            raise typer.BadParameter(f"`{name}` must be a number") from exc
    if schema_type == "boolean":
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise typer.BadParameter(f"`{name}` must be a boolean")
    raise typer.BadParameter(
        f"`{name}` uses an unsupported schema shape; pass it via `--input-json`"
    )


def _coerce_capability_option(
    name: str, schema: dict[str, Any], values: list[str]
) -> Any:
    """Coerce one parsed option according to one property schema."""
    schema_type = schema.get("type")
    if schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise typer.BadParameter(
                f"`{name}` uses an unsupported array schema; pass it via `--input-json`"
            )
        return [_coerce_capability_value(name, items, item) for item in values]
    if len(values) != 1:
        raise typer.BadParameter(f"`{name}` does not accept multiple values")
    return _coerce_capability_value(name, schema, values[0])


def _parse_capability_cli_args(
    *, descriptor: Any, args: list[str], input_json: str | None
) -> dict[str, Any]:
    """Parse extra CLI args into one CES capability input payload."""
    payload = {} if input_json is None else _json_object(input_json)
    schema = _capability_input_schema(descriptor)
    if schema is None:
        if len(args) != 0:
            raise typer.BadParameter(
                "this capability does not expose CLI flags; use `--input-json`"
            )
        return payload
    if schema.get("type") not in (None, "object"):
        if len(args) != 0:
            raise typer.BadParameter(
                "this capability requires `--input-json` because its input is not a flat object"
            )
        return payload

    properties = schema.get("properties", {})
    property_map = properties if isinstance(properties, dict) else {}
    required_raw = schema.get("required", ())
    required = {str(item) for item in required_raw if isinstance(item, str)}
    parsed_values: dict[str, list[str]] = {}

    index = 0
    while index < len(args):
        token = args[index]
        if not token.startswith("--"):
            raise typer.BadParameter(
                f"unexpected argument `{token}`; use named options or `--input-json`"
            )

        if token.startswith("--no-"):
            option_name = token[5:].replace("-", "_")
            option_schema = property_map.get(option_name)
            if (
                not isinstance(option_schema, dict)
                or option_schema.get("type") != "boolean"
            ):
                raise typer.BadParameter(f"unknown option `{token}`")
            parsed_values[option_name] = ["false"]
            index += 1
            continue

        if "=" in token:
            option_token, attached_value = token.split("=", 1)
        else:
            option_token = token
            attached_value = None

        option_name = option_token[2:].replace("-", "_")
        option_schema = property_map.get(option_name)
        if not isinstance(option_schema, dict):
            raise typer.BadParameter(f"unknown option `{option_token}`")

        values = parsed_values.setdefault(option_name, [])
        if attached_value is not None:
            values.append(attached_value)
            index += 1
            continue

        if option_schema.get("type") == "boolean":
            next_token = args[index + 1] if index + 1 < len(args) else None
            if next_token is None or next_token.startswith("--"):
                values.append("true")
                index += 1
                continue

        if index + 1 >= len(args):
            raise typer.BadParameter(f"missing value for `{option_token}`")
        values.append(args[index + 1])
        index += 2

    for name, values in parsed_values.items():
        option_schema = property_map.get(name)
        if not isinstance(option_schema, dict):
            continue
        payload[name] = _coerce_capability_option(name, option_schema, values)

    missing = sorted(name for name in required if name not in payload)
    if len(missing) != 0:
        formatted = ", ".join(f"`--{name.replace('_', '-')}`" for name in missing)
        raise typer.BadParameter(f"missing required options: {formatted}")

    return payload


def _invoke_capability_result(
    *,
    client: BrainSdkClient,
    cfg: CliConfig,
    capability_id: str,
    input_payload: dict[str, Any],
) -> Any:
    """Invoke one CES capability and return its output payload."""
    result = invoke_capability(
        client=client,
        capability_id=capability_id,
        input_payload=input_payload,
        actor=cfg.principal,
        channel=cfg.source,
        principal=cfg.principal,
        source=cfg.source,
        trace_id=cfg.trace_id,
        parent_id=cfg.parent_id,
    )
    return result.output


def _invoke_loaded_capability(
    *,
    ctx: typer.Context,
    capability_id: str,
    input_json: str | None,
) -> None:
    """Resolve one loaded descriptor, parse CLI args, and invoke it."""
    cfg = _require_config(ctx)
    descriptor = _require_capability(cfg, capability_id)
    input_payload = _parse_capability_cli_args(
        descriptor=descriptor,
        args=list(ctx.args),
        input_json=input_json,
    )
    _run_command(
        cfg,
        lambda client: _invoke_capability_result(
            client=client,
            cfg=cfg,
            capability_id=capability_id,
            input_payload=input_payload,
        ),
    )


app = typer.Typer(no_args_is_help=True, help="Brain command-line interface")
health_app = typer.Typer(help="Core domain commands")
capability_app = typer.Typer(help="Capability discovery and invocation commands")


@app.callback()
def main(
    ctx: typer.Context,
    host: str | None = typer.Option(
        None,
        envvar="BRAIN_ACTORS_CORE__HOST",
        help="Brain Core host",
    ),
    port: int | None = typer.Option(
        None,
        envvar="BRAIN_ACTORS_CORE__PORT",
        min=1,
        max=65535,
        help="Brain Core TCP port",
    ),
    principal: str | None = typer.Option(None, help="Envelope principal"),
    source: str | None = typer.Option(None, help="Envelope source"),
    timeout: float | None = typer.Option(
        None,
        min=0.001,
        help="Request timeout in seconds",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
    trace_id: str | None = typer.Option(None, help="Optional trace id"),
    parent_id: str | None = typer.Option(None, help="Optional parent envelope id"),
) -> None:
    """Store global options for all domain/action commands."""
    actor_settings = load_actor_settings()

    base_config = CliConfig(
        host=host if host is not None else actor_settings.core.host,
        port=port if port is not None else actor_settings.core.port,
        principal=principal if principal is not None else actor_settings.cli.principal,
        source=source if source is not None else actor_settings.cli.source,
        timeout=timeout if timeout is not None else actor_settings.core.timeout_seconds,
        as_json=as_json,
        trace_id=trace_id,
        parent_id=parent_id,
        capabilities=(),
    )
    ctx.obj = dataclasses.replace(
        base_config,
        capabilities=_load_capabilities(base_config),
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


@capability_app.command("list")
def capability_list(ctx: typer.Context) -> None:
    """List discovered CES capabilities and their CLI command forms."""
    cfg = _require_config(ctx)
    _emit_output(
        [
            {
                "capability_id": _capability_id(item),
                "command": _command_label_for_capability(_capability_id(item)),
                "summary": _capability_summary(item),
            }
            for item in cfg.capabilities
        ],
        cfg.as_json,
    )
    raise typer.Exit(code=SUCCESS_EXIT_CODE)


@capability_app.command("describe")
def capability_describe(ctx: typer.Context, capability_id: str) -> None:
    """Describe one discovered capability through CES."""
    cfg = _require_config(ctx)
    _run_command(
        cfg,
        lambda client: describe_capability(
            client=client,
            capability_id=capability_id,
            principal=cfg.principal,
            source=cfg.source,
            trace_id=cfg.trace_id,
            parent_id=cfg.parent_id,
        ),
    )


@capability_app.command(
    "invoke",
    context_settings=_DYNAMIC_COMMAND_CONTEXT_SETTINGS,
)
def capability_invoke(
    ctx: typer.Context,
    capability_id: str = typer.Argument(..., help="Capability identifier"),
    input_json: str | None = typer.Option(
        None,
        "--input-json",
        help="Raw JSON object payload for complex capability inputs",
    ),
) -> None:
    """Invoke one discovered capability by id."""
    _invoke_loaded_capability(
        ctx=ctx,
        capability_id=capability_id,
        input_json=input_json,
    )


def _build_service_command(prefix: str) -> Callable[..., None]:
    """Create one known-prefix CLI command backed by CES capability lookup."""

    def _service_command(
        ctx: typer.Context,
        operation: str = typer.Argument(..., help=f"{prefix} capability operation"),
        input_json: str | None = typer.Option(
            None,
            "--input-json",
            help="Raw JSON object payload for complex capability inputs",
        ),
    ) -> None:
        _invoke_loaded_capability(
            ctx=ctx,
            capability_id=f"{prefix}-{operation}",
            input_json=input_json,
        )

    _service_command.__name__ = f"{prefix}_command"
    _service_command.__doc__ = f"Invoke `{prefix}-*` CES capabilities."
    return _service_command


app.add_typer(health_app, name="health")
app.add_typer(capability_app, name="capability")

for _prefix in sorted(KNOWN_SERVICE_PREFIXES):
    app.command(
        _prefix,
        context_settings=_DYNAMIC_COMMAND_CONTEXT_SETTINGS,
    )(_build_service_command(_prefix))


if __name__ == "__main__":
    app()
