"""Logic skill for persisting text content through Object Authority Service."""


def execute(input_payload, invoke_call_target):
    """Encode text content and persist it as one object blob."""
    content = input_payload.get("content")
    if not isinstance(content, str) or content == "":
        raise ValueError("content is required")

    encoding = input_payload.get("encoding", "utf-8")
    if not isinstance(encoding, str) or encoding.strip() == "":
        raise ValueError("encoding must be a non-empty string")
    normalized_encoding = encoding.strip()

    payload = invoke_call_target(
        call_target="service_object_authority.put_object",
        input_payload={
            "content": content.encode(normalized_encoding),
            "extension": input_payload.get("extension", "txt"),
            "content_type": input_payload.get(
                "content_type",
                "text/plain; charset=utf-8",
            ),
            "original_filename": input_payload.get("original_filename", ""),
            "source_uri": input_payload.get("source_uri", ""),
        },
    )
    return payload.model_dump(mode="json")
