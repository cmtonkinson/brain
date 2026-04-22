"""Capability registry loading immutable manifests and runtime handlers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import inspect
import json
import os
from pathlib import Path
from types import NoneType, UnionType
from typing import (
    Any,
    ForwardRef,
    Protocol,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    CapabilityManifest,
    OpCapabilityManifest,
    PipelineStep,
    SkillCapabilityManifest,
)
from services.action.language_model.service import LanguageModelService
from services.action.policy_service.service import PolicyService
from services.action.attention_router.service import AttentionRouterService
from services.action.switchboard.service import SwitchboardService
from services.action.utility_service.service import UtilityService
from services.action.policy_service.domain import CapabilityInvocationRequest
from services.control.ingestion.service import IngestionService
from services.state.cache_authority.service import CacheAuthorityService
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.memory_authority.service import MemoryAuthorityService
from services.state.object_authority.service import ObjectAuthorityService
from services.state.vault_authority.service import VaultAuthorityService


class CapabilityRuntime(Protocol):
    """Runtime helper contract exposed to capability handlers."""

    def invoke_nested(
        self,
        *,
        capability_id: str,
        input_payload: dict[str, Any],
    ) -> CapabilityExecutionResponse:
        """Invoke a nested capability under narrowed lineage context."""


CapabilityHandler = Callable[
    [CapabilityInvocationRequest, CapabilityRuntime], CapabilityExecutionResponse
]


@dataclass(frozen=True, slots=True)
class CallTargetContract:
    """Contract for one callable target used by Op capability manifests."""

    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None


class CapabilityRegistry:
    """In-memory capability registry backed by manifest discovery and handlers."""

    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}
        self._handlers: dict[str, CapabilityHandler] = {}
        self._slash_commands: dict[str, CapabilityManifest] = {}

    def discover(
        self,
        *,
        root: Path,
        call_targets: dict[str, CallTargetContract] | None = None,
    ) -> None:
        """Auto-discover ``capability.json`` declarations under one root."""
        if not root.exists():
            return

        discovered: dict[str, CapabilityManifest] = {}
        for manifest_path in self._iter_manifest_paths(root=root):
            package_dir = manifest_path.parent
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = self._parse_manifest(raw)
            if not manifest.enabled:
                continue
            self._validate_manifest_files(package_dir=package_dir, manifest=manifest)
            if manifest.capability_id in discovered:
                raise ValueError(
                    f"duplicate capability_id discovered: {manifest.capability_id}"
                )
            discovered[manifest.capability_id] = manifest

        self._validate_closure(discovered)
        self._validate_call_targets_and_io(
            manifests=discovered,
            call_targets=self._build_call_target_contracts(extra=call_targets),
        )
        self._manifests = discovered
        self._slash_commands = self._build_slash_index(discovered)

    def _iter_manifest_paths(self, *, root: Path) -> tuple[Path, ...]:
        """Yield package manifest paths under ``root`` in stable order.

        Discovery is recursive, but once a directory is identified as a
        capability package (it contains ``capability.json``), traversal does
        not descend beneath it. This keeps nested grouping directories
        organizational while preventing accidental discovery of files inside a
        package's implementation or tests.
        """
        manifest_paths: list[Path] = []
        for current_root, dir_names, _file_names in os.walk(root, topdown=True):
            dir_names.sort()
            package_dir = Path(current_root)
            manifest_path = package_dir / "capability.json"
            if not manifest_path.exists():
                continue
            manifest_paths.append(manifest_path)
            dir_names[:] = []
        return tuple(manifest_paths)

    def _parse_manifest(self, raw: dict[str, Any]) -> CapabilityManifest:
        kind = raw.get("kind")
        if kind in ("native_op", "mcp_op"):
            return OpCapabilityManifest.model_validate(raw)
        if kind in ("logic_skill", "pipeline_skill"):
            return SkillCapabilityManifest.model_validate(raw)
        raise ValueError(f"Unknown or missing capability kind in manifest: {kind}")

    def _validate_manifest_files(
        self,
        *,
        package_dir: Path,
        manifest: CapabilityManifest,
    ) -> None:
        if package_dir.name != manifest.capability_id:
            raise ValueError(
                "capability package directory must match manifest capability_id"
            )

        readme_path = package_dir / "README.md"
        if not readme_path.exists():
            raise ValueError(
                f"capability package missing README.md: {manifest.capability_id}"
            )

        if isinstance(manifest, SkillCapabilityManifest):
            if manifest.kind == "logic_skill":
                entrypoint = package_dir / manifest.entrypoint
                if not entrypoint.exists():
                    raise ValueError(
                        f"logic skill missing entrypoint: {manifest.capability_id}"
                    )
                has_tests = any((package_dir / "test").glob("test_*.py"))
                if not has_tests:
                    raise ValueError(
                        f"logic skill missing tests: {manifest.capability_id}"
                    )
            elif manifest.kind == "pipeline_skill" and len(manifest.pipeline) == 0:
                raise ValueError(
                    f"pipeline skill must declare pipeline entries: {manifest.capability_id}"
                )

    def _validate_closure(self, manifests: dict[str, CapabilityManifest]) -> None:
        manifest_ids = set(manifests.keys())
        for capability_id, manifest in manifests.items():
            for dependency in manifest.required_capabilities:
                if dependency not in manifest_ids:
                    raise ValueError(
                        f"capability {capability_id} requires unknown dependency {dependency}"
                    )
            if isinstance(manifest, SkillCapabilityManifest):
                for step in manifest.pipeline:
                    nested = self._pipeline_step(step).capability
                    if nested not in manifest_ids:
                        raise ValueError(
                            f"pipeline skill {capability_id} references unknown capability {nested}"
                        )

    def _strip_descriptions(self, schema: Any) -> Any:
        """Recursively remove 'description' keys from a schema."""
        if isinstance(schema, dict):
            return {
                key: self._strip_descriptions(value)
                for key, value in schema.items()
                if key != "description"
            }
        if isinstance(schema, list):
            return [self._strip_descriptions(item) for item in schema]
        return schema

    @classmethod
    def _schemas_compatible(
        cls,
        manifest_schema: dict[str, Any] | None,
        contract_schema: dict[str, Any] | None,
    ) -> bool:
        """Check schema compatibility, falling back to structural match.

        The auto-derived contract schemas are coarse stubs for complex types
        (e.g. ``{"type": "object", "title": "FileEdit"}``).  Accept the
        manifest schema whenever the contract side is a stub whose ``type``
        matches, and recurse into ``properties`` / ``items`` so that nested
        stubs are also tolerated.
        """
        if manifest_schema == contract_schema:
            return True
        if manifest_schema is None or contract_schema is None:
            return False
        if not isinstance(manifest_schema, dict) or not isinstance(
            contract_schema, dict
        ):
            return manifest_schema == contract_schema

        manifest_simple_types = cls._simple_type_set(manifest_schema)
        contract_simple_types = cls._simple_type_set(contract_schema)
        if manifest_simple_types is not None and contract_simple_types is not None:
            return manifest_simple_types == contract_simple_types

        # Stub: contract has a type but no properties/items detail.
        contract_is_stub = (
            "properties" not in contract_schema
            and "items" not in contract_schema
            and contract_schema.get("type") == manifest_schema.get("type")
        )
        if contract_is_stub:
            return True

        # Both have type — must agree.
        if contract_schema.get("type") != manifest_schema.get("type"):
            return False

        # Recurse into object properties: every contract property must be
        # compatible with the corresponding manifest property.
        contract_props = contract_schema.get("properties", {})
        manifest_props = manifest_schema.get("properties", {})
        if contract_props:
            if set(contract_props) != set(manifest_props):
                return False
            for key in contract_props:
                if not cls._schemas_compatible(
                    manifest_props.get(key), contract_props.get(key)
                ):
                    return False

        # Recurse into array items.
        if "items" in contract_schema and "items" in manifest_schema:
            if not cls._schemas_compatible(
                manifest_schema["items"], contract_schema["items"]
            ):
                return False

        return True

    @staticmethod
    def _simple_type_set(schema: dict[str, Any]) -> set[str] | None:
        """Return simple scalar/union type set when one schema is type-only."""
        if "properties" in schema or "items" in schema:
            return None

        schema_type = schema.get("type")
        if isinstance(schema_type, str):
            return {schema_type}
        if isinstance(schema_type, list) and all(
            isinstance(value, str) for value in schema_type
        ):
            return set(schema_type)

        any_of = schema.get("anyOf")
        if not isinstance(any_of, list) or not any_of:
            return None

        types: set[str] = set()
        for option in any_of:
            if not isinstance(option, dict) or "type" not in option:
                return None
            option_type = option.get("type")
            if not isinstance(option_type, str):
                return None
            types.add(option_type)
        return types

    def _validate_call_targets_and_io(
        self,
        *,
        manifests: dict[str, CapabilityManifest],
        call_targets: dict[str, CallTargetContract],
    ) -> None:
        for capability_id, manifest in manifests.items():
            if isinstance(manifest, OpCapabilityManifest):
                if manifest.kind == "mcp_op":
                    continue
                contract = call_targets.get(manifest.call_target)
                if contract is None:
                    raise ValueError(
                        f"op capability {capability_id} references unknown call target {manifest.call_target}"
                    )

                manifest_input_schema = self._strip_descriptions(manifest.input_schema)
                if not self._schemas_compatible(
                    manifest_input_schema, contract.input_schema
                ):
                    raise ValueError(
                        f"op capability {capability_id} input schema does not match call target {manifest.call_target}"
                    )

                manifest_output_schema = self._strip_descriptions(
                    manifest.output_schema
                )
                if not self._schemas_compatible(
                    manifest_output_schema, contract.output_schema
                ):
                    raise ValueError(
                        f"op capability {capability_id} output schema does not match call target {manifest.call_target}"
                    )
                continue

            if manifest.kind != "pipeline_skill":
                continue
            if len(manifest.pipeline) == 0:
                continue

            first_step = self._pipeline_step(manifest.pipeline[0])
            first = manifests[first_step.capability]
            if not self._pipeline_handoff_compatible(
                producer_schema=manifest.input_schema,
                consumer_schema=self._pipeline_step_input_schema(
                    step=first_step,
                    consumer_schema=first.input_schema,
                ),
            ):
                raise ValueError(
                    "pipeline skill "
                    f"{capability_id} input schema does not satisfy first call target "
                    f"{first.capability_id}"
                )
            for index in range(1, len(manifest.pipeline)):
                previous_step = self._pipeline_step(manifest.pipeline[index - 1])
                current_step = self._pipeline_step(manifest.pipeline[index])
                previous = manifests[previous_step.capability]
                current = manifests[current_step.capability]
                if not self._pipeline_handoff_compatible(
                    producer_schema=previous.output_schema,
                    consumer_schema=self._pipeline_step_input_schema(
                        step=current_step,
                        consumer_schema=current.input_schema,
                    ),
                ):
                    raise ValueError(
                        f"pipeline skill {capability_id} has incompatible call targets {previous.capability_id} -> {current.capability_id}"
                    )
            last = manifests[self._pipeline_step(manifest.pipeline[-1]).capability]
            if not self._pipeline_handoff_compatible(
                producer_schema=last.output_schema,
                consumer_schema=manifest.output_schema,
            ):
                raise ValueError(
                    "pipeline skill "
                    f"{capability_id} output schema is not satisfied by final call target "
                    f"{last.capability_id}"
                )

    def _pipeline_handoff_compatible(
        self,
        *,
        producer_schema: dict[str, Any] | None,
        consumer_schema: dict[str, Any] | None,
    ) -> bool:
        """Return whether one step's output can satisfy the next step's input.

        Required consumer fields must be present in the producer with compatible
        schemas. Optional consumer fields may be omitted, but if present in the
        producer they must also be compatible. Producer-only extra fields are
        allowed and ignored at runtime.
        """
        producer = self._strip_descriptions(producer_schema)
        consumer = self._strip_descriptions(consumer_schema)

        if producer == consumer:
            return True
        if consumer is None:
            return True
        if producer is None:
            return self._schema_required_fields(consumer) == set()
        if not isinstance(producer, dict) or not isinstance(consumer, dict):
            return producer == consumer

        producer_props, _producer_required = self._schema_object_fields(producer)
        consumer_props, consumer_required = self._schema_object_fields(consumer)
        if producer_props is None or consumer_props is None:
            return self._schemas_compatible(producer, consumer)

        for field_name in consumer_required:
            if (
                self._resolve_schema_source_field(
                    field_name=field_name,
                    consumer_field_schema=consumer_props[field_name],
                    producer_props=producer_props,
                )
                is None
            ):
                return False

        for field_name, consumer_field_schema in consumer_props.items():
            producer_field_name = self._resolve_schema_source_field(
                field_name=field_name,
                consumer_field_schema=consumer_field_schema,
                producer_props=producer_props,
            )
            if producer_field_name is None:
                continue
            producer_field_schema = producer_props.get(producer_field_name)
            if producer_field_schema is None:
                continue
            if not self._schemas_compatible(
                producer_field_schema,
                consumer_field_schema,
            ):
                return False
        return True

    def project_pipeline_payload(
        self,
        *,
        payload: Mapping[str, Any] | None,
        consumer_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Project one payload to the fields accepted by a consumer schema."""
        consumer = self._strip_descriptions(consumer_schema)
        if consumer is None:
            return {}

        consumer_props, consumer_required = self._schema_object_fields(consumer)
        if consumer_props is None:
            if payload is None:
                return {}
            if isinstance(payload, Mapping):
                return dict(payload)
            raise ValueError("pipeline payload must be a mapping")

        if payload is None:
            payload_mapping: Mapping[str, Any] = {}
        elif isinstance(payload, Mapping):
            payload_mapping = payload
        else:
            raise ValueError("pipeline payload must be a mapping")

        projected: dict[str, Any] = {}
        missing_required = sorted(
            field_name
            for field_name in consumer_required
            if self._resolve_payload_source_field(
                field_name=field_name,
                consumer_field_schema=consumer_props[field_name],
                payload=payload_mapping,
            )
            is None
        )
        if missing_required:
            raise ValueError(f"missing required input keys: {missing_required}")

        for field_name, consumer_field_schema in consumer_props.items():
            source_field_name = self._resolve_payload_source_field(
                field_name=field_name,
                consumer_field_schema=consumer_field_schema,
                payload=payload_mapping,
            )
            if source_field_name is None:
                continue
            projected[field_name] = payload_mapping[source_field_name]
        return projected

    def _schema_object_fields(
        self,
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, set[str]]:
        """Return object properties and required fields when schema is object-like."""
        if schema.get("type") != "object":
            return None, set()
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None, set()
        required = self._schema_required_fields(schema)
        return properties, required

    def _schema_required_fields(self, schema: dict[str, Any]) -> set[str]:
        """Return the set of required fields declared by one object schema."""
        required = schema.get("required", ())
        if not isinstance(required, list):
            return set()
        return {field_name for field_name in required if isinstance(field_name, str)}

    def _pipeline_step(self, entry: str | PipelineStep) -> PipelineStep:
        """Normalize one pipeline entry to the object form."""
        return PipelineStep.from_entry(entry)

    def _pipeline_step_input_schema(
        self,
        *,
        step: PipelineStep,
        consumer_schema: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Overlay one step's explicit input mapping onto its input schema."""
        if not step.input_mapping:
            return consumer_schema
        if consumer_schema is None:
            raise ValueError(
                f"pipeline step {step.capability} declares input_mapping but target has no input schema"
            )
        if not isinstance(consumer_schema, dict):
            raise ValueError(
                f"pipeline step {step.capability} input schema must be an object when using input_mapping"
            )
        if consumer_schema.get("type") != "object":
            raise ValueError(
                f"pipeline step {step.capability} input schema must be an object when using input_mapping"
            )
        properties = consumer_schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(
                f"pipeline step {step.capability} input schema must declare object properties when using input_mapping"
            )

        schema = json.loads(json.dumps(consumer_schema))
        remapped_properties = schema.get("properties", {})
        assert isinstance(remapped_properties, dict)
        for consumer_field, producer_field in step.input_mapping.items():
            field_schema = remapped_properties.get(consumer_field)
            if not isinstance(field_schema, dict):
                raise ValueError(
                    f"pipeline step {step.capability} input_mapping references unknown input field {consumer_field}"
                )
            field_schema["x-from"] = producer_field
        return schema

    def _resolve_schema_source_field(
        self,
        *,
        field_name: str,
        consumer_field_schema: Any,
        producer_props: Mapping[str, Any],
    ) -> str | None:
        """Return the producer field that satisfies one consumer field."""
        for candidate in self._consumer_source_field_names(
            field_name=field_name,
            consumer_field_schema=consumer_field_schema,
        ):
            if candidate in producer_props:
                return candidate
        return None

    def _resolve_payload_source_field(
        self,
        *,
        field_name: str,
        consumer_field_schema: Any,
        payload: Mapping[str, Any],
    ) -> str | None:
        """Return the payload field to project into one consumer field."""
        for candidate in self._consumer_source_field_names(
            field_name=field_name,
            consumer_field_schema=consumer_field_schema,
        ):
            if candidate in payload:
                return candidate
        return None

    def _consumer_source_field_names(
        self,
        *,
        field_name: str,
        consumer_field_schema: Any,
    ) -> tuple[str, ...]:
        """Return accepted source field names for one consumer field."""
        if not isinstance(consumer_field_schema, dict):
            return (field_name,)

        source_field = consumer_field_schema.get("x-from")
        if not isinstance(source_field, str):
            return (field_name,)

        normalized_source_field = source_field.strip()
        if not normalized_source_field or normalized_source_field == field_name:
            return (field_name,)
        return (field_name, normalized_source_field)

    def _build_call_target_contracts(
        self, *, extra: dict[str, CallTargetContract] | None
    ) -> dict[str, CallTargetContract]:
        contracts = self._discover_native_service_targets()
        if extra:
            contracts.update(extra)
        return contracts

    def _discover_native_service_targets(self) -> dict[str, CallTargetContract]:
        from services.control.commitment.service import CommitmentService

        contracts: dict[str, CallTargetContract] = {}
        services: tuple[tuple[str, type[Any]], ...] = (
            ("service_cache_authority", CacheAuthorityService),
            ("service_embedding_authority", EmbeddingAuthorityService),
            ("service_memory_authority", MemoryAuthorityService),
            ("service_object_authority", ObjectAuthorityService),
            ("service_vault_authority", VaultAuthorityService),
            ("service_language_model", LanguageModelService),
            ("service_policy_service", PolicyService),
            ("service_attention_router", AttentionRouterService),
            ("service_switchboard", SwitchboardService),
            ("service_utility_service", UtilityService),
            ("service_commitment", CommitmentService),
            ("service_ingestion", IngestionService),
        )
        for component_id, service_cls in services:
            for method_name, contract in self._service_target_contracts(
                service_cls=service_cls
            ).items():
                key = f"{component_id}.{method_name}"
                contracts[key] = contract
        return contracts

    def _service_target_contracts(
        self, *, service_cls: type[Any]
    ) -> dict[str, CallTargetContract]:
        contracts: dict[str, CallTargetContract] = {}
        for method_name, method in inspect.getmembers(
            service_cls, predicate=inspect.isfunction
        ):
            if method_name.startswith("_"):
                continue
            signature = inspect.signature(method)
            try:
                hints = get_type_hints(method)
            except Exception:
                hints = {}
            contracts[method_name] = CallTargetContract(
                input_schema=self._schema_from_signature(signature, hints),
                output_schema=self._schema_from_return_annotation(
                    hints.get("return", signature.return_annotation)
                ),
            )
        return contracts

    def _schema_from_signature(
        self,
        signature: inspect.Signature,
        hints: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        properties = {}
        required = []
        for parameter in signature.parameters.values():
            if parameter.name in {"self", "meta"}:
                continue
            annotation = (
                hints.get(parameter.name, parameter.annotation)
                if hints
                else parameter.annotation
            )
            prop_schema = self._schema_from_annotation(annotation)
            properties[parameter.name] = prop_schema
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)

        if not properties:
            return None

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }

        if required:
            schema["required"] = required
        return schema

    def _schema_from_return_annotation(self, annotation: Any) -> dict[str, Any] | None:
        if annotation is inspect.Signature.empty:
            return None
        # Unpack Envelope[...] — try stdlib generics first, then Pydantic metadata
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is None or not args:
            pydantic_meta = getattr(annotation, "__pydantic_generic_metadata__", None)
            if pydantic_meta:
                origin = pydantic_meta.get("origin")
                args = pydantic_meta.get("args", ())
        if (
            origin is not None
            and getattr(origin, "__name__", "") == "Envelope"
            and args
        ):
            return self._schema_from_annotation(args[0])
        return self._schema_from_annotation(annotation)

    def _schema_from_annotation(self, annotation: Any) -> dict[str, Any]:
        type_map = {
            str: {"type": "string"},
            int: {"type": "integer"},
            bool: {"type": "boolean"},
            float: {"type": "number"},
            datetime: {"type": "date-time"},
            dict: {"type": "object"},
            NoneType: {"type": "null"},
        }
        if annotation in type_map:
            return type_map[annotation]

        if annotation is Any:
            return {}  # Any type

        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is list or origin is Sequence:
            return {"type": "array", "items": self._schema_from_annotation(args[0])}

        if origin is Union or origin is UnionType:
            # Handles Optional[X] which is Union[X, None]
            return {"anyOf": [self._schema_from_annotation(arg) for arg in args]}

        if isinstance(annotation, ForwardRef):
            # Handle forward references by creating a schema for a dictionary
            return {"type": "object"}

        if hasattr(annotation, "__name__"):
            return {"type": "object", "title": annotation.__name__}

        return {"type": "object"}  # Default fallback

    def _build_slash_index(
        self,
        manifests: dict[str, CapabilityManifest],
    ) -> dict[str, CapabilityManifest]:
        """Build the slash command name/alias → manifest index from discovered manifests."""
        index: dict[str, CapabilityManifest] = {}
        for manifest in manifests.values():
            sc = manifest.slash_command
            if sc is None:
                continue
            resolved_name = sc.name or manifest.capability_id
            for token in (resolved_name, *sc.aliases):
                key = token.lower()
                if key in index:
                    raise ValueError(
                        f"duplicate slash command '{key}' in "
                        f"'{index[key].capability_id}' and '{manifest.capability_id}'"
                    )
                index[key] = manifest
        return index

    def resolve_slash_command(self, *, name: str) -> CapabilityManifest | None:
        """Return the manifest bound to one slash command name or alias."""
        return self._slash_commands.get(name.lower())

    def list_slash_commands(self) -> tuple[CapabilityManifest, ...]:
        """Return all manifests that expose a slash command, in stable order, deduplicated."""
        seen: set[str] = set()
        result: list[CapabilityManifest] = []
        for manifest in (self._slash_commands[k] for k in sorted(self._slash_commands)):
            if manifest.capability_id not in seen:
                seen.add(manifest.capability_id)
                result.append(manifest)
        return tuple(result)

    def register_manifest(self, *, manifest: CapabilityManifest) -> None:
        """Register one manifest directly without filesystem discovery."""
        self._manifests[manifest.capability_id] = manifest
        sc = manifest.slash_command
        if sc is not None:
            resolved_name = sc.name or manifest.capability_id
            for token in (resolved_name, *sc.aliases):
                self._slash_commands[token.lower()] = manifest

    def register_handler(
        self,
        *,
        capability_id: str,
        handler: CapabilityHandler,
    ) -> None:
        """Register one runtime handler for an existing capability manifest."""
        self._handlers[capability_id] = handler

    def resolve_manifest(self, *, capability_id: str) -> CapabilityManifest | None:
        """Resolve one capability manifest by package capability identifier."""
        return self._manifests.get(capability_id)

    def resolve_handler(self, *, capability_id: str) -> CapabilityHandler | None:
        """Resolve one capability handler by package capability identifier."""
        return self._handlers.get(capability_id)

    def list_manifests(self) -> tuple[CapabilityManifest, ...]:
        """Return all registered capability manifests in stable order."""
        return tuple(self._manifests[k] for k in sorted(self._manifests))

    def count(self) -> int:
        """Return number of discovered capability manifests."""
        return len(self._manifests)
