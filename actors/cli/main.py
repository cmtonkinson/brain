"""Phase-1 Brain CLI actor implemented with Typer."""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Literal

from click import get_current_context
from click.core import ParameterSource
import typer
from lib.sdk import (
    BrainSdkClient,
    DomainError,
    TransportError,
    core_health,
    describe_capability,
    describe_capabilities,
    invoke_capability,
)
from lib.shared.config import load_actor_settings

SUCCESS_EXIT_CODE = 0
DOMAIN_ERROR_EXIT_CODE = 3
TRANSPORT_ERROR_EXIT_CODE = 4
CLI_CACHE_PATH = Path.home() / ".cache" / "brain" / "cli-capabilities.json"
_DEFAULT_CATALOG_TIMEOUT_SECONDS = 1.5
_COMPLEX_CAPABILITY_COMMAND = "capability unsupported-cli"
_DEFAULT_OUTPUT_MODE = "text"
_BOOLEAN_DEFAULT_RE = re.compile(
    r"Defaults to ['`\"]?(true|false)['`\"]?\.",
    flags=re.IGNORECASE,
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
    output_mode: Literal["json", "json_pretty", "text", "simple"] = _DEFAULT_OUTPUT_MODE
    capability_source: Literal["live", "cached", "none"] = "none"
    capability_status: str = ""


@dataclass(frozen=True)
class CapabilityCatalog:
    """Resolved capability catalog used to build CLI commands and help text."""

    capabilities: tuple[dict[str, Any], ...]
    source: Literal["live", "cached", "none"]
    status_message: str
    cache_path: Path


@dataclass(frozen=True)
class CapabilityParamSpec:
    """Derived CLI parameter definition for one capability input field."""

    field_name: str
    annotation: Any
    option: Any
    required: bool
    multiple: bool = False


@dataclass(frozen=True)
class UnsupportedCapabilitySpec:
    """One capability omitted from CLI command generation."""

    capability_id: str
    command: str
    summary: str
    reason: str


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


def _effective_output_mode(
    cfg: CliConfig,
) -> Literal["json", "json_pretty", "text", "simple"]:
    """Return the resolved output mode for one CLI invocation."""
    if cfg.output_mode != _DEFAULT_OUTPUT_MODE:
        return cfg.output_mode
    return "json" if cfg.as_json else "text"


def _emit_output(result: Any, output_mode: str) -> None:
    """Render command output in requested format."""

    data = _serialize(result)
    if output_mode == "json":
        typer.echo(json.dumps(data, sort_keys=True, separators=(",", ":")))
        return
    if output_mode == "json_pretty":
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
        return
    rendered = _render_human(data)
    if rendered is not None:
        typer.echo(rendered)
        return
    if data is None:
        typer.echo("ok")
        return
    typer.echo(str(data))


def _emit_error(exc: Exception, output_mode: str) -> None:
    """Render mapped SDK errors to stderr."""

    if output_mode == "json":
        typer.echo(json.dumps({"error": str(exc)}), err=True)
        return
    if output_mode == "json_pretty":
        typer.echo(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), err=True)
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
        line = (
            f"{padding}{_humanize_component_name(key)}: "
            f"{_status_icon(ready)} {_status_label(ready)}"
        )
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


def _run_command(
    cfg: CliConfig,
    invoke: Callable[[BrainSdkClient], Any],
    *,
    renderer: Callable[[Any], None] | None = None,
) -> None:
    """Execute one SDK call and map outputs/errors to process semantics."""
    try:
        with _with_client(cfg) as client:
            result = invoke(client)
    except DomainError as exc:
        _emit_error(exc, _effective_output_mode(cfg))
        raise typer.Exit(code=DOMAIN_ERROR_EXIT_CODE) from exc
    except TransportError as exc:
        _emit_error(exc, _effective_output_mode(cfg))
        raise typer.Exit(code=TRANSPORT_ERROR_EXIT_CODE) from exc

    if renderer is not None:
        renderer(result)
        raise typer.Exit(code=SUCCESS_EXIT_CODE)
    _emit_output(result, _effective_output_mode(cfg))
    raise typer.Exit(code=SUCCESS_EXIT_CODE)


def _load_capabilities(cfg: CliConfig) -> tuple[Any, ...]:
    """Load the published CES capability list from live Core."""
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
        _emit_error(exc, _effective_output_mode(cfg))
        raise typer.Exit(code=DOMAIN_ERROR_EXIT_CODE) from exc
    except TransportError as exc:
        _emit_error(exc, _effective_output_mode(cfg))
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
    """Return the canonical input schema object for one descriptor when available."""
    value = _capability_field(descriptor, "input_schema")
    return dict(value) if isinstance(value, dict) else None


def _capability_simple_output_path(descriptor: Any) -> str | None:
    """Return the configured simple-output projection path for one descriptor."""
    value = _capability_field(descriptor, "simple_output_path")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _capability_command_path(capability_id: str) -> tuple[str, ...]:
    """Map one capability id to a CLI command path."""
    prefix, separator, remainder = capability_id.partition("-")
    if separator == "":
        return (capability_id,)
    return prefix, remainder


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
    if schema.get("type") != "object":
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
    return " ".join(_capability_command_path(capability_id))


def _resolve_output_mode(
    *,
    json_output: bool,
    json_pretty: bool,
    text_output: bool,
    simple_output: bool,
) -> Literal["json", "json_pretty", "text", "simple"]:
    """Resolve one mutually-exclusive CLI output mode."""
    enabled = [
        mode
        for mode, active in (
            ("json", json_output),
            ("json_pretty", json_pretty),
            ("text", text_output),
            ("simple", simple_output),
        )
        if active
    ]
    if len(enabled) > 1:
        raise typer.BadParameter(
            "output mode flags are mutually exclusive; choose only one of "
            "`--json`, `--json-pretty`, `--text`, or `--simple`"
        )
    if len(enabled) == 0:
        return "text"
    return enabled[0]


def _simple_output_tokens(path: str) -> list[str]:
    """Tokenize one simple-output projection path."""
    if path == ".":
        return []
    if not path.startswith("."):
        raise ValueError("simple_output_path must start with '.'")
    raw = [segment for segment in path[1:].split(".") if segment != ""]
    tokens: list[str] = []
    for segment in raw:
        if segment == "[]":
            tokens.append("each")
            continue
        if segment.endswith("[]"):
            tokens.append(segment[:-2])
            tokens.append("each")
            continue
        tokens.append(segment)
    return tokens


def _extract_simple_output(*, data: Any, path: str) -> Any:
    """Extract one simple projection from a capability output payload."""
    values = [data]
    for token in _simple_output_tokens(path):
        next_values: list[Any] = []
        if token == "each":
            for value in values:
                if not isinstance(value, list):
                    raise ValueError(
                        f"simple_output_path `{path}` expected a list before `.each`"
                    )
                next_values.extend(value)
            values = next_values
            continue
        for value in values:
            if not isinstance(value, dict) or token not in value:
                raise ValueError(
                    f"simple_output_path `{path}` could not resolve field `{token}`"
                )
            next_values.append(value[token])
        values = next_values
    if "each" in _simple_output_tokens(path):
        return values
    if len(values) != 1:
        raise ValueError(f"simple_output_path `{path}` did not resolve one value")
    return values[0]


def _simple_output_line(value: Any) -> str:
    """Render one extracted simple-output item as a single output line."""
    if value is None:
        return "null"
    if isinstance(value, (bool, int, float, str)):
        return str(value)
    return json.dumps(_serialize(value), sort_keys=True, separators=(",", ":"))


def _emit_simple_output(*, descriptor: Any, result: Any) -> None:
    """Render one capability result using its configured simple projection."""
    path = _capability_simple_output_path(descriptor)
    capability_id = _capability_id(descriptor)
    if path is None:
        raise typer.BadParameter(
            f"`{_command_label_for_capability(capability_id)}` does not define "
            "`simple_output_path`; use `--text`, `--json`, or `--json-pretty`"
        )
    extracted = _extract_simple_output(data=_serialize(result), path=path)
    if isinstance(extracted, list):
        typer.echo("\n".join(_simple_output_line(item) for item in extracted))
        return
    typer.echo(_simple_output_line(extracted))


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


def _catalog_status_markup(catalog: CapabilityCatalog) -> str:
    """Return rich-formatted help text describing capability metadata source."""
    if catalog.source == "live":
        return (
            "[green]Capability Metadata: live Core connection[/green]\n"
            "Help and generated subcommands reflect the current published catalog."
        )
    if catalog.source == "cached":
        return (
            "[yellow]Capability Metadata: cached catalog[/yellow]\n"
            "Live Core was unavailable; help reflects the last cached published catalog."
        )
    return (
        "[yellow]Capability Metadata: unavailable[/yellow]\n"
        "Live Core was unavailable and no cached catalog exists; only static commands are shown."
    )


def _cache_payload(capabilities: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Return serialized cache document for one capability catalog."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "capabilities": list(capabilities),
    }


def _write_capability_cache(
    cache_path: Path,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> None:
    """Persist one canonicalized capability catalog to disk."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(_cache_payload(capabilities), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _read_capability_cache(cache_path: Path) -> tuple[dict[str, Any], ...]:
    """Load one cached capability catalog from disk."""
    if not cache_path.exists():
        return ()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    items = payload.get("capabilities")
    if not isinstance(items, list):
        return ()
    capabilities: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        capabilities.append(item)
    return tuple(capabilities)


def _catalog_config_from_settings() -> CliConfig:
    """Build one lightweight config object for capability-catalog loading."""
    actor_settings = load_actor_settings()
    return CliConfig(
        host=actor_settings.core.host,
        port=actor_settings.core.port,
        principal=actor_settings.cli.principal,
        source=actor_settings.cli.source,
        timeout=min(
            float(actor_settings.core.timeout_seconds),
            _DEFAULT_CATALOG_TIMEOUT_SECONDS,
        ),
        as_json=False,
        trace_id=None,
        parent_id=None,
        capabilities=(),
        capability_source="none",
        capability_status="",
    )


def _load_live_capability_catalog() -> tuple[dict[str, Any], ...]:
    """Load one canonicalized capability catalog from live Core."""
    cfg = _catalog_config_from_settings()
    with _with_client(cfg) as client:
        capabilities = describe_capabilities(
            client=client,
            source=cfg.source,
            principal=cfg.principal,
            trace_id=None,
            parent_id=None,
        )
    return tuple(
        serialized
        for item in capabilities
        if isinstance((serialized := _serialize(item)), dict)
    )


def _load_capability_catalog(cache_path: Path = CLI_CACHE_PATH) -> CapabilityCatalog:
    """Resolve capability catalog from live Core or cached fallback."""
    try:
        live = _load_live_capability_catalog()
    except DomainError, TransportError, OSError, ValueError, json.JSONDecodeError:
        live = ()
    if live:
        _write_capability_cache(cache_path, capabilities=live)
        return CapabilityCatalog(
            capabilities=live,
            source="live",
            status_message="live Core connection",
            cache_path=cache_path,
        )

    cached = _read_capability_cache(cache_path)
    if cached:
        return CapabilityCatalog(
            capabilities=cached,
            source="cached",
            status_message="cached catalog",
            cache_path=cache_path,
        )

    return CapabilityCatalog(
        capabilities=(),
        source="none",
        status_message="unavailable",
        cache_path=cache_path,
    )


def _field_annotation(schema: dict[str, Any], *, field_name: str) -> Any:
    """Map one canonical JSON-schema field shape to a Python annotation."""
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null = [item for item in schema_type if item != "null"]
        if len(non_null) != 1:
            raise ValueError(f"{field_name} uses an unsupported union type")
        schema_type = non_null[0]
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{field_name} uses an unsupported array schema")
        item_annotation = _field_annotation(items, field_name=field_name)
        if item_annotation not in {str, int, float, bool}:
            raise ValueError(f"{field_name} uses an unsupported array item schema")
        return list[item_annotation]
    raise ValueError(f"{field_name} uses an unsupported schema shape")


def _boolean_default(description: str | None) -> bool:
    """Return an inferred boolean default from one schema description."""
    if not isinstance(description, str):
        return False
    match = _BOOLEAN_DEFAULT_RE.search(description)
    if match is None:
        return False
    return match.group(1).strip().lower() == "true"


def _schema_is_cli_eligible(schema: dict[str, Any] | None) -> tuple[bool, str]:
    """Return whether one canonical input schema can be represented as CLI flags."""
    if schema is None:
        return True, ""
    if schema.get("type") != "object":
        return False, "input schema is not a flat object"
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return True, ""
    if "anyOf" in schema or "allOf" in schema or "oneOf" in schema:
        return False, "input schema uses an unsupported combinator"
    for field_name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            return False, f"`{field_name}` does not have a canonical property schema"
        if (
            "anyOf" in field_schema
            or "allOf" in field_schema
            or "oneOf" in field_schema
        ):
            return False, f"`{field_name}` uses an unsupported combinator"
        try:
            _field_annotation(field_schema, field_name=field_name)
        except ValueError as exc:
            return False, str(exc)
    return True, ""


def _build_param_specs(descriptor: dict[str, Any]) -> tuple[CapabilityParamSpec, ...]:
    """Build Typer option specs for one CLI-eligible capability descriptor."""
    schema = _capability_input_schema(descriptor)
    if schema is None:
        return ()
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return ()
    required = {
        str(item) for item in schema.get("required", ()) if isinstance(item, str)
    }
    specs: list[CapabilityParamSpec] = []
    for field_name in sorted(properties.keys()):
        property_schema = properties[field_name]
        if not isinstance(property_schema, dict):
            continue
        annotation = _field_annotation(property_schema, field_name=field_name)
        option_name = f"--{field_name.replace('_', '-')}"
        description = str(property_schema.get("description", "")).strip() or None
        is_required = field_name in required
        is_multiple = getattr(annotation, "__origin__", None) is list
        if annotation is bool:
            default_value: Any = ... if is_required else _boolean_default(description)
        elif is_multiple:
            default_value = ... if is_required else None
        else:
            default_value = ... if is_required else None
        specs.append(
            CapabilityParamSpec(
                field_name=field_name,
                annotation=annotation,
                option=typer.Option(default_value, option_name, help=description),
                required=is_required,
                multiple=is_multiple,
            )
        )
    return tuple(specs)


def _parameter_source(
    ctx: typer.Context,
    field_name: str,
) -> ParameterSource | None:
    """Return how one parameter was provided to the current Click context."""
    source = ctx.get_parameter_source(field_name)
    return source if isinstance(source, ParameterSource) else None


def _payload_from_option_values(
    *,
    ctx: typer.Context,
    param_specs: tuple[CapabilityParamSpec, ...],
    values: dict[str, Any],
) -> dict[str, Any]:
    """Build one CES input payload from parsed option values."""
    payload: dict[str, Any] = {}
    for spec in param_specs:
        value = values.get(spec.field_name)
        source = _parameter_source(ctx, spec.field_name)
        if spec.required:
            payload[spec.field_name] = value
            continue
        if source == ParameterSource.DEFAULT:
            continue
        if value is None:
            continue
        if spec.multiple and len(value) == 0:
            continue
        payload[spec.field_name] = value
    return payload


def _dynamic_command_callback(
    *,
    capability_id: str,
    param_specs: tuple[CapabilityParamSpec, ...],
) -> Callable[..., None]:
    """Build one dynamic Typer callback for a CLI-generated capability command."""

    def _handler(**kwargs: Any) -> None:
        ctx = get_current_context(silent=True)
        if ctx is None:
            raise RuntimeError("missing Typer context")
        cfg = _require_config(ctx)
        input_payload = _payload_from_option_values(
            ctx=ctx,
            param_specs=param_specs,
            values=kwargs,
        )
        mode = _effective_output_mode(cfg)
        if mode == "simple":
            _run_command(
                cfg,
                lambda client: _invoke_capability_result(
                    client=client,
                    cfg=cfg,
                    capability_id=capability_id,
                    input_payload=input_payload,
                ),
                renderer=lambda result: _emit_simple_output(
                    descriptor=_require_capability(cfg, capability_id),
                    result=result,
                ),
            )
            return
        _run_command(
            cfg,
            lambda client: _invoke_capability_result(
                client=client,
                cfg=cfg,
                capability_id=capability_id,
                input_payload=input_payload,
            ),
        )

    locals_map: dict[str, Any] = {
        "_handler": _handler,
    }
    parameters: list[str] = []
    arguments: list[str] = []
    for spec in param_specs:
        annotation_name = f"{spec.field_name}_annotation"
        option_name = f"{spec.field_name}_option"
        locals_map[annotation_name] = spec.annotation
        locals_map[option_name] = spec.option
        parameters.append(f"{spec.field_name}: {annotation_name} = {option_name}")
        arguments.append(f"{spec.field_name}={spec.field_name}")

    source = (
        "def dynamic_command("
        + ", ".join(parameters)
        + "):\n"
        + f"    return _handler({', '.join(arguments)})\n"
    )
    namespace: dict[str, Any] = {}
    exec(source, locals_map, namespace)
    callback = namespace["dynamic_command"]
    callback.__name__ = capability_id.replace("-", "_")
    return callback


def _unsupported_capabilities(
    capabilities: tuple[dict[str, Any], ...],
) -> tuple[UnsupportedCapabilitySpec, ...]:
    """Return published capabilities that cannot be exposed as CLI commands."""
    unsupported: list[UnsupportedCapabilitySpec] = []
    for descriptor in capabilities:
        capability_id = _capability_id(descriptor)
        supported, reason = _schema_is_cli_eligible(
            _capability_input_schema(descriptor)
        )
        if supported:
            continue
        unsupported.append(
            UnsupportedCapabilitySpec(
                capability_id=capability_id,
                command=_command_label_for_capability(capability_id),
                summary=_capability_summary(descriptor),
                reason=reason,
            )
        )
    return tuple(sorted(unsupported, key=lambda item: item.capability_id))


def _supported_capabilities(
    capabilities: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Return published capabilities that can be exposed as CLI commands."""
    return tuple(
        descriptor
        for descriptor in capabilities
        if _schema_is_cli_eligible(_capability_input_schema(descriptor))[0]
    )


def _catalog_help_text(
    *,
    title: str,
    catalog: CapabilityCatalog,
) -> str:
    """Build one common help string including capability-metadata status."""
    return f"{title}\n\n{_catalog_status_markup(catalog)}"


def _build_root_app(catalog: CapabilityCatalog) -> typer.Typer:
    """Build the full Typer application from one resolved capability catalog."""
    app = typer.Typer(
        no_args_is_help=True,
        help=_catalog_help_text(title="Brain command-line interface", catalog=catalog),
    )
    health_app = typer.Typer(help="Core domain commands")
    capability_app = typer.Typer(
        help=_catalog_help_text(
            title="Capability discovery and invocation commands",
            catalog=catalog,
        )
    )

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
        as_json: bool = typer.Option(False, "--json", help="Emit compact JSON output"),
        json_pretty: bool = typer.Option(
            False,
            "--json-pretty",
            help="Emit indented JSON output",
        ),
        text_output: bool = typer.Option(
            False,
            "--text",
            help="Emit human-readable text output",
        ),
        simple_output: bool = typer.Option(
            False,
            "--simple",
            help="Emit the configured simple projection for capability results",
        ),
        trace_id: str | None = typer.Option(None, help="Optional trace id"),
        parent_id: str | None = typer.Option(None, help="Optional parent envelope id"),
    ) -> None:
        """Store global options for all domain/action commands."""
        actor_settings = load_actor_settings()
        ctx.obj = CliConfig(
            host=host if host is not None else actor_settings.core.host,
            port=port if port is not None else actor_settings.core.port,
            principal=principal
            if principal is not None
            else actor_settings.cli.principal,
            source=source if source is not None else actor_settings.cli.source,
            timeout=timeout
            if timeout is not None
            else actor_settings.core.timeout_seconds,
            as_json=as_json,
            output_mode=_resolve_output_mode(
                json_output=as_json,
                json_pretty=json_pretty,
                text_output=text_output,
                simple_output=simple_output,
            ),
            trace_id=trace_id,
            parent_id=parent_id,
            capabilities=catalog.capabilities,
            capability_source=catalog.source,
            capability_status=catalog.status_message,
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
        """List discovered capabilities and their CLI command forms."""
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
            _effective_output_mode(cfg),
        )
        raise typer.Exit(code=SUCCESS_EXIT_CODE)

    @capability_app.command("describe")
    def capability_describe(ctx: typer.Context, capability_id: str) -> None:
        """Describe one discovered capability."""
        cfg = _require_config(ctx)
        if cfg.capability_source != "live":
            _emit_output(
                _require_capability(cfg, capability_id),
                _effective_output_mode(cfg),
            )
            raise typer.Exit(code=SUCCESS_EXIT_CODE)
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
        cfg = _require_config(ctx)
        descriptor = _require_capability(cfg, capability_id)
        input_payload = _parse_capability_cli_args(
            descriptor=descriptor,
            args=list(ctx.args),
            input_json=input_json,
        )
        mode = _effective_output_mode(cfg)
        if mode == "simple":
            _run_command(
                cfg,
                lambda client: _invoke_capability_result(
                    client=client,
                    cfg=cfg,
                    capability_id=capability_id,
                    input_payload=input_payload,
                ),
                renderer=lambda result: _emit_simple_output(
                    descriptor=descriptor,
                    result=result,
                ),
            )
            return
        _run_command(
            cfg,
            lambda client: _invoke_capability_result(
                client=client,
                cfg=cfg,
                capability_id=capability_id,
                input_payload=input_payload,
            ),
        )

    @capability_app.command("unsupported-cli")
    def capability_unsupported_cli(ctx: typer.Context) -> None:
        """List published capabilities omitted from generated CLI commands."""
        cfg = _require_config(ctx)
        _emit_output(
            [
                {
                    "capability_id": item.capability_id,
                    "command": item.command,
                    "summary": item.summary,
                    "reason": item.reason,
                }
                for item in _unsupported_capabilities(
                    tuple(_serialize(cap) for cap in cfg.capabilities)
                )
            ],
            _effective_output_mode(cfg),
        )
        raise typer.Exit(code=SUCCESS_EXIT_CODE)

    app.add_typer(health_app, name="health")
    app.add_typer(capability_app, name="capability")

    supported = _supported_capabilities(catalog.capabilities)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for descriptor in supported:
        path = _capability_command_path(_capability_id(descriptor))
        if len(path) != 2:
            continue
        grouped.setdefault(path[0], []).append(descriptor)

    for prefix in sorted(grouped.keys()):
        service_app = typer.Typer(
            help=_catalog_help_text(
                title=f"Invoke `{prefix}-*` capabilities.",
                catalog=catalog,
            )
        )
        for descriptor in sorted(
            grouped[prefix], key=lambda item: _capability_id(item)
        ):
            capability_id = _capability_id(descriptor)
            _, command_name = _capability_command_path(capability_id)
            callback = _dynamic_command_callback(
                capability_id=capability_id,
                param_specs=_build_param_specs(descriptor),
            )
            callback.__doc__ = _capability_summary(descriptor)
            service_app.command(command_name)(callback)
        app.add_typer(service_app, name=prefix)

    return app


def build_app(cache_path: Path = CLI_CACHE_PATH) -> typer.Typer:
    """Build one CLI application using live capability metadata or cached fallback."""
    return _build_root_app(_load_capability_catalog(cache_path))


app = build_app()


if __name__ == "__main__":
    app()
