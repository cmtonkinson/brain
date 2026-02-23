# Component README Guide
This document defines the canonical structure for per-Component README files in
Brain.

------------------------------------------------------------------------
## Scope
This guide applies to:
- `services/<system>/<service>/README.md`
- `resources/<kind>/<resource>/README.md`
- `actors/<actor>/README.md`

Use this document as the source of truth for component README structure and
content expectations.

------------------------------------------------------------------------
## Goals
Each component README should help a reviewer or contributor quickly answer:
- What is this _Component_?
- What does it own?
- How does it interact with the rest of Brain?
- Where are the key code paths, tests, and configuration surfaces?

------------------------------------------------------------------------
## Required Structure
Every component README should include these sections in this order:
1. **What This Component Is**
2. **Boundary and Ownership**
3. **Interactions**
4. **Operational Flow (High Level)**
5. **Failure Modes and Error Semantics**
6. **Configuration Surface**
7. **Testing and Validation**
8. **Contributor Notes**

------------------------------------------------------------------------
## Content Rules
- Keep it breadth-first and concise.
- Prefer links to canonical global docs over restating global doctrine.
- Describe current behavior only.
- Do not include migration narratives or compatibility notes.
- Use concrete paths and module names so contributors can jump directly to code.

------------------------------------------------------------------------
## Type-Specific Emphasis
### Service READMEs
Emphasize:
- Public API surface (`service.py`, `api.py`)
- owned _Resource_ components
- cross-service dependencies

### Resource READMEs
Emphasize:
- owning _Service_ component(s)
- side-effect boundaries
- substrate/adapter contract and health/error behavior

### Actor READMEs
Emphasize:
- entrypoints and runtime triggers
- Brain SDK usage and external integration boundaries
- policy and control flow handoff to L1 services

------------------------------------------------------------------------
## Minimal Authoring Template
Use this exact skeleton and fill it with component-specific details:

```md
# <Component Name>
<One-sentence description of the component's role in Brain.>

------------------------------------------------------------------------
## What This Component Is
...

------------------------------------------------------------------------
## Boundary and Ownership
...

------------------------------------------------------------------------
## Interactions
...

------------------------------------------------------------------------
## Operational Flow (High Level)
...

------------------------------------------------------------------------
## Failure Modes and Error Semantics
...

------------------------------------------------------------------------
## Configuration Surface
...

------------------------------------------------------------------------
## Testing and Validation
...

------------------------------------------------------------------------
## Contributor Notes
...

------------------------------------------------------------------------
_End of <Component Name> README_
```

------------------------------------------------------------------------
_End of Component README Guide_
