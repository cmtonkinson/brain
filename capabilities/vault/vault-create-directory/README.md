# vault-create-directory

Create one directory in the vault.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `directory_path` | `str` | yes | — | Vault-relative path for the new directory. |
| `recursive` | `bool` | no | `false` | Create parent directories as needed. |

## Returns

`VaultEntry` — metadata for the created directory.
