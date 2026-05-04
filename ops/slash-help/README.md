# slash-help

Lists slash commands registered in the Execution, formatted for display in operator channels (console, Signal).

Bound to `/help`. With no argument, lists all slash commands sorted alphabetically (with aliases and descriptions). With a `query` argument, narrows to matches:

* exact match on a slash name, alias, or `op_id` returns the per-op detail view (gates, inputs, outputs, required ops);
* substring match returns a filtered list, or the detail view when exactly one slash binding survives the filter;
* no match returns a friendly guidance message.

Examples: `/help` (full listing), `/help orksp` (filters to workspace-related commands), `/help workspace-register` (detail view).
