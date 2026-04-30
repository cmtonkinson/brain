# Configuration Reference
This document describes Brain's runtime configuration model: where config lives,
how files merge, and how YAML paths, environment variables, and CLI flags map
to the same canonical setting paths.

------------------------------------------------------------------------
## Runtime Directory
Brain runtime configuration lives under `~/.config/brain/`.

Runtime config is discovered by scanning that directory for top-level
`*.yaml` files:
* scan is non-recursive
* files are merged in lexical filename order
* later files win
* `dashboard.yaml` and `mcp-adapter.yaml` are not part of the Brain runtime
  config scan

This means users may combine or split files however they prefer. The sample
files in `config/` are recommended groupings, not required filenames.

------------------------------------------------------------------------
## Sample Files
Checked-in sample files are:
* `config/shared.yaml.sample`
* `config/state.yaml.sample`
* `config/effect.yaml.sample`
* `config/reason.yaml.sample`
* `config/actors.yaml.sample`
* `config/secrets.yaml.sample`

`secrets*.yaml` is the conventional private layer for values that should not be
committed to git. Those files are merged like any other runtime YAML file; the
privacy convention is by filename and operator practice, not by a special merge
rule.

------------------------------------------------------------------------
## Precedence
Settings resolve in this order (highest wins):
1. CLI parameters
2. Environment variables
3. Top-level runtime YAML files in lexical merge order
4. Model defaults

------------------------------------------------------------------------
## Canonical Naming
Brain uses one path model everywhere:
* YAML path: `component.segment.subsegment`
* env var: `BRAIN_COMPONENT__SEGMENT__SUBSEGMENT`
* CLI flag: `--component-segment-subsegment`

Examples:
* YAML: `core.http.port`
* env: `BRAIN_CORE__HTTP__PORT=8898`
* flag: `--core-http-port 8898`

* YAML: `seaweedfs.access_key_id`
* env: `BRAIN_SEAWEEDFS__ACCESS_KEY_ID=replace-me`
* flag: `--seaweedfs-access-key-id replace-me`

* YAML: `assistant.personality`
* env: `BRAIN_ASSISTANT__PERSONALITY=default`
* flag: `--assistant-personality default`

------------------------------------------------------------------------
## Root Namespaces
Top-level YAML roots are direct component names plus a small set of shared
global namespaces.

Shared roots:
* `logging`
* `observability`
* `profile`
* `core`

Service roots:
* `cache`
* `commitment`
* `delegation`
* `embedding`
* `execution`
* `ingestion`
* `job`
* `language`
* `object`
* `policy`
* `recall`
* `relay`
* `utility`
* `vault`

Resource roots:
* `llm`
* `mcp`
* `obsidian`
* `postgres`
* `qdrant`
* `seaweedfs`
* `signal`
* `utcp_code_mode`
* `valkey`

Actor roots:
* `assistant`
* `cli`
* `console`
* `subagent`
* `worker`

------------------------------------------------------------------------
## Shared Roots
### `logging`
Shared process logging settings consumed by Core and actors.

Important keys:
* `logging.level`
* `logging.file_capture_enabled`
* `logging.file_capture_level`
* `logging.file_capture_directory`
* `logging.json_output`
* `logging.process_name`
* `logging.environment`

### `observability`
Shared process observability settings consumed by Core and actors.

Important keys:
* `observability.enabled`
* `observability.otlp.endpoint`
* `observability.traces.enabled`
* `observability.metrics.enabled`
* `observability.llm.enabled`

### `profile`
Shared operator and presentation settings.

Important keys:
* `profile.operator.signal_contact_e164`
* `profile.default_dial_code`
* `profile.operator_name`
* `profile.brain_name`
* `profile.brain_verbosity`
* `profile.preferred_timezone`

### `core`
Shared Core connection and Core runtime settings.

Important keys:
* actor/client connection:
  * `core.host`
  * `core.port`
  * `core.timeout_seconds`
* Core runtime:
  * `core.boot.run_migrations_on_startup`
  * `core.http.host`
  * `core.http.port`
  * `core.health.max_timeout_seconds`

------------------------------------------------------------------------
## Service and Resource Roots
Examples of canonical paths:
* `commitment.dedupe_scan_limit`
* `relay.inbound.callback_register_max_retries`
* `relay.outbound.default_channel`
* `language.standard.model`
* `embedding.max_list_limit`
* `obsidian.search_context_length`
* `postgres.url`
* `qdrant.request_timeout_seconds`
* `seaweedfs.bucket`
* `signal.base_url`
* `llm.providers.anthropic.api_key`

------------------------------------------------------------------------
## Actors
Actor-specific settings live under their direct actor roots:
* `assistant.*`
* `cli.*`
* `console.*`
* `worker.*`
* `subagent.*`

Examples:
* `assistant.personality`
* `assistant.environment_context`
* `cli.principal`
* `console.editor`
* `worker.max_workers`
* `subagent.default_max_turns`

------------------------------------------------------------------------
## Environment Variable Examples
```sh
BRAIN_LOGGING__LEVEL=DEBUG
BRAIN_PROFILE__OPERATOR__SIGNAL_CONTACT_E164=+12025550100
BRAIN_CORE__HTTP__HOST=0.0.0.0
BRAIN_CORE__HTTP__PORT=8898
BRAIN_POSTGRES__URL=postgresql+psycopg://user:pass@host:5432/db
BRAIN_QDRANT__URL=http://qdrant:6333
BRAIN_VALKEY__URL=valkey://valkey:6379/0
BRAIN_SEAWEEDFS__ENDPOINT_URL=http://seaweedfs:8333
BRAIN_SEAWEEDFS__BUCKET=brain-oas
BRAIN_LLM__TIMEOUT_SECONDS=60
BRAIN_SIGNAL__BASE_URL=http://signal-api:8080
BRAIN_CLI__PRINCIPAL=operator
BRAIN_ASSISTANT__TOOL_LOOP_TIER2_HOP_THRESHOLD=3
BRAIN_SUBAGENT__DEFAULT_MAX_TURNS=8
```

------------------------------------------------------------------------
## Secrets Guidance
Values that should not be committed should be placed in a top-level
`secrets*.yaml` file and demonstrated in `config/secrets.yaml.sample`.

Typical secret-bearing paths include:
* `obsidian.api_key`
* `seaweedfs.access_key_id`
* `seaweedfs.secret_access_key`
* `signal.receive_e164`
* `llm.providers.anthropic.api_key`
* `llm.providers.voyage.api_key`

------------------------------------------------------------------------
## Notes
* Runtime config scanning does not recurse into subdirectories.
* Support configs such as observability stack files should live in subdirectories
  or use non-runtime filenames so they are not picked up by the runtime scan.
* `dashboard.yaml` remains a separate out-of-band dashboard config file.
* Op discovery additionally honors a user-config overlay at
  `{BRAIN_CONFIG_DIR}/ops` on top of every directory listed in
  `execution.discovery_roots`. Later roots win on op_id collision; see
  [Op Design](op-design.md#discovery-roots-and-the-user-overlay).


------------------------------------------------------------------------
_End of Configuration Reference_
