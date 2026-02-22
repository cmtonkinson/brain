# Glossary
_This document is generated from `docs/glossary.yaml`. Do not edit by hand._

------------------------------------------------------------------------
## Terms
- **Action System &mdash;** The _System_ responsible for external consequences: comprises Services and _Adapter_ Resources responsible for external I/O.
- **Actor &mdash;** A client of the _Brain Core Sdk_, such as the Agent, CLI, or Celery Worker.
- **Adapter &mdash;** A _Resource_ which governs interaction with the outside world such as an MCP Server, messaging platform, web API, etc.
- **Brain Core SDK &mdash;** The gRPC interface generated on top of the _Public Api_ for direct consumption by _Layer_ 2. This is the only _System_ interface available to Actors.
- **Capability &mdash;** A governed, testable unit of action with a clear input/output contract, bounded authority, and inspectable results. Types are `Op` and `Skill`.
- **Capability SDK &mdash;** The SDK for definition, registration, and management of Capabilities (Ops and Skills) including logic and metadata such as Policy declarations.
- **Component &mdash;** An isolated unit of responsibility or work. Each _Actor_, _Service_, and _Resource_ is a _Component_.
- **Control System &mdash;** The _System_ housing higher-order executive functions by composing functionality from the _State System_ and _Action System_.
- **Envelope &mdash;** The structured message wrapper used for all cross-_Layer_ and cross-_Service_ communication, consisting of metadata, payload, and errors.
- **Layer &mdash;** An abstract 'horizontal' segment of Brain architecture defined by its purpose and access control rules. There are three Layers: 0, 1, and 2.
- **Manifest &mdash;** The self-registration declaration that each _Component_ exports to join the global registry at import time.
- **Op &mdash;** A _Capability_ which wraps a _Resource_ API call. Ops are the foundational units of work exposed to Actors.
- **Operator &mdash;** The human user of the _System_. All personal-assistant work rolls up to the _Operator_ as the accountable _Principal_.
- **Principal &mdash;** The accountable identity for a request, propagated unchanged across calls in _Envelope_ metadata. Examples: `operator`, `core`, or a _Service_ name.
- **Public API &mdash;** The internal, native, Python surface exported by a given _Service_. The _Public Api_ is the canonical interface for any _Service_.
- **Resource &mdash;** Trustees of side effects. All real-world consequences are gated by a _Resource_ _Component_. Types are `Substrate` and `Adapter`.
- **Service &mdash;** The primary carriers of business logic, responsible for coordinating _System_ state and behavior.
- **Skill &mdash;** A compound _Capability_ implementing either a sequence of Ops or custom Python code.
- **State System &mdash;** The _System_ responsible for durable data, comprised of Authority Services and _Substrate_ Resources.
- **Substrate &mdash;** A _Resource_ which governs state, such as a database, document store, or cache.
- **System &mdash;** An abstract 'vertical' segment of Brain architecture defined by its ontological purpose. There are three Systems: State, Action and Control.
- **Trace &mdash;** A `trace_id`-scoped execution episode linking causally related Envelopes. Cross-_Trace_ causality is preserved via `parent_id` references.

------------------------------------------------------------------------
_End of Glossary_
