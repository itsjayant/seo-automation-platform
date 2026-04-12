# Implementation Plan — Phase 4: Technical SEO Agent

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-4` |
| Phase | 4 — Technical SEO Agent |
| Status | `Draft` |
| Owner | Developer Agent — Technical SEO |
| Start Date | TBD (after Phase 3 complete) |
| Target Date | TBD |
| Related PRODUCT.md Phase | Phase 4 — Lighthouse CI agent + schema generation |

---

## Objective

Deploy the Technical SEO Agent that autonomously audits site health on a schedule: Core Web Vitals via Lighthouse CI, broken links, canonical/redirect issues, sitemap and robots.txt health, and JSON-LD schema markup generation. Findings are stored as structured issues and surfaced for human review before any site changes are applied.

---

## Scope

### In Scope
- [ ] `TechnicalSEOAgent` — scheduled crawler and auditor
- [ ] Lighthouse CI integration for Core Web Vitals (LCP, FID/INP, CLS, TTFB)
- [ ] Broken link scanner using Playwright headless browser
- [ ] Canonical tag and redirect chain validator
- [ ] Sitemap.xml and robots.txt health checks
- [ ] JSON-LD schema markup generator (Article, BreadcrumbList, FAQPage types)
- [ ] `technical_issues` table for storing audit findings (Alembic migration)
- [ ] Issues queued for human review via approval gate when fix requires site change
- [ ] Monthly audit schedule via APScheduler
- [ ] Page-speed regression alert (if CWV score drops >10 points)

### Out of Scope
- Automatic deployment of site changes without approval
- Image optimisation pipeline (future)
- Server-side redirect configuration (requires server access beyond WordPress)

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Phase 3 complete | Internal | Prerequisite | Approval gate and CMS connector must be operational |
| Playwright 1.4x | Python package | Required | Headless Chromium for crawling |
| Lighthouse CI (CLI) | Node.js tool | Required | `npm install -g @lhci/cli` in Docker image |
| `httpx` 0.27+ | Python package | Required | Async HTTP for link checking |
| `extruct` | Python package | Required | Extract existing structured data from HTML |
| `jinja2` | Python package | Required | JSON-LD template rendering |

---

## Technical Design

### Components Touched

```
agents/technical_seo_agent.py                 — create
agents/__init__.py                            — modify (register agent)
integrations/lighthouse/client.py             — create
integrations/crawler/link_checker.py          — create
integrations/crawler/sitemap_checker.py       — create
integrations/schema/generator.py              — create
db/migrations/versions/0004_technical.py      — create
db/models.py                                  — modify (add technical_issues)
scheduler/jobs.py                             — modify (add monthly technical audit job)
tests/agents/test_technical_seo_agent.py      — create
tests/integrations/test_lighthouse.py         — create
tests/integrations/test_link_checker.py       — create
tests/integrations/test_schema_generator.py   — create
```

### Data Model Changes

| Table | Change | Reason |
|-------|--------|--------|
| `technical_issues` | New table | Store all detected technical SEO problems per page |
| `cwv_snapshots` | New table | Time-series Core Web Vitals scores per page |
| `schema_drafts` | New table | Generated JSON-LD markup awaiting approval |

**Key columns — `technical_issues`**: `id`, `site_id`, `page_url`, `issue_type` (`broken_link/redirect_chain/missing_canonical/robots_blocked/missing_schema`), `severity` (`critical/warning/info`), `detail` (JSONB), `status` (`open/approved_fix/resolved`), `created_at`, `updated_at`

**Key columns — `cwv_snapshots`**: `id`, `site_id`, `page_url`, `lcp_ms`, `cls_score`, `inp_ms`, `ttfb_ms`, `performance_score`, `recorded_at`

### Agent / Service Logic

**`agents/technical_seo_agent.py`**
1. Consumes `technical_audit` tasks from Redis Streams
2. Fetches all page URLs from `sites` table for the target site
3. For each page (max 50 pages/run, configurable):
   a. Runs Lighthouse CLI via subprocess — parses JSON report
   b. Stores CWV metrics to `cwv_snapshots`
   c. Checks all outbound links with `httpx` — flags broken (4xx/5xx)
   d. Validates canonical tag present and pointing to correct URL
   e. Checks for redirect chains (>1 hop flagged as warning)
4. Checks sitemap.xml: valid XML, all URLs reachable, no blocked by robots.txt
5. Checks robots.txt: no critical paths accidentally blocked
6. For pages missing schema: calls `schema/generator.py` to produce JSON-LD draft
7. Writes all findings to `technical_issues`
8. For schema drafts: writes to `schema_drafts` and queues approval via NATS
9. If CWV score drops >10 points from previous snapshot → queues alert to NATS `alerts.cwv`
10. Logs all actions to `audit_log`

**`integrations/schema/generator.py`**
1. Accepts page HTML and page type (`article/faq/breadcrumb`)
2. Extracts existing schema using `extruct`
3. If schema missing or incomplete, renders JSON-LD template via Jinja2
4. Returns structured dict — caller writes to `schema_drafts`, not directly to CMS
5. Schema applied to CMS only after human approval (Phase 3 gate)

---

## Approval Gate Checklist

- [ ] `schema_drafts` insertion into CMS — requires approval: modifying page HTML/meta
- [ ] Robots.txt or sitemap.xml change recommendation — requires approval: structural site change

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| Lighthouse client parses mock JSON report correctly | Unit | Returns `CWVSnapshot` with correct field values |
| Link checker detects 404 in mock HTTP responses | Unit | Returns issue with `type=broken_link`, `severity=critical` |
| Canonical validator flags missing canonical tag | Unit | Returns issue with `type=missing_canonical` |
| Schema generator produces valid Article JSON-LD | Unit | Output validates against schema.org Article spec |
| CWV regression alert fires when score drops >10 | Unit | NATS publish called with correct alert payload |
| Technical agent processes 50-page mock site | Integration | All issues written to `technical_issues` table |
| Approval gate blocks direct schema CMS injection | Unit | Raises `ApprovalRequiredError` without NATS ack |

---

## Environment Variables Added

```
# Phase 4 — Technical SEO Agent

# Crawler settings
MAX_PAGES_PER_AUDIT=50         # Default: 50 — pages per technical audit run
LIGHTHOUSE_TIMEOUT_SECONDS=60  # Default: 60 — per-page Lighthouse timeout

# CWV regression threshold
CWV_REGRESSION_THRESHOLD=10    # Default: 10 — performance score drop to trigger alert

# Technical audit schedule
TECHNICAL_AUDIT_CRON=0 4 1 * * # Default: 1st of month at 4 AM
```

---

## Rollback Plan

- Run `alembic downgrade -1` to drop `technical_issues`, `cwv_snapshots`, `schema_drafts` tables
- Deregister `TechnicalSEOAgent` from `agents/__init__.py`
- Remove technical audit job from `scheduler/jobs.py`

---

## Completion Criteria

- [ ] Technical audit runs successfully against at least one live test site
- [ ] Lighthouse scores captured in `cwv_snapshots` for all audited pages
- [ ] At least one broken link or schema issue detected and stored in `technical_issues`
- [ ] Schema draft generated and queued for approval (not applied directly)
- [ ] CWV regression alert tested with mock data
- [ ] `pytest -v` — all tests green
- [ ] `audit_log` populated for all agent actions
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-12 | Lighthouse CLI (subprocess) over Lighthouse Node API | Python-native agent; subprocess call is simpler and sufficient |
| 2026-04-12 | Cap at 50 pages per run | Controlled resource usage on low-cost VPS |
| 2026-04-12 | INP replaces FID | FID deprecated by Google in March 2024; using INP from Lighthouse 11+ |
