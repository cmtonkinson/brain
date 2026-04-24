# object-put-base64

Persist one base64-encoded blob and return the authoritative object record.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `content_base64` | `str` | yes | — | Base64-encoded blob content. |
| `extension` | `str` | yes | — | File extension recorded for the object. |
| `content_type` | `str` | yes | — | MIME type recorded for the object. |
| `original_filename` | `str` | no | `""` | Optional original filename metadata. |
| `source_uri` | `str` | no | `""` | Optional source URI metadata. |

## Returns

`ObjectRecord` — object identity and metadata.
