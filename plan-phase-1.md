# Implementation Plan — Phase 1: Foundation

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-1` |
| Phase | 1 — Foundation |
| Status | `Draft` |
| Owner | Developer Agent — Foundation |
| Start Date | TBD |
| Target Date | TBD |
| Related PRODUCT.md Phase | Phase 1 — Data layer, GSC/GA4 ingestion, rank tracking |

---

## Objective

Stand up the complete infrastructure skeleton: PostgreSQL + pgvector data layer, Redis Streams task queue, NATS notification bus, Docker Compose orchestration, and live data ingestion pipelines for Google Search Console and Google Analytics 4. By the end of this phase the system can ingest real performance data, store it, and track keyword rankings — with no agents or UI yet.

---

## Scope

### In Scope
- [ ] Docker Compose stack with all service containers defined
- [ ] PostgreSQL 16 + pgvector extension setup with base schema and Alembic migrations
- [ ] `audit_log` and `sites` tables
- [ ] Redis 7 Streams configuration with task queue boilerplate
- [ ] NATS.io container and `approvals.*` subject definition
- [ ] GSC API integration — fetch clicks, impressions, CTR per URL per day
- [ ] GA4 API integration — fetch organic sessions, bounce rate per page
- [ ] SerpAPI integration — daily rank tracking for configured keywords
- [ ] `BaseAgent` interface in `agents/base.py`
- [ ] Shared rate limiter in `integrations/utils/rate_limiter.py`
- [ ] `.env.example` with all required variables documented
- [ ] pytest baseline with fixtures for mocked APIs
- [ ] Alembic migration runner confirmed working (`alembic upgrade head`)

### Out of Scope
- Agent logic (Phase 2)
- CMS connectors (Phase 3)
- Web dashboard (Phase 3)
- Any content publishing actions

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Docker Desktop (macOS) | External tooling | Required | Dev environment |
| Google Search Console API credentials | External | Required | OAuth 2.0 service account |
| Google Analytics 4 API credentials | External | Required | GA4 Data API service account |
| SerpAPI account | External | Required | Free or micro plan |
| Python 3.12 | Runtime | Required | All agents and integrations |
| Node.js 20 LTS | Runtime | Required | Next.js in later phases; install now |

---

## Technical Design

### Components Touched

```
docker-compose.yml                          — create
.env.example                                — create
agents/__init__.py                          — create
agents/base.py                              — create
integrations/__init__.py                    — create
integrations/utils/rate_limiter.py          — create
integrations/gsc/client.py                  — create
integrations/ga4/client.py                  — create
integrations/serp/client.py                 — create
db/__init__.py                              — create
db/models.py                                — create (SQLAlchemy ORM models)
db/migrations/env.py                        — create (Alembic env)
db/migrations/versions/0001_initial.py      — create
queue/producer.py                           — create
queue/consumer.py                           — create
notifications/publisher.py                  — create
tests/conftest.py                           — create
tests/integrations/test_gsc.py              — create
tests/integrations/test_ga4.py              — create
tests/integrations/test_serp.py             — create
tests/queue/test_producer.py                — create
```

### Data Model Changes

| Table | Change | Reason |
|-------|--------|--------|
| `sites` | New table | Register each managed website |
| `keywords` | New table | Target keywords per site |
| `rankings` | New table (TimescaleDB hypertable) | Daily rank snapshots per keyword |
| `gsc_metrics` | New table | Daily GSC click/impression/CTR per URL |
| `ga4_metrics` | New table | Daily GA4 organic session metrics per page |
| `audit_log` | New table | Record every automated action across all phases |

**Key columns — `sites`**: `id`, `name`, `url`, `cms_type` (`wordpress` / `custom`), `created_at`, `updated_at`

**Key columns — `rankings`**: `id`, `site_id`, `keyword_id`, `position`, `url`, `recorded_at` (partition key)

**Key columns — `audit_log`**: `id`, `agent_name`, `action`, `payload` (JSONB), `status`, `phase`, `created_at`

### Agent / Service Logic

**`integrations/gsc/client.py`**
1. Authenticates using OAuth2 service account credentials from `os.getenv("GSC_CREDENTIALS_JSON")`
2. Calls Search Console API `searchAnalytics.query` for each configured site
3. Passes every outbound request through `rate_limiter` (max 5 req/sec)
4. Returns normalised list of `{url, query, clicks, impressions, ctr, date}` dicts
5. Caller is responsible for persisting to `gsc_metrics`

**`integrations/serp/client.py`**
1. Reads `SERPAPI_KEY` from env
2. Accepts keyword + site URL, returns SERP position (1–100) or `null` if not found
3. Rate limited: max 100 queries/day enforced by rate limiter using Redis counter
4. Caller persists result to `rankings` table

**`queue/producer.py`**
1. Publishes task dicts to Redis Streams key `seo:tasks`
2. Task schema: `{task_id, agent, action, payload, priority, site_id}`
3. Raises `TaskPublishError` on connection failure — no silent failures

**`notifications/publisher.py`**
1. Publishes approval request to NATS subject `approvals.<scope>`
2. Payload: `{task_id, action, diff, site_id, requires_approval_by}`
3. Writes pending approval row to `audit_log` with `status=pending`

---

## Approval Gate Checklist

No CMS writes in this phase. No approval gates triggered.

- [ ] Confirm: no content is published in Phase 1

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| GSC client returns normalised metrics with mocked API | Unit | Returns list of dicts with correct keys |
| GA4 client returns page-level sessions with mocked API | Unit | Returns valid metrics without live API call |
| SerpAPI client respects 100/day rate limit | Unit | Raises `RateLimitError` on 101st call |
| Redis producer publishes task with correct schema | Unit | Task appears in stream with all required fields |
| NATS publisher writes pending row to audit_log | Unit | `audit_log` row has `status=pending` |
| `alembic upgrade head` runs without error | Integration | All 5 tables created in local Postgres |
| All 5 tables have `created_at` / `updated_at` | Integration | Schema inspection confirms columns present |

---

## Environment Variables Added

```
# Phase 1 — Foundation

# Google Search Console
GSC_CREDENTIALS_JSON=   # Path to service account JSON file

# Google Analytics 4
GA4_CREDENTIALS_JSON=   # Path to GA4 service account JSON file
GA4_PROPERTY_ID=        # GA4 numeric property ID

# SerpAPI
SERPAPI_KEY=            # SerpAPI API key (micro plan)

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=seo_platform
POSTGRES_USER=seo
POSTGRES_PASSWORD=      # Strong random password

# Redis
REDIS_URL=redis://localhost:6379

# NATS
NATS_URL=nats://localhost:4222

# Rate limits
SERPAPI_DAILY_LIMIT=100   # Default: 100 — max SERP queries per day
```

---

## Rollback Plan

- Run `alembic downgrade base` to drop all Phase 1 tables
- Remove all Phase 1 containers from `docker-compose.yml`
- Delete all files listed in Components Touched above

---

## Completion Criteria

- [ ] `docker compose up -d` starts all 5 containers with no errors
- [ ] `alembic upgrade head` creates all tables with correct schema
- [ ] GSC and GA4 integrations successfully fetch real data in manual smoke test
- [ ] SerpAPI integration returns rank position for at least one test keyword
- [ ] Redis producer / NATS publisher unit tests pass
- [ ] `pytest -v` — all tests green, no skips
- [ ] No secrets committed — `.env` in `.gitignore`
- [ ] `ARCHITECTURE.md` accurate for this phase (no changes needed)
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-12 | Use TimescaleDB extension for `rankings` table | Time-series queries for ranking history are significantly faster |
| 2026-04-12 | OAuth2 service account (not user OAuth) for GSC/GA4 | Headless server operation — no browser login flow |
| 2026-04-12 | Rate limiter backed by Redis counter | Shared state across multiple agent workers |
