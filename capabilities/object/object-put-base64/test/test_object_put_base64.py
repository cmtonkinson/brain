"""Unit tests for the object-put-base64 logic skill."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_execute():
    path = Path(__file__).resolve().parent.parent / "execute.py"
    spec = importlib.util.spec_from_file_location("object_put_base64_execute", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.execute


class _FakeRecord:
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {"ref": {"object_key": "b1:sha256:" + ("b" * 64)}}


def test_execute_decodes_base64_and_delegates() -> None:
    execute = _load_execute()
    seen = {}

    def _invoke_call_target(*, call_target, input_payload):
        seen["call_target"] = call_target
        seen["input_payload"] = input_payload
        return _FakeRecord()

    result = execute(
        {
            "content_base64": "aGVsbG8=",
            "extension": "bin",
            "content_type": "application/octet-stream",
        },
        _invoke_call_target,
    )

    assert seen["call_target"] == "service_object_authority.put_object"
    assert seen["input_payload"]["content"] == b"hello"
    assert result["ref"]["object_key"].startswith("b1:sha256:")
