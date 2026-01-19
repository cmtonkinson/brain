# PRD: Firecrawl MCP Server Integration
## Policy-Governed Web Scraping for Brain

---

## 1. Overview

### Feature Name
**Firecrawl MCP Server (Web Scraping Integration)**

### Summary
Integrate **Firecrawl** as an MCP-accessible web scraping capability for Brain, enabling the agent to fetch, render, and extract content from the web in a **policy-governed, observable, and ingestion-safe** manner.

This feature allows Brain to treat the web as a **structured ingestion source**, not an ad‑hoc side channel, and routes all scraped content through the **Universal Ingestion Pipeline**.

---

## 2. Problem Statement

The web is a primary source of information, but naïve scraping introduces:
- brittle scripts
- inconsistent extraction quality
- silent failures
- legal / ethical ambiguity
- uncontrolled data flow into the agent context

Brain needs a **single, auditable, bounded mechanism** for web access that:
- separates fetching from reasoning
- respects autonomy and policy constraints
- preserves raw artifacts for review and rebuild
- avoids “copy‑paste web into prompt” anti‑patterns

---

## 3. Goals and Non-Goals

### Goals
- Enable agent-driven web scraping via MCP
- Support dynamic, JS-rendered pages
- Preserve raw fetched content as artifacts
- Integrate cleanly with the ingestion pipeline
- Ensure scraping actions are policy-checked and observable

### Non-Goals
- Circumventing paywalls or access controls
- High-frequency crawling at scale
- Acting as a general-purpose search engine
- Bypassing robots.txt or legal constraints

---

## 4. Design Principles

1. **Web access is a tool, not a privilege**
2. **Fetching is separate from reasoning**
3. **Raw content is preserved**
4. **Scraping is ingestion, not memory**
5. **All web access is attributable and auditable**

---

## 5. High-Level Architecture

```
Agent (Brain)
   ↓
MCP Host Bridge
   ↓
Firecrawl MCP Server
   ↓
Web (HTTP / JS Render)
   ↓
Raw Content → MinIO
   ↓
Universal Ingestion Pipeline
```

The agent never directly embeds scraped content into prompts.

---

## 6. Functional Requirements

### 6.1 MCP Tool Exposure

Expose Firecrawl capabilities via MCP, such as:
- fetch URL (static HTML)
- fetch URL with JS rendering
- extract main content
- return metadata (title, author, publish date, etc.)

Each invocation must return:
- fetch status
- content type
- raw content reference (not inline body by default)

---

### 6.2 Raw Artifact Handling

For each scrape:
- store raw HTML / rendered output in MinIO
- record headers, status codes, timestamps
- compute checksum for deduplication

Raw artifacts are **Tier 1 inputs**.

---

### 6.3 Ingestion Integration

Scraped content must flow through:
- extraction (article text, tables, etc.)
- normalization (Markdown)
- Obsidian anchor creation
- embeddings and optional summaries

No direct scraping → memory promotion allowed.

---

### 6.4 Rate Limiting & Scope Control

The system must support:
- per-domain rate limits
- allow/deny lists
- maximum fetch size
- maximum render time

Defaults must be conservative.

---

## 7. Policy & Autonomy

- Default autonomy: **L1 (approval required)** for new domains
- L2 allowed for:
  - known domains
  - low-risk fetches
  - previously approved workflows

Scheduled jobs may scrape only pre-approved domains.

---

## 8. Observability & Audit

For each scrape, record:
- URL
- domain
- purpose / intent
- invoking actor
- policy decision
- ingestion trace ID
- downstream artifacts created

Scraping must be fully traceable.

---

## 9. Security & Safety

- Firecrawl runs in an isolated container
- Network access restricted to HTTP/HTTPS
- No credential storage unless explicitly configured
- Scraped content treated as untrusted input

---

## 10. Risks and Mitigations

### Risk: Web Content Poisoning
Mitigation:
- provenance tracking
- raw artifact preservation
- no blind trust in scraped data

### Risk: Over-Scraping
Mitigation:
- strict rate limits
- policy gating
- observability and review

---

## 11. Success Metrics

- Reliable ingestion of web content
- Reduced manual copy/paste
- Clear audit trail for all web access
- No uncontrolled data entering prompts
- Smooth integration with ingestion pipeline

---

## 12. Definition of Done

- [ ] Firecrawl MCP server deployed
- [ ] MCP tool schema defined
- [ ] Raw artifacts stored in MinIO
- [ ] Ingestion pipeline integration working
- [ ] Policy gating enforced
- [ ] Observability traces linked

---

## 13. Alignment with Brain Manifesto

- **Truth Is Explicit:** provenance preserved
- **Actions Are Bounded:** web access is gated
- **Sovereignty First:** data is stored locally
- **Everything Compounds:** web knowledge feeds durable systems

---

_End of PRD_
