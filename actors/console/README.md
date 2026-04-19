# Brain Console
The Brain Console is an L2 actor that provides a terminal UI for operator
interaction with Brain.

Like all actors, its only access path into Core is the Brain SDK over HTTP.

------------------------------------------------------------------------
## Running
```sh
bin/console
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `BRAIN_HOST` | `127.0.0.1` | Core HTTP host |
| `BRAIN_PORT` | `8898` | Core HTTP port |
| `BRAIN_TIMEOUT_SECONDS` | `60.0` | SDK request timeout |
| `BRAIN_CONSOLE_POLL_TIMEOUT_SECONDS` | `30.0` | Long-poll wait on each response check |
| `EDITOR` | `vim` | Editor launched by `ctrl+g` |

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
Timestamps appear on each bubble. History from the current MAS session
loads on startup.

------------------------------------------------------------------------
## Key Bindings
| Key | Action |
|---|---|
| `enter` | Send message |
| `alt+enter` | Insert newline |
| `ctrl+g` | Open `$EDITOR` with a temp file; send contents on save+exit |
| `ctrl+l` | Clear input field |
| `ctrl+q` | Quit |

------------------------------------------------------------------------
## Message Flow
```
Operator types → POST /switchboard/enqueue_console_message
                         ↓
                  console_inbound queue (CAS)
                         ↓
                  Agent poll_operator_instruction
                         ↓
                  Agent processes turn (same session as Signal)
                         ↓
                  attention-notify capability → channel="console"
                         ↓
                  Attention Router _deliver_via_console
                         ↓
                  console_outbound queue (CAS)
                         ↓
Console polls → POST /attention-router/poll_console_response
                         ↓
                  Brain bubble rendered in TUI
```

Console and Signal share one MAS session. A message sent from Signal is
visible in Console history and vice versa.

------------------------------------------------------------------------
## Architecture Notes
The console uses two CAS queues:
- `console_inbound` — operator messages waiting for the Agent
- `console_outbound` — Brain responses waiting for the TUI

Queue names are configured in `config/core.yaml` under
`service.switchboard.console_queue_name` and
`service.switchboard.console_response_queue_name`.

The poll loop runs as a daemon thread inside the Textual app. It uses a
configurable long-poll timeout (`BRAIN_CONSOLE_POLL_TIMEOUT_SECONDS`,
default 30 s). The daemon thread exits immediately when the process exits,
so `ctrl+q` is always responsive.


------------------------------------------------------------------------
_End of Brain Console README_
