# object-stat

Read metadata for one persisted object by canonical object key.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `object_key` | `str` | yes | — | Canonical object key (`<version>:<algorithm>:<64hex>`). |

## Returns

`ObjectRecord` — object identity and metadata.
