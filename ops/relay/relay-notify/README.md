# relay-notify

Route one outbound notification and let the Relay outbound decide to send, suppress, or batch.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `actor` | `str` | no | `operator` | Actor identity for routing context. |
| `channel` | `str` | no | `""` | Channel identifier (for example `signal`). |
| `title` | `str` | no | `""` | Optional title rendered above message content. |
| `message` | `str` | yes | — | Notification body to route. |
| `recipient_e164` | `str` | no | `""` | Optional recipient E.164 override. |
| `sender_e164` | `str` | no | `""` | Optional sender E.164 override. |
| `dedupe_key` | `str` | no | `""` | Optional dedupe key for suppression window checks. |
| `batch_key` | `str` | no | `""` | Optional batch key for deferred digest delivery. |
| `force` | `bool` | no | `false` | Bypass dedupe, batching, and rate-limit suppression checks. |

## Returns

A routed-notification result object with decision metadata and delivery state.
