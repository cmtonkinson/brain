"""Tests for merged-directory shared configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.shared.config import (
    ActorCoreConnectionSettings,
    CoreRuntimeSettings,
    CoreSettings,
    LoggingSettings,
    ObservabilitySettings,
    ProfileSettings,
    ResourcesSettings,
    load_actor_settings,
    load_core_runtime_settings,
    load_core_settings,
    load_resources_settings,
    resolve_component_settings,
)
from lib.shared.config.models import AssistantActorSettings
from resources.adapters.llm.config import (
    LlmAdapterSettings,
    resolve_llm_adapter_settings,
)
from resources.substrates.postgres.config import PostgresSettings
from resources.substrates.seaweedfs.config import SeaweedFSSubstrateSettings
from services.state.embedding.component import SERVICE_COMPONENT_ID
from services.state.embedding.config import EmbeddingServiceSettings


def _write_yaml(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def _install_samples(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sample_dir = repo_root / "config"
    for sample_path in sorted(sample_dir.glob("*.yaml.sample")):
        target = tmp_path / sample_path.name.removesuffix(".sample")
        target.write_text(sample_path.read_text(encoding="utf-8"), encoding="utf-8")


def test_load_core_settings_uses_brain_precedence_cascade(tmp_path: Path) -> None:
    """CLI params override env, env overrides YAML, then defaults."""
    _write_yaml(
        tmp_path / "shared.yaml",
        [
            "logging:",
            "  level: WARNING",
            "core:",
            "  boot:",
            "    boot_retry_attempts: 5",
        ],
    )

    settings = load_core_settings(
        cli_params={"logging": {"level": "DEBUG"}},
        environ={
            "BRAIN_LOGGING__LEVEL": "ERROR",
            "BRAIN_CORE__BOOT__BOOT_RETRY_ATTEMPTS": "4",
            "BRAIN_CORE__HTTP__HOST": "127.0.0.9",
            "BRAIN_CORE__HTTP__PORT": "8123",
        },
        config_path=tmp_path,
    )

    assert settings.logging.level == "DEBUG"
    assert settings.boot.boot_retry_attempts == 4
    assert settings.http.host == "127.0.0.9"
    assert settings.http.port == 8123


def test_load_core_runtime_settings_resolves_substrate_component(
    tmp_path: Path,
) -> None:
    """Component resolution should read direct resource roots."""
    _write_yaml(tmp_path / "state.yaml", ["postgres:", "  pool_size: 7"])

    runtime = load_core_runtime_settings(
        core_config_path=tmp_path,
        environ={
            "BRAIN_SEAWEEDFS__ACCESS_KEY_ID": "test-key",
            "BRAIN_SEAWEEDFS__SECRET_ACCESS_KEY": "test-secret",
        },
    )

    postgres = resolve_component_settings(
        settings=runtime,
        component_id="substrate_postgres",
        model=PostgresSettings,
    )
    assert postgres.pool_size == 7


def test_load_resources_settings_reads_component_root_env_keys(tmp_path: Path) -> None:
    """Resource env overrides should use `BRAIN_{COMPONENT}__...`."""
    resources = load_resources_settings(
        config_path=tmp_path,
        environ={
            "BRAIN_SEAWEEDFS__ACCESS_KEY_ID": "test-key",
            "BRAIN_SEAWEEDFS__SECRET_ACCESS_KEY": "test-secret",
        },
    )

    runtime = load_core_runtime_settings(
        core_config_path=tmp_path,
        environ={
            "BRAIN_SEAWEEDFS__ACCESS_KEY_ID": "test-key",
            "BRAIN_SEAWEEDFS__SECRET_ACCESS_KEY": "test-secret",
        },
    )
    resolved = resolve_component_settings(
        settings=runtime,
        component_id="substrate_seaweedfs",
        model=SeaweedFSSubstrateSettings,
    )

    assert isinstance(resources, ResourcesSettings)
    assert resolved.access_key_id == "test-key"
    assert resolved.secret_access_key == "test-secret"


def test_load_core_runtime_settings_resolves_service_component(tmp_path: Path) -> None:
    """Component resolution should read direct service roots."""
    _write_yaml(tmp_path / "state.yaml", ["embedding:", "  max_list_limit: 250"])

    runtime = load_core_runtime_settings(core_config_path=tmp_path, environ={})

    embedding = resolve_component_settings(
        settings=runtime,
        component_id=str(SERVICE_COMPONENT_ID),
        model=EmbeddingServiceSettings,
    )
    assert embedding.max_list_limit == 250


def test_load_core_settings_uses_model_defaults_when_sources_missing(
    tmp_path: Path,
) -> None:
    """Missing YAML and env should fall back to model defaults."""
    settings = load_core_settings(config_path=tmp_path, environ={})

    assert settings.logging == LoggingSettings()
    assert settings.observability == ObservabilitySettings()
    assert settings.profile.operator.signal_contact_e164 == "+12222222222"
    assert settings.http.host == "0.0.0.0"
    assert settings.http.port == 8898


def test_load_core_settings_reads_profile_preferred_timezone(tmp_path: Path) -> None:
    """Preferred timezone should load from the shared profile root."""
    _write_yaml(
        tmp_path / "shared.yaml",
        ["profile:", "  preferred_timezone: America/New_York"],
    )

    settings = load_core_settings(config_path=tmp_path, environ={})

    assert settings.profile.preferred_timezone == "America/New_York"


def test_load_core_settings_rejects_invalid_profile_preferred_timezone(
    tmp_path: Path,
) -> None:
    """Invalid timezone configuration should fail at load time."""
    _write_yaml(
        tmp_path / "shared.yaml",
        ["profile:", "  preferred_timezone: Mars/Olympus"],
    )

    with pytest.raises(ValueError, match="invalid preferred_timezone"):
        load_core_settings(config_path=tmp_path, environ={})


def test_load_actor_settings_reads_assistant_prompt_settings(tmp_path: Path) -> None:
    """Actor config should load prompt settings from the `assistant` root."""
    _write_yaml(
        tmp_path / "actors.yaml",
        [
            "assistant:",
            "  personality: focused",
            "  operator_profile: Refer to me as 'captain'",
            "  system_prompt_append: Appendix",
        ],
    )

    settings = load_actor_settings(config_path=tmp_path, environ={})

    assert settings.assistant.personality == "focused"
    assert settings.assistant.operator_profile == "Refer to me as 'captain'"
    assert settings.assistant.system_prompt_append == "Appendix"


def test_load_actor_settings_reads_dynamic_environment_context_inputs(
    tmp_path: Path,
) -> None:
    """Assistant environment-context entries should validate recursive resolvers."""
    _write_yaml(
        tmp_path / "actors.yaml",
        [
            "assistant:",
            "  environment_context:",
            "    - op_id: eventkit--list-calendar-events",
            "      input_payload:",
            "        start_date:",
            "          resolve: local_datetime_boundary",
            "          boundary: start_of_day",
            "          day_offset: 0",
            "        end_date:",
            "          resolve: local_datetime_boundary",
            "          boundary: end_of_day",
            "          day_offset: 1",
        ],
    )

    settings = load_actor_settings(config_path=tmp_path, environ={})

    entry = settings.assistant.environment_context[0]
    assert entry.op_id == "eventkit--list-calendar-events"
    assert entry.input_payload["start_date"]["format"] == "iso8601"
    assert entry.input_payload["end_date"]["day_offset"] == 1


def test_load_core_settings_applies_secrets_yaml_over_non_secret_yaml(
    tmp_path: Path,
) -> None:
    """Secrets files should merge by lexical order and override sibling files."""
    _write_yaml(
        tmp_path / "shared.yaml",
        [
            "profile:",
            "  operator_name: Public Operator",
            "logging:",
            "  level: WARNING",
        ],
    )
    _write_yaml(
        tmp_path / "zz-secrets.local.yaml",
        ["profile:", "  operator_name: Private Operator"],
    )

    settings = load_core_settings(config_path=tmp_path, environ={})

    assert settings.profile.operator_name == "Private Operator"
    assert settings.logging.level == "WARNING"


def test_load_resources_settings_deep_merges_yaml_mappings(tmp_path: Path) -> None:
    """Split config files should deep-merge nested component settings."""
    _write_yaml(
        tmp_path / "effect.yaml",
        [
            "llm:",
            "  providers:",
            "    anthropic:",
            "      api_base: https://api.anthropic.com",
        ],
    )
    _write_yaml(
        tmp_path / "secrets.private.yaml",
        [
            "llm:",
            "  providers:",
            "    anthropic:",
            "      api_key: secret-key",
        ],
    )

    runtime = load_core_runtime_settings(core_config_path=tmp_path, environ={})
    resolved = resolve_llm_adapter_settings(runtime)

    assert resolved.providers["anthropic"].api_base == "https://api.anthropic.com"
    assert resolved.providers["anthropic"].api_key == "secret-key"
    assert resolved.providers["voyage"].api_base == "https://api.voyageai.com"


def test_resolve_component_settings_deep_merges_component_model_defaults() -> None:
    """Nested model defaults should survive partial direct component overrides."""
    runtime = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings={
            "llm": {
                "providers": {
                    "anthropic": {
                        "api_key": "secret-key",
                    }
                }
            }
        },
    )

    resolved = resolve_llm_adapter_settings(runtime)

    assert isinstance(resolved, LlmAdapterSettings)
    assert resolved.providers["anthropic"].api_base == "https://api.anthropic.com"
    assert resolved.providers["anthropic"].api_key == "secret-key"
    assert resolved.providers["voyage"].options == {"output_dimension": 2048}


def test_load_actor_settings_deep_merges_assistant_defaults_with_secrets_yaml(
    tmp_path: Path,
) -> None:
    """Assistant overrides should preserve model defaults under partial merges."""
    _write_yaml(
        tmp_path / "actors.yaml",
        ["assistant:", "  principal: assistant", "  personality: focused"],
    )
    _write_yaml(
        tmp_path / "secrets.local.yaml",
        ["assistant:", "  source: test-assistant", "  system_prompt_append: Appendix"],
    )

    actors = load_actor_settings(config_path=tmp_path, environ={})

    assert actors.assistant.principal == "assistant"
    assert actors.assistant.source == "test-assistant"
    assert actors.assistant.personality == "focused"
    assert actors.assistant.operator_profile == "Refer to me as 'boss'"
    assert actors.assistant.system_prompt_append == "Appendix"


def test_core_runtime_settings_exposes_profile_via_core() -> None:
    """The runtime settings dataclass should expose profile through `.core.profile`."""
    runtime_settings = load_core_runtime_settings()
    assert not hasattr(runtime_settings, "profile")
    profile = runtime_settings.core.profile
    assert isinstance(profile, ProfileSettings)
    assert profile.operator_name


def test_sample_config_files_load_cleanly(tmp_path: Path) -> None:
    """Checked-in sample config files should validate after lexical merge."""
    _install_samples(tmp_path)

    core = load_core_settings(config_path=tmp_path, environ={})
    runtime = load_core_runtime_settings(core_config_path=tmp_path, environ={})
    actors = load_actor_settings(config_path=tmp_path, environ={})
    postgres = resolve_component_settings(
        settings=runtime,
        component_id="substrate_postgres",
        model=PostgresSettings,
    )

    assert core.http.host == "0.0.0.0"
    assert core.http.port == 8898
    assert actors.logging.process_name is None
    assert postgres.url == PostgresSettings().url


def test_sample_config_files_match_current_schema_exactly(tmp_path: Path) -> None:
    """Merged sample files should produce the current typed default surfaces."""
    _install_samples(tmp_path)

    core = load_core_settings(config_path=tmp_path, environ={})
    actors = load_actor_settings(config_path=tmp_path, environ={})
    runtime = load_core_runtime_settings(core_config_path=tmp_path, environ={})

    assert core.logging == LoggingSettings()
    assert core.profile.operator_name == ProfileSettings().operator_name
    assert actors.core == ActorCoreConnectionSettings()
    assert actors.assistant == AssistantActorSettings()
    assert (
        resolve_component_settings(
            settings=runtime,
            component_id="substrate_postgres",
            model=PostgresSettings,
        ).url
        == PostgresSettings().url
    )
