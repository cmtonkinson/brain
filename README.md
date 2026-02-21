# Brain
An exocortex for attention, memory, and action. This is a local-first AI system
grounded in data sovereignty and durable knowledge; cognitive infrastructure
that prioritizes context, directs intent deliberately, and closes loops.

_**NOTE:** 🚫 This project is in active/experimental development and extremely
unstable. Don't @ me, bro. When it gets a non-Cthullian version number, you'll
know it's safe(r) to use._

![Status: Pre-Alpha](https://img.shields.io/badge/Pre--Alpha-red?style=flat)
![CI](https://github.com/cmtonkinson/brain/actions/workflows/tests.yaml/badge.svg?branch=main)
![Python: 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)
![macOS](https://img.shields.io/badge/macOS-supported-lightgrey?logo=apple&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

![Brain](img/brain-purple-512.png)

## Motivation
I wanted a Siri that didn't suck; a Jarvis. An assistant which had access to my:
- files
- meeting transcripts
- calendar events
- messages
- the web (news, weather, search, ...)
- et cetera

and the capability to:
- answer questions
- remind me of things (as and when pertinent, not robotically)
- assist me in tasks
- ... and continuously learn from all of it

On January 1st, 2026, I decided to start by bolting
[PydanticAI](https://ai.pydantic.dev) onto [Obsidian](https://obsidian.md) and
piping it through [Signal](https://signal.org). What exists now is a maturation
& formalization of that initial prototype, redesigned from the ground up with
crisp boundaries to ensure:
- data sovereignty
- security & governance
- extensibility

## Overview
_Conceptually_, Brain has three primary domains:
1. A **personal knowledge base**: durable, human-readable, locally-stored
   information. At its simplest, this could be a single (if very large) file.
2. A **reasoning engine**: an LLM used to interpret context, propose actions,
   explain decisions, and interact with you conversationally.
3. **Capabilities**: governed operations that interact with the real world
   (files, calendars, messaging, etc.) via native APIs or MCP Servers.

_Operationally_, the system takes advantage of Docker for process isolattion. In
an ideal world every process would be containerized, but for various reasons
(security, usability, performance) there are a limited number of services that
need to run directly on your host system:
- **Obsidian**, with its various plugins &mdash; _required_
- **Ollama** &mdash; _recommended_ for embedding, _optional_ for inference
- The **Host MCP Gateway** server (an HTTP proxy) &mdash; _required assuming you
  want MCP Servers with host-level access (e.g. EventKit on macOS)_

All other services are run with Docker Compose:
- Brain Agent, built with **Pydantic AI**
- Brain Core, which houses all runtime State, Action, and Control services
- Secure messaging thanks to **Signal**
- Durable working state and application logs are kept in **Postgres**
- Caching and queueing are handled by **Redis**
- Vector search for semantic embeddings is powered by **Qdrant**
- Memory (short- and long-term) is managed by **Letta**

There is also an optional OpenTelemetry-based observability stack (a separate
but related Docker Compose) which leverages **Prometheus**, **Loki**,
**Grafana**, and **cAdvisor**.

## Architecture
If you aren't familiar with the [C4 Model](https://c4model.com), I'd highly
recommend it.

### C4 System Context Diagram
It's just you, your agent, and your local system ...and whatever parts of the
Internet you choose to aim it at.
![C4 Context](img/c4-context.png)

### C4 Container Diagram
"That's a lot of processes!" Yeah... I know.
![C4 Container](img/c4-container.png)

### System Boundaries & Responsibilities
Boundaries & Responsibilities are one of the most useful ways to think about the
system architecture... just remember, this is conceptual - it's not a
deployment, network, or data flow diagram. This is a companion visualization for
the full [Boundaries &
Responsibilities](docs/boundaries-and-responsibilities.md) document.
![Boundaries & Responsibilities](img/boundaries-and-responsibilities.png)

## Data Protection
What _really_ needs to be backed up?

**High Priority —** Authoritative Information
- Custom configuration & policy files under `~/.config/brain`
- Obsidian vault (canonical knowledge, notes, promoted memory)
- Postgres (operational state - scheduels, logs, etc.)
- Local object store `root_dir` (raw artifacts)

**Medium Priority —** Durable System State
- Signal CLI state (device + message metadata)

**Low Priority —** Derived / Cache
- Qdrant embeddings and indexes
- TODO: Add Redis

## Phased Implementation
### Phase 1: (✅ DONE) ~~Text interaction + memory + MCP tools~~
- ~~Obsidian Local REST API integration (read/write)~~
- ~~Letta archival memory~~
- ~~Code-Mode (UTCP) for MCP tool calls~~
- ~~Signal messaging with allowlisted senders~~
- ~~Vault indexer + Qdrant semantic search~~
- ~~Optional observability stack (OTel)~~

### Phase 2: (✅ DONE) ~~The "Assitant Triangle"~~
- ~~Skill framework + capability registry~~
- ~~Attention router + interruption policy~~
- ~~Commitment tracking + loop closure~~
- ~~Requires scheduled/background jobs, policy engine, ingestion pipeline~~

### Phase 3: (⚠️ IN WORK) Refactor
- ~~Define clean subsystem boundaries & responsibilities~~
- Refactor codebase along clean boundaries with crisp public APIs
- Extensive testing for enforcement of new semantics
- Review all documentation to ensure truth & alignment with actual system

### Phase 4: Voice + telephony + SMS (unstarted)
- Local voice (whisper.cpp + Piper, openWakeWord)
- POTS phone support (Twilio Media Streams)
- SMS fallback (Google Voice)
