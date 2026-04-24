# object-delete

Delete one persisted object by canonical object key.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `object_key` | `str` | yes | — | Canonical object key (`<version>:<algorithm>:<64hex>`). |

## Returns

`bool` — `true` on success. Deletion is idempotent.
