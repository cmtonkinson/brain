"""Validators and prompt helpers used by the install wizard."""

from __future__ import annotations

import pytest

from lib.setup.prompts import (
    prompt_choice,
    prompt_e164_phone,
    prompt_path,
    prompt_text,
    prompt_yes_no,
)


def _scripted_input(monkeypatch, answers: list[str]) -> list[str]:
    """Wire ``builtins.input`` to consume ``answers`` in order; return prompts."""
    answers = list(answers)
    seen_prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        seen_prompts.append(prompt)
        if not answers:
            raise EOFError("scripted_input exhausted")
        return answers.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return seen_prompts


def test_prompt_text_returns_stripped_value(monkeypatch):
    _scripted_input(monkeypatch, ["  hello  "])

    assert prompt_text("name") == "hello"


def test_prompt_text_repeats_on_empty_without_default(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["", "answer"])

    assert prompt_text("name") == "answer"
    assert "please enter a value" in capsys.readouterr().out


def test_prompt_text_returns_default_when_blank(monkeypatch):
    _scripted_input(monkeypatch, [""])

    assert prompt_text("name", default="anon") == "anon"


def test_prompt_text_allow_empty_returns_empty(monkeypatch):
    _scripted_input(monkeypatch, [""])

    assert prompt_text("note", allow_empty=True) == ""


@pytest.mark.parametrize(
    "answer,expected",
    [("y", True), ("Y", True), ("yes", True), ("n", False), ("no", False)],
)
def test_prompt_yes_no_accepts_common_forms(monkeypatch, answer, expected):
    _scripted_input(monkeypatch, [answer])

    assert prompt_yes_no("ok?") is expected


def test_prompt_yes_no_uses_default_on_empty(monkeypatch):
    _scripted_input(monkeypatch, ["", ""])

    assert prompt_yes_no("ok?", default=True) is True
    assert prompt_yes_no("ok?", default=False) is False


def test_prompt_yes_no_repeats_on_garbage(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["maybe", "y"])

    assert prompt_yes_no("ok?") is True
    assert "please answer y or n" in capsys.readouterr().out


def test_prompt_path_returns_existing_path(monkeypatch, tmp_path):
    target = tmp_path / "vault"
    target.mkdir()
    _scripted_input(monkeypatch, [str(target)])

    assert prompt_path("vault") == target


def test_prompt_path_expands_user(monkeypatch, tmp_path, monkeypatch_home):
    """~ in the input expands relative to $HOME."""
    home = monkeypatch_home
    target = home / "Documents"
    target.mkdir()
    _scripted_input(monkeypatch, ["~/Documents"])

    result = prompt_path("vault")

    assert result == target


def test_prompt_path_repeats_until_path_exists(monkeypatch, tmp_path, capsys):
    nope = tmp_path / "nope"
    yes = tmp_path / "yes"
    yes.mkdir()
    _scripted_input(monkeypatch, [str(nope), str(yes)])

    assert prompt_path("vault") == yes
    assert "path does not exist" in capsys.readouterr().out


def test_prompt_path_skips_existence_check_when_disabled(monkeypatch, tmp_path):
    nonexistent = tmp_path / "future"
    _scripted_input(monkeypatch, [str(nonexistent)])

    assert prompt_path("dir", must_exist=False) == nonexistent


def test_prompt_path_default_used_on_empty(monkeypatch, tmp_path):
    target = tmp_path / "default"
    target.mkdir()
    _scripted_input(monkeypatch, [""])

    assert prompt_path("vault", default=target) == target


def test_prompt_e164_normalizes_formatting(monkeypatch):
    _scripted_input(monkeypatch, ["+1 (555) 123-4567"])

    assert prompt_e164_phone("phone") == "+15551234567"


def test_prompt_e164_repeats_on_invalid(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["555-1234", "not-a-number", "+15551234567"])

    assert prompt_e164_phone("phone") == "+15551234567"
    assert "invalid E.164" in capsys.readouterr().out


def test_prompt_e164_allow_empty(monkeypatch):
    _scripted_input(monkeypatch, [""])

    assert prompt_e164_phone("phone", allow_empty=True) == ""


def test_prompt_e164_uses_default(monkeypatch):
    _scripted_input(monkeypatch, [""])

    assert prompt_e164_phone("phone", default="+15551234567") == "+15551234567"


def test_prompt_choice_by_number(monkeypatch):
    _scripted_input(monkeypatch, ["2"])

    assert prompt_choice("pick", ["alpha", "beta", "gamma"]) == "beta"


def test_prompt_choice_by_name(monkeypatch):
    _scripted_input(monkeypatch, ["gamma"])

    assert prompt_choice("pick", ["alpha", "beta", "gamma"]) == "gamma"


def test_prompt_choice_uses_default_on_empty(monkeypatch):
    _scripted_input(monkeypatch, [""])

    assert prompt_choice("pick", ["alpha", "beta"], default="beta") == "beta"


def test_prompt_choice_repeats_on_garbage(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["delta", "0", "10", "1"])

    assert prompt_choice("pick", ["alpha", "beta"]) == "alpha"


def test_prompt_choice_rejects_default_outside_choices(monkeypatch):
    with pytest.raises(ValueError, match="not in choices"):
        prompt_choice("pick", ["alpha"], default="beta")


def test_prompt_choice_rejects_empty_choices(monkeypatch):
    with pytest.raises(ValueError, match="at least one choice"):
        prompt_choice("pick", [])


@pytest.fixture
def monkeypatch_home(monkeypatch, tmp_path):
    """Pin $HOME to a tmp dir so ~-expansion is hermetic."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home
