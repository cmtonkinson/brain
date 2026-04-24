"""Logic op for reading text content through Object Service."""


def execute(input_payload, invoke_call_target):
    """Read one object and decode its bytes as text."""
    object_key = input_payload.get("object_key")
    if not isinstance(object_key, str) or object_key.strip() == "":
        raise ValueError("object_key is required")

    encoding = input_payload.get("encoding", "utf-8")
    if not isinstance(encoding, str) or encoding.strip() == "":
        raise ValueError("encoding must be a non-empty string")
    normalized_encoding = encoding.strip()

    payload = invoke_call_target(
        call_target="service_object.get_object",
        input_payload={"object_key": object_key},
    )
    return {
        "object": payload.object.model_dump(mode="json"),
        "content": payload.content.decode(normalized_encoding),
        "encoding": normalized_encoding,
    }
