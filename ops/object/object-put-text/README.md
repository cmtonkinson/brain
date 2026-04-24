# object-put-text

Persist one UTF-8 text blob and return the authoritative object record.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `content` | `str` | yes | — | Text content to persist. |
| `extension` | `str` | no | `txt` | File extension recorded for the object. |
| `content_type` | `str` | no | `text/plain; charset=utf-8` | MIME type recorded for the object. |
| `original_filename` | `str` | no | `""` | Optional original filename metadata. |
| `source_uri` | `str` | no | `""` | Optional source URI metadata. |
| `encoding` | `str` | no | `utf-8` | Text encoding used before persistence. |

## Returns

`ObjectRecord` — object identity and metadata.
