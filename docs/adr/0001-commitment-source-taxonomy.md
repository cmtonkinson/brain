# ADR 0001: Commitment Source Taxonomy

- Status: Accepted
- Date: 2026-02-10

## Context

Commitment provenance fields were overloaded across multiple meanings (who raised it, what it is, where it came from, and how Brain received it). This made ingestion-heavy scenarios ambiguous and conflicted with existing channel terminology used by the Attention Router.

## Decision

Adopt the following canonical inbound provenance taxonomy for commitments:

- `source_actor`: human or system that brought the item to attention
- `source_medium`: form of the source item (for example: `message`, `email`, `transcript`, `web_page`, `file`)
- `source_uri`: canonical locator/identifier for the source item
- `intake_channel`: how Brain received the item (currently `signal` or `ingest`)

`intake_channel` is strictly inbound transport and must not be used for outbound routing semantics.

Avoid derived intake-channel variants (for example `email_ingest`); encode that detail in `source_medium`.

## Consequences

- Reduces ambiguity between provenance and routing concepts.
- Keeps ingestion-specific detail in the correct field (`source_medium`) without exploding channel enums.
- Improves auditability and downstream analytics by preserving separate dimensions.

## Related

- `commitment-source-taxonomy.md`
