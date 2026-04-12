# Implementation Plan — Phase 6: Continuous Optimisation & Feedback Loop

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-6` |
| Phase | 6 — Continuous Optimisation & Feedback Loop |
| Status | `Draft` |
| Owner | Developer Agent — ML & Optimisation |
| Start Date | TBD (after Phase 5 complete + 4 weeks of live data) |
| Target Date | TBD |
| Related PRODUCT.md Phase | Phase 6 — Feedback loop ML, link prospect discovery |

---

## Objective

Close the learning loop: use real-world outcomes (ranking changes, CTR improvements, traffic deltas) to automatically refine keyword priority scores, content recommendation quality, and agent scheduling parameters. Add link prospect discovery as a read-only intelligence feed. The system now self-improves over time without manual reconfiguration.

---

## Scope

### In Scope
- [ ] Outcome tracking: correlate approved recommendations with search performance delta
- [ ] Keyword priority rescoring based on real click and ranking trajectory data
- [ ] Content recommendation quality scoring (track which suggestions improved CTR most)
- [ ] Dynamic scheduling: agents run more frequently for high-traffic pages
- [ ] Link prospect discovery agent — identifies unlinked brand mentions and link gap opportunities (read-only, no outreach)
- [ ] `outcomes` and `link_prospects` tables (Alembic migration)
- [ ] Feedback loop metrics surfaced on the Grafana dashboard
- [ ] Agent self-tuning config written to `agent_config` table (not hardcoded)

### Out of Scope
- Automated outreach email sending (requires additional human approval design)
- Paid link acquisition
- A/B testing framework (future)

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Phase 5 complete | Internal | Prerequisite | Reporting layer must exist to measure outcomes |
| ≥4 weeks of live data | Data | Required | Need sufficient rankings history for correlation analysis |
| `scikit-learn` 1.5+ | Python package | Required | Already present from Phase 2; used for regression scoring |
| SerpAPI | External | Required | Phase 1 setup; reused for link gap queries |

---

## Technical Design

### Components Touched

```
agents/optimisation_agent.py                  — create
agents/link_prospect_agent.py                 — create
agents/__init__.py                            — modify (register agents)
db/migrations/versions/0006_optimisation.py   — create
db/models.py                                  — modify (add outcomes, link_prospects, agent_config)
scheduler/jobs.py                             — modify (make schedules data-driven from agent_config)
web/app/insights/page.tsx                     — create (link prospects + outcome trends)
web/components/OutcomeTrendChart.tsx          — create
tests/agents/test_optimisation_agent.py       — create
tests/agents/test_link_prospect_agent.py      — create
```

### Data Model Changes

| Table | Change | Reason |
|-------|--------|--------|
| `outcomes` | New table | Link approved recommendation → measured performance delta |
| `link_prospects` | New table | Discovered link opportunities per site |
| `agent_config` | New table | Per-site, per-agent dynamic tuning parameters |

**Key columns — `outcomes`**: `id`, `site_id`, `recommendation_id`, `metric_type` (`ranking/ctr/sessions`), `value_before`, `value_after`, `delta`, `measured_at`

**Key columns — `link_prospects`**: `id`, `site_id`, `source_url`, `anchor_text`, `opportunity_type` (`unlinked_mention/link_gap`), `domain_authority`, `status` (`new/reviewed/dismissed`), `created_at`

**Key columns — `agent_config`**: `id`, `site_id`, `agent_name`, `config` (JSONB), `updated_at`

### Agent / Service Logic

**`agents/optimisation_agent.py`**
1. Runs weekly (after `ReportingAgent` completes)
2. Joins `outcomes` with `content_recommendations` to identify high-impact vs. low-impact recommendation types
3. Computes Pearson correlation between recommendation type and CTR / ranking delta
4. Updates `keyword_clusters.priority_score` based on actual search volume and CTR trajectory
5. Writes updated scheduling frequency to `agent_config` for each site
   - High-traffic pages (>500 organic sessions/week): content analysis monthly → bi-weekly
   - Low-traffic pages: maintain monthly cadence
6. Writes summary of tuning changes to `audit_log`

**`agents/link_prospect_agent.py`**
1. Runs monthly
2. Queries SerpAPI for branded keyword mentions (site name, key topics) — rate limited
3. Checks which mention pages do not link back to target site (unlinked mention detection)
4. Queries SerpAPI for competitors' backlink profiles to find link gap opportunities
5. Writes prospects to `link_prospects` with `status=new` — read-only, no outreach
6. Surfaces new prospects in Next.js dashboard for human review
7. Logs all discovery actions to `audit_log`

**Dynamic Scheduler**
1. `scheduler/jobs.py` reads schedules from `agent_config` table at startup
2. Overrides default cron strings with site-specific values from DB
3. Re-reads config on each scheduler tick (no restart required for config changes)

---

## Approval Gate Checklist

No CMS writes in this phase. Approval gate not triggered.

- [ ] Confirm: `link_prospects` are informational only — no automated outreach
- [ ] Confirm: `agent_config` changes are logged to `audit_log` but do not require approval (internal config only)

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| Optimisation agent increases priority score for keywords with rising CTR | Unit | `priority_score` updated correctly in mock data |
| Optimisation agent increases audit frequency for mock high-traffic page | Unit | `agent_config` updated with bi-weekly schedule |
| Link prospect agent detects unlinked mention in mock SERP data | Unit | Returns `link_prospects` row with `type=unlinked_mention` |
| Dynamic scheduler reads updated config without restart | Integration | Job fires at new interval after DB update |
| Outcome tracking correctly correlates recommendation to ranking delta | Unit | Delta computed correctly for mock before/after values |

---

## Environment Variables Added

```
# Phase 6 — Continuous Optimisation

# Outcome measurement window
OUTCOME_MEASUREMENT_DAYS=28   # Default: 28 — days after approval to measure impact

# Link prospect discovery
LINK_PROSPECT_CRON=0 5 1 * *  # Default: 1st of month at 5 AM

# Optimisation agent schedule
OPTIMISATION_CRON=0 7 * * 1   # Default: Mondays at 7 AM (after reporting agent)
```

---

## Rollback Plan

- Run `alembic downgrade -1` to drop Phase 6 tables
- Deregister `OptimisationAgent` and `LinkProspectAgent` from `agents/__init__.py`
- Revert `scheduler/jobs.py` to static cron strings from Phase 5

---

## Completion Criteria

- [ ] Outcome tracking correctly links at least one approved recommendation to a measurable ranking change
- [ ] Keyword priority scores updated after one full optimisation cycle
- [ ] Dynamic scheduling changes confirmed in `agent_config` after optimisation run
- [ ] Link prospects discovered and visible in dashboard for at least one site
- [ ] `pytest -v` — all tests green
- [ ] No automated outreach or external messages sent
- [ ] `audit_log` records all optimisation decisions
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-12 | Link prospect discovery is read-only (no outreach automation in this phase) | Conservative approach — outreach requires careful human review to avoid spam |
| 2026-04-12 | Dynamic scheduling via DB config (not env vars) | Allows per-site tuning without redeployment |
| 2026-04-12 | Pearson correlation for outcome scoring (not ML model) | Sufficient signal with small dataset; avoids overfitting on 2–3 sites |
