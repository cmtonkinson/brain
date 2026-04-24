"""Unit tests for op schema shorthand expansion."""

from __future__ import annotations

import pytest

from services.effect.execution.schema import SchemaExpansionError, expand_schema


def test_null_schema_returns_none() -> None:
    assert expand_schema(None) is None


def test_primitive_type_only() -> None:
    assert expand_schema("string") == {"type": "string"}


def test_primitive_with_description() -> None:
    assert expand_schema("string | A greeting.") == {
        "type": "string",
        "description": "A greeting.",
    }


def test_primitive_with_null_modifier() -> None:
    assert expand_schema("string | null | Might be absent.") == {
        "type": ["string", "null"],
        "description": "Might be absent.",
    }


def test_primitive_optional_modifier_ignored() -> None:
    result = expand_schema("integer | optional | A count.")
    assert result == {"type": "integer", "description": "A count."}


def test_object_shorthand_required_by_default() -> None:
    result = expand_schema({"name": "string | The name."})
    assert result == {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The name."}},
        "required": ["name"],
        "additionalProperties": False,
    }


def test_object_shorthand_optional_modifier() -> None:
    result = expand_schema({"tag": "string | optional | A tag."})
    assert result == {
        "type": "object",
        "properties": {"tag": {"type": "string", "description": "A tag."}},
        "additionalProperties": False,
    }
    assert "required" not in result


def test_object_shorthand_null_modifier() -> None:
    result = expand_schema({"value": "integer | null | Nullable int."})
    assert result["properties"]["value"]["type"] == ["integer", "null"]


def test_object_shorthand_from_modifier() -> None:
    result = expand_schema({"text": "string | from=content | Text to chunk."})
    assert result["properties"]["text"] == {
        "type": "string",
        "description": "Text to chunk.",
        "x-from": "content",
    }
    assert result["required"] == ["text"]


def test_object_shorthand_mixed_required_and_optional() -> None:
    result = expand_schema(
        {
            "id": "string | The identifier.",
            "label": "string | optional | An optional label.",
        }
    )
    assert result["required"] == ["id"]


def test_canonical_schema_passthrough() -> None:
    canonical = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    assert expand_schema(canonical) is canonical


def test_canonical_with_properties_key_passthrough() -> None:
    canonical = {"properties": {"x": {"type": "string"}}}
    assert expand_schema(canonical) is canonical


def test_canonical_with_any_of_passthrough() -> None:
    canonical = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert expand_schema(canonical) is canonical


def test_unsupported_type_raises() -> None:
    with pytest.raises(SchemaExpansionError, match="Unsupported schema shorthand type"):
        expand_schema(42)


def test_empty_shorthand_string_raises() -> None:
    with pytest.raises(SchemaExpansionError, match="cannot be empty"):
        expand_schema("")


def test_object_shorthand_non_string_value_raises() -> None:
    with pytest.raises(SchemaExpansionError, match="must be a string"):
        expand_schema({"count": 123})


def test_object_shorthand_empty_property_value_raises() -> None:
    with pytest.raises(SchemaExpansionError, match="cannot be empty"):
        expand_schema({"bad": ""})


def test_object_shorthand_array_of_string_sugar() -> None:
    """``array<string>`` sugar expands to canonical array+items schema."""
    result = expand_schema({"words": "array<string> | required | listy thing."})
    assert result == {
        "type": "object",
        "properties": {
            "words": {
                "type": "array",
                "items": {"type": "string"},
                "description": "listy thing.",
            },
        },
        "required": ["words"],
        "additionalProperties": False,
    }


def test_object_shorthand_description_with_embedded_pipes() -> None:
    """Descriptions can contain ``|`` characters; only modifier prefix is stripped."""
    result = expand_schema(
        {
            "words": (
                "array<string> | required | one or more words drawn from "
                "the effect set (read|write|execute|external) and/or "
                "the approval set (always|never)."
            ),
        }
    )
    description = result["properties"]["words"]["description"]
    assert "(read|write|execute|external)" in description
    assert description.endswith("(always|never).")
    assert result["properties"]["words"]["type"] == "array"
    assert result["properties"]["words"]["items"] == {"type": "string"}


def test_mixed_shorthand_and_canonical_properties() -> None:
    """Shorthand strings and canonical JSON Schema dicts can coexist."""
    result = expand_schema(
        {
            "file_path": "string | The path.",
            "edits": {
                "type": "array",
                "description": "Edits to apply.",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                        "content": {"type": "string"},
                    },
                    "required": ["start_line", "end_line", "content"],
                },
            },
        }
    )
    assert result["type"] == "object"
    assert result["properties"]["file_path"] == {
        "type": "string",
        "description": "The path.",
    }
    # Canonical dict property passed through unchanged.
    assert result["properties"]["edits"]["type"] == "array"
    assert result["properties"]["edits"]["items"]["properties"]["start_line"] == {
        "type": "integer"
    }
    assert result["required"] == ["file_path", "edits"]


def test_mixed_shorthand_canonical_property_is_optional_when_not_in_required() -> None:
    """A canonical dict property is required by default in shorthand context."""
    result = expand_schema(
        {
            "name": "string | The name.",
            "metadata": {"type": "object", "description": "Extra data."},
        }
    )
    assert "name" in result["required"]
    assert "metadata" in result["required"]
