"""Small ``input()`` helpers and validators for the install wizard.

All helpers re-prompt on invalid input until the operator supplies a valid
answer (or sends EOF/Ctrl-D, which raises ``EOFError`` and surfaces to the
caller). Tests drive these by ``monkeypatch.setattr("builtins.input", …)``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")
_NON_DIGIT_E164 = re.compile(r"[\s().\-]")


def print_section(title: str, *, stream=None) -> None:
    """Print a visually distinct section header."""
    out = stream if stream is not None else sys.stdout
    print("", file=out)
    print(f"=== {title} ===", file=out)


def prompt_text(
    message: str,
    *,
    default: str | None = None,
    allow_empty: bool = False,
) -> str:
    """Prompt for free-form text. Re-prompts on empty unless ``allow_empty``."""
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{message}{suffix}: ").strip()
        if not raw:
            if default is not None:
                return default
            if allow_empty:
                return ""
            print("  please enter a value")
            continue
        return raw


def prompt_yes_no(message: str, *, default: bool | None = None) -> bool:
    """Prompt for yes/no. ``default`` is selected on empty input if provided."""
    if default is True:
        suffix = " [Y/n]"
    elif default is False:
        suffix = " [y/N]"
    else:
        suffix = " [y/n]"
    while True:
        raw = input(f"{message}{suffix}: ").strip().lower()
        if not raw and default is not None:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("  please answer y or n")


def prompt_path(
    message: str,
    *,
    must_exist: bool = True,
    default: Path | None = None,
) -> Path:
    """Prompt for a filesystem path. Optionally re-prompt until it exists."""
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{message}{suffix}: ").strip()
        if not raw:
            if default is not None:
                raw = str(default)
            else:
                print("  please enter a path")
                continue
        path = Path(raw).expanduser()
        if must_exist and not path.exists():
            print(f"  path does not exist: {path}")
            continue
        return path


def prompt_e164_phone(
    message: str,
    *,
    default: str | None = None,
    allow_empty: bool = False,
) -> str:
    """Prompt for an E.164 phone number (e.g. ``+15551234567``).

    Strips spaces, parens, dots, and hyphens before validation. Re-prompts on
    invalid input. Returns the canonical E.164 string, or ``""`` if
    ``allow_empty`` is True and the operator presses Enter.
    """
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{message}{suffix}: ").strip()
        if not raw:
            if default is not None:
                return default
            if allow_empty:
                return ""
            print("  please enter a phone number in E.164 format (e.g. +15551234567)")
            continue
        canonical = _NON_DIGIT_E164.sub("", raw)
        if not E164_PATTERN.match(canonical):
            print(
                "  invalid E.164 phone number; expected format: "
                "+<countrycode><number>, e.g. +15551234567"
            )
            continue
        return canonical


def prompt_choice(
    message: str,
    choices: list[str],
    *,
    default: str | None = None,
) -> str:
    """Prompt for one of ``choices``, displayed as a numbered menu."""
    if not choices:
        raise ValueError("prompt_choice requires at least one choice")
    if default is not None and default not in choices:
        raise ValueError(f"default {default!r} not in choices {choices!r}")

    while True:
        for idx, choice in enumerate(choices, start=1):
            marker = " (default)" if choice == default else ""
            print(f"  {idx}) {choice}{marker}")
        suffix = f" [{default}]" if default else ""
        raw = input(f"{message}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        if raw in choices:
            return raw
        print("  please choose by number or by name")
