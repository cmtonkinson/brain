# native LLM Adapter
Action *Adapter* *Resource* that executes chat and embedding calls against a native LLM gateway for the Language Service.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/llm/` provides the concrete Tier 1 native LLM
integration:
* `component.py`: `ResourceManifest` registration (`adapter_llm`)
* `adapter.py`: adapter protocol, DTOs, and adapter exception taxonomy
* `llm_adapter.py`: HTTP implementation (`HttpLlmAdapter`)
* `config.py`: Pydantic settings model and resolver for adapter config

------------------------------------------------------------------------
## Boundary and Ownership
This *Resource* is owned by `service_language` via `owner_service_id` in
`resources/adapters/llm/component.py`.

Boundary rules:
* Adapter owns network calls and response mapping to typed adapter DTOs.
* Adapter does not own domain-level request validation or profile policy.
* Adapter does not persist data.

------------------------------------------------------------------------
## Interactions
Primary interactions:
* Language Service composes `HttpLlmAdapter` in
  `DefaultLanguageService.from_settings(...)`.
* Language calls adapter methods:
  * `chat` / `chat_batch`
  * `chat_with_tools`
  * `embed` / `embed_batch`
  * `health`
* Adapter returns typed results or raises adapter-level exceptions that Language
  maps to service error semantics.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Language resolves provider/model profile and passes it to adapter methods.
2. Adapter constructs native LLM request payloads and sends HTTP requests.
3. Adapter validates response JSON shape and maps to typed DTOs.
4. Adapter raises dependency/internal exceptions for failure paths.
5. Language maps adapter output/failures to envelope-level service responses.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
* HTTP/network timeout and transport failures map to `AdapterDependencyError`.
* 5xx responses map to `AdapterDependencyError` (with bounded retry).
* malformed JSON or invalid response shape maps to `AdapterInternalError`.
* `health()` reports readiness payload and does not raise on dependency failure.

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from `components.adapter.llm`:
* `api_base`
* `api_key`
* `timeout_seconds`
* `max_retries`

See `docs/configuration.md` for canonical key definitions and overrides.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
* `resources/adapters/llm/tests/test_llm_config.py`
* `resources/adapters/llm/tests/test_llm_adapter.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
* Keep this resource transport-focused and side-effect-boundary oriented.
* Keep adapter DTOs strict (`extra="forbid"`, immutable).
* Keep adapter exceptions small and explicit to preserve stable Language error
  mapping.
* If endpoint shapes change, update adapter mappings and component docs
  together.


------------------------------------------------------------------------
_End of native LLM Adapter README_
