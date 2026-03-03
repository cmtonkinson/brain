"""Unit tests for the object-get-text logic skill."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_execute():
    path = Path(__file__).resolve().parent.parent / "execute.py"
    spec = importlib.util.spec_from_file_location("object_get_text_execute", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.execute


class _FakeObject:
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {"ref": {"object_key": "b1:sha256:" + ("a" * 64)}}


class _FakeGetResult:
    object = _FakeObject()
    content = b"hello"


def test_execute_decodes_text_and_returns_structured_output() -> None:
    execute = _load_execute()
    seen = {}

    def _invoke_call_target(*, call_target, input_payload):
        seen["call_target"] = call_target
        seen["input_payload"] = input_payload
        return _FakeGetResult()

    result = execute(
        {
            "object_key": "b1:sha256:" + ("a" * 64),
        },
        _invoke_call_target,
    )

    assert seen["call_target"] == "service_object_authority.get_object"
    assert result["content"] == "hello"
    assert result["encoding"] == "utf-8"
