"""Logic op for persisting base64 content through Object Service."""

from __future__ import annotations

import base64


def execute(input_payload, invoke_call_target):
    """Decode base64 content and persist it as one object blob."""
    content_base64 = input_payload.get("content_base64")
    if not isinstance(content_base64, str) or content_base64 == "":
        raise ValueError("content_base64 is required")

    payload = invoke_call_target(
        call_target="service_object.put_object",
        input_payload={
            "content": base64.b64decode(content_base64, validate=True),
            "extension": input_payload.get("extension", ""),
            "content_type": input_payload.get("content_type", ""),
            "original_filename": input_payload.get("original_filename", ""),
            "source_uri": input_payload.get("source_uri", ""),
        },
    )
    return payload.model_dump(mode="json")
