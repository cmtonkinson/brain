"""Standalone Signal account provisioning for Brain.

Drives the signal-cli-rest-api container (already running from ``make up``)
through the captcha → register → SMS/voice verify → trust sequence so the
operator only types: the captcha token from a browser, the verification
code from Brain's phone. Everything else is automated.

Re-runnable: if Brain's number is already registered, the script
short-circuits to the trust step (which is itself idempotent).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from lib.setup.prompts import print_section, prompt_text, prompt_yes_no

CAPTCHA_URL = "https://signalcaptchas.org/registration/generate.html"
CAPTCHA_PREFIX = "signalcaptcha://"
DEFAULT_HOST_URL = "http://localhost:8080"
HEALTH_BUDGET_SECONDS = 15.0
HEALTH_POLL_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 30.0


class SetupError(RuntimeError):
    """Raised when the operator-facing setup cannot proceed."""


@dataclass(frozen=True, slots=True)
class SignalNumbers:
    """Numbers required to provision Brain's Signal account."""

    brain_e164: str
    operator_e164: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="signal-setup",
        description="Register Brain's Signal number and trust the operator's identity.",
    )
    parser.add_argument(
        "--host-url",
        default=os.getenv("BRAIN_SIGNAL_API_HOST_URL", DEFAULT_HOST_URL),
        help=(
            "signal-api base URL as reachable from the host "
            f"(default: {DEFAULT_HOST_URL})"
        ),
    )
    args = parser.parse_args(argv)

    config_dir = _resolve_config_dir()

    try:
        numbers = _load_numbers(config_dir=config_dir)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        with httpx.Client(
            base_url=args.host_url, timeout=HTTP_TIMEOUT_SECONDS
        ) as client:
            run_setup(client=client, numbers=numbers)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    return 0


def run_setup(*, client: httpx.Client, numbers: SignalNumbers) -> None:
    """Drive the full provisioning flow against an opened ``signal-api`` client."""
    print_section("Signal setup")
    print(f"Brain's number:    {numbers.brain_e164}")
    print(f"Operator's number: {numbers.operator_e164}")
    print(f"signal-api:        {client.base_url}")

    _wait_for_healthy(client=client)

    if _account_exists(client=client, e164=numbers.brain_e164):
        print(f"\n{numbers.brain_e164} is already registered; skipping registration.")
    else:
        captcha = _prompt_captcha()
        use_voice = prompt_yes_no(
            "Use voice call instead of SMS for the verification code?",
            default=False,
        )
        _register(
            client=client,
            e164=numbers.brain_e164,
            captcha=captcha,
            use_voice=use_voice,
        )
        print(
            "\nSignal will deliver a verification code to "
            f"{numbers.brain_e164} via {'voice call' if use_voice else 'SMS'}."
        )
        _verify_with_retries(client=client, e164=numbers.brain_e164)
        if not _account_exists(client=client, e164=numbers.brain_e164):
            raise SetupError(
                f"verification reported success but {numbers.brain_e164} is not "
                "in /v1/accounts; re-run `make signal-setup` to retry"
            )

    _trust_operator(client=client, numbers=numbers)

    print(
        "\nSignal configured ✓\n"
        f"Send a message from {numbers.operator_e164} to {numbers.brain_e164} "
        "to confirm Brain replies."
    )


def _wait_for_healthy(*, client: httpx.Client) -> None:
    """Poll ``/v1/health`` until 2xx or budget exhaustion."""
    deadline = time.monotonic() + HEALTH_BUDGET_SECONDS
    last_error: str = ""
    while time.monotonic() < deadline:
        try:
            response = client.get("/v1/health")
        except httpx.HTTPError as exc:
            last_error = str(exc)
        else:
            if response.is_success:
                return
            last_error = f"HTTP {response.status_code}"
        time.sleep(HEALTH_POLL_SECONDS)
    raise SetupError(
        f"signal-api at {client.base_url} did not respond healthy within "
        f"{HEALTH_BUDGET_SECONDS:.0f}s ({last_error}); "
        "did you run `make up`?"
    )


def _account_exists(*, client: httpx.Client, e164: str) -> bool:
    """True iff ``/v1/accounts`` lists this number."""
    response = client.get("/v1/accounts")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise SetupError(
            f"GET /v1/accounts returned unexpected shape: {type(payload).__name__}"
        )
    return any(isinstance(item, str) and item == e164 for item in payload)


def _prompt_captcha() -> str:
    """Walk the operator through the captcha-token extraction recipe."""
    print_section("Captcha")
    print(
        "Signal requires a captcha token to register a new number.\n"
        f"  1) Open {CAPTCHA_URL} in a browser.\n"
        "  2) Solve the captcha. The page will try to navigate to a "
        "`signalcaptcha://...` URL and silently fail.\n"
        "  3) Open the browser's developer console and find a line like:\n"
        '       Prevented navigation to "signalcaptcha://<token>"\n'
        "  4) Copy everything after `signalcaptcha://` (or the whole URL — "
        "the prefix is stripped automatically)."
    )
    raw = prompt_text("Paste the captcha token")
    if raw.startswith(CAPTCHA_PREFIX):
        return raw[len(CAPTCHA_PREFIX) :]
    return raw


def _register(
    *,
    client: httpx.Client,
    e164: str,
    captcha: str,
    use_voice: bool,
) -> None:
    """Submit the captcha-bearing registration request."""
    response = client.post(
        f"/v1/register/{e164}",
        json={"captcha": captcha, "use_voice": use_voice},
    )
    if response.is_success:
        return
    detail = _decode_error(response)
    raise SetupError(
        f"POST /v1/register/{e164} failed (HTTP {response.status_code}): {detail}"
    )


def _verify_with_retries(*, client: httpx.Client, e164: str) -> None:
    """Prompt for the verification code and re-prompt on rejection."""
    while True:
        code = prompt_text("Verification code (e.g. 123-456 or 123456)")
        normalized = code.replace("-", "").strip()
        response = client.post(f"/v1/register/{e164}/verify/{normalized}")
        if response.is_success:
            return
        detail = _decode_error(response)
        print(f"  verification rejected (HTTP {response.status_code}): {detail}")
        if not prompt_yes_no("Try a different code?", default=True):
            raise SetupError(
                "verification aborted; re-run `make signal-setup` when ready"
            )


def _trust_operator(*, client: httpx.Client, numbers: SignalNumbers) -> None:
    """Trust the operator's identity from Brain's account.

    Failure here is non-fatal — the operator can re-run later. We surface a
    warning so they know the trust anchor wasn't recorded.
    """
    response = client.put(
        f"/v1/identities/{numbers.brain_e164}/trust/{numbers.operator_e164}",
        json={"trust_all_known_keys": True},
    )
    if response.is_success:
        print(
            f"\nTrusted {numbers.operator_e164} from "
            f"{numbers.brain_e164}'s identity store."
        )
        return
    detail = _decode_error(response)
    print(
        f"\nwarning: trust call failed (HTTP {response.status_code}): {detail}\n"
        "  Re-run `make signal-setup` once Brain has seen at least one "
        "message from the operator's number; signal-cli holds first inbound "
        "messages until trust is recorded.",
        file=sys.stderr,
    )


def _decode_error(response: httpx.Response) -> str:
    """Extract a human-readable error string from a non-2xx signal-api response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "<empty body>"
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(payload)


def _resolve_config_dir() -> Path:
    """Mirror the wizard's resolution of the operator config directory."""
    override = os.getenv("BRAIN_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / "brain"


def _load_numbers(*, config_dir: Path) -> SignalNumbers:
    """Read the brain + operator E.164 numbers from ``~/.config/brain/*.yaml``."""
    if not config_dir.is_dir():
        raise SetupError(
            f"config directory {config_dir} does not exist; run `make install` first"
        )
    merged = _load_merged_yaml(config_dir=config_dir)

    brain_e164 = _lookup(merged, "signal", "receive_e164")
    operator_e164 = _lookup(merged, "profile", "operator", "signal_contact_e164")

    missing: list[str] = []
    if not brain_e164:
        missing.append("signal.receive_e164")
    if not operator_e164:
        missing.append("profile.operator.signal_contact_e164")
    if missing:
        raise SetupError(
            "missing required Signal config keys in "
            f"{config_dir}: {', '.join(missing)}; "
            "re-run `make install RECONFIGURE=1` and enable Signal"
        )

    return SignalNumbers(brain_e164=brain_e164, operator_e164=operator_e164)


def _load_merged_yaml(*, config_dir: Path) -> dict[str, Any]:
    """Deep-merge every top-level ``*.yaml`` file in ``config_dir``."""
    merged: dict[str, Any] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        try:
            parsed = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise SetupError(f"failed to parse {path}: {exc}") from exc
        if parsed is None:
            continue
        if not isinstance(parsed, dict):
            raise SetupError(f"{path} must be a YAML mapping at the top level")
        merged = _deep_merge(merged, parsed)
    return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two mappings; non-mapping leaves are replaced."""
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _lookup(mapping: dict[str, Any], *keys: str) -> str:
    """Walk a nested mapping by keys, returning ``""`` on miss."""
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    if isinstance(current, str):
        return current.strip()
    return ""


if __name__ == "__main__":
    sys.exit(main())
