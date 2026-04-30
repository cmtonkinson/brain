# Brain
Brain is a local, private, personal assistant. It pays attention to your stuff,
turns it into durable memory, and takes (or proposes) bounded action on your
behalf.

More academically, it's an exocortex for attention, memory, and action:
cognitive infrastructure that prioritizes context, directs intent deliberately,
and closes loops.

***NOTE:** This project is still in active development and somewhat unstable.
Don't @ me, bro.*

![Status: alpha](https://img.shields.io/badge/Alpha-orange?style=flat)
![CI](https://github.com/cmtonkinson/brain/actions/workflows/tests.yaml/badge.svg?branch=main)
![Python: 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)
![macOS](https://img.shields.io/badge/macOS-supported-lightgrey?logo=apple&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

![Brain](img/brain-purple-512.png)

------------------------------------------------------------------------
## Motivation
I wanted a Siri that didn't suck; a real Jarvis.

My initial use case was to manage commitments: to look across messages, email,
meetings, etc. and not just build up a todo list, but actually capture the
essence, impact, effort, and timeline of obligations and then facilitate timely
action without abusing my limited attention span. Think:

> Hey boss, I know we have that project meeting next Thursday but I don't think
> we've prepped yet - tomorrow looks pretty open so I've put a 90 minute focus
> block on the calendar for that.

January 1st, 2026, I decided to start an experiment, bolting [PydanticAI] on top
of [Obsidian] and piping communication through [Signal]. What exists now is a
maturation & formalization of that initial prototype, redesigned from the ground
up with crisp boundaries to ensure:
* governance
* transparency
* observability
* extensibility

------------------------------------------------------------------------
## What It Does Today
* Conversational interaction over [Signal] and a local console TUI.
* Read/write your [Obsidian] vault with revision-safe edits, atomic moves, and
  trash-aware deletes.
* Semantic vault search using local embeddings and [Qdrant].
* Governed tool execution: every Op is policy-gated and real-world side effects
  flow through approval-aware gateways. Every invocation is auditable.
* First-class [MCP] integration for third-party tools, with per-tool effect and
  approval classification.
* Commitment capture, miss detection, and timing-aware operator reminders.
* Scheduled and background work via the Worker actor, plus optional Subagent
  delegation for focused, budget-bounded subtasks.
* Universal ingestion pipeline: capture &rarr; normalize &rarr; anchor &rarr;
  index, for arbitrary content.

See the [Roadmap](docs/roadmap.md) for what's next.

------------------------------------------------------------------------
## Conceptual Model
Brain has three primary domains:
1. A **personal knowledge base**: durable, human-readable, locally-stored
   information. At its simplest, this could be a single (if very large) file.
2. A **reasoning engine**: an LLM used to interpret context, propose actions,
   explain decisions, and interact with you conversationally.
3. **Ops**: governed, testable units of action that wrap a single capability
   (e.g. "create a calendar event") via native APIs or MCP Servers.

Internally those domains are organized along two orthogonal axes &mdash; Planes
(what does it own?) and Tiers (who is allowed to talk to whom?).

### Planes
* **State**: owns data
* **Effect**: owns action
* **Reason**: owns coordination

### Tiers
* **3 (Actors)**: operator interaction surface
* **2 (Services)**: internal business logic
* **1 (Resources)**: integrations with the outside world

The Boundaries & Responsibilities diagram is a conceptual map of those axes. It
is not a deployment or data flow diagram and it doesn't describe the full scope
of the project, but it captures how control flow, cohesion, and decoupling are
intended to work. See the full [Boundaries &
Responsibilities](docs/boundaries-and-responsibilities.md) document for details.

![Boundaries & Responsibilities](img/boundaries-and-responsibilities.png)

------------------------------------------------------------------------
## Runtime Topology
Brain uses Docker for process isolation. In an ideal world every process would
be containerized, but for security, usability, and performance reasons a
limited number of services need to run directly on the host:
* [Obsidian] with the [Local REST API] plugin &mdash; *required*
* [Ollama] &mdash; *recommended* for embedding, *optional* for inference
* Companion project [Host MCP Gateway] &mdash; a bridge to localhost APIs;
  *optional*

All other services run in isolation under Docker Compose:
* Brain Assistant, built with [PydanticAI]
* Brain Core, which houses all runtime *State*, *Effect*, and *Reason*
  Components
* Brain Worker and Subagent, for async/parallel work
* Brain MCP Adapter sidecar, connecting to configured MCP servers
* Secure messaging thanks to [Signal]
* Durable working state and application logs in [Postgres]
* Caching and queueing handled by [Valkey]
* Vector search for semantic embeddings powered by [Qdrant]
* Object blobs stored in [SeaweedFS]

There is also an optional OpenTelemetry-based observability stack in
`docker-compose.observability.yaml`. It routes Brain traces through an OTel
Collector to self-hosted [Langfuse] (backed by [ClickHouse]) and [Grafana]
([Prometheus], [Loki], [cAdvisor]), on top of the existing [Postgres], [Valkey],
and [SeaweedFS] services. See [Observability](docs/observability.md) for
connection details, required secrets, environment variables, and startup
checks.

------------------------------------------------------------------------
## Quickstart
On macOS, with Docker, Python 3.14, and [Obsidian] + the [Local REST API]
plugin already installed:
```sh
make deps
cp .env.sample .env
mkdir -p ~/.config/brain
for f in config/*.yaml.sample; do
  cp "$f" ~/.config/brain/"$(basename "$f" .sample)"
done
# edit ~/.config/brain/secrets.yaml with your API keys, etc.
make up
```

See the [Development Guide](docs/development-guide.md) for full prerequisites,
configuration details, and the test/lint workflow.

------------------------------------------------------------------------
## Key Documentation
For the full index see the [`docs/`](docs/) directory, but this is where I'd
start as a gentle introduction:
* [Manifesto](docs/manifesto.md) &mdash; Design philosophy and first
  principles.
* [Boundaries & Responsibilities](docs/boundaries-and-responsibilities.md)
  &mdash; Tier and Plane model, service catalog, and shared infrastructure.
* [Development Guide](docs/development-guide.md) &mdash; Setup, make targets,
  testing, and contributor workflows.
* [Roadmap](docs/roadmap.md) &mdash; Phased implementation plan and current
  status.

------------------------------------------------------------------------
## License
Released under the [MIT License](LICENSE.txt).


[Claude Cowork]: https://claude.com/product/cowork
[ClickHouse]: https://clickhouse.com
[Grafana]: https://grafana.com
[Hermes Agent]: https://github.com/NousResearch/hermes-agent
[issues]: https://github.com/cmtonkinson/brain/issues
[Langfuse]: https://langfuse.com
[Local REST API]: https://github.com/coddingtonbear/obsidian-local-rest-api
[Loki]: https://grafana.com/oss/loki/
[MCP]: https://modelcontextprotocol.io
[Obsidian]: https://obsidian.md
[Ollama]: https://ollama.com
[OpenClaw]: https://github.com/openclaw/openclaw
[Postgres]: https://www.postgresql.org
[Prometheus]: https://prometheus.io
[PydanticAI]: https://ai.pydantic.dev
[Qdrant]: https://qdrant.tech
[SeaweedFS]: https://github.com/seaweedfs/seaweedfs
[Signal]: https://signal.org
[Valkey]: https://valkey.io
[cAdvisor]: https://github.com/google/cadvisor
[Host MCP Gateway]: https://github.com/cmtonkinson/host-mcp-gateway


------------------------------------------------------------------------
_End of README_
