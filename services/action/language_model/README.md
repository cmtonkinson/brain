# Language Model Service
Action _Service_ that provides stateless chat and embedding APIs and gates all model access through the LiteLLM adapter resource.

------------------------------------------------------------------------
## What This Component Is
`services/action/language_model/` is the Layer 1 _Service_ for model inference
and embedding generation.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_language_model`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: concrete service behavior (`DefaultLanguageModelService`)
- `api.py`: gRPC adapter for Layer 2 callers
- `domain.py`: Pydantic payload contracts
- `validation.py`: strict Pydantic ingress request validation
- `config.py`: service-local profile settings and resolver

------------------------------------------------------------------------
## Boundary and Ownership
Language Model Service is an Action-System _Service_ (`layer=1`,
`system="action"`). It declares ownership of the LiteLLM adapter resource
(`adapter_litellm`) in `services/action/language_model/component.py`.

Boundary rules:
- LMS owns request validation and profile selection semantics.
- LMS does not persist chat state or embeddings.
- External provider/network details are delegated to the adapter resource.

------------------------------------------------------------------------
## Interactions
Primary system interactions:
- In-process callers use `LanguageModelService` (`service.py`).
- Layer 2 callers use gRPC via `GrpcLanguageModelService` (`api.py`).
- `DefaultLanguageModelService.from_settings(...)` resolves:
  - `components.service.language_model`
  - `components.adapter.litellm`
- LMS invokes owned adapter methods for:
  - `chat` / `chat_batch`
  - `embed` / `embed_batch`
  - `health`

------------------------------------------------------------------------
## Operational Flow (High Level)
1. LMS receives envelope metadata plus typed request parameters.
2. LMS validates metadata and request shape using Pydantic request models.
3. LMS resolves one model profile (`embedding`, `quick`, `standard`, `deep`)
   with fallback from `quick`/`deep` to `standard`.
4. LMS dispatches to the LiteLLM adapter resource.
5. LMS returns typed envelope payloads (`ChatResponse`, `EmbeddingVector`,
   `HealthStatus`) or structured errors.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Validation failures return validation-category errors in envelope responses.
- Adapter dependency failures return dependency-category errors.
- Adapter internal failures return internal-category errors.
- In gRPC transport (`api.py`), dependency/internal categories are mapped to
  transport aborts (`UNAVAILABLE` / `INTERNAL`), while domain errors remain in
  response envelopes.

------------------------------------------------------------------------
## Configuration Surface
Service settings are sourced from `components.service.language_model`:
- `embedding.provider`
- `embedding.model`
- `quick.provider`
- `quick.model`
- `standard.provider`
- `standard.model`
- `deep.provider`
- `deep.model`

Adapter settings are sourced from `components.adapter.litellm`.

See `docs/configuration.md` for canonical key definitions and override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/action/language_model/tests/test_language_model_service.py`
- `services/action/language_model/tests/test_language_model_api.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep profile resolution logic in LMS; keep provider transport logic in the
  adapter resource.
- Keep boundary request/response contracts in Pydantic models.
- Keep transport mapping concerns in `api.py` and service logic in
  `implementation.py`.
- Do not introduce persistence/session state into LMS without an explicit
  design update.

------------------------------------------------------------------------
_End of Language Model Service README_
