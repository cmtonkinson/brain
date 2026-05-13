# Glossary
*This document is generated from `docs/meta/glossary.yaml`. Do not edit by hand.*

------------------------------------------------------------------------
## Terms
* **Actor &mdash;** A client of the *Brain Core SDK*, such as the Assistant, CLI, Console, *Subagent*, or Worker.
* **Adapter &mdash;** A *Resource* which governs interaction with the outside world such as an MCP Server, messaging platform, web API, etc.
* **Brain Core SDK &mdash;** The interface on top of the *Public API* for direct consumption (via HTTP) by *Tier* 3 Actors. This is the only system interface available to Actors.
* **Component &mdash;** A registered unit of responsibility or work. Current runtime Components are Services and Resources.
* **Conversation Episode &mdash;** A Recall-owned grouping of related dialogue turns within a *Session*. Conversation Episodes rotate on explicit boundaries or configured idle gaps and are used for observability *Session* grouping such as Langfuse sessions.
* **Delegation &mdash;** The Reason-*Plane* *Service* that owns the lifecycle of *Subagent* invocations: queue, claim, status, transcripts, budget ledger, and cancel.
* **Effect Plane &mdash;** The *Plane* responsible for external consequences: comprises Services and *Adapter* Resources responsible for external I/O.
* **Envelope &mdash;** The structured message wrapper used for all cross-*Tier* and cross-*Service* communication, consisting of metadata, payload, and errors.
* **Logic Op &mdash;** An *Op* implementing arbitrary/custom Python code.
* **Manifest &mdash;** The self-registration declaration that each *Component* exports to join the global registry at import time.
* **MCP Op &mdash;** An *Op* which wraps a single MCP tool call, scoped by the name of the MCP server as configured.
  *(Note: The MCP spec does not enforce useful schema definitions over tool output format, which can be limiting for automation. Brain provides a mechanism to manually define these via per-server JSON files; see `docs/op-design.md`.)*
* **Native Op &mdash;** An *Op* which wraps a *Service* API call. Native Ops are the foundational units of work for Actors.
* **Op &mdash;** A governed, testable unit of action with a clear input/output contract, bounded authority, and inspectable results. Kinds are `Native`, `MCP`, `Pipeline`, and `Logic`.
* **Operator &mdash;** The human user of the system. All personal-assistant work rolls up to the *Operator* as the accountable *Principal*.
* **Pipeline Op &mdash;** A compound *Op* defined by an ordered set of other *Op* references; assuming the output format schema of each *Op* is compatible with the input format schema of the next, they form an execution chain: you provide inputs to the first *Op* and receive a return value from the final *Op*.
* **Plane &mdash;** An abstract 'vertical' segment of Brain architecture defined by its ontological purpose. There are three Planes: State, Effect, and Reason.
* **Principal &mdash;** The accountable identity for a request, propagated unchanged across calls in *Envelope* metadata. Examples: `operator`, `core`, or a *Service* name.
* **Provider &mdash;** The concrete backing surface behind a *Resource*, such as a containerized system, a host process/file, or some third-party API. Resources are Brain-facing interfaces over Providers.
* **Public API &mdash;** The internal, native, Python surface exported by a given *Service*. The *Public API* is the canonical interface for any *Service*.
* **Reason Plane &mdash;** The logical housing of higher-order executive functions by composing State and Effect functionality.
* **Resource &mdash;** Trustees of side effects. All real-world consequences are gated by a *Resource* *Component*. Types are `Substrate` and `Adapter`.
* **Service &mdash;** The primary carriers of business logic, responsible for coordinating system state and behavior.
* **Session &mdash;** A Recall-owned durable memory continuity scope for dialogue, focus, and rolling summaries. A *Session* may contain multiple Conversation Episodes over time.
* **State Plane &mdash;** The *Plane* responsible for durable data, comprising *Substrate*-owning Services and their *Substrate* Resources.
* **Subagent &mdash;** A focused, headless agentic loop spawned by *Delegation* to accomplish one task. Distinct from the conversational Assistant: runs under its own *Principal* and Channel, with a narrowed tool allowlist and per-invocation budgets.
* **Substrate &mdash;** A *Resource* which governs state, such as a database, document store, or cache.
* **Tier &mdash;** An abstract 'horizontal' segment of Brain architecture defined by its purpose and access control rules. Brain architecture uses three Tiers: 1, 2, and 3.
* **Trace &mdash;** A `trace_id`-scoped execution episode linking causally related Envelopes. Cross-*Trace* causality is preserved via `parent_id` references.
* **Turn &mdash;** One persisted dialogue item in a *Session*, either inbound from the *Operator* or outbound from Brain. Turns carry *Trace* and *Conversation Episode* identifiers for correlation.


------------------------------------------------------------------------
_End of Glossary_
