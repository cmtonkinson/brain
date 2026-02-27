"""Settings-driven implementation of the UTCP code-mode adapter."""

from __future__ import annotations

from pydantic import ValidationError

from resources.adapters.utcp_code_mode.adapter import (
    UtcpCodeModeAdapter,
    UtcpCodeModeConfig,
    UtcpCodeModeConfigSchemaError,
    UtcpCodeModeHealthStatus,
    UtcpCodeModeLoadResult,
    UtcpMcpManualCallTemplate,
    UtcpMcpTemplateSummary,
)
from resources.adapters.utcp_code_mode.config import UtcpCodeModeAdapterSettings


class LocalFileUtcpCodeModeAdapter(UtcpCodeModeAdapter):
    """UTCP code-mode adapter that builds config from inline settings."""

    def __init__(self, *, settings: UtcpCodeModeAdapterSettings) -> None:
        self._settings = settings

    def health(self) -> UtcpCodeModeHealthStatus:
        """Always ready — config is inline, no external dependency."""
        return UtcpCodeModeHealthStatus(ready=True, detail="ok")

    def load(self) -> UtcpCodeModeLoadResult:
        """Build canonical UTCP config from inline adapter settings."""
        code_mode = self._settings.code_mode
        generated_payload = _transpose_to_utcp_config_payload(code_mode)
        config = _validate_config(payload=generated_payload)
        mcp_templates = _extract_mcp_templates(config=config)
        return UtcpCodeModeLoadResult(
            config=config,
            mcp_templates=mcp_templates,
        )


def _validate_config(*, payload: object) -> UtcpCodeModeConfig:
    """Validate canonical payload against UTCP config schema."""
    try:
        return UtcpCodeModeConfig.model_validate(payload)
    except ValidationError as exc:
        raise UtcpCodeModeConfigSchemaError(
            f"utcp config schema validation failed: {exc}"
        ) from None


def _transpose_to_utcp_config_payload(
    code_mode: object,
) -> dict[str, object]:
    """Transpose inline code_mode settings into canonical UTCP config payload."""
    call_template_type = code_mode.defaults.call_template_type  # type: ignore[union-attr]
    manual_call_templates: list[dict[str, object]] = []
    for server_name in sorted(code_mode.servers):  # type: ignore[union-attr]
        server_config = code_mode.servers[server_name]  # type: ignore[union-attr]
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


def _extract_mcp_templates(
    *,
    config: UtcpCodeModeConfig,
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
                f"invalid mcp manual_call_templates[{index}]: {exc}"
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
            "utcp config does not define any mcp manual_call_templates"
        ) from None
    return tuple(summaries)
