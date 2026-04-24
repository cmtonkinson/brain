# Op Design
An _Op_ is a discrete, stateless, and declarative unit of functionality
that is registered with and executed by the Execution. Ops represent the
fundamental "verbs" or "tools" that the system can use to perform tasks.

> Check the [Glossary](glossary.md) for key terms such as _Op_,
> _Execution_, and _Op SDK_.

------------------------------------------------------------------------
## Global Structure
All ops are defined within the `ops/` directory. Each
op resides in its own package directory somewhere under that tree. Any
intermediate subdirectories are organizational only. The package directory
itself must be named in `kebab-case` and match the `op_id` defined in
its manifest.

### Discovery Roots and the User Overlay
Execution scans every directory listed in `execution.discovery_roots`
(default: `["ops"]`) and additionally the user-config overlay rooted at
`{BRAIN_CONFIG_DIR}/ops` (default: `~/.config/brain/ops`). Roots are
walked in order; later roots overlay earlier ones, so the user overlay
always wins on op_id collision and the same `(server_id, tool_name)`
collision in `mcp-overrides/`. Within a single root, duplicate op_ids
remain a hard error. Missing roots are skipped silently. This lets
operators override built-in ops or pre-declared MCP overrides without
touching the project tree.

### Required Files
Every op package must contain:
- `op.json`: The manifest file that defines the op's identity,
  contract, and metadata.
- `README.md`: Human-readable documentation explaining the op's purpose,
  inputs, and outputs.

### The `op.json` Manifest
The manifest is the source of truth for a op's contract. Key fields
include:
- `op_id`: A unique identifier that matches the directory name.
  Intermediate grouping directories are not part of the identifier.
- `kind`: Defines the specific type of the op. Must be one of
  `native`, `mcp`, `pipeline`, or `logic`.
- `owner_service_id`: The canonical T2 service `ComponentId` that owns the
  op. This is required for `logic` and `pipeline`
  ops, and optional for `native` because ownership is derivable
  from `call_target`.
- `summary`: A brief, one-sentence description of what the op does.
- `input_schema` / `output_schema`: Defines the contract for the op's
  inputs and outputs.
- `required_ops`: Optional only for `logic`. It must be omitted
  for `native`, `mcp`, and `pipeline`.

#### Canonical Schema
Under the hood, all op schemas are standard JSON Schema objects. This
verbose, canonical format is always available for defining complex data
structures, but it is not the preferred syntax for most use cases.

**Example: Canonical Object Schema**
```json
"output_schema": {
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "The full path of the file in the vault."
    },
    "revision": {
      "type": "string",
      "description": "The revision identifier for the file."
    }
  },
  "required": ["path", "revision"]
}
```

#### Shorthand Schema
To improve developer experience, the system supports a concise shorthand syntax
that is expanded into the canonical format at runtime. This is the preferred way
to define schemas.

The shorthand has three main forms:

**1. Object Schema**
If the schema value is a JSON object, it defines an object where keys are
property names and values are property definition strings.

- **Convention:** Properties are **required by default** unless marked `optional`.
- **Property Syntax:** `"<type> | [modifiers...] | <description>"`
  - **`type`**: A standard type like `string`, `integer`, `boolean`, `date-time`, or `any`.
  - **`optional`**: A modifier indicating the property may be omitted.
  - **`null`**: A modifier indicating the property's value can be `null`.

**Example: Shorthand Object Schema**
This is the shorthand equivalent of the canonical example above.
```json
"output_schema": {
  "path": "string | The full path of the file in the vault.",
  "revision": "string | The revision identifier for the file."
}
```

**2. Primitive Schema**
If the schema value is a single string, it defines a primitive type using the
property syntax directly.

**Example: Shorthand String Schema**
```json
"output_schema": "string | Returns a static greeting."
```

**3. Null Schema**
If the schema value is `null`, it signifies that the op does not accept
input or does not return data.

**Example: Shorthand Null Schema (for no inputs)**
```json
"input_schema": null
```

By convention, properties are **required by default** unless explicitly marked
`optional`.

------------------------------------------------------------------------
## Op Types
There are four types of Ops, each serving a different purpose.

### 1. Native Op
Native Ops expose system primitives as Ops; each is a declarative
wrapper around a single method from the Public API of some T2 Service.
- **`kind`**: `"native"`
- **Purpose**: To provide a safe and simple entrypoint to a core system
  function.
- **Structure**: An Op package contains only the required `op.json` and
  `README.md`. It contains no executable code.
- **Implementation**: The `call_target` field in `op.json` specifies the
  exact service function to invoke (e.g., `service_vault.get_file`).

### 2. MCP Op
MCP Ops wrap a single MCP tool call, routed through the MCP Adapter sidecar.
- **`kind`**: `"mcp"`
- **Purpose**: Expose MCP tools as first-class, policy-gated ops.
- **`call_target`**: `"mcp:{server_id}:{tool_name}"` — identifies the MCP
  server and tool to invoke via the adapter.
- **Discovery**: At boot, Execution calls `adapter.list_tools()` and dynamically
  registers each discovered tool as an `NativeOpManifest`. Static
  `op.json` manifests with `kind: "mcp"` are also supported.
- **Per-tool overrides**: The MCP protocol does not declare an output
  schema, an effect, or an approval requirement. Operators can pre-declare
  any subset of these by placing per-server JSON files at
  `ops/mcp-overrides/<server_id>.json`. Each file maps a tool name to an
  override object with optional `effect`, `approval`, and `output_schema`
  fields. Example:
  ```json
  {
    "list_calendars": {
      "effect": "read",
      "approval": "always",
      "output_schema": {"type": "array"}
    },
    "create_event": {"effect": "write", "approval": "never"}
  }
  ```
  Precedence at sync time is `DB > file > unset`, so the `/op-classify`
  slash command can still override file-declared values, and the per-tool
  classification persists in the database. MCP Ops without an
  `output_schema` (file-declared or otherwise) cannot participate in
  Pipeline Ops.

### 3. Pipeline Op
Pipeline Ops are a declarative way to chain together multiple Ops in
a specific, ordered sequence. (The name is a nod to "piping" command line
utilities together.)
- **`kind`**: `"pipeline"`
- **Purpose**: To create a composite Op from a simple, linear sequence
  of other Ops.
- **Structure**: A Pipeline Op contains no executable code. Its
  `op.json` manifest must include a `pipeline` array.
- **Implementation**: The `pipeline` field in the manifest contains an ordered
  list of steps to be executed in sequence. Each step may be either:
  - a bare op ID string
  - an object with:
    - `op`: The step op ID
    - `input_mapping`: Optional `consumer_field -> producer_field` remapping
      applied only for that step
  The output of each step is projected into the input of the next.

### 4. Logic Op
Logic Ops define executable Python code to perform unique or complex tasks;
they are the only type of Op that isn't pure declaration over some other
business logic.
- **`kind`**: `"logic"`
- **Purpose**: To implement custom logic.
- **Structure**: In addition to the base files, a Logic Op must contain:
    - `execute.py`: The entrypoint module containing the Op's implementation.
    - `test/`: A directory with one or more `test_*.py` files containing unit
      tests for the Op.
- **Manifest**: Logic Ops are the only Op type that may declare
  `required_ops`.
- **Implementation**: The logic is written in Python within the `execute.py`
  file. `execute()` may declare any subset of the supported parameter names
  `input_payload`, `request`, `runtime`, and `invoke_call_target`.


------------------------------------------------------------------------
_End of Op Design_
