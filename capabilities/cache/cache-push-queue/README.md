# cache-push-queue

Push one component-scoped queue value.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `component_id` | `str` | yes | — | Canonical component id namespace for the queue. |
| `queue` | `str` | yes | — | Queue name within the component namespace. |
| `value` | `object` | yes | — | JSON-serializable value to enqueue. |

## Returns

`QueueDepth` — the queue depth snapshot after the push.
