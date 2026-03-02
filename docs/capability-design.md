# Capability Design
A _Capability_ is a discrete, stateless, and declarative unit of functionality
that is registered with and executed by the Capability Engine. Capabilities
represent the fundamental "verbs" or "tools" that the system can use to perform
tasks.

> Check the [Glossary](glossary.md) for key terms such as _Capability_,
> _Capability Engine_, _Op_, and _Skill_.

------------------------------------------------------------------------
## Global Structure
All capabilities are defined within the `capabilities/` directory. Each
capability resides in its own subdirectory, which must be named in `kebab-case`
and match the `capability_id` defined in its manifest.

### Required Files
Every capability package must contain:
- `capability.json`: The manifest file that defines the capability's identity,
  contract, and metadata.
- `README.md`: Human-readable documentation explaining the capability's purpose,
  inputs, and outputs.

### The `capability.json` Manifest
The manifest is the source of truth for a capability's contract. Key fields
include:
- `capability_id`: A unique identifier that matches the directory name.
- `kind`: Defines the specific type of the capability. Must be one of
  `native_op`, `mcp_op`, `pipeline_skill`, or `logic_skill`.
- `summary`: A brief, one-sentence description of what the capability does.
- `input_schema` / `output_schema`: Defines the contract for the capability's
  inputs and outputs.

#### Canonical Schema
Under the hood, all capability schemas are standard JSON Schema objects. This
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
If the schema value is `null`, it signifies that the capability does not accept
input or does not return data.

**Example: Shorthand Null Schema (for no inputs)**
```json
"input_schema": null
```

By convention, properties are **required by default** unless explicitly marked
`optional`.

------------------------------------------------------------------------
## Capability Types
There are four types of Capabilities, each serving a different purpose.

### 1. Native Op
Native Ops expose system primatives as Capabilities; each is a declarative
wrapper around a single method from the Public API of some L1 Service.
- **`kind`**: `"native_op"`
- **Purpose**: To provide a safe and simple entrypoint to a core system
  function.
- **Structure**: An Op package contains only the required `capability.json` and
  `README.md`. It contains no executable code.
- **Implementation**: The `call_target` field in `capability.json` specifies the
  exact service function to invoke (e.g., `service_vault_authority.get_file`).

### 2. MCP Op
_Note: This capability type is future/planned for integration with Code-Mode._
MCP Ops are similar to Native Ops, but instead of wrapping a first-party
primative, they wrap a single MCP UTCP/Code-Mode call.
- **`kind`**: `"mcp_op"`
- **Purpose**: To expose an agent-facing tool provided by the Master Control
  Program (MCP) as a native capability.
- **Structure & Implementation**: To be determined.

### 3. Pipeline Skill
Pipeline Skills are a declarative way to chain together multiple capabilities in
a specific, ordered sequence. (The name is a nod to "piping" command line
utilities together.)
- **`kind`**: `"pipeline_skill"`
- **Purpose**: To create a composite capability from a simple, linear sequence
  of other capabilities.
- **Structure**: A Pipeline Skill contains no executable code. Its
  `capability.json` manifest must include a `pipeline` array.
- **Implementation**: The `pipeline` field in the manifest contains an ordered
  list of `capability_id`s to be executed in sequence. The output of each step
  is passed as the input to the next.

### 4. Logic Skill
Logic Skills define executable Python code to perform unique or complex tasks;
they are the only type of Capability that isn't pure declaration over some other
business logic.
- **`kind`**: `"logic_skill"`
- **Purpose**: To implement custom logic.
- **Structure**: In addition to the base files, a Logic Skill must contain:
    - `execute.py`: The entrypoint module containing the skill's implementation.
    - `test/`: A directory with one or more `test_*.py` files containing unit
      tests for the skill.
- **Implementation**: The logic is written in Python within the `execute.py`
  file.


------------------------------------------------------------------------
_End of Capability Design_
