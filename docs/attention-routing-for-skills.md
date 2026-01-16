# Attention Routing for Skills (Stub)

This document defines the intended routing behavior for skill outputs. The runtime
includes a routing hook, but it currently performs no action.

## Intended Rules (Deferred)

- Skills tagged with `requires_routing` should send results through the attention
  router before notifying the user.
- Read-only skills may run silently and return results directly.
- Write or side-effect skills should request confirmation or escalation depending on
  autonomy level.

## Runtime Hook

The runtime calls a routing hook before policy evaluation and execution. The default
hook is a no-op; future implementations may inspect skill metadata and decide whether
or how to surface results.
