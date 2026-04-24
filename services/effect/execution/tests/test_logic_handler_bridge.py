"""Unit tests for logic op handler loading and invocation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.shared.envelope import EnvelopeKind, new_meta, success
from services.effect.execution.logic_handler_bridge import (
    build_logic_op_handler,
)
from services.effect.execution.registry import OpRuntime
from services.reason.policy.domain import (
    OpInvocationRequest,
    OpPolicyInput,
    InvocationPolicyInput,
)


class _FakeRuntime(OpRuntime):
    def invoke_nested(
        self,
        *,
        op_id: str,
        input_payload: dict[str, Any],
    ):
        raise NotImplementedError


class _FakeObjectService:
    def stat_object(self, *, meta: Any, object_key: str):
        return success(
            meta=meta,
            payload={
                "object_key": object_key,
                "size_bytes": 42,
            },
        )


def _write_logic_op(tmp_path: Path, execute_source: str) -> Path:
    package_dir = tmp_path / "demo-logic"
    (package_dir / "test").mkdir(parents=True, exist_ok=True)
    (package_dir / "op.json").write_text(
        json.dumps(
            {
                "op_id": "demo-logic",
                "kind": "logic",
                "version": "1.0.0",
                "summary": "Demo logic op",
                "effect": "execute",
                "approval": "never",
            }
        ),
        encoding="utf-8",
    )
    (package_dir / "README.md").write_text("# demo-logic\n", encoding="utf-8")
    (package_dir / "execute.py").write_text(execute_source, encoding="utf-8")
    (package_dir / "test" / "test_demo_logic.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    return package_dir


def _request(*, input_payload: dict[str, Any]) -> OpInvocationRequest:
    return OpInvocationRequest(
        metadata=new_meta(
            kind=EnvelopeKind.COMMAND,
            source="test",
            principal="operator",
        ),
        op_policy=OpPolicyInput(
            op_id="demo-logic",
            kind="logic",
            version="1.0.0",
            effect="execute",
            approval="never",
        ),
        invocation=InvocationPolicyInput(
            actor="operator",
            source="assistant",
            channel="test",
            invocation_id="inv-1",
        ),
        input_payload=input_payload,
    )


def test_logic_op_handler_supports_zero_argument_execute(tmp_path: Path) -> None:
    package_dir = _write_logic_op(
        tmp_path,
        "def execute():\n    return {'ok': True}\n",
    )
    handler = build_logic_op_handler(
        op_id="demo-logic",
        package_dir=package_dir,
        entrypoint="execute.py",
        components={},
    )

    result = handler(_request(input_payload={}), _FakeRuntime())

    assert result.output == {"ok": True}


def test_logic_op_handler_supports_call_target_helper(tmp_path: Path) -> None:
    package_dir = _write_logic_op(
        tmp_path,
        "\n".join(
            [
                "def execute(input_payload, invoke_call_target):",
                "    payload = invoke_call_target(",
                "        call_target='service_object.stat_object',",
                "        input_payload={'object_key': input_payload['object_key']},",
                "    )",
                "    return payload",
            ]
        )
        + "\n",
    )
    handler = build_logic_op_handler(
        op_id="demo-logic",
        package_dir=package_dir,
        entrypoint="execute.py",
        components={"service_object": _FakeObjectService()},
    )

    result = handler(_request(input_payload={"object_key": "obj-1"}), _FakeRuntime())

    assert result.output == {"object_key": "obj-1", "size_bytes": 42}
