# Implementation Plan — [Phase Name]

> **Template Instructions**: Duplicate this file, rename it `plan-phase-N.md`, fill every section before writing a single line of code. Delete this instruction block when done.

---

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-N` |
| Phase | N — [Phase Title] |
| Status | `Draft` / `In Progress` / `Complete` |
| Owner | [Your name] |
| Start Date | YYYY-MM-DD |
| Target Date | YYYY-MM-DD |
| Related PRODUCT.md Phase | Phase N — [Feature Name] |

---

## Objective

_One paragraph. What does completing this phase deliver? What user-visible or system-visible capability is unlocked?_

---

## Scope

### In Scope
- [ ] Item 1
- [ ] Item 2

### Out of Scope
- Item A (deferred to Phase N+1)
- Item B (architectural decision — see ARCHITECTURE.md)

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| PostgreSQL schema migration | Internal | Required | Must exist before agent can write |
| SerpAPI credentials | External | Required | Add to `.env.example` |
| Phase N-1 complete | Internal | Prerequisite | [Link to plan-phase-N-1.md] |

---

## Technical Design

### Components Touched

_List every file or module that will be created or modified._

```
agents/<new_agent>.py          — create
integrations/<connector>.py    — create
db/migrations/<version>_....py — create
web/app/<route>/page.tsx       — modify
tests/agents/test_<agent>.py   — create
```

### Data Model Changes

_Describe new tables, columns, or indexes. Write in plain English; the migration file is the source of truth._

| Table | Change | Reason |
|-------|--------|--------|
| `keyword_clusters` | New table | Store clustered keywords per site |
| `audit_log` | Add `phase` column | Tag log entries to implementation phase |

### Agent / Service Logic

_Describe the key decision logic and data flow for each new component. Use pseudocode or bullet points — no actual code._

**`<AgentName>`**
1. Reads X from PostgreSQL
2. Calls Y external API with rate limiter
3. Computes Z and stores result in `<table>`
4. If result triggers approval gate → publishes to NATS `approvals.<scope>`

---

## Approval Gate Checklist

_List every action in this phase that requires a human approval gate._

- [ ] `<action>` — reason: `<why it needs approval>`

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| Agent processes mock GSC data | Unit | Returns expected keyword list without API call |
| Approval gate blocks direct CMS write | Unit | Raises `ApprovalRequiredError` if not acknowledged |
| End-to-end keyword → draft in WordPress | Integration | Draft appears in WP with correct meta fields |

---

## Environment Variables Added

_Append these to `.env.example` with descriptions before merging._

```
# Phase N — [Phase Title]
NEW_API_KEY=          # Description of what this key is for
NEW_CONFIG_VALUE=     # Default: X — explain what it controls
```

---

## Rollback Plan

_What needs to be undone if this phase is reverted?_

- Run `alembic downgrade -1` to remove new migrations
- Remove new containers from `docker-compose.yml`
- Revert `agents/__init__.py` registration

---

## Completion Criteria

_The phase is complete when ALL of the following are true:_

- [ ] All in-scope items implemented
- [ ] All tests in the Testing Plan pass (`pytest -v`)
- [ ] No secrets committed (verified with `git diff --stat`)
- [ ] Approval gates respected for all CMS writes
- [ ] `ARCHITECTURE.md` updated if topology changed
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

_Running log of decisions made during implementation. Date-stamped entries._

| Date | Decision | Reason |
|------|----------|--------|
| YYYY-MM-DD | | |
