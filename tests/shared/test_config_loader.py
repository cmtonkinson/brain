"""Tests for pydantic-settings-backed shared configuration loading."""

from __future__ import annotations

from pathlib import Path

import yaml

from packages.brain_shared.config import (
    ApprovalResponseSettings,
    ActorCoreConnectionSettings,
    ActorNamespaceSettings,
    CoreRuntimeSettings,
    CoreSettings,
    CoreBootSettings,
    CoreHealthSettings,
    CoreHttpSettings,
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
from packages.brain_shared.config.models import AgentActorSettings, CliActorSettings
from packages.brain_shared.config.models import OperatorProfileSettings
from resources.adapters.litellm.config import resolve_litellm_adapter_settings
from resources.adapters.litellm.config import LiteLlmAdapterSettings
from resources.adapters.signal.config import SignalAdapterSettings
from resources.substrates.filesystem.config import FilesystemSubstrateSettings
from resources.substrates.obsidian.config import ObsidianSubstrateSettings
from resources.substrates.postgres.config import PostgresSettings
from resources.substrates.qdrant.config import QdrantSettings
from resources.substrates.redis.config import RedisSettings
from services.action.attention_router.config import AttentionRouterServiceSettings
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.language_model.config import LanguageModelServiceSettings
from services.action.policy_service.config import PolicyServiceSettings
from services.state.cache_authority.config import CacheAuthoritySettings
from services.state.embedding_authority.component import SERVICE_COMPONENT_ID
from services.state.embedding_authority.config import EmbeddingServiceSettings
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.object_authority.config import ObjectAuthoritySettings
from services.state.vault_authority.config import VaultAuthoritySettings


def test_load_core_settings_uses_brain_precedence_cascade(tmp_path: Path) -> None:
    """Init params should override env, env should override YAML, then defaults."""
    config_file = tmp_path / "core.yaml"
    config_file.write_text(
        "\n".join(
            [
                "logging:",
                "  level: WARNING",
                "boot:",
                "  boot_retry_attempts: 5",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_core_settings(
        cli_params={"logging": {"level": "DEBUG"}},
        environ={
            "BRAIN_CORE_LOGGING__LEVEL": "ERROR",
            "BRAIN_CORE_BOOT__BOOT_RETRY_ATTEMPTS": "4",
            "BRAIN_CORE_HTTP__HOST": "127.0.0.9",
            "BRAIN_CORE_HTTP__PORT": "8123",
        },
        config_path=config_file,
    )

    assert settings.logging.level == "DEBUG"
    assert settings.boot.boot_retry_attempts == 4
    assert settings.http.host == "127.0.0.9"
    assert settings.http.port == 8123


def test_load_core_runtime_settings_resolves_substrate_component(
    tmp_path: Path,
) -> None:
    """resolve_component_settings should find substrate config from resources settings."""
    resources_file = tmp_path / "resources.yaml"
    resources_file.write_text(
        "\n".join(
            [
                "substrate:",
                "  postgres:",
                "    pool_size: 7",
            ]
        ),
        encoding="utf-8",
    )

    runtime = load_core_runtime_settings(
        resources_config_path=resources_file,
        core_config_path=tmp_path / "core.yaml",
    )

    postgres = resolve_component_settings(
        settings=runtime,
        component_id="substrate_postgres",
        model=PostgresSettings,
    )
    assert postgres.pool_size == 7


def test_load_core_runtime_settings_resolves_service_component(tmp_path: Path) -> None:
    """resolve_component_settings should find service config from core settings."""
    core_file = tmp_path / "core.yaml"
    core_file.write_text(
        "\n".join(
            [
                "service:",
                "  embedding_authority:",
                "    max_list_limit: 250",
            ]
        ),
        encoding="utf-8",
    )

    runtime = load_core_runtime_settings(
        core_config_path=core_file,
        resources_config_path=tmp_path / "resources.yaml",
    )

    embedding = resolve_component_settings(
        settings=runtime,
        component_id=str(SERVICE_COMPONENT_ID),
        model=EmbeddingServiceSettings,
    )
    assert embedding.max_list_limit == 250


def test_load_core_settings_uses_model_defaults_when_sources_missing(
    tmp_path: Path,
) -> None:
    """Settings should fall back to model defaults when env and YAML are absent."""
    settings = load_core_settings(config_path=tmp_path / "core.yaml", environ={})

    assert settings.logging.process_name == "core"
    assert settings.logging.level == "INFO"
    assert settings.logging.file_capture_enabled is False
    assert settings.logging.file_capture_level == "VERBOSE"
    assert settings.logging.file_capture_directory == "logs"
    assert settings.boot.boot_retry_attempts == 3
    assert settings.http.host == "0.0.0.0"
    assert settings.http.port == 8898
    assert settings.profile.operator.signal_contact_e164 == "+12222222222"
    assert settings.profile.operator_name == "Operator"


def test_load_actor_settings_reads_agent_prompt_settings(tmp_path: Path) -> None:
    """actors.yaml should support agent-owned prompt settings."""
    config_file = tmp_path / "actors.yaml"
    config_file.write_text(
        "\n".join(
            [
                "agent:",
                "  personality: focused",
                "  profile_context: Refer to me as 'captain'",
                "  system_prompt_append: Appendix",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_actor_settings(config_path=config_file, environ={})

    assert settings.agent.personality == "focused"
    assert settings.agent.profile_context == "Refer to me as 'captain'"
    assert settings.agent.system_prompt_append == "Appendix"


def test_load_core_settings_applies_secrets_yaml_over_core_yaml(tmp_path: Path) -> None:
    """Optional secrets.yaml should override matching keys from core.yaml only."""
    config_file = tmp_path / "core.yaml"
    config_file.write_text(
        "\n".join(
            [
                "profile:",
                "  operator_name: Public Operator",
                "logging:",
                "  level: WARNING",
            ]
        ),
        encoding="utf-8",
    )
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text(
        "\n".join(
            [
                "profile:",
                "  operator_name: Private Operator",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_core_settings(config_path=config_file, environ={})

    assert settings.profile.operator_name == "Private Operator"
    assert settings.logging.level == "WARNING"


def test_load_core_settings_ignores_secrets_yaml_when_missing(tmp_path: Path) -> None:
    """core.yaml values should be used unchanged when secrets.yaml does not exist."""
    config_file = tmp_path / "core.yaml"
    config_file.write_text(
        "\n".join(
            [
                "profile:",
                "  operator_name: Public Operator",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_core_settings(config_path=config_file, environ={})

    assert settings.profile.operator_name == "Public Operator"


def test_load_resources_settings_deep_merges_yaml_mappings(tmp_path: Path) -> None:
    """resources.yaml and secrets.yaml should deep-merge nested dict settings."""
    resources_file = tmp_path / "resources.yaml"
    resources_file.write_text(
        "\n".join(
            [
                "adapter:",
                "  litellm:",
                "    providers:",
                "      ollama:",
                "        api_base: http://host.docker.internal:11434",
            ]
        ),
        encoding="utf-8",
    )
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text(
        "\n".join(
            [
                "adapter:",
                "  litellm:",
                "    providers:",
                "      anthropic:",
                "        api_key: secret-key",
            ]
        ),
        encoding="utf-8",
    )

    resources = load_resources_settings(config_path=resources_file, environ={})
    runtime = load_core_runtime_settings(
        core_config_path=tmp_path / "core.yaml",
        resources_config_path=resources_file,
        environ={},
    )

    assert resources.adapter.model_dump(mode="python")["litellm"]["providers"] == {
        "ollama": {"api_base": "http://host.docker.internal:11434"},
        "anthropic": {"api_key": "secret-key"},
    }
    resolved = resolve_litellm_adapter_settings(runtime)
    assert set(resolved.providers) == {"ollama", "anthropic"}


def test_resolve_component_settings_deep_merges_component_model_defaults() -> None:
    """Component resolution should preserve nested model defaults under overrides."""
    runtime = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate(
            {
                "adapter": {
                    "litellm": {
                        "providers": {
                            "anthropic": {
                                "api_key": "secret-key",
                            }
                        }
                    }
                }
            }
        ),
    )

    resolved = resolve_litellm_adapter_settings(runtime)

    assert set(resolved.providers) == {"ollama", "anthropic"}
    assert resolved.providers["ollama"].api_base == "http://host.docker.internal:11434"
    assert resolved.providers["anthropic"].api_key == "secret-key"


def test_load_actor_settings_deep_merges_agent_defaults_with_secrets_yaml(
    tmp_path: Path,
) -> None:
    """Actor config overrides should preserve default deny-list entries."""
    actors_file = tmp_path / "actors.yaml"
    actors_file.write_text(
        "\n".join(
            [
                "agent:",
                "  principal: assistant",
                "  personality: focused",
            ]
        ),
        encoding="utf-8",
    )
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text(
        "\n".join(
            [
                "agent:",
                "  source: test-agent",
                "  system_prompt_append: Appendix",
            ]
        ),
        encoding="utf-8",
    )

    actors = load_actor_settings(config_path=actors_file, environ={})

    assert actors.agent.principal == "assistant"
    assert actors.agent.source == "test-agent"
    assert actors.agent.personality == "focused"
    assert actors.agent.profile_context == "Refer to me as 'boss'"
    assert actors.agent.system_prompt_append == "Appendix"
    assert actors.agent.capability_discovery_deny_list == ("attention-notify",)
    assert actors.agent.tool_loop_tier2_hop_threshold == 3


def test_core_runtime_settings_exposes_profile_via_core() -> None:
    """CoreRuntimeSettings must access profile via .core.profile, not .profile."""
    runtime_settings = load_core_runtime_settings()

    # CoreRuntimeSettings should NOT have a top-level .profile attribute.
    assert not hasattr(runtime_settings, "profile"), (
        "CoreRuntimeSettings must not expose 'profile' directly; "
        "use settings.core.profile instead"
    )

    # The correct path should work.
    profile = runtime_settings.core.profile
    assert profile.operator.signal_contact_e164
    assert profile.default_dial_code
    assert profile.operator_name
    assert profile.brain_name


def test_sample_config_files_load_cleanly(tmp_path: Path) -> None:
    """Checked-in sample config files should validate against current settings models."""
    repo_root = Path(__file__).resolve().parents[2]
    sample_dir = repo_root / "config"

    (tmp_path / "core.yaml").write_text(
        (sample_dir / "core.yaml.sample").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "resources.yaml").write_text(
        (sample_dir / "resources.yaml.sample").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "actors.yaml").write_text(
        (sample_dir / "actors.yaml.sample").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "secrets.yaml").write_text(
        (sample_dir / "secrets.yaml.sample").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    core = load_core_settings(config_path=tmp_path / "core.yaml", environ={})
    runtime = load_core_runtime_settings(
        core_config_path=tmp_path / "core.yaml",
        resources_config_path=tmp_path / "resources.yaml",
        environ={},
    )
    actors = load_actor_settings(config_path=tmp_path / "actors.yaml", environ={})

    assert core.http.host == "0.0.0.0"
    assert core.http.port == 8898
    assert (
        runtime.resources.substrate.model_dump(mode="python")["obsidian"][
            "timeout_seconds"
        ]
        == 10.0
    )
    assert core.logging.process_name == "core"
    assert actors.logging.process_name == "agent"
    assert actors.logging.json_output is True


def test_sample_config_files_match_current_schema_exactly() -> None:
    """Checked-in sample configs should stay in sync with current settings shapes."""
    repo_root = Path(__file__).resolve().parents[2]
    sample_dir = repo_root / "config"

    assert yaml.safe_load(
        (sample_dir / "core.yaml.sample").read_text(encoding="utf-8")
    ) == {
        "logging": LoggingSettings().model_dump(mode="json"),
        "observability": ObservabilitySettings().model_dump(mode="json"),
        "profile": {
            "operator": OperatorProfileSettings().model_dump(mode="json"),
            "approval_responses": ApprovalResponseSettings().model_dump(mode="json"),
            "default_dial_code": ProfileSettings().default_dial_code,
            "operator_name": ProfileSettings().operator_name,
            "brain_name": ProfileSettings().brain_name,
            "brain_verbosity": ProfileSettings().brain_verbosity,
        },
        "boot": CoreBootSettings().model_dump(mode="json"),
        "http": CoreHttpSettings().model_dump(mode="json"),
        "health": CoreHealthSettings().model_dump(mode="json"),
        "service": {
            "attention_router": AttentionRouterServiceSettings().model_dump(
                mode="json"
            ),
            "capability_engine": CapabilityEngineSettings().model_dump(mode="json"),
            "embedding_authority": EmbeddingServiceSettings().model_dump(mode="json"),
            "cache_authority": CacheAuthoritySettings().model_dump(mode="json"),
            "memory_authority": MemoryAuthoritySettings().model_dump(mode="json"),
            "object_authority": ObjectAuthoritySettings().model_dump(mode="json"),
            "policy_service": PolicyServiceSettings().model_dump(mode="json"),
            "vault_authority": VaultAuthoritySettings().model_dump(mode="json"),
            "language_model": LanguageModelServiceSettings(
                quick=LanguageModelServiceSettings.model_fields["standard"].default,
                deep=LanguageModelServiceSettings.model_fields["standard"].default,
            ).model_dump(mode="json"),
            "switchboard": {
                "queue_name": "signal_inbound",
                "callback_register_max_retries": 8,
                "callback_register_retry_delay_seconds": 2.0,
            },
        },
    }

    assert yaml.safe_load(
        (sample_dir / "resources.yaml.sample").read_text(encoding="utf-8")
    ) == {
        "substrate": {
            "filesystem": FilesystemSubstrateSettings().model_dump(mode="json"),
            "obsidian": {
                "base_url": ObsidianSubstrateSettings().base_url,
                "timeout_seconds": ObsidianSubstrateSettings().timeout_seconds,
                "max_retries": ObsidianSubstrateSettings().max_retries,
            },
            "postgres": PostgresSettings().model_dump(mode="json"),
            "qdrant": QdrantSettings().model_dump(mode="json"),
            "redis": RedisSettings().model_dump(mode="json"),
        },
        "adapter": {
            "litellm": {
                "timeout_seconds": LiteLlmAdapterSettings().timeout_seconds,
                "max_retries": LiteLlmAdapterSettings().max_retries,
                "timeout_retry_attempts": LiteLlmAdapterSettings().timeout_retry_attempts,
                "timeout_retry_initial_delay_seconds": LiteLlmAdapterSettings().timeout_retry_initial_delay_seconds,
                "timeout_retry_max_delay_seconds": LiteLlmAdapterSettings().timeout_retry_max_delay_seconds,
                "timeout_retry_backoff_multiplier": LiteLlmAdapterSettings().timeout_retry_backoff_multiplier,
                "timeout_retry_jitter_ratio": LiteLlmAdapterSettings().timeout_retry_jitter_ratio,
                "providers": {
                    "ollama": {
                        "api_base": LiteLlmAdapterSettings()
                        .providers["ollama"]
                        .api_base,
                        "timeout_seconds": LiteLlmAdapterSettings()
                        .providers["ollama"]
                        .timeout_seconds,
                        "max_retries": LiteLlmAdapterSettings()
                        .providers["ollama"]
                        .max_retries,
                        "options": LiteLlmAdapterSettings().providers["ollama"].options,
                    }
                },
            },
            "signal": {
                "base_url": SignalAdapterSettings().base_url,
                "health_timeout_seconds": SignalAdapterSettings().health_timeout_seconds,
                "receive_connect_timeout_seconds": SignalAdapterSettings().receive_connect_timeout_seconds,
                "receive_heartbeat_seconds": SignalAdapterSettings().receive_heartbeat_seconds,
                "send_timeout_seconds": SignalAdapterSettings().send_timeout_seconds,
                "max_retries": SignalAdapterSettings().max_retries,
                "failure_backoff_initial_seconds": SignalAdapterSettings().failure_backoff_initial_seconds,
                "failure_backoff_max_seconds": SignalAdapterSettings().failure_backoff_max_seconds,
                "failure_backoff_multiplier": SignalAdapterSettings().failure_backoff_multiplier,
                "failure_backoff_jitter_ratio": SignalAdapterSettings().failure_backoff_jitter_ratio,
            },
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
            },
        },
    }

    assert yaml.safe_load(
        (sample_dir / "actors.yaml.sample").read_text(encoding="utf-8")
    ) == {
        "logging": {
            **LoggingSettings().model_dump(mode="json"),
            "process_name": "agent",
        },
        "core": ActorCoreConnectionSettings().model_dump(mode="json"),
        "cli": CliActorSettings().model_dump(mode="json"),
        "agent": AgentActorSettings().model_dump(mode="json"),
        "beat": ActorNamespaceSettings(source="beat").model_dump(mode="json"),
        "worker": ActorNamespaceSettings(source="worker").model_dump(mode="json"),
    }

    assert yaml.safe_load(
        (sample_dir / "secrets.yaml.sample").read_text(encoding="utf-8")
    ) == {
        "profile": {
            "operator": {"signal_contact_e164": "+12222222222"},
        },
        "substrate": {"obsidian": {"api_key": "replace-me"}},
        "adapter": {
            "signal": {"receive_e164": "+13333333333"},
            "litellm": {
                "providers": {
                    "openai": {"api_key": "replace-me"},
                    "anthropic": {"api_key": "replace-me"},
                }
            },
        },
    }
