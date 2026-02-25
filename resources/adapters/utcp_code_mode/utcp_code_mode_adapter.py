"""Local file-backed implementation of the UTCP code-mode adapter."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import yaml

from resources.adapters.utcp_code_mode.adapter import (
    UtcpCodeModeAdapter,
    UtcpCodeModeConfig,
    UtcpCodeModeConfigNotFoundError,
    UtcpCodeModeConfigParseError,
    UtcpCodeModeConfigSchemaError,
    UtcpCodeModeConfigReadError,
    UtcpCodeModeLoadResult,
    UtcpMcpManualCallTemplate,
    UtcpMcpTemplateSummary,
    UtcpOperatorYamlConfig,
)
from resources.adapters.utcp_code_mode.config import UtcpCodeModeAdapterSettings


class LocalFileUtcpCodeModeAdapter(UtcpCodeModeAdapter):
    """UTCP code-mode adapter that loads operator YAML and generates UTCP JSON."""

    def __init__(self, *, settings: UtcpCodeModeAdapterSettings) -> None:
        self._settings = settings

    def load(self) -> UtcpCodeModeLoadResult:
        """Load operator YAML, generate canonical config, and summarize MCP data."""
        source_path = self._settings.yaml_config_path()
        generated_path = self._settings.generated_json_path()

        source_payload = _read_yaml_file(path=source_path)
        source_config = _validate_operator_yaml(
            payload=source_payload, path=source_path
        )
        generated_payload = _transpose_operator_yaml_to_utcp_config_payload(
            source_config=source_config
        )
        config = _validate_config(payload=generated_payload, path=source_path)
        _write_generated_json_file(config=config, path=generated_path)
        mcp_templates = _extract_mcp_templates(config=config, path=source_path)
        return UtcpCodeModeLoadResult(
            config=config,
            mcp_templates=mcp_templates,
            generated_json_path=str(generated_path),
        )


def _read_yaml_file(*, path: Path) -> object:
    """Read and parse one YAML file or raise explicit adapter exceptions."""
    if not path.exists():
        raise UtcpCodeModeConfigNotFoundError(
            f"utcp operator yaml config file not found: {path}"
        ) from None
    if not path.is_file():
        raise UtcpCodeModeConfigReadError(
            f"utcp operator yaml config path is not a file: {path}"
        ) from None

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UtcpCodeModeConfigReadError(
            f"failed to read utcp operator yaml config '{path}': {exc}"
        ) from None

    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        line = getattr(exc, "problem_mark", None)
        if line is not None:
            location = f" at line {line.line + 1}, column {line.column + 1}"
        else:
            location = ""
        raise UtcpCodeModeConfigParseError(
            f"utcp operator yaml config contains invalid YAML{location}"
        ) from None


def _validate_config(*, payload: object, path: Path) -> UtcpCodeModeConfig:
    """Validate canonical payload against UTCP config schema."""
    try:
        return UtcpCodeModeConfig.model_validate(payload)
    except ValidationError as exc:
        raise UtcpCodeModeConfigSchemaError(
            f"generated utcp config schema validation failed for source '{path}': {exc}"
        ) from None


def _validate_operator_yaml(*, payload: object, path: Path) -> UtcpOperatorYamlConfig:
    """Validate source YAML against operator-facing UTCP schema."""
    try:
        return UtcpOperatorYamlConfig.model_validate(payload)
    except ValidationError as exc:
        raise UtcpCodeModeConfigSchemaError(
            f"utcp operator yaml schema validation failed for '{path}': {exc}"
        ) from None


def _transpose_operator_yaml_to_utcp_config_payload(
    *,
    source_config: UtcpOperatorYamlConfig,
) -> dict[str, object]:
    """Transpose operator YAML schema into canonical UTCP JSON config payload."""
    call_template_type = source_config.code_mode.defaults.call_template_type
    manual_call_templates: list[dict[str, object]] = []
    for server_name in sorted(source_config.code_mode.servers):
        server_config = source_config.code_mode.servers[server_name]
        manual_call_templates.append(
            {
                "name": server_name,
                "call_template_type": call_template_type,
                "config": {
                    "mcpServers": {
                        server_name: server_config,
                    }
                },
            }
        )
    return {"manual_call_templates": manual_call_templates}


def _write_generated_json_file(*, config: UtcpCodeModeConfig, path: Path) -> None:
    """Persist one generated canonical UTCP config JSON file."""
    payload = config.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    serialized = json.dumps(payload, indent=2)
    if path.exists() and not path.is_file():
        raise UtcpCodeModeConfigReadError(
            f"generated utcp config path is not a file: {path}"
        ) from None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{serialized}\n", encoding="utf-8")
    except OSError as exc:
        raise UtcpCodeModeConfigReadError(
            f"failed to write generated utcp config '{path}': {exc}"
        ) from None


def _extract_mcp_templates(
    *,
    config: UtcpCodeModeConfig,
    path: Path,
) -> tuple[UtcpMcpTemplateSummary, ...]:
    """Extract only ``call_template_type='mcp'`` templates with server names."""
    summaries: list[UtcpMcpTemplateSummary] = []
    for index, item in enumerate(config.manual_call_templates):
        if item.call_template_type.strip() != "mcp":
            continue
        try:
            mcp_template = UtcpMcpManualCallTemplate.model_validate(
                item.model_dump(mode="python")
            )
        except ValidationError as exc:
            raise UtcpCodeModeConfigSchemaError(
                f"invalid mcp manual_call_templates[{index}] in '{path}': {exc}"
            ) from None
        server_names = tuple(sorted(mcp_template.config.mcp_servers.keys()))
        summaries.append(
            UtcpMcpTemplateSummary(
                name=mcp_template.name,
                server_names=server_names,
            )
        )

    if len(summaries) == 0:
        raise UtcpCodeModeConfigSchemaError(
            f"utcp config '{path}' does not define any mcp manual_call_templates"
        ) from None
    return tuple(summaries)
