# Language Model Service
Action _Service_ that provides stateless chat and embedding APIs and gates all model access through the native LLM adapter resource.

------------------------------------------------------------------------
## What This Component Is
`services/action/language_model/` is the Layer 1 _Service_ for model inference
and embedding generation.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_language_model`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: concrete service behavior (`DefaultLanguageModelService`)
- `api.py`: FastAPI route adapter for Layer 2 callers
- `domain.py`: Pydantic payload contracts
- `validation.py`: strict Pydantic ingress request validation
- `config.py`: service-local profile settings and resolver

------------------------------------------------------------------------
## Boundary and Ownership
Language Model Service is an Action-System _Service_ (`layer=1`,
`system="action"`). It declares ownership of the native LLM adapter resource
(`adapter_llm`) in `services/action/language_model/component.py`.

Boundary rules:
- LMS owns request validation and profile selection semantics.
- LMS does not persist chat state or embeddings.
- External provider/network details are delegated to the adapter resource.
- The canonical tool-capable request contract is one provider-agnostic
  `InferenceRequest`, not a provider-shaped transcript.

------------------------------------------------------------------------
## Interactions
Primary system interactions:
- In-process callers use `LanguageModelService` (`service.py`).
- Layer 2 callers use HTTP via FastAPI routes (`api.py`).
- `DefaultLanguageModelService.from_settings(...)` resolves:
  - `components.service.language_model`
  - `components.adapter.llm`
- LMS invokes owned adapter methods for:
  - `chat` / `chat_batch`
  - `embed` / `embed_batch`
  - `health`

------------------------------------------------------------------------
## Operational Flow (High Level)
1. LMS receives envelope metadata plus typed request parameters.
2. For tool-capable generation, LMS receives one provider-agnostic
   `InferenceRequest` assembled by the Agent.
3. LMS validates metadata and request shape using Pydantic request models.
4. LMS resolves one model profile (`embedding`, `quick`, `standard`, `deep`)
   with fallback from `quick`/`deep` to `standard`.
5. LMS dispatches to the native LLM adapter resource.
6. The adapter lowers the canonical request into provider-specific request JSON.
7. LMS returns typed envelope payloads (`ChatResponse`, `EmbeddingVector`,
   `HealthStatus`) or structured errors.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Validation failures return validation-category errors in envelope responses.
- Adapter dependency failures return dependency-category errors.
- Adapter internal failures return internal-category errors.
- In HTTP transport (`api.py`), dependency/internal categories are mapped to
  appropriate HTTP error status codes, while domain errors remain in response
  envelopes.

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

Adapter settings are sourced from `components.adapter.llm`.

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
- Keep provider-specific wire-shape decisions isolated to the adapter; do not
  reintroduce provider-specific transcript semantics into LMS.
- Keep transport mapping concerns in `api.py` and service logic in
  `implementation.py`.
- Do not introduce persistence/session state into LMS without an explicit
  design update.


------------------------------------------------------------------------
_End of Language Model Service README_
