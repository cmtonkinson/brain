"""Interactive install wizard.

Re-runnable. On a fresh install, collects operator answers, writes the
minimal set of ``~/.config/brain/*.yaml`` files (overrides only, per project
convention), copies the Software-service compose override if requested, and
initializes the upgrade ledger by grandfathering all current upgrades.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from lib.core.upgrades.ledger import ledger_path
from lib.setup.ledger_init import write_grandfathered_ledger
from lib.setup.prompts import (
    print_section,
    prompt_e164_phone,
    prompt_path,
    prompt_text,
    prompt_yes_no,
)

API_KEY_PLACEHOLDER = "replace-me"
DEFAULT_BRAIN_NAME = "Brain"
DEFAULT_OPERATOR_NAME = "Operator"


class InstallError(RuntimeError):
    """Raised when the install cannot proceed (e.g. inconsistent state)."""


class InstallMode(Enum):
    """Which install path applies to the current host state."""

    FRESH = "fresh"
    CONFIGS_ONLY = "configs_only"
    ALREADY_CONFIGURED = "already_configured"
    LEDGER_ONLY = "ledger_only"


@dataclass(frozen=True, slots=True)
class WizardAnswers:
    """Operator inputs gathered by the wizard."""

    operator_name: str
    brain_name: str
    vault_path: Path
    signal_enabled: bool
    operator_phone_e164: str  # blank if signal disabled
    brain_phone_e164: str  # blank if signal disabled
    software_enabled: bool
    anthropic_api_key: str  # blank → omit from secrets.yaml
    voyage_api_key: str  # blank → omit from secrets.yaml
    obsidian_api_key: str


def determine_mode(*, config_dir: Path, ledger_target: Path) -> InstallMode:
    """Classify the install state from configs + ledger presence."""
    secrets_populated = _secrets_yaml_populated(config_dir / "secrets.yaml")
    ledger_exists = ledger_target.exists()

    if secrets_populated and ledger_exists:
        return InstallMode.ALREADY_CONFIGURED
    if secrets_populated and not ledger_exists:
        return InstallMode.CONFIGS_ONLY
    if not secrets_populated and ledger_exists:
        return InstallMode.LEDGER_ONLY
    return InstallMode.FRESH


def run_install(
    *,
    repo_root: Path,
    config_dir: Path,
    reconfigure: bool = False,
    upgrades_root: Path | None = None,
) -> InstallMode:
    """Top-level install flow. Returns the resolved mode for caller logging."""
    target_ledger = ledger_path()
    mode = determine_mode(config_dir=config_dir, ledger_target=target_ledger)

    if mode is InstallMode.LEDGER_ONLY:
        raise InstallError(
            f"upgrade ledger exists at {target_ledger} but configs are missing "
            f"at {config_dir}; if you mean to start fresh, remove "
            f"{target_ledger.parent} and re-run `make install`"
        )

    if mode is InstallMode.ALREADY_CONFIGURED and not reconfigure:
        print(
            f"Brain already configured at {config_dir}. "
            "Re-run with `make install RECONFIGURE=1` to update settings."
        )
        return mode

    if mode is InstallMode.CONFIGS_ONLY:
        print(
            f"Configs found at {config_dir}; initializing upgrade ledger "
            "from current main."
        )
        roots = upgrades_root or (repo_root / "upgrades")
        write_grandfathered_ledger(upgrades_root=roots)
        print(f"Wrote {target_ledger}.")
        return mode

    answers = gather_answers(repo_root=repo_root)
    write_configs(answers=answers, repo_root=repo_root, config_dir=config_dir)

    if mode is InstallMode.FRESH:
        roots = upgrades_root or (repo_root / "upgrades")
        ledger = write_grandfathered_ledger(upgrades_root=roots)
        print(
            f"Grandfathered {len(ledger.applied)} upgrades from current "
            f"main; ledger at {target_ledger}."
        )
    else:
        print("Reconfigure complete; ledger left unchanged.")
    print("Next: `make up`.")
    return mode


def gather_answers(*, repo_root: Path) -> WizardAnswers:
    """Walk the operator through the prompts that drive config rendering."""
    print_section("Identity")
    operator_name = prompt_text("Your display name", default=DEFAULT_OPERATOR_NAME)
    brain_name = prompt_text("What to call Brain", default=DEFAULT_BRAIN_NAME)

    print_section("Obsidian vault")
    default_vault = _detect_default_vault()
    vault_path = prompt_path(
        "Path to your Obsidian vault",
        must_exist=True,
        default=default_vault,
    )
    obsidian_api_key = (
        prompt_text(
            "Obsidian Local REST API key (leave blank to fill in later)",
            allow_empty=True,
        )
        or API_KEY_PLACEHOLDER
    )

    print_section("Signal enrollment")
    signal_enabled = prompt_yes_no(
        "Use Signal for operator <-> Brain messaging?", default=False
    )
    operator_phone = ""
    brain_phone = ""
    if signal_enabled:
        operator_phone = prompt_e164_phone("Your Signal phone number")
        brain_phone = prompt_e164_phone("Brain's Signal phone number")
        print(
            "  After `make up`, run `make signal-setup` to register Brain's "
            "number with Signal (captcha + SMS/voice verify)."
        )

    print_section("Software service")
    software_enabled = prompt_yes_no(
        "Enable the Software service (running coding tasks against your repos)?",
        default=False,
    )

    print_section("LLM provider")
    anthropic_key, voyage_key = _gather_llm_keys(repo_root=repo_root)

    return WizardAnswers(
        operator_name=operator_name,
        brain_name=brain_name,
        vault_path=vault_path,
        signal_enabled=signal_enabled,
        operator_phone_e164=operator_phone,
        brain_phone_e164=brain_phone,
        software_enabled=software_enabled,
        anthropic_api_key=anthropic_key,
        voyage_api_key=voyage_key,
        obsidian_api_key=obsidian_api_key,
    )


def write_configs(
    *,
    answers: WizardAnswers,
    repo_root: Path,
    config_dir: Path,
) -> list[Path]:
    """Atomically render the override-only YAMLs and copy any side files.

    Returns the list of final paths written.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    staging = config_dir / ".install-tmp"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    rendered: dict[str, str] = {
        "secrets.yaml": _render_secrets(answers),
        "shared.yaml": _render_shared(answers),
    }
    if answers.software_enabled:
        rendered["software.yaml"] = _render_software(answers)

    written: list[Path] = []
    try:
        for filename, contents in rendered.items():
            staging_path = staging / filename
            staging_path.write_text(contents)
        for filename in rendered:
            final_path = config_dir / filename
            os.replace(staging / filename, final_path)
            written.append(final_path)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    if answers.software_enabled:
        compose_target = repo_root / "docker-compose.override.yaml"
        compose_sample = repo_root / "docker-compose.override.yaml.sample"
        if compose_sample.is_file() and not compose_target.exists():
            shutil.copyfile(compose_sample, compose_target)
            written.append(compose_target)

    print("")
    print("Wrote:")
    for path in written:
        print(f"  {path}")
    return written


def _render_secrets(answers: WizardAnswers) -> str:
    """Render the smallest valid ``secrets.yaml`` for this operator."""
    data: dict = {
        "obsidian": {"api_key": answers.obsidian_api_key},
    }
    providers: dict = {}
    if answers.anthropic_api_key:
        providers["anthropic"] = {"api_key": answers.anthropic_api_key}
    if answers.voyage_api_key:
        providers["voyage"] = {"api_key": answers.voyage_api_key}
    if providers:
        data["llm"] = {"providers": providers}
    if answers.signal_enabled:
        data.setdefault("profile", {})["operator"] = {
            "signal_contact_e164": answers.operator_phone_e164,
        }
        data["signal"] = {"receive_e164": answers.brain_phone_e164}
    return _dump_yaml(data)


def _gather_llm_keys(*, repo_root: Path) -> tuple[str, str]:
    """Walk the operator through provider selection. Returns (anthropic, voyage).

    Empty strings mean "skip" — the corresponding entry is omitted from
    ``secrets.yaml``. The displayed default profiles are read from
    ``config/effect.yaml.sample`` so the operator sees exactly what the
    sample would set up.
    """
    profiles = _load_sample_language_profiles(repo_root=repo_root)
    print("Default: local Ollama (no API keys needed; requires Ollama on the host)")
    if profiles:
        print("  Chat:")
        for tier in ("quick", "standard", "deep"):
            if tier in profiles:
                print(f"    - {tier:<8} {_format_profile(profiles[tier])}")
        if "document_embedding" in profiles:
            print("  Embeddings:")
            print(f"    - documents: {_format_profile(profiles['document_embedding'])}")
    print(
        "Pull listed models with `ollama pull <name>` before `make up`. "
        "Supported hosted alternatives: Anthropic (chat), Voyage (embeddings)."
    )

    if prompt_yes_no("Use the local Ollama defaults?", default=True):
        return "", ""

    anthropic_key = prompt_text(
        "Anthropic API key (leave blank to skip)", allow_empty=True
    )
    voyage_key = prompt_text("Voyage API key (leave blank to skip)", allow_empty=True)
    if not anthropic_key and not voyage_key:
        print(
            "  no hosted keys provided; secrets.yaml will omit the llm block. "
            "You can re-run `make install RECONFIGURE=1` to add them later."
        )
    print(
        "  note: keys are recorded in secrets.yaml but profiles still default to "
        "Ollama. Override `language.<profile>.provider` in "
        "`~/.config/brain/effect.yaml` to switch a profile to a hosted provider; "
        "see `config/effect.yaml.sample` for the keys."
    )
    return anthropic_key, voyage_key


def _format_profile(profile: dict) -> str:
    """Render a profile dict as ``provider / model`` for display."""
    return f"{profile.get('provider', '?')} / {profile.get('model', '?')}"


def _load_sample_language_profiles(*, repo_root: Path) -> dict[str, dict]:
    """Read default chat/embedding profiles from ``config/effect.yaml.sample``.

    Returns a dict keyed by profile name (``quick``/``standard``/``deep``/
    ``document_embedding``). Missing or malformed sample → empty dict; the
    wizard then prints only the static heading.
    """
    sample = repo_root / "config" / "effect.yaml.sample"
    if not sample.is_file():
        return {}
    try:
        parsed = yaml.safe_load(sample.read_text())
    except yaml.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    language = parsed.get("language", {})
    if not isinstance(language, dict):
        return {}
    profiles: dict[str, dict] = {}
    for key in ("quick", "standard", "deep", "document_embedding"):
        value = language.get(key)
        if isinstance(value, dict) and "provider" in value and "model" in value:
            profiles[key] = value
    return profiles


def _render_shared(answers: WizardAnswers) -> str:
    """Render the override-only ``shared.yaml``.

    Operator defaults that match Pydantic defaults are intentionally omitted.
    """
    profile: dict = {}
    if answers.operator_name != DEFAULT_OPERATOR_NAME:
        profile["operator_name"] = answers.operator_name
    if answers.brain_name != DEFAULT_BRAIN_NAME:
        profile["brain_name"] = answers.brain_name
    if answers.signal_enabled:
        profile.setdefault("operator", {})["signal_contact_e164"] = (
            answers.operator_phone_e164
        )

    obsidian: dict = {"vault_path": str(answers.vault_path)}

    data: dict = {"obsidian": obsidian}
    if profile:
        data["profile"] = profile
    return _dump_yaml(data)


def _render_software(answers: WizardAnswers) -> str:
    """Render an empty ``software.yaml`` placeholder when Software is enabled.

    The defaults in ``lib.shared.config`` are sufficient out of the box; this
    file's presence is the operator-visible signal that Software is on.
    """
    return _dump_yaml({"software": {}})


def _dump_yaml(data: dict) -> str:
    """Project-standard YAML dump: 2-space indent, key order preserved."""
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, indent=2)


def _secrets_yaml_populated(path: Path) -> bool:
    """True iff secrets.yaml exists and parses as a non-empty mapping.

    Placeholder values (``replace-me``) still count as "configured" — the
    operator chose to skip those keys and Brain treats the install as
    set-up. To re-walk the wizard, pass ``--reconfigure``.
    """
    if not path.is_file():
        return False
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and len(data) > 0


def _detect_default_vault() -> Path | None:
    """Best-effort: look for an Obsidian vault in common locations."""
    home = Path.home()
    for candidate in (
        home / "Documents" / "Obsidian",
        home / "Obsidian",
        home / "vault",
    ):
        if candidate.is_dir():
            return candidate
    return None
