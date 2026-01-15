# Brain OS — Security, Trust, and Boundary Model
## Threats, Actors, and Containment

---

## Purpose

This document defines the **trust boundaries** and **threat model** of Brain OS.

The goal is not perfect security, but:
- clear containment
- explicit trust decisions
- survivability under compromise

---

## Trust Model

### Assumed Trusted
- Local machine OS
- User account
- Physical access
- Encrypted local storage

### Explicitly Untrusted
- Internet content
- Ingested files
- Web pages
- Emails
- External APIs

---

## Actor Model

### Human
- Ultimate authority
- Can override policy
- Owns Tier 0 data

### Agent (Brain)
- No inherent authority
- Acts only through policy
- Cannot self-elevate

### Scheduled Jobs
- Lowest privilege
- No write authority to memory
- Cannot message without routing

### Tools / MCP Servers
- Capability-scoped
- Treated as semi-trusted
- Never autonomous

---

## Trust Boundaries

```
[ Internet ]
     ↓
[ Ingestion ]
     ↓
[ Blob Storage ] —— sandbox boundary
     ↓
[ Extraction / Derivation ]
     ↓
[ Agent Reasoning ]
     ↓
[ Policy Engine ]
     ↓
[ Side Effects ]
```

Crossing boundaries always reduces trust, never increases it.

---

## Key Security Principles

- No direct UI → tool execution
- No background job → messaging without approval
- No memory writes without Letta
- No agent action without policy evaluation

---

## Failure Assumptions

Assume:
- the agent can hallucinate
- tools can fail
- ingestion can be malicious
- embeddings can be poisoned

Design assumes failure and limits blast radius.

---

## Secrets & Credentials

- Stored in environment variables or OS keychain
- Never written to Obsidian
- Never summarized or embedded
- Rotatable without data loss

---

_End of security model_
