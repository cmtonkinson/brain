# Brain Skills Glossary
This document defines the canonical vocabulary used by Brain to describe
capabilities, execution units, and composition rules. These terms are normative.

---
## Core Terms
### Skill
A Skill is a named, governed unit of capability that may orchestrate one or more
operations or other Skills. Skills are **never implicit**. Skills are subject to:
- policy and autonomy enforcement
- observability and audit
- capability declaration
- explicit call-graph constraints

Skills may be **Logic Skills** or **Pipeline Skills**, as defined below.

### Logic Skill
A **Logic Skill** executes custom logic (e.g. Python code). Logic Skills:
- may perform branching, conditionals, retries, or analysis
- must explicitly declare *all* skills and ops it may invoke
- runtime enforces declared call graph (undeclared calls error)

### Pipeline Skill
A **Pipeline Skill** is a declarative composition of other skills and/or ops; in other words it's a call-graph declaration. Pipeline Skills: 
- define an ordered sequence of steps
- perform no custom logic of their own
- are validated statically for type safety and capability closure

### Op (Operation)
An **Op** is an atomic, executable unit with a stable input/output contract. Ops are the fundamental "instruction set" of the system, granting the agent real capabilities. Ops:
- cannot invoke other skills or ops
- are treated as opaque at runtime
- are always wrapped by policy, tracing, and observability
- may be invoked by any Skill (provided it is declared appropriately)

There are two types of Ops: **MCP** and **native**, explained below. Both MCP and native Ops are treated identically at the Skill layer.

### Native Op
A Native Op is implemented directly by Brain’s runtime or internal services; in other words, it's agent Python code. Examples:
- Obsidian file read
- Qdrant vector search
- Signal message send

### MCP Op
An MCP Op is a configuration wrapper around underlying functions exposed via `@UTCP/code_mode`. Examples of MCP functions that may be wrapped:
- `filesystem.list_directory`
- `github.get_commit`
- `evenkit.list_calendar_events`

### Call Target
A **Call Target** is any Skill or Op, that is to say, an executable unit a Skill may invoke.

Logic Skills MUST explicitly declare all Call Targets which may be invoked
during its execution so that the policy engine can work correctly. If a Skill
attempts invocation of an undeclared Call Target, the policy engine will reject it and the Skill will immediately fail & return. Note that only Call Targets invoked directly by the Skill must be listed (if Skill A invokes Skill B and Op C, and Skill B invokes Op D, Skill A need only declare Skill B and Op C).

Pipeline Skills, given their nature, already self-declare their Call Targets; no supplemental declarations are needed.

---
## Design Invariants
- All execution flows through Skills and/or Ops
- No implicit calls are allowed
- Composition is explicit and validated
- Governance applies uniformly across native and MCP functionality

_End of Glossary_
