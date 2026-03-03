"""Capability schema shorthand expansion into canonical JSON Schema."""

from typing import Any


class SchemaExpansionError(ValueError):
    """Raised when schema shorthand is invalid."""


def expand_schema(
    shorthand: Any, *, allow_field_aliases: bool = True
) -> dict[str, Any] | None:
    """
    Expands a capability schema shorthand into a canonical JSON Schema.

    Args:
        shorthand: The shorthand representation. Can be None, a string, a
          shorthand object, or a canonical JSON schema.

    Returns:
        The canonical JSON schema as a dictionary, or None if the input is None.
    """
    if shorthand is None:
        # Represents no schema.
        return None

    if isinstance(shorthand, str):
        # E.g., "string | The description."
        return _expand_primitive_shorthand(shorthand)

    if isinstance(shorthand, dict):
        # Can be a canonical schema or a shorthand object.
        if "type" in shorthand or "properties" in shorthand or "anyOf" in shorthand:
            _validate_field_alias_usage(
                shorthand,
                allow_field_aliases=allow_field_aliases,
            )
            # Looks like a canonical schema, return as-is.
            return shorthand
        # E.g., {"path": "string | The path."}
        return _expand_object_shorthand(
            shorthand,
            allow_field_aliases=allow_field_aliases,
        )

    raise SchemaExpansionError(f"Unsupported schema shorthand type: {type(shorthand)}")


def _expand_primitive_shorthand(shorthand_str: str) -> dict[str, Any]:
    """Expands a primitive shorthand string like "type | mod... | desc"."""
    parts = [p.strip() for p in shorthand_str.split("|")]
    if not parts or not parts[0]:
        raise SchemaExpansionError("Shorthand string cannot be empty.")

    schema_type = parts[0]
    modifiers, description = _parse_shorthand_tail(parts[1:])

    schema: dict[str, Any] = {"type": schema_type}
    if description:
        schema["description"] = description

    if "null" in modifiers:
        schema["type"] = [schema_type, "null"]

    # 'optional' is ignored for top-level primitives as it has no meaning.
    return schema


def _expand_object_shorthand(
    shorthand_obj: dict[str, Any], *, allow_field_aliases: bool
) -> dict[str, Any]:
    """Expands a shorthand object like {"prop": "type | desc"}."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    for prop_name, prop_value in shorthand_obj.items():
        if isinstance(prop_value, dict):
            # Already a canonical JSON Schema fragment — pass through.
            schema["properties"][prop_name] = prop_value
            schema["required"].append(prop_name)
            continue

        if not isinstance(prop_value, str):
            raise SchemaExpansionError(
                f"Value for property '{prop_name}' in shorthand object must be a string."
            )

        parts = [p.strip() for p in prop_value.split("|")]
        if not parts or not parts[0]:
            raise SchemaExpansionError(
                f"Shorthand for property '{prop_name}' is empty."
            )

        prop_type = parts[0]
        modifiers, description = _parse_shorthand_tail(parts[1:])

        prop_schema: dict[str, Any] = {"type": prop_type}
        if description:
            prop_schema["description"] = description

        if "null" in modifiers:
            prop_schema["type"] = [prop_type, "null"]

        source_field = _extract_source_field(modifiers)
        if source_field:
            if not allow_field_aliases:
                raise SchemaExpansionError(
                    "Field alias modifier 'from=' is only allowed for pipeline skills."
                )
            prop_schema["x-from"] = source_field

        schema["properties"][prop_name] = prop_schema

        if "optional" not in modifiers:
            schema["required"].append(prop_name)

    if not schema["required"]:
        del schema["required"]

    return schema


def _extract_source_field(modifiers: set[str]) -> str:
    """Return the source-field alias declared by one shorthand modifier set."""
    for modifier in modifiers:
        if modifier.startswith("from="):
            return modifier.removeprefix("from=").strip()
    return ""


def _parse_shorthand_tail(parts: list[str]) -> tuple[set[str], str | None]:
    """Split shorthand tail segments into modifiers and optional description."""
    if not parts:
        return set(), None

    description: str | None = None
    modifier_parts = parts
    if not _is_modifier(parts[-1]):
        description = parts[-1]
        modifier_parts = parts[:-1]
    return {part for part in modifier_parts if part}, description


def _is_modifier(part: str) -> bool:
    """Return whether one shorthand segment is a recognized modifier."""
    return part in {"optional", "null"} or part.startswith("from=")


def _validate_field_alias_usage(
    schema: Any,
    *,
    allow_field_aliases: bool,
) -> None:
    """Reject canonical field aliases when they are not allowed."""
    if allow_field_aliases:
        return
    if _contains_field_alias(schema):
        raise SchemaExpansionError(
            "Schema field alias 'x-from' is only allowed for pipeline skills."
        )


def _contains_field_alias(value: Any) -> bool:
    """Return whether one schema fragment contains an ``x-from`` field alias."""
    if isinstance(value, dict):
        if "x-from" in value:
            return True
        return any(_contains_field_alias(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_field_alias(item) for item in value)
    return False
