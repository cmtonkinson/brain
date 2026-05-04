"""List slash commands, or describe one in detail when a query is given."""

from __future__ import annotations

from typing import Any


def execute(input_payload: dict[str, object] | None = None) -> str:
    """Return formatted help text for registered slash commands.

    No query: list every command. Query exact-matches one slash name,
    alias, or op_id: detailed view. Query substring-matches: filtered
    list (or detail when exactly one survives).
    """
    from lib.sdk.client import BrainSdkClient

    payload = {} if input_payload is None else input_payload
    raw_query = payload.get("query")
    query = (str(raw_query) if raw_query is not None else "").strip().lower()

    brain_client = BrainSdkClient(source="slash-help", principal="operator")
    caps = brain_client.describe_ops()
    slash_caps = [c for c in caps if c.slash_command_name]

    if not slash_caps:
        return "No slash commands registered."

    if query == "":
        return _format_list(slash_caps, header="Available commands:")

    exact = [c for c in slash_caps if _exact_match(c, query)]
    if len(exact) == 1:
        return _format_detail(exact[0])
    if len(exact) > 1:
        return _format_list(exact, header=f"Commands matching '{query}':")

    substring = [c for c in slash_caps if _substring_match(c, query)]
    if len(substring) == 1:
        return _format_detail(substring[0])
    if len(substring) > 1:
        return _format_list(substring, header=f"Commands matching '{query}':")

    return f"No slash commands match '{query}'. Type /help for the full list."


def _exact_match(cap: Any, query: str) -> bool:
    """Return True when ``query`` exactly matches a slash token or op_id."""
    return query in _candidate_tokens(cap)


def _substring_match(cap: Any, query: str) -> bool:
    """Return True when ``query`` is a substring of any slash token or op_id."""
    return any(query in token for token in _candidate_tokens(cap))


def _candidate_tokens(cap: Any) -> tuple[str, ...]:
    """Return the lowercase tokens used for matching against ``cap``."""
    tokens: list[str] = [cap.op_id.lower()]
    if cap.slash_command_name:
        tokens.append(cap.slash_command_name.lower())
    tokens.extend(alias.lower() for alias in cap.slash_command_aliases)
    return tuple(tokens)


def _format_list(caps: list[Any], *, header: str) -> str:
    """Render a sorted slash-command summary list."""
    lines = [header]
    for cap in sorted(caps, key=lambda c: c.slash_command_name or ""):
        line = f"  /{cap.slash_command_name}"
        if cap.slash_command_aliases:
            aliases = ", ".join(f"/{a}" for a in cap.slash_command_aliases)
            line += f" (aliases: {aliases})"
        desc = cap.slash_command_description or cap.summary
        if desc:
            line += f" — {desc}"
        lines.append(line)
    return "\n".join(lines)


def _format_detail(cap: Any) -> str:
    """Render a per-op detail view: gates, inputs, outputs, dependencies."""
    desc = cap.slash_command_description or cap.summary
    lines = [
        f"/{cap.slash_command_name} — {desc}" if desc else f"/{cap.slash_command_name}"
    ]
    if cap.slash_command_aliases:
        aliases = ", ".join(f"/{a}" for a in cap.slash_command_aliases)
        lines.append(f"  Aliases: {aliases}")
    lines.append(f"  Op:      {cap.op_id} ({cap.kind}, v{cap.version})")
    lines.append(f"  Gates:   effect={cap.effect}, approval={cap.approval}")
    if cap.required_ops:
        lines.append(f"  Requires: {', '.join(cap.required_ops)}")

    input_lines = _format_schema(cap.input_schema, kind="Inputs")
    if input_lines:
        lines.append("")
        lines.extend(input_lines)

    output_lines = _format_schema(cap.output_schema, kind="Outputs")
    if output_lines:
        lines.append("")
        lines.extend(output_lines)
        if cap.simple_output_path:
            lines.append(f"  Simple output: {cap.simple_output_path}")

    return "\n".join(lines)


def _format_schema(schema: dict[str, Any] | None, *, kind: str) -> list[str]:
    """Render one input or output schema as indented human-readable lines."""
    if schema is None:
        return []
    if not isinstance(schema, dict):
        return [f"  {kind}: {schema}"]

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        return _format_object_schema(schema, header=f"  {kind}:")
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict) and (
            items.get("type") == "object" or "properties" in items
        ):
            return _format_object_schema(items, header=f"  {kind} (array of object):")
        return [f"  {kind} (array): {_render_type(items or {})}"]
    return [
        f"  {kind} ({_render_type(schema)}): {schema.get('description') or ''}".rstrip()
    ]


def _format_object_schema(schema: dict[str, Any], *, header: str) -> list[str]:
    """Render an object schema's properties as ``  name  type  desc`` rows."""
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return [header.rstrip(":") + " (no fields)"]
    required = set(schema.get("required") or [])
    lines = [header]
    for name, prop in properties.items():
        prop_dict = prop if isinstance(prop, dict) else {}
        is_required = name in required
        type_label = _render_type(prop_dict, omit_null=not is_required)
        modifier = "required" if is_required else "optional"
        if "default" in prop_dict:
            modifier = f"{modifier}, default {_render_default(prop_dict['default'])}"
        prop_desc = prop_dict.get("description") or ""
        suffix = f" — {prop_desc}" if prop_desc else ""
        lines.append(f"    {name} ({type_label}, {modifier}){suffix}")
    return lines


def _render_default(value: Any) -> str:
    """Render a JSON Schema default value for human-readable display."""
    if isinstance(value, str):
        return f'"{value}"'
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_type(schema: dict[str, Any], *, omit_null: bool = False) -> str:
    """Render a JSON Schema type fragment as a compact label like ``string|null``.

    ``omit_null=True`` suppresses ``null`` members in unions; ``optional``
    already implies absence-on-the-wire, so showing ``integer|null`` for an
    optional integer just adds noise.
    """
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type
    if isinstance(schema_type, list):
        members = [str(t) for t in schema_type]
        if omit_null:
            non_null = [t for t in members if t != "null"]
            if non_null:
                members = non_null
        return "|".join(members)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        rendered = [
            _render_type(item, omit_null=omit_null)
            for item in any_of
            if isinstance(item, dict)
        ]
        if omit_null:
            rendered = [r for r in rendered if r != "null"] or rendered
        return "|".join(rendered)
    return "any"
