# cache-pop-queue

Pop one component-scoped queue value using FIFO order.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `component_id` | `str` | yes | — | Canonical component id namespace for the queue. |
| `queue` | `str` | yes | — | Queue name within the component namespace. |

## Returns

`QueueEntry | null` — the next queued value, or `null` when the queue is empty.
