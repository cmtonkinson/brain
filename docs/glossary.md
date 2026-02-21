# Glossary of Terms

This document is generated from `docs/glossary.yaml`. Do not edit by hand.

- **Actor &mdash;** A client of the Brain Core SDK, such as the Agent, CLI, or Celery Worker.
- **Adapter &mdash;** A _Resource_ which governs interaction with the outside world such as an MCP Server, messaging platform, web API, etc.
- **Component &mdash;** An isolated unit of responsibility or work. Each _Actor_, _Service_, and _Resource_ is a _Component_.
- **Resource &mdash;** Trustees of side effects. All real-world consequences are gated by a _Resource_ _Component_. Types are _Substrate_ and _Adapter_.
- **Service &mdash;** The primary carriers of business logic, responsible for coordinating system state and behavior.
- **Substrate &mdash;** A _Resource_ which governs state, such as a database, document store, or cache.
