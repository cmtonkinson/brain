"""Capability schema shorthand expansion into canonical JSON Schema."""

from typing import Any


class SchemaExpansionError(ValueError):
    """Raised when schema shorthand is invalid."""


def expand_schema(shorthand: Any) -> dict[str, Any] | None:
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
            # Looks like a canonical schema, return as-is.
            return shorthand
        # E.g., {"path": "string | The path."}
        return _expand_object_shorthand(shorthand)

    raise SchemaExpansionError(f"Unsupported schema shorthand type: {type(shorthand)}")


def _expand_primitive_shorthand(shorthand_str: str) -> dict[str, Any]:
    """Expands a primitive shorthand string like "type | mod... | desc"."""
    parts = [p.strip() for p in shorthand_str.split("|")]
    if not parts or not parts[0]:
        raise SchemaExpansionError("Shorthand string cannot be empty.")

    schema_type = parts[0]
    description = parts[-1] if len(parts) > 1 and parts[-1] != schema_type else None
    modifiers = set(p for p in parts[1:-1] if p) if len(parts) > 2 else set()

    schema: dict[str, Any] = {"type": schema_type}
    if description:
        schema["description"] = description

    if "null" in modifiers:
        schema["type"] = [schema_type, "null"]

    # 'optional' is ignored for top-level primitives as it has no meaning.
    return schema


def _expand_object_shorthand(shorthand_obj: dict[str, Any]) -> dict[str, Any]:
    """Expands a shorthand object like {"prop": "type | desc"}."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    for prop_name, prop_value in shorthand_obj.items():
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
        description = parts[-1] if len(parts) > 1 and parts[-1] != prop_type else None
        modifiers = set(p for p in parts[1:-1] if p) if len(parts) > 2 else set()

        prop_schema: dict[str, Any] = {"type": prop_type}
        if description:
            prop_schema["description"] = description

        if "null" in modifiers:
            prop_schema["type"] = [prop_type, "null"]

        schema["properties"][prop_name] = prop_schema

        if "optional" not in modifiers:
            schema["required"].append(prop_name)

    if not schema["required"]:
        del schema["required"]

    return schema
