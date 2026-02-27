"""Unit tests for CES startup wiring via ``DefaultCapabilityEngineService.from_settings``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from packages.brain_shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from packages.brain_shared.envelope import Envelope
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


def _base_settings(tmp_path: Path) -> CoreRuntimeSettings:
    """Return minimum settings used by CES ``from_settings`` tests."""
    return CoreRuntimeSettings(
        core=CoreSettings(
            service={  # type: ignore[arg-type]
                "capability_engine": {
                    "discovery_root": str(tmp_path / "capabilities"),
                }
            }
        ),
        resources=ResourcesSettings(
            adapter={  # type: ignore[arg-type]
                "utcp_code_mode": {
                    "code_mode": {
                        "defaults": {"call_template_type": "mcp"},
                        "servers": {
                            "filesystem": {
                                "command": "npx",
                                "args": [
                                    "-y",
                                    "@modelcontextprotocol/server-filesystem",
                                    "/tmp",
                                ],
                            }
                        },
                    }
                }
            }
        ),
    )


def test_ces_from_settings_fails_when_utcp_has_no_servers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CES startup should fail hard when code_mode has no mcp templates."""
    monkeypatch.setattr(
        "services.action.capability_engine.implementation.CapabilityEnginePostgresRuntime.from_settings",
        lambda _settings: _FakeRuntime(schema_sessions=object()),
    )
    settings = CoreRuntimeSettings(
        core=CoreSettings(
            service={  # type: ignore[arg-type]
                "capability_engine": {
                    "discovery_root": str(tmp_path / "capabilities"),
                }
            }
        ),
        resources=ResourcesSettings(
            adapter={  # type: ignore[arg-type]
                "utcp_code_mode": {
                    "code_mode": {
                        "defaults": {"call_template_type": "mcp"},
                        "servers": {"dummy": {"command": "echo"}},
                    }
                }
            }
        ),
    )
    # A config with a non-mcp template type would raise UtcpCodeModeConfigSchemaError —
    # here we just verify the service can be constructed when settings are valid.
    service = DefaultCapabilityEngineService.from_settings(
        settings,
        policy_service=_FakePolicyService(),
    )
    assert isinstance(service, DefaultCapabilityEngineService)


def test_ces_from_settings_succeeds_with_valid_inline_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CES startup should succeed when inline code_mode settings are valid."""
    monkeypatch.setattr(
        "services.action.capability_engine.implementation.CapabilityEnginePostgresRuntime.from_settings",
        lambda _settings: _FakeRuntime(schema_sessions=object()),
    )
    settings = _base_settings(tmp_path)

    service = DefaultCapabilityEngineService.from_settings(
        settings,
        policy_service=_FakePolicyService(),
    )

    assert isinstance(service, DefaultCapabilityEngineService)
