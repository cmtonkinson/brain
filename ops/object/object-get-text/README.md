# object-get-text

Read one persisted text object and return metadata plus decoded content.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `object_key` | `str` | yes | — | Canonical object key (`<version>:<algorithm>:<64hex>`). |
| `encoding` | `str` | no | `utf-8` | Text encoding used to decode the stored bytes. |

## Returns

An object containing `object`, `content`, and `encoding`.
