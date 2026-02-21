# Glossary of Terms

_This document is generated from `docs/glossary.yaml`. Do not edit by hand._

- **Actor &mdash;** A client of the _Brain Core Sdk_, such as the Agent, CLI, or Celery Worker.
- **Adapter &mdash;** A _Resource_ which governs interaction with the outside world such as an MCP Server, messaging platform, web API, etc.
- **Brain Core SDK &mdash;** The gRPC interface generated on top of the _Public Api_ for direct consumption by _Layer_ 2. This is the only _System_ interface available to Actors.
- **Component &mdash;** An isolated unit of responsibility or work. Each _Actor_, _Service_, and _Resource_ is a _Component_.
- **Layer &mdash;** An abstract 'horizontal' segment of Brain architecture defined by its purpose and access control rules. There are three Layers: 0, 1, and 2.
- **Public API &mdash;** The internal, native, Python surface exported by a given _Service_. The _Public Api_ is the canonical interface for any _Service_.
- **Resource &mdash;** Trustees of side effects. All real-world consequences are gated by a _Resource_ _Component_. Types are _Substrate_ and _Adapter_.
- **Service &mdash;** The primary carriers of business logic, responsible for coordinating _System_ state and behavior.
- **Substrate &mdash;** A _Resource_ which governs state, such as a database, document store, or cache.
- **System &mdash;** An abstract 'vertical' segment of Brain architecture defined by its ontological purpose. There are three Systems: State, Action and Control.
