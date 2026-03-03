# object-get-base64

Read one persisted object and return metadata plus base64-encoded content.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `object_key` | `str` | yes | — | Canonical object key (`<version>:<algorithm>:<64hex>`). |

## Returns

An object containing `object` and `content_base64`.
