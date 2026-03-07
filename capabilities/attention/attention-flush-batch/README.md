# attention-flush-batch

Flush one pending Attention Router batch and deliver a consolidated summary notification.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `batch_key` | `str` | yes | — | Batch key to flush. |
| `actor` | `str` | no | `operator` | Actor identity for routing context. |
| `channel` | `str` | no | `""` | Channel identifier (for example `signal`). |
| `recipient_e164` | `str` | no | `""` | Optional recipient E.164 override. |
| `sender_e164` | `str` | no | `""` | Optional sender E.164 override. |
| `title` | `str` | no | `""` | Optional notification title for the flushed summary. |

## Returns

A routed-notification result object with decision metadata and delivery state.
