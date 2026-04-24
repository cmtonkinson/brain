"""Logic op for reading base64 content through Object Service."""

from __future__ import annotations

import base64


def execute(input_payload, invoke_call_target):
    """Read one object and return its bytes encoded as base64."""
    object_key = input_payload.get("object_key")
    if not isinstance(object_key, str) or object_key.strip() == "":
        raise ValueError("object_key is required")

    payload = invoke_call_target(
        call_target="service_object.get_object",
        input_payload={"object_key": object_key},
    )
    return {
        "object": payload.object.model_dump(mode="json"),
        "content_base64": base64.b64encode(payload.content).decode("ascii"),
    }
