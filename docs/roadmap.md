# Roadmap
Phased implementation plan and current development status.

------------------------------------------------------------------------
## Phase 1: (✅ done) ~~Text interaction + memory + MCP tools~~
- ~~Obsidian Local REST API integration (read/write)~~
- ~~Letta archival memory~~
- ~~Code-Mode (UTCP) for MCP tool calls~~
- ~~Signal messaging with allowlisted senders~~
- ~~Vault indexer + Qdrant semantic search~~
- ~~Optional observability stack (OTel)~~

------------------------------------------------------------------------
## Phase 2: (✅ done) ~~The "Assistant Triangle"~~
- ~~Skill framework + capability registry~~
- ~~Attention router + interruption policy~~
- ~~Commitment tracking + loop closure~~
- ~~Requires scheduled/background jobs, policy engine, ingestion pipeline~~

------------------------------------------------------------------------
## Phase 3: (⚠️ in progress) Refactor
- ~~Define clean subsystem boundaries & responsibilities~~
- Refactor codebase along clean boundaries with crisp public APIs
- Extensive testing for enforcement of new semantics
- Review all documentation to ensure truth & alignment with actual system

------------------------------------------------------------------------
## Phase 4: Voice + telephony + SMS (unstarted)
- Local voice (whisper.cpp + Piper, openWakeWord)
- POTS phone support (Twilio Media Streams)
- SMS fallback (Google Voice)

------------------------------------------------------------------------
_End of Roadmap_
