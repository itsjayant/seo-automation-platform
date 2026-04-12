# Implementation Plan — Phase 5: Reporting & KPI Dashboard

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-5` |
| Phase | 5 — Reporting & KPI Dashboard |
| Status | `Draft` |
| Owner | Developer Agent — Reporting |
| Start Date | TBD (after Phase 4 complete) |
| Target Date | TBD |
| Related PRODUCT.md Phase | Phase 5 — Weekly digest + KPI dashboard |

---

## Objective

Deliver the full reporting layer: a live KPI dashboard in Next.js, an AI-generated weekly SEO health digest, and automated email/notification delivery. Stakeholders see organic session trends, ranking positions, CWV scores, and a plain-English executive summary — all generated autonomously with no manual report writing.

---

## Scope

### In Scope
- [ ] KPI dashboard page in Next.js — organic sessions, ranking positions, CWV, backlink count cards
- [ ] Ranking trend chart (7-day and 30-day sparklines per keyword)
- [ ] `ReportingAgent` — weekly digest generation using LLM (Claude Sonnet 4 via API)
- [ ] `weekly_reports` table for storing generated reports
- [ ] Weekly email delivery via Resend (free tier: 3,000 emails/month)
- [ ] In-dashboard report view with AI executive summary
- [ ] Month-over-month organic traffic comparison component
- [ ] Alert system: ranking drops >3 positions trigger real-time dashboard notification
- [ ] Grafana dashboard for system health (agent run times, error rates, queue depth)

### Out of Scope
- Backlink acquisition (Phase 6)
- Custom date-range report builder (future)
- PDF export

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Phase 4 complete | Internal | Prerequisite | All data sources populated |
| Anthropic Claude API | External | Required | `ANTHROPIC_API_KEY` — weekly digest only |
| Resend | External | Required | Free tier: 3,000 emails/mo, no credit card |
| Recharts 2.x | npm package | Required | Ranking trend charts in Next.js |
| Grafana OSS | Docker service | Required | System observability |
| Prometheus | Docker service | Required | Metrics scraping |

---

## Technical Design

### Components Touched

```
agents/reporting_agent.py                     — create
agents/__init__.py                            — modify (register agent)
integrations/email/resend_client.py           — create
db/migrations/versions/0005_reporting.py      — create
db/models.py                                  — modify (add weekly_reports)
scheduler/jobs.py                             — modify (add weekly report job)
web/app/dashboard/page.tsx                    — modify (add KPI cards + charts)
web/app/reports/page.tsx                      — create (report list)
web/app/reports/[id]/page.tsx                 — create (full report view)
web/components/KPICard.tsx                    — create
web/components/RankingChart.tsx               — create
web/components/TrafficChart.tsx               — create
web/components/ExecutiveSummary.tsx           — create
docker-compose.yml                            — modify (add Grafana + Prometheus)
tests/agents/test_reporting_agent.py          — create
tests/integrations/test_email.py              — create
```

### Data Model Changes

| Table | Change | Reason |
|-------|--------|--------|
| `weekly_reports` | New table | Store generated weekly SEO digest per site |
| `report_metrics_snapshot` | New table | Point-in-time KPI snapshot for each report |

**Key columns — `weekly_reports`**: `id`, `site_id`, `report_date`, `executive_summary` (text), `metrics_snapshot_id`, `status` (`generating/ready/sent`), `sent_at`, `created_at`

### Agent / Service Logic

**`agents/reporting_agent.py`**
1. Consumes `generate_report` tasks from Redis Streams (triggered every Monday 6 AM)
2. Queries PostgreSQL for the past 7 days of data:
   - Top 10 ranking changes from `rankings` table
   - Organic session delta from `ga4_metrics`
   - CWV score delta from `cwv_snapshots`
   - Open technical issues count from `technical_issues`
   - Pending approvals count from `approval_queue`
3. Builds structured data dict and passes to Claude Sonnet 4 with a strict prompt
4. Claude generates a 200-word plain-English executive summary
5. Writes full report to `weekly_reports` with `status=ready`
6. Calls `resend_client.send_report()` — rate limited, one email per site per week
7. Updates `weekly_reports.status=sent` and logs to `audit_log`

**Prompt discipline for Claude (no hallucination)**
- All metrics passed as structured JSON in the system message
- Claude is instructed to reference only provided data — no fabrication
- Output format enforced with response schema (`summary`, `top_win`, `top_risk`, `recommended_action`)

**`integrations/email/resend_client.py`**
1. Uses Resend API with key from env
2. Renders HTML email from Jinja2 template with report data
3. Rate limited: max 1 report email per site per week
4. Logs delivery to `audit_log`

---

## Approval Gate Checklist

No CMS writes in this phase. Approval gate not triggered.

- [ ] Confirm: `weekly_reports` are read-only artifacts — no site modification

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| Reporting agent builds correct metrics dict from mock DB data | Unit | Dict contains all 5 required metric keys |
| Claude prompt returns valid structured JSON (mocked) | Unit | Response parses to expected schema |
| Email client sends report with mocked Resend API | Unit | API called once with correct `to` and HTML body |
| KPI cards render correct values from mock API | Component | Organic sessions card shows correct delta % |
| Ranking chart renders sparkline for mock 7-day data | Component | Chart renders without error |
| Alert fires when ranking drops >3 in mock data | Unit | NATS publish called with `alerts.ranking_drop` |
| Weekly report job triggers at correct cron time | Integration | Job executes on scheduler tick with correct site_id |

---

## Environment Variables Added

```
# Phase 5 — Reporting

# LLM for report generation
ANTHROPIC_API_KEY=          # Claude Sonnet 4 API key

# Email delivery
RESEND_API_KEY=             # Resend API key (free tier)
REPORT_RECIPIENT_EMAIL=     # Email address to deliver weekly reports to

# Report schedule
REPORTING_CRON=0 6 * * 1   # Default: Mondays at 6 AM

# Ranking alert threshold
RANKING_DROP_ALERT_THRESHOLD=3  # Default: 3 — positions dropped to trigger alert
```

---

## Rollback Plan

- Run `alembic downgrade -1` to drop `weekly_reports` and `report_metrics_snapshot`
- Deregister `ReportingAgent` from `agents/__init__.py`
- Remove reporting job from `scheduler/jobs.py`
- Remove Grafana and Prometheus from `docker-compose.yml`

---

## Completion Criteria

- [ ] Weekly report generated for at least one live site with real data
- [ ] Executive summary produced by Claude references actual metrics (no hallucination)
- [ ] Report email successfully delivered via Resend
- [ ] KPI dashboard cards display live data from PostgreSQL
- [ ] Ranking drop alert fires correctly in test scenario
- [ ] Grafana dashboard shows agent run times and queue depth
- [ ] `pytest -v` and `npm test` — all tests green
- [ ] LLM calls only made for report generation (no other phases use API)
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-12 | Resend over SendGrid or AWS SES | Free tier is generous; simpler API; no credit card for 3,000 emails/mo |
| 2026-04-12 | Claude only for report narrative; all analysis stays in Python | Minimises API costs — one LLM call per site per week |
| 2026-04-12 | Recharts over Chart.js | Better React/TypeScript integration; tree-shakeable |
