# vault-list-directory

List file and directory entries under one vault-relative path.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `directory_path` | `str` | yes | — | Vault-relative directory path to list. |

## Returns

`list[VaultEntry]` — list of file and directory entry metadata objects.
