# Glossary
_This document is generated from `docs/meta/glossary.yaml`. Do not edit by hand._

------------------------------------------------------------------------
## Terms
- **Actor &mdash;** A client of the _Brain Core Sdk_, such as the Agent, CLI, or Worker.
- **Adapter &mdash;** A _Resource_ which governs interaction with the outside world such as an MCP Server, messaging platform, web API, etc.
- **Brain Core SDK &mdash;** The interface on top of the _Public Api_ for direct consumption (via HTTP) by _Tier_ 3 Actors. This is the only system interface available to Actors.
- **Component &mdash;** An isolated unit of responsibility or work. Each _Actor_, _Service_, and _Resource_ is a _Component_.
- **Conversation Episode &mdash;** A Recall-owned grouping of related dialogue turns within a _Session_. Conversation Episodes rotate on explicit boundaries or configured idle gaps and are used for observability _Session_ grouping such as Langfuse sessions.
- **Delegation &mdash;** The Reason-_Plane_ _Service_ that owns the lifecycle of _Subagent_ invocations: queue, claim, status, transcripts, budget ledger, and cancel.
- **Effect Plane &mdash;** The _Plane_ responsible for external consequences: comprises Services and _Adapter_ Resources responsible for external I/O.
- **Envelope &mdash;** The structured message wrapper used for all cross-_Tier_ and cross-_Service_ communication, consisting of metadata, payload, and errors.
- **Logic Op &mdash;** An _Op_ implementing arbitrary/custom Python code.
- **Manifest &mdash;** The self-registration declaration that each _Component_ exports to join the global registry at import time.
- **MCP Op &mdash;** An _Op_ which wraps a single MCP tool call, scoped by the name of the MCP server as configured.
  _(Note: The MCP spec does not enforce useful schema definitions over tool output format, which can be limiting for automation. Brain provides a mechanism to manually define these, however (see XXX).)_
- **Native Op &mdash;** An _Op_ which wraps a _Resource_ API call. Native Ops are the foundational units of work exposed to Actors.
- **Op &mdash;** A governed, testable unit of action with a clear input/output contract, bounded authority, and inspectable results. Kinds are `Native`, `MCP`, `Pipeline`, and `Logic`.
- **Operator &mdash;** The human user of the system. All personal-assistant work rolls up to the _Operator_ as the accountable _Principal_.
- **Pipeline Op &mdash;** A compound _Op_ defined by an ordered set of other _Op_ references; assuming the output format schema of each _Op_ is compatible with the input format schema of the next, they form an execution chain: you provide inputs to the first _Op_ and receive a return value from the final _Op_.
- **Plane &mdash;** An abstract 'vertical' segment of Brain architecture defined by its ontological purpose. There are three Planes: State, Effect, and Reason.
- **Principal &mdash;** The accountable identity for a request, propagated unchanged across calls in _Envelope_ metadata. Examples: `operator`, `core`, or a _Service_ name.
- **Provider &mdash;** The concrete backing surface behind a _Resource_, such as a containerized system, a host process/file, or some third-party API. Resources are Brain-facing interfaces over Providers.
- **Public API &mdash;** The internal, native, Python surface exported by a given _Service_. The _Public Api_ is the canonical interface for any _Service_.
- **Reason Plane &mdash;** The _Plane_ housing higher-order executive functions by composing functionality from the _State Plane_ and _Effect Plane_.
- **Resource &mdash;** Trustees of side effects. All real-world consequences are gated by a _Resource_ _Component_. Types are `Substrate` and `Adapter`.
- **Service &mdash;** The primary carriers of business logic, responsible for coordinating system state and behavior.
- **Session &mdash;** A Recall-owned durable memory continuity scope for dialogue, focus, and rolling summaries. A _Session_ may contain multiple Conversation Episodes over time.
- **State Plane &mdash;** The _Plane_ responsible for durable data, comprising _Substrate_-owning Services and their _Substrate_ Resources.
- **Subagent &mdash;** A focused, headless agentic loop spawned by _Delegation_ to accomplish one task. Distinct from the conversational Agent: runs under its own _Principal_ and Channel, with a narrowed tool allowlist and per-invocation budgets.
- **Substrate &mdash;** A _Resource_ which governs state, such as a database, document store, or cache.
- **Tier &mdash;** An abstract 'horizontal' segment of Brain architecture defined by its purpose and access control rules. Brain components fall into three Tiers: 1, 2, and 3.
- **Trace &mdash;** A `trace_id`-scoped execution episode linking causally related Envelopes. Cross-_Trace_ causality is preserved via `parent_id` references.
- **Turn &mdash;** One persisted dialogue item in a _Session_, either inbound from the _Operator_ or outbound from Brain. Turns carry _Trace_ and _Conversation Episode_ identifiers for correlation.


------------------------------------------------------------------------
_End of Glossary_
