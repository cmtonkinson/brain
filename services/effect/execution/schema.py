"""Op schema shorthand expansion into canonical JSON Schema."""

import re
from typing import Any


class SchemaExpansionError(ValueError):
    """Raised when schema shorthand is invalid."""


_ARRAY_SUGAR_RE = re.compile(r"^array<\s*([a-zA-Z0-9_<>\s]+?)\s*>$")


def expand_schema(
    shorthand: Any, *, allow_field_aliases: bool = True
) -> dict[str, Any] | None:
    """
    Expands an op schema shorthand into a canonical JSON Schema.

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
    schema_type, modifiers, description = _split_shorthand(shorthand_str)
    schema = _type_token_to_schema(schema_type)
    if description:
        schema["description"] = description

    if "null" in modifiers:
        existing_type = schema["type"]
        if isinstance(existing_type, list):
            if "null" not in existing_type:
                schema["type"] = [*existing_type, "null"]
        else:
            schema["type"] = [existing_type, "null"]

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

        try:
            prop_type, modifiers, description = _split_shorthand(prop_value)
        except SchemaExpansionError as exc:
            raise SchemaExpansionError(
                f"Shorthand for property '{prop_name}' is invalid: {exc}"
            ) from exc

        prop_schema = _type_token_to_schema(prop_type)
        if description:
            prop_schema["description"] = description

        if "null" in modifiers:
            existing_type = prop_schema["type"]
            if isinstance(existing_type, list):
                if "null" not in existing_type:
                    prop_schema["type"] = [*existing_type, "null"]
            else:
                prop_schema["type"] = [existing_type, "null"]

        source_field = _extract_source_field(modifiers)
        if source_field:
            if not allow_field_aliases:
                raise SchemaExpansionError(
                    "Field alias modifier 'from=' is only allowed for pipeline ops."
                )
            prop_schema["x-from"] = source_field

        has_default, default_value = _extract_default(modifiers, prop_type)
        if has_default:
            prop_schema["default"] = default_value

        schema["properties"][prop_name] = prop_schema

        # An explicit default implies the field is optional even if the
        # operator did not also write the ``optional`` modifier.
        if "optional" not in modifiers and not has_default:
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


def _split_shorthand(value: str) -> tuple[str, set[str], str | None]:
    """Split one shorthand string into ``(type_token, modifiers, description)``.

    Grammar: ``<type> ['|' <modifier>]* ['|' <description>]``.

    Description is everything after the last contiguous run of modifiers.
    Pipes inside the description are preserved by re-joining trailing
    segments — so descriptions like
    ``"effects (read|write|execute|external)"`` round-trip intact.
    """
    if not value or not value.strip():
        raise SchemaExpansionError("Shorthand string cannot be empty.")

    raw_parts = value.split("|")
    type_token = raw_parts[0].strip()
    if not type_token:
        raise SchemaExpansionError("Shorthand type token cannot be empty.")

    modifiers: set[str] = set()
    desc_segments: list[str] = []
    in_description = False
    for segment in raw_parts[1:]:
        if not in_description:
            stripped = segment.strip()
            if _is_modifier(stripped):
                modifiers.add(stripped)
                continue
            in_description = True
            desc_segments.append(segment)
        else:
            desc_segments.append(segment)

    description: str | None = None
    if desc_segments:
        description = "|".join(desc_segments).strip() or None
    return type_token, modifiers, description


def _type_token_to_schema(type_token: str) -> dict[str, Any]:
    """Translate one shorthand type token into a draft-2020-12 schema fragment.

    Recognizes ``array<X>`` sugar (recursively) and emits the canonical
    ``{"type": "array", "items": <X>}``. Other tokens land verbatim in
    ``"type"``.
    """
    match = _ARRAY_SUGAR_RE.match(type_token)
    if match is None:
        return {"type": type_token}
    inner = match.group(1).strip()
    return {"type": "array", "items": _type_token_to_schema(inner)}


def _is_modifier(part: str) -> bool:
    """Return whether one shorthand segment is a recognized modifier.

    ``required`` is accepted but has no effect: object-property shorthand is
    required by default; ``optional`` opts out. Operators may write
    ``required`` explicitly for symmetry without it being absorbed into the
    description text.
    """
    return (
        part in {"optional", "null", "required"}
        or part.startswith("from=")
        or part.startswith("default=")
    )


def _extract_default(modifiers: set[str], type_token: str) -> tuple[bool, Any]:
    """Return ``(present, value)`` for any ``default=<value>`` modifier.

    The literal value is parsed against the property's type token so that
    ``"integer | optional | default=3600"`` produces an int default rather
    than the string ``"3600"``.
    """
    for modifier in modifiers:
        if not modifier.startswith("default="):
            continue
        raw = modifier.removeprefix("default=").strip()
        return True, _coerce_default_literal(raw, type_token)
    return False, None


def _coerce_default_literal(raw: str, type_token: str) -> Any:
    """Convert a ``default=`` literal into its declared property type."""
    if type_token == "integer":
        try:
            return int(raw)
        except ValueError:
            return raw
    if type_token == "number":
        try:
            return float(raw)
        except ValueError:
            return raw
    if type_token == "boolean":
        lower = raw.lower()
        if lower in {"true", "1", "yes"}:
            return True
        if lower in {"false", "0", "no"}:
            return False
        return raw
    if type_token == "null":
        return None
    return raw


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
            "Schema field alias 'x-from' is only allowed for pipeline ops."
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
