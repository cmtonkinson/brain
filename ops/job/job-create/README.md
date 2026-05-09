# job-create

Create a Job Service schedule that invokes one op later. Use `start_state: "active"` when the job should begin firing, or `draft` when it should be reviewed before activation.

The action shape is currently `{"type": "op_invocation", "op_id": "...", "input_payload": {...}}`.
