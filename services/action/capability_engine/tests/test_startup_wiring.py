"""Unit tests for CES startup wiring via ``DefaultCapabilityEngineService.from_settings``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import Envelope
from resources.adapters.utcp_code_mode import (
    UtcpCodeModeConfigNotFoundError,
    UtcpCodeModeConfigParseError,
)
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    PolicyExecutionResult,
    PolicyHealthStatus,
)
from services.action.policy_service.service import PolicyExecuteCallback, PolicyService


class _FakePolicyService(PolicyService):
    """Minimal Policy Service stub for CES from_settings construction tests."""

    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        raise NotImplementedError("not used by these tests")

    def health(self, *, meta: Any) -> Envelope[PolicyHealthStatus]:
        raise NotImplementedError("not used by these tests")


@dataclass(frozen=True)
class _FakeRuntime:
    """Lightweight CES runtime stub providing only required constructor fields."""

    schema_sessions: object


def _base_components(tmp_path: Path) -> dict[str, object]:
    """Return minimum component config used by CES ``from_settings`` tests."""
    return {
        "service": {
            "capability_engine": {
                "discovery_root": str(tmp_path / "capabilities"),
            }
        },
        "adapter": {
            "utcp_code_mode": {
                "utcp_yaml_config_path": str(tmp_path / "utcp.yaml"),
                "generated_utcp_json_path": str(tmp_path / "generated-utcp.json"),
            }
        },
    }


def test_ces_from_settings_fails_when_utcp_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CES startup should fail hard when configured UTCP YAML file does not exist."""
    monkeypatch.setattr(
        "services.action.capability_engine.implementation.CapabilityEnginePostgresRuntime.from_settings",
        lambda _settings: _FakeRuntime(schema_sessions=object()),
    )
    settings = BrainSettings(components=_base_components(tmp_path))

    with pytest.raises(UtcpCodeModeConfigNotFoundError):
        DefaultCapabilityEngineService.from_settings(
            settings,
            policy_service=_FakePolicyService(),
        )


def test_ces_from_settings_fails_when_utcp_file_has_invalid_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CES startup should fail hard when configured UTCP YAML is malformed."""
    monkeypatch.setattr(
        "services.action.capability_engine.implementation.CapabilityEnginePostgresRuntime.from_settings",
        lambda _settings: _FakeRuntime(schema_sessions=object()),
    )
    (tmp_path / "utcp.yaml").write_text("code_mode: [", encoding="utf-8")
    settings = BrainSettings(components=_base_components(tmp_path))

    with pytest.raises(UtcpCodeModeConfigParseError):
        DefaultCapabilityEngineService.from_settings(
            settings,
            policy_service=_FakePolicyService(),
        )


def test_ces_from_settings_succeeds_with_valid_utcp_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CES startup should succeed when configured UTCP YAML fixture is valid."""
    monkeypatch.setattr(
        "services.action.capability_engine.implementation.CapabilityEnginePostgresRuntime.from_settings",
        lambda _settings: _FakeRuntime(schema_sessions=object()),
    )
    (tmp_path / "utcp.yaml").write_text(
        """
code_mode:
  defaults:
    call_template_type: mcp
  servers:
    filesystem:
      command: npx
      args:
        - -y
        - "@modelcontextprotocol/server-filesystem"
        - "/tmp"
""".strip(),
        encoding="utf-8",
    )
    settings = BrainSettings(components=_base_components(tmp_path))

    service = DefaultCapabilityEngineService.from_settings(
        settings,
        policy_service=_FakePolicyService(),
    )

    assert isinstance(service, DefaultCapabilityEngineService)
    generated_payload = json.loads(
        (tmp_path / "generated-utcp.json").read_text(encoding="utf-8")
    )
    assert isinstance(generated_payload, dict)
    assert len(generated_payload["manual_call_templates"]) == 1
    assert generated_payload["manual_call_templates"][0]["name"] == "filesystem"
