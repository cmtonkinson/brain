# PRD: Self-Modifying Agent with Safe Restart & Rollback
## Autonomous Repair, Controlled Evolution, and Recovery for Brain OS

---

## 1. Overview

### Feature Name
**Self-Modifying Agent (Safe Autoupdate & Repair)**

### Summary
Enable Brain OS to **inspect, modify, and evolve its own codebase** in a controlled manner by granting the agent the ability to:

1. stop and restart itself
2. rollback automatically to a last-known-good state on failure
3. invoke a non-interactive coding agent (e.g., Codex CLI–style) to propose and apply changes

The initial use case is **autonomous self-repair**: monitoring logs, detecting errors, proposing fixes, and safely deploying them without human intervention unless required by policy.

---

## 2. Problem Statement

As Brain OS grows in complexity, manual maintenance becomes brittle and slow:
- regressions slip through
- configuration drift accumulates
- minor bugs require disruptive human attention
- recovery from partial failure is reactive

A system that reasons continuously should be able to **repair itself**, but only under **strict guardrails** that prevent runaway self-modification or catastrophic corruption.

---

## 3. Goals and Non-Goals

### Goals
- Allow Brain OS to propose and apply code changes to itself
- Ensure failed changes are automatically rolled back
- Keep a last-known-good state always recoverable
- Allow autonomous fixes for well-scoped, low-risk issues
- Make all self-modification auditable and reversible

### Non-Goals
- Fully autonomous open-ended self-improvement
- Model/prompt self-tuning without policy review
- Modification of security boundaries or policy engine
- Continuous deployment without health checks

---

## 4. Design Principles

1. **Self-modification is a privileged capability**
2. **Nothing deploys without rollback**
3. **The agent cannot delete its own recovery path**
4. **Change is staged, not live-edited**
5. **Failure is expected and contained**

---

## 5. Core Architecture

```
Brain Agent (Runtime)
   ↓
Self-Modification Controller
   ↓
Working Copy / Staging Branch
   ↓
Coding Agent (Non-interactive)
   ↓
Tests / Health Checks
   ↓
Atomic Restart
   ↓
Health Verification
   ↓
Commit OR Rollback
```

---

## 6. Functional Requirements

### 6.1 Controlled Shutdown & Restart

The system must support:
- graceful agent shutdown
- clean restart from disk
- restart triggered by agent intent or supervisor

Restart must be **externalized** (agent cannot hot-replace itself).

---

### 6.2 Last-Known-Good State

The system must maintain:
- a versioned release marker (commit hash or tag)
- immutable reference to last-known-good
- ability to boot from that state

Rollback must be automatic on failure.

---

### 6.3 Self-Modification Workflow

1. Agent detects issue (logs, metrics, errors)
2. Agent proposes a change plan
3. Policy Engine evaluates autonomy level
4. Coding agent generates patch in staging area
5. Tests and checks run
6. Agent restarts into new version
7. Health checks pass → promote
8. Health checks fail → rollback

---

### 6.4 Coding Agent Invocation

The coding agent:
- runs non-interactively
- has scoped filesystem access
- cannot modify:
  - policy definitions
  - secrets
  - recovery bootstrap
- produces diffs and commit messages

---

### 6.5 Health Checks

Minimum required:
- process starts
- core API responds
- policy engine loads
- no fatal errors in logs

Failure triggers rollback.

---

## 7. Policy & Autonomy

- Self-modification defaults to **L1 (approval required)**
- L2 allowed only for:
  - formatting fixes
  - dependency pin corrections
  - log-level adjustments
- No scheduled job may self-modify without explicit enablement
- Maximum retry count enforced

---

## 8. Security & Safety Constraints

- Coding agent cannot access secrets
- Network access may be disabled during modification
- No self-modification of:
  - Policy Engine
  - Attention Router
  - Recovery Supervisor
- All changes are logged and attributable

---

## 9. Observability & Audit

Record:
- reason for modification
- files changed
- diff summary
- test results
- restart outcome
- rollback events

Optional:
- Obsidian “Self-Change Log” note

---

## 10. Failure Modes & Recovery

### Failed Restart
→ automatic rollback

### Repeated Failure
→ disable self-modification
→ notify human

### Corrupt Working Tree
→ reset to last-known-good
→ re-clone if necessary

---

## 11. Success Metrics

- Reduced manual intervention
- Fast recovery from regressions
- Zero unrecoverable self-corruption events
- Clear audit trail of changes

---

## 12. Definition of Done

- [ ] Restart supervisor implemented
- [ ] Staging + rollback mechanism present
- [ ] Coding agent integration working
- [ ] Health checks enforced
- [ ] Policy gating active
- [ ] Audit logging complete

---

## 13. Alignment with Brain OS Manifesto

- **Actions Are Bounded:** self-change is constrained
- **Truth Is Explicit:** diffs and intent recorded
- **Sovereignty First:** no opaque self-mutation
- **Everything Compounds:** system improves safely over time

---

_End of PRD_
