# Language Service
Action _Service_ that provides stateless chat and embedding APIs and gates all model access through the native LLM adapter resource.

------------------------------------------------------------------------
## What This Component Is
`services/effect/language/` is the Tier 2 _Service_ for model inference
and embedding generation.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_language`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: concrete service behavior (`DefaultLanguageService`)
- `api.py`: FastAPI route adapter for Tier 3 callers
- `domain.py`: Pydantic payload contracts
- `validation.py`: strict Pydantic ingress request validation
- `config.py`: service-local profile settings and resolver

------------------------------------------------------------------------
## Boundary and Ownership
Language Service is an Action-System _Service_ (`tier=2`,
`plane="effect"`). It declares ownership of the native LLM adapter resource
(`adapter_llm`) in `services/effect/language/component.py`.

Boundary rules:
- Language owns request validation and profile selection semantics.
- Language does not persist chat state or embeddings.
- External provider/network details are delegated to the adapter resource.
- The canonical tool-capable request contract is one provider-agnostic
  `InferenceRequest`, not a provider-shaped transcript.

------------------------------------------------------------------------
## Interactions
Primary system interactions:
- In-process callers use `LanguageService` (`service.py`).
- Tier 3 callers use HTTP via FastAPI routes (`api.py`).
- `build_language_service(settings=...)` resolves:
  - `language`
  - `core.resources.llm`
- Language invokes owned adapter methods for:
  - `chat` / `chat_batch`
  - `embed` / `embed_batch`
  - `health`

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Language receives envelope metadata plus typed request parameters.
2. For tool-capable generation, Language receives one provider-agnostic
   `InferenceRequest` assembled by the Agent.
3. Language validates metadata and request shape using Pydantic request models.
4. Language resolves one model profile (`embedding`, `quick`, `standard`, `deep`)
   with fallback from `quick`/`deep` to `standard`.
5. Language dispatches to the native LLM adapter resource.
6. The adapter lowers the canonical request into provider-specific request JSON.
7. Language returns typed envelope payloads (`ChatResponse`, `EmbeddingVector`,
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
Service settings are sourced from `language`:
- `document_embedding.provider`
- `document_embedding.model`
- `document_embedding.dimensions`
- `op_embedding.provider`
- `op_embedding.model`
- `op_embedding.dimensions`
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
- `services/effect/language/tests/test_language_service.py`
- `services/effect/language/tests/test_language_audit_repository_integration.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep profile resolution logic in Language; keep provider transport logic in the
  adapter resource.
- Keep boundary request/response contracts in Pydantic models.
- Keep provider-specific wire-shape decisions isolated to the adapter; do not
  reintroduce provider-specific transcript semantics into Language.
- Keep transport mapping concerns in `api.py` and service logic in
  `implementation.py`.
- Do not introduce persistence/session state into Language without an explicit
  design update.


------------------------------------------------------------------------
_End of Language Service README_
