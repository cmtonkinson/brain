"""Static validation helpers for pipeline skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .registry_schema import CallTargetKind, PipelineSkillDefinition


@dataclass(frozen=True)
class PipelineValidationContext:
    """Lookup context for pipeline validation."""

    skills_by_key: dict[tuple[str, str], Any]
    ops_by_key: dict[tuple[str, str], Any]

    def resolve_skill(self, name: str, version: str | None) -> Any | None:
        """Resolve a skill definition by name and optional version."""
        if version is None:
            matches = [value for (key_name, _), value in self.skills_by_key.items() if key_name == name]
            if len(matches) == 1:
                return matches[0]
            return None
        return self.skills_by_key.get((name, version))

    def resolve_op(self, name: str, version: str | None) -> Any | None:
        """Resolve an op definition by name and optional version."""
        if version is None:
            matches = [value for (key_name, _), value in self.ops_by_key.items() if key_name == name]
            if len(matches) == 1:
                return matches[0]
            return None
        return self.ops_by_key.get((name, version))


def validate_pipeline_skill(
    skill: PipelineSkillDefinition,
    context: PipelineValidationContext,
) -> tuple[list[str], set[str]]:
    """Validate pipeline wiring and return errors plus capability closure."""
    errors: list[str] = []
    capabilities: set[str] = set()

    pipeline_inputs = _schema_properties_map(skill.inputs_schema)
    pipeline_output_required = set(skill.outputs_schema.get("required", []))
    pipeline_output_properties = _schema_properties_map(skill.outputs_schema)
    mapped_pipeline_outputs: set[str] = set()

    step_outputs: dict[str, dict[str, dict[str, Any]]] = {}

    for step in skill.steps:
        if step.target.kind == CallTargetKind.skill:
            target = context.resolve_skill(step.target.name, step.target.version)
            if target is None:
                errors.append(f"pipeline step {step.id} references unknown skill {step.target.name}")
                continue
        else:
            target = context.resolve_op(step.target.name, step.target.version)
            if target is None:
                errors.append(f"pipeline step {step.id} references unknown op {step.target.name}")
                continue

        capabilities.update(getattr(target, "capabilities", []))

        input_schema = getattr(target, "inputs_schema", {})
        output_schema = getattr(target, "outputs_schema", {})
        target_input_props = _schema_properties_map(input_schema)
        target_output_props = _schema_properties_map(output_schema)
        required_inputs = set(input_schema.get("required", []))

        missing_required = required_inputs - set(step.inputs.keys())
        if missing_required:
            errors.append(
                f"pipeline step {step.id} missing required inputs: {sorted(missing_required)}"
            )

        for input_name, source in step.inputs.items():
            if input_name not in target_input_props:
                errors.append(
                    f"pipeline step {step.id} maps unknown input {input_name}"
                )
                continue
            source_schema, source_errors = _resolve_input_source_schema(
                step,
                source,
                pipeline_inputs,
                step_outputs,
            )
            errors.extend(source_errors)
            if source_schema is None:
                continue
            errors.extend(
                _validate_schema_compatibility(
                    source_schema,
                    target_input_props[input_name],
                    f"pipeline step {step.id} input {input_name}",
                )
            )

        output_fields: dict[str, dict[str, Any]] = {}
        for output_name, destination in step.outputs.items():
            if output_name not in target_output_props:
                errors.append(
                    f"pipeline step {step.id} maps unknown output {output_name}"
                )
                continue
            output_fields[output_name] = target_output_props[output_name]
            if destination.startswith("$outputs."):
                output_field = destination.split(".", 1)[1]
                mapped_pipeline_outputs.add(output_field)
                if output_field not in pipeline_output_properties:
                    errors.append(
                        f"pipeline step {step.id} maps to unknown pipeline output {output_field}"
                    )
                else:
                    errors.extend(
                        _validate_schema_compatibility(
                            target_output_props[output_name],
                            pipeline_output_properties[output_field],
                            f"pipeline output {output_field}",
                        )
                    )

        step_outputs[step.id] = output_fields

    missing_outputs = pipeline_output_required - mapped_pipeline_outputs
    if missing_outputs:
        errors.append(
            f"pipeline outputs missing required fields: {sorted(missing_outputs)}"
        )

    return errors, capabilities


def _schema_properties_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return property schemas from a JSON Schema object."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {key: value for key, value in properties.items() if isinstance(value, dict)}


def _resolve_input_source_schema(
    step: Any,
    source: str,
    pipeline_inputs: dict[str, dict[str, Any]],
    step_outputs: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve a pipeline input mapping source schema."""
    errors: list[str] = []
    if source.startswith("$inputs."):
        field = source.split(".", 1)[1]
        schema = pipeline_inputs.get(field)
        if schema is None:
            errors.append(
                f"pipeline step {step.id} references unknown pipeline input {field}"
            )
        return schema, errors

    if source.startswith("$step."):
        parts = source.split(".")
        if len(parts) < 3:
            errors.append(f"pipeline step {step.id} has invalid source {source}")
            return None, errors
        step_id = parts[1]
        field = parts[2]
        if step_id not in step_outputs:
            errors.append(
                f"pipeline step {step.id} references unknown step output {step_id}"
            )
            return None, errors
        if field not in step_outputs[step_id]:
            errors.append(
                f"pipeline step {step.id} references unknown output field {field} from {step_id}"
            )
            return None, errors
        return step_outputs[step_id][field], errors

    errors.append(f"pipeline step {step.id} has invalid source {source}")
    return None, errors


def _validate_schema_compatibility(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
) -> list[str]:
    """Validate that a source schema satisfies a downstream target schema."""
    errors: list[str] = []
    source_type = source.get("type")
    target_type = target.get("type")

    if target_type:
        if source_type is None:
            errors.append(f"{label} missing source type for required {target_type}")
            return errors
        if source_type != target_type:
            errors.append(
                f"{label} type {source_type} incompatible with required {target_type}"
            )
            return errors

    target_enum = target.get("enum")
    if target_enum is not None:
        source_enum = source.get("enum")
        if source_enum is None:
            errors.append(f"{label} missing source enum constraint")
        else:
            missing = [value for value in source_enum if value not in target_enum]
            if missing:
                errors.append(f"{label} enum values not allowed: {missing}")

    if target_type == "string":
        errors.extend(_validate_string_compatibility(source, target, label))
    if target_type in {"integer", "number"}:
        errors.extend(_validate_number_compatibility(source, target, label))
    if target_type == "array":
        errors.extend(_validate_array_compatibility(source, target, label))
    if target_type == "object":
        errors.extend(_validate_object_compatibility(source, target, label))

    return errors


def _validate_string_compatibility(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
) -> list[str]:
    """Validate string constraints between source and target schemas."""
    errors: list[str] = []
    target_format = target.get("format")
    if target_format is not None:
        source_format = source.get("format")
        if source_format is None:
            errors.append(f"{label} missing source format constraint")
        elif source_format != target_format:
            errors.append(f"{label} format {source_format} incompatible with {target_format}")

    errors.extend(_validate_min_constraint(source, target, label, "minLength"))
    errors.extend(_validate_max_constraint(source, target, label, "maxLength"))
    return errors


def _validate_number_compatibility(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
) -> list[str]:
    """Validate numeric constraints between source and target schemas."""
    errors: list[str] = []
    errors.extend(_validate_min_constraint(source, target, label, "minimum"))
    errors.extend(_validate_max_constraint(source, target, label, "maximum"))
    return errors


def _validate_array_compatibility(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
) -> list[str]:
    """Validate array constraints between source and target schemas."""
    errors: list[str] = []
    errors.extend(_validate_min_constraint(source, target, label, "minItems"))
    errors.extend(_validate_max_constraint(source, target, label, "maxItems"))
    target_items = target.get("items")
    if isinstance(target_items, dict):
        source_items = source.get("items")
        if not isinstance(source_items, dict):
            errors.append(f"{label} missing source items schema")
        else:
            errors.extend(
                _validate_schema_compatibility(
                    source_items,
                    target_items,
                    f"{label} items",
                )
            )
    return errors


def _validate_object_compatibility(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
) -> list[str]:
    """Validate object constraints between source and target schemas."""
    errors: list[str] = []
    target_required = set(target.get("required", []))
    source_required = set(source.get("required", []))
    missing_required = target_required - source_required
    if missing_required:
        errors.append(f"{label} missing required fields {sorted(missing_required)}")

    source_properties = _schema_properties_map(source)
    target_properties = _schema_properties_map(target)
    for field in target_required:
        target_schema = target_properties.get(field)
        source_schema = source_properties.get(field)
        if target_schema is None:
            continue
        if source_schema is None:
            errors.append(f"{label} missing property schema for {field}")
            continue
        errors.extend(
            _validate_schema_compatibility(
                source_schema,
                target_schema,
                f"{label}.{field}",
            )
        )

    target_additional = target.get("additionalProperties")
    if target_additional is False:
        if source.get("additionalProperties") is not False:
            errors.append(f"{label} allows additional properties not accepted by target")
    elif isinstance(target_additional, dict):
        source_additional = source.get("additionalProperties")
        if source_additional is True:
            errors.append(f"{label} additional properties are unconstrained")
        elif isinstance(source_additional, dict):
            errors.extend(
                _validate_schema_compatibility(
                    source_additional,
                    target_additional,
                    f"{label} additionalProperties",
                )
            )
    return errors


def _validate_min_constraint(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
    field: str,
) -> list[str]:
    """Validate lower-bound constraints between source and target schemas."""
    errors: list[str] = []
    target_value = target.get(field)
    if target_value is None:
        return errors
    source_value = source.get(field)
    if source_value is None:
        errors.append(f"{label} missing source {field} constraint")
    elif source_value < target_value:
        errors.append(f"{label} {field} {source_value} below required {target_value}")
    return errors


def _validate_max_constraint(
    source: dict[str, Any],
    target: dict[str, Any],
    label: str,
    field: str,
) -> list[str]:
    """Validate upper-bound constraints between source and target schemas."""
    errors: list[str] = []
    target_value = target.get(field)
    if target_value is None:
        return errors
    source_value = source.get(field)
    if source_value is None:
        errors.append(f"{label} missing source {field} constraint")
    elif source_value > target_value:
        errors.append(f"{label} {field} {source_value} above allowed {target_value}")
    return errors
