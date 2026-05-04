"""Wizard mode detection, atomic config writes, ledger init bridging."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    Ledger,
    ledger_path,
    now_utc_iso,
    read_ledger,
    write_ledger,
)
from lib.setup.wizard import (
    API_KEY_PLACEHOLDER,
    InstallError,
    InstallMode,
    WizardAnswers,
    determine_mode,
    run_install,
    write_configs,
)


def _scripted_input(monkeypatch, answers: list[str]) -> None:
    answers = list(answers)

    def fake_input(_prompt: str = "") -> str:
        if not answers:
            raise EOFError("scripted_input exhausted")
        return answers.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


def _signal_disabled_answers(vault_path: Path) -> WizardAnswers:
    return WizardAnswers(
        operator_name="Chris",
        brain_name="Jarvis",
        vault_path=vault_path,
        signal_enabled=False,
        operator_phone_e164="",
        brain_phone_e164="",
        software_enabled=False,
        anthropic_api_key="sk-real",
        voyage_api_key="",
        obsidian_api_key=API_KEY_PLACEHOLDER,
    )


def test_determine_mode_fresh(tmp_path):
    assert (
        determine_mode(
            config_dir=tmp_path / "config",
            ledger_target=tmp_path / "ledger.json",
        )
        is InstallMode.FRESH
    )


def test_determine_mode_already_configured(isolated_install_env):
    cfg = isolated_install_env["config_dir"]
    (cfg / "secrets.yaml").write_text(
        "llm:\n  providers:\n    anthropic:\n      api_key: sk-real\n"
    )
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )

    assert (
        determine_mode(config_dir=cfg, ledger_target=ledger_path())
        is InstallMode.ALREADY_CONFIGURED
    )


def test_determine_mode_configs_only(isolated_install_env):
    cfg = isolated_install_env["config_dir"]
    (cfg / "secrets.yaml").write_text(
        "llm:\n  providers:\n    anthropic:\n      api_key: sk-real\n"
    )

    assert (
        determine_mode(config_dir=cfg, ledger_target=ledger_path())
        is InstallMode.CONFIGS_ONLY
    )


def test_determine_mode_ledger_only(isolated_install_env):
    cfg = isolated_install_env["config_dir"]
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )

    assert (
        determine_mode(config_dir=cfg, ledger_target=ledger_path())
        is InstallMode.LEDGER_ONLY
    )


def test_determine_mode_treats_placeholder_only_secrets_as_configured(
    isolated_install_env,
):
    cfg = isolated_install_env["config_dir"]
    (cfg / "secrets.yaml").write_text(
        "obsidian:\n  api_key: replace-me\n"
        "llm:\n  providers:\n    anthropic:\n      api_key: replace-me\n"
    )

    # Presence of a structurally-valid secrets.yaml = configured, even with
    # all-placeholder values. Re-walk via --reconfigure to fill them in.
    assert (
        determine_mode(config_dir=cfg, ledger_target=ledger_path())
        is InstallMode.CONFIGS_ONLY
    )


def test_write_configs_writes_minimal_signal_disabled(isolated_install_env, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]

    write_configs(
        answers=_signal_disabled_answers(vault),
        repo_root=isolated_install_env["tmp_path"],
        config_dir=cfg,
    )

    secrets = yaml.safe_load((cfg / "secrets.yaml").read_text())
    assert "signal" not in secrets
    assert secrets["llm"]["providers"]["anthropic"]["api_key"] == "sk-real"
    # Voyage key was blank → entry omitted from secrets.yaml.
    assert "voyage" not in secrets["llm"]["providers"]

    shared = yaml.safe_load((cfg / "shared.yaml").read_text())
    assert shared["obsidian"]["vault_path"] == str(vault)
    # operator_name override (Chris != "Operator") is recorded.
    assert shared["profile"]["operator_name"] == "Chris"
    # brain_name override (Jarvis != "Brain") is recorded.
    assert shared["profile"]["brain_name"] == "Jarvis"
    # signal block must not appear when disabled.
    assert "operator" not in shared.get("profile", {})


def test_write_configs_writes_signal_block_when_enabled(isolated_install_env, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]
    answers = WizardAnswers(
        operator_name="Operator",  # default → omitted from shared.yaml
        brain_name="Brain",  # default → omitted
        vault_path=vault,
        signal_enabled=True,
        operator_phone_e164="+15551112222",
        brain_phone_e164="+15553334444",
        software_enabled=False,
        anthropic_api_key="sk-real",
        voyage_api_key="",
        obsidian_api_key="ob-real",
    )

    write_configs(
        answers=answers,
        repo_root=isolated_install_env["tmp_path"],
        config_dir=cfg,
    )

    secrets = yaml.safe_load((cfg / "secrets.yaml").read_text())
    assert secrets["signal"]["receive_e164"] == "+15553334444"
    assert secrets["profile"]["operator"]["signal_contact_e164"] == "+15551112222"

    shared = yaml.safe_load((cfg / "shared.yaml").read_text())
    assert shared["profile"]["operator"]["signal_contact_e164"] == "+15551112222"
    assert "operator_name" not in shared["profile"]
    assert "brain_name" not in shared["profile"]


def test_write_configs_omits_software_yaml_when_declined(
    isolated_install_env, tmp_path
):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]

    write_configs(
        answers=_signal_disabled_answers(vault),
        repo_root=isolated_install_env["tmp_path"],
        config_dir=cfg,
    )

    assert not (cfg / "software.yaml").exists()
    assert not (
        isolated_install_env["tmp_path"] / "docker-compose.override.yaml"
    ).exists()


def test_write_configs_copies_compose_override_when_software_enabled(
    isolated_install_env, tmp_path
):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]
    repo_root = isolated_install_env["tmp_path"]
    sample = repo_root / "docker-compose.override.yaml.sample"
    sample.write_text("services: {}\n")

    answers = WizardAnswers(
        operator_name="Operator",
        brain_name="Brain",
        vault_path=vault,
        signal_enabled=False,
        operator_phone_e164="",
        brain_phone_e164="",
        software_enabled=True,
        anthropic_api_key="sk-real",
        voyage_api_key="",
        obsidian_api_key=API_KEY_PLACEHOLDER,
    )

    write_configs(answers=answers, repo_root=repo_root, config_dir=cfg)

    assert (cfg / "software.yaml").exists()
    target = repo_root / "docker-compose.override.yaml"
    assert target.exists()
    assert target.read_text() == "services: {}\n"


def test_write_configs_atomic_failure_leaves_no_partial_files(
    isolated_install_env, tmp_path, monkeypatch
):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]

    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated mid-replace crash")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("lib.setup.wizard.os.replace", flaky_replace)

    with pytest.raises(RuntimeError, match="simulated"):
        write_configs(
            answers=_signal_disabled_answers(vault),
            repo_root=isolated_install_env["tmp_path"],
            config_dir=cfg,
        )

    # Staging dir is cleaned up on failure.
    assert not (cfg / ".install-tmp").exists()


def test_write_configs_omits_llm_block_when_no_hosted_keys(
    isolated_install_env, tmp_path
):
    """Default Ollama path: blank LLM keys → secrets.yaml has no llm block."""
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]

    answers = WizardAnswers(
        operator_name="Operator",
        brain_name="Brain",
        vault_path=vault,
        signal_enabled=False,
        operator_phone_e164="",
        brain_phone_e164="",
        software_enabled=False,
        anthropic_api_key="",
        voyage_api_key="",
        obsidian_api_key=API_KEY_PLACEHOLDER,
    )

    write_configs(
        answers=answers, repo_root=isolated_install_env["tmp_path"], config_dir=cfg
    )

    secrets = yaml.safe_load((cfg / "secrets.yaml").read_text())
    assert "llm" not in secrets
    # Obsidian key is still recorded (with placeholder when skipped).
    assert secrets["obsidian"]["api_key"] == API_KEY_PLACEHOLDER


def test_run_install_fresh_writes_configs_and_grandfathers_ledger(
    isolated_install_env, monkeypatch, tmp_path, capsys
):
    vault = tmp_path / "vault"
    vault.mkdir()
    upgrades_dir = isolated_install_env["upgrades_dir"]
    # One upgrade present: it should be grandfathered.
    fixture = upgrades_dir / "20260505_0001_alpha"
    fixture.mkdir()
    (fixture / "upgrade.py").write_text(
        'DESCRIPTION="x"\nPHASE="post-services"\n\ndef run(ctx):\n    pass\n'
    )

    _scripted_input(
        monkeypatch,
        [
            "Chris",  # operator name
            "Jarvis",  # brain name
            str(vault),  # vault path
            "",  # obsidian api key (blank → placeholder)
            "n",  # signal? no
            "n",  # software? no
            "y",  # use Ollama defaults? yes (no key prompts follow)
        ],
    )

    mode = run_install(
        repo_root=isolated_install_env["tmp_path"],
        config_dir=isolated_install_env["config_dir"],
        upgrades_root=upgrades_dir,
    )

    assert mode is InstallMode.FRESH
    cfg = isolated_install_env["config_dir"]
    assert (cfg / "secrets.yaml").exists()
    assert (cfg / "shared.yaml").exists()
    ledger_after = read_ledger()
    assert {e.upgrade_id for e in ledger_after.applied} == {"20260505_0001"}
    assert ledger_after.applied[0].grandfathered is True


def test_run_install_skips_when_already_configured(
    isolated_install_env, monkeypatch, tmp_path, capsys
):
    cfg = isolated_install_env["config_dir"]
    (cfg / "secrets.yaml").write_text(
        "llm:\n  providers:\n    anthropic:\n      api_key: sk-real\n"
    )
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )

    mode = run_install(
        repo_root=isolated_install_env["tmp_path"],
        config_dir=cfg,
        upgrades_root=isolated_install_env["upgrades_dir"],
    )

    assert mode is InstallMode.ALREADY_CONFIGURED
    out = capsys.readouterr().out
    assert "already configured" in out


def test_run_install_reconfigure_walks_wizard_but_preserves_ledger(
    isolated_install_env, monkeypatch, tmp_path
):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = isolated_install_env["config_dir"]
    (cfg / "secrets.yaml").write_text(
        "llm:\n  providers:\n    anthropic:\n      api_key: existing\n"
    )
    upgrades_dir = isolated_install_env["upgrades_dir"]
    fixture = upgrades_dir / "20260505_0001_alpha"
    fixture.mkdir()
    (fixture / "upgrade.py").write_text(
        'DESCRIPTION="x"\nPHASE="post-services"\n\ndef run(ctx):\n    pass\n'
    )
    # Simulate an existing ledger with a real (non-grandfathered) entry.
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at="2026-04-01T00:00:00+00:00",
            applied=[],
        )
    )

    _scripted_input(
        monkeypatch,
        [
            "Newname",
            "Brain",
            str(vault),
            "",
            "n",  # signal? no
            "n",  # software? no
            "n",  # use Ollama defaults? no → key prompts follow
            "newkey",  # anthropic
            "",  # voyage (skip)
        ],
    )

    mode = run_install(
        repo_root=isolated_install_env["tmp_path"],
        config_dir=cfg,
        reconfigure=True,
        upgrades_root=upgrades_dir,
    )

    assert mode is InstallMode.ALREADY_CONFIGURED
    secrets = yaml.safe_load((cfg / "secrets.yaml").read_text())
    assert secrets["llm"]["providers"]["anthropic"]["api_key"] == "newkey"
    assert "voyage" not in secrets["llm"]["providers"]
    # Ledger preserved: still has the original installed_at, no new entries
    # added by the reconfigure.
    after = read_ledger()
    assert after.installed_at == "2026-04-01T00:00:00+00:00"
    assert after.applied == []


def test_run_install_configs_only_initializes_ledger_without_walking_wizard(
    isolated_install_env, monkeypatch, capsys
):
    """The author-today path: pre-existing operator before upgrades shipped."""
    cfg = isolated_install_env["config_dir"]
    (cfg / "secrets.yaml").write_text(
        "llm:\n  providers:\n    anthropic:\n      api_key: sk-real\n"
    )
    upgrades_dir = isolated_install_env["upgrades_dir"]
    fixture = upgrades_dir / "20260505_0001_alpha"
    fixture.mkdir()
    (fixture / "upgrade.py").write_text(
        'DESCRIPTION="x"\nPHASE="post-services"\n\ndef run(ctx):\n    pass\n'
    )

    # No input() should be called; if it is, the test will hang. To prove the
    # wizard isn't walked, replace input with a raiser.
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": (_ for _ in ()).throw(
            AssertionError("wizard should not have prompted")
        ),
    )

    mode = run_install(
        repo_root=isolated_install_env["tmp_path"],
        config_dir=cfg,
        upgrades_root=upgrades_dir,
    )

    assert mode is InstallMode.CONFIGS_ONLY
    ledger = read_ledger()
    assert {e.upgrade_id for e in ledger.applied} == {"20260505_0001"}
    assert ledger.applied[0].grandfathered is True
    out = capsys.readouterr().out
    assert "initializing upgrade ledger" in out


def test_run_install_ledger_only_refuses(isolated_install_env):
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )

    with pytest.raises(InstallError, match="configs are missing"):
        run_install(
            repo_root=isolated_install_env["tmp_path"],
            config_dir=isolated_install_env["config_dir"],
            upgrades_root=isolated_install_env["upgrades_dir"],
        )
