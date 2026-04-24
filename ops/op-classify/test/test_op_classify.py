"""Tests for the op-classify slash command op."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _load_execute() -> Any:
    path = Path(__file__).resolve().parents[1] / "execute.py"
    spec = importlib.util.spec_from_file_location("op_classify_execute", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeClient:
    def __init__(self, *, source: str, principal: str) -> None:
        del source, principal
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def classify_dynamic_op(
        self,
        *,
        op_id: str,
        effect: str | None = None,
        approval: str | None = None,
    ) -> SimpleNamespace:
        self.calls.append({"op_id": op_id, "effect": effect, "approval": approval})
        # Mimic server behavior: persist supplied values, leave others unset.
        return SimpleNamespace(op_id=op_id, effect=effect, approval=approval)


@pytest.fixture
def loaded(monkeypatch: Any) -> tuple[Any, list[dict[str, object]]]:
    module = _load_execute()
    captured: list[dict[str, object]] = []

    def _factory(**kwargs):
        client = _FakeClient(**kwargs)
        captured.append(client.calls)  # share list reference
        return client

    monkeypatch.setattr(module, "BrainSdkClient", _factory)
    return module, captured


def test_classify_full_pair(loaded: tuple[Any, list[Any]]) -> None:
    """Words from both sets in any order set both fields."""
    module, captured = loaded
    result = module.execute(
        {"op_id": "eventkit--list-events", "words": ["never", "read"]}
    )
    assert "effect=read" in result
    assert "approval=never" in result
    assert "active and invokable" in result
    assert captured[0] == [
        {"op_id": "eventkit--list-events", "effect": "read", "approval": "never"}
    ]


def test_classify_partial_effect_only(loaded: tuple[Any, list[Any]]) -> None:
    """Effect-only word leaves approval unset."""
    module, captured = loaded
    result = module.execute({"op_id": "eventkit--probe", "words": ["read"]})
    assert "set effect=read" in result
    assert "approval=<unset>" in result
    assert "remains inactive" in result
    assert captured[0] == [
        {"op_id": "eventkit--probe", "effect": "read", "approval": None}
    ]


def test_classify_partial_approval_only(loaded: tuple[Any, list[Any]]) -> None:
    """Approval-only word leaves effect unset."""
    module, captured = loaded
    result = module.execute({"op_id": "eventkit--probe", "words": ["always"]})
    assert "set approval=always" in result
    assert captured[0] == [
        {"op_id": "eventkit--probe", "effect": None, "approval": "always"}
    ]


def test_unknown_word_rejected(loaded: tuple[Any, list[Any]]) -> None:
    """Any word outside the effect/approval sets raises before persisting."""
    module, captured = loaded
    with pytest.raises(ValueError, match="unknown classification word"):
        module.execute({"op_id": "x", "words": ["read", "purple"]})
    assert captured == []


def test_conflicting_effects_rejected(loaded: tuple[Any, list[Any]]) -> None:
    """Two effect words from the same set raise rather than picking one."""
    module, captured = loaded
    with pytest.raises(ValueError, match="conflicting effect words"):
        module.execute({"op_id": "x", "words": ["read", "write"]})
    assert captured == []


def test_conflicting_approvals_rejected(loaded: tuple[Any, list[Any]]) -> None:
    """Two approval words from the same set raise."""
    module, captured = loaded
    with pytest.raises(ValueError, match="conflicting approval words"):
        module.execute({"op_id": "x", "words": ["always", "never"]})
    assert captured == []


def test_three_word_input_accepted(loaded: tuple[Any, list[Any]]) -> None:
    """`read never execute` is rejected (two effects), `read never write` rejected too."""
    module, _ = loaded
    with pytest.raises(ValueError, match="conflicting effect words"):
        module.execute({"op_id": "x", "words": ["read", "never", "execute"]})


def test_repeated_same_word_accepted(loaded: tuple[Any, list[Any]]) -> None:
    """Same effect repeated is not a conflict."""
    module, captured = loaded
    module.execute({"op_id": "x", "words": ["read", "read", "never"]})
    assert captured[0][-1]["effect"] == "read"


def test_missing_op_id(loaded: tuple[Any, list[Any]]) -> None:
    module, _ = loaded
    with pytest.raises(ValueError, match="op_id is required"):
        module.execute({"words": ["read"]})


def test_missing_words(loaded: tuple[Any, list[Any]]) -> None:
    module, _ = loaded
    with pytest.raises(ValueError, match="words must"):
        module.execute({"op_id": "x"})
    with pytest.raises(ValueError, match="words must"):
        module.execute({"op_id": "x", "words": []})


def test_word_case_insensitive(loaded: tuple[Any, list[Any]]) -> None:
    module, captured = loaded
    module.execute({"op_id": "x", "words": ["READ", "Never"]})
    assert captured[0][-1]["effect"] == "read"
    assert captured[0][-1]["approval"] == "never"
