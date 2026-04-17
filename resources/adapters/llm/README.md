# native LLM Adapter
Action _Adapter_ _Resource_ that executes chat and embedding calls against a native LLM gateway for the Language Model Service.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/llm/` provides the concrete Layer 0 native LLM
integration:
- `component.py`: `ResourceManifest` registration (`adapter_llm`)
- `adapter.py`: adapter protocol, DTOs, and adapter exception taxonomy
- `llm_adapter.py`: HTTP implementation (`HttpLlmAdapter`)
- `config.py`: Pydantic settings model and resolver for adapter config

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_language_model` via `owner_service_id` in
`resources/adapters/llm/component.py`.

Boundary rules:
- Adapter owns network calls and response mapping to typed adapter DTOs.
- Adapter does not own domain-level request validation or profile policy.
- Adapter does not persist data.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- Language Model Service composes `HttpLlmAdapter` in
  `DefaultLanguageModelService.from_settings(...)`.
- LMS calls adapter methods:
  - `chat` / `chat_batch`
  - `embed` / `embed_batch`
  - `health`
- Adapter returns typed results or raises adapter-level exceptions that LMS
  maps to service error semantics.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. LMS resolves provider/model profile and passes it to adapter methods.
2. Adapter constructs native LLM request payloads and sends HTTP requests.
3. Adapter validates response JSON shape and maps to typed DTOs.
4. Adapter raises dependency/internal exceptions for failure paths.
5. LMS maps adapter output/failures to envelope-level service responses.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- HTTP/network timeout and transport failures map to `AdapterDependencyError`.
- 5xx responses map to `AdapterDependencyError` (with bounded retry).
- malformed JSON or invalid response shape maps to `AdapterInternalError`.
- `health()` reports readiness payload and does not raise on dependency failure.

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from `components.adapter.llm`:
- `base_url`
- `api_key`
- `timeout_seconds`
- `max_retries`

See `docs/configuration.md` for canonical key definitions and overrides.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `resources/adapters/llm/tests/test_llm_config.py`
- `resources/adapters/llm/tests/test_llm_adapter.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep this resource transport-focused and side-effect-boundary oriented.
- Keep adapter DTOs strict (`extra="forbid"`, immutable).
- Keep adapter exceptions small and explicit to preserve stable LMS error
  mapping.
- If endpoint shapes change, update adapter mappings and component docs
  together.


------------------------------------------------------------------------
_End of native LLM Adapter README_
