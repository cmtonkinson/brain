# Brain Console
The Brain Console is a T3 actor that provides a terminal UI for operator
interaction with Brain.

Like all actors, its only access path into Core is the Brain SDK over HTTP.

------------------------------------------------------------------------
## Running
```sh
bin/console
```

All settings are loaded by `load_actor_settings()` from the shared
`actors.yaml` config file. See [`actors.console` in the Configuration
Reference](../../docs/configuration.md) for the full key reference.

The `EDITOR` env var overrides the configured editor when set.

------------------------------------------------------------------------
## Layout
```
┌─────────────────────────────────────────────────────┐
│ Brain Console                                       │  ← header
├─────────────────────────────────────────────────────┤
│                                                     │
│  Brain  09:41                                       │  ← Brain bubble (left)
│    Response text here.                              │
│                                                     │
│                                         09:42  You  │  ← Operator bubble (right)
│                           Message text here.        │
│                                                     │
├─────────────────────────────────────────────────────┤
│ > _                                                 │  ← input
│ [enter] send  [ctrl+g] $EDITOR  [ctrl+l] clear      │
└─────────────────────────────────────────────────────┘
```

Brain messages are left-aligned. Operator messages are right-aligned.
Timestamps appear on each bubble. History from the current Recall session
loads on startup.

------------------------------------------------------------------------
## Key Bindings
| Key | Action |
|---|---|
| `enter` | Send message |
| `alt+enter` | Insert newline |
| `ctrl+g` | Open `$EDITOR` with a temp file; load contents into input on save+exit |
| `ctrl+l` | Clear input field |
| `ctrl+q` | Quit |

------------------------------------------------------------------------
## Message Flow
```
Operator types → POST /relay/ingest_inbound_message
                          ↓
                   operator_inbound queue (Cache)
                         ↓
                  Agent poll_operator_instruction
                         ↓
                  Agent processes turn (same session as Signal)
                         ↓
                  relay-notify op → channel="console"
                         ↓
                  Relay outbound _deliver_via_console
                         ↓
                  console_outbound queue (Cache)
                         ↓
Console polls → POST /relay/poll_console_response
                         ↓
                  Brain bubble rendered in TUI
```

Console and Signal share one Recall session. A message sent from Signal is
visible in Console history and vice versa.

------------------------------------------------------------------------
## Architecture Notes
The console uses shared Relay queues:
* `operator_inbound` — normalized operator messages waiting for the Agent
* `console_outbound` — Brain responses waiting for the TUI

Queue names are configured in `config/core.yaml` under
`service.inbound.queue_name` and `service.inbound.console_response_queue_name`.

The poll loop runs as a daemon thread inside the Textual app. It uses a
configurable long-poll timeout (`actors.console.poll_timeout_seconds`,
default 30 s). The daemon thread exits immediately when the process exits,
so `ctrl+q` is always responsive.


------------------------------------------------------------------------
_End of Brain Console README_
