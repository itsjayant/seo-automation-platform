# Implementation Plan — Phase 2: Analysis Agents

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-2` |
| Phase | 2 — Analysis Agents |
| Status | `Draft` |
| Owner | Developer Agent — Analysis |
| Start Date | TBD (after Phase 1 complete) |
| Target Date | TBD |
| Related PRODUCT.md Phase | Phase 2 — Keyword research + content gap agents |

---

## Objective

Implement the SEO Orchestrator (LangGraph) and two core analysis agents: Keyword Research Agent and Content Analysis Agent. By the end of this phase, the system autonomously discovers keyword opportunities, clusters them by intent, scores existing content via vector embeddings, and generates a prioritised action list — all written to the data layer, none published to a CMS yet.

---

## Scope

### In Scope
- [ ] LangGraph SEO Orchestrator with persistent state machine
- [ ] `KeywordResearchAgent` — discovery, clustering, intent classification, SERP gap
- [ ] `ContentAnalysisAgent` — semantic scoring, gap detection, on-page recommendations
- [ ] pgvector embeddings pipeline for all site content (page-level)
- [ ] `keyword_clusters` and `content_recommendations` tables (Alembic migration)
- [ ] Scheduled job runner (APScheduler) for weekly keyword and monthly content cycles
- [ ] Orchestrator writes every action to `audit_log`
- [ ] Unit tests for both agents using mocked data layer
- [ ] Agents registered in `agents/__init__.py`

### Out of Scope
- CMS publishing (Phase 3)
- Approval gate triggering (Phase 3)
- Technical SEO audit (Phase 4)
- Web dashboard (Phase 3)

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Phase 1 complete | Internal | Prerequisite | Data layer, rate limiter, and base tables must exist |
| LangGraph 0.2+ | Python package | Required | `pip install langgraph` |
| LlamaIndex 0.10+ | Python package | Required | Content embedding pipeline |
| `sentence-transformers` | Python package | Required | `all-MiniLM-L6-v2` model for embeddings |
| Google Trends (pytrends) | Python package | Required | Free keyword trend data |
| SerpAPI (Phase 1) | Internal | Required | Already set up — used for SERP gap queries |
| APScheduler 3.x | Python package | Required | Cron-style job scheduling |

---

## Technical Design

### Components Touched

```
agents/base.py                                — modify (finalise interface)
agents/orchestrator.py                        — create
agents/keyword_research_agent.py              — create
agents/content_analysis_agent.py              — create
agents/__init__.py                            — modify (register new agents)
integrations/trends/client.py                 — create
db/migrations/versions/0002_analysis.py       — create
db/models.py                                  — modify (add new tables)
scheduler/jobs.py                             — create
tests/agents/test_keyword_research_agent.py   — create
tests/agents/test_content_analysis_agent.py   — create
tests/agents/test_orchestrator.py             — create
```

### Data Model Changes

| Table | Change | Reason |
|-------|--------|--------|
| `keyword_clusters` | New table | Store clustered keywords with intent label and priority score |
| `content_scores` | New table | Per-page semantic score and optimisation status |
| `content_recommendations` | New table | Agent-generated on-page recommendation per page |
| `page_embeddings` | New table (pgvector) | 1536-dim vector per crawled page for similarity search |

**Key columns — `keyword_clusters`**: `id`, `site_id`, `cluster_name`, `intent` (`informational/navigational/commercial/transactional`), `keywords` (JSONB array), `priority_score` (float), `created_at`, `updated_at`

**Key columns — `content_recommendations`**: `id`, `site_id`, `page_url`, `recommendation_type`, `current_value`, `suggested_value`, `status` (`pending/approved/rejected`), `created_at`, `updated_at`

### Agent / Service Logic

**`agents/orchestrator.py` (LangGraph StateMachine)**
1. Loads active sites from `sites` table
2. Emits `keyword_analysis` and `content_analysis` tasks to Redis Streams
3. Waits for agent completion events before advancing state
4. Writes a `started` and `completed` row to `audit_log` for every task
5. Handles `failed` state — logs error and moves to next site without crashing

**`agents/keyword_research_agent.py`**
1. Consumes `keyword_analysis` tasks from Redis Streams
2. Fetches existing keyword data from `gsc_metrics` and `keywords` tables
3. Calls Google Trends (pytrends) for trend signals — rate limited
4. Calls SerpAPI for top 10 SERP results per candidate keyword — rate limited
5. Clusters keywords using cosine similarity on TF-IDF vectors (scikit-learn KMeans)
6. Classifies intent using rule-based heuristics (no LLM call — keeps costs zero)
7. Writes clusters to `keyword_clusters` table
8. Logs completion to `audit_log`

**`agents/content_analysis_agent.py`**
1. Consumes `content_analysis` tasks from Redis Streams
2. Fetches page URLs from `sites` table; scrapes page text using httpx + BeautifulSoup
3. Generates sentence-transformer embeddings (local model, no API cost)
4. Stores vectors in `page_embeddings` (pgvector)
5. Performs cosine similarity search against `keyword_clusters` to find coverage gaps
6. Scores each page (0–100) and writes to `content_scores`
7. Generates structured on-page recommendations (title, meta, headings, internal links)
8. Writes recommendations to `content_recommendations` with `status=pending`
9. Does NOT publish to CMS — recommendation rows only

**`integrations/trends/client.py`**
1. Wraps `pytrends` TrendReq with rate limiter (5-second sleep between requests)
2. Returns 12-month interest-over-time data for a list of keywords
3. Raises `TrendsUnavailableError` on HTTP 429 — caller retries with backoff

---

## Approval Gate Checklist

No CMS writes in this phase. Approval gate not triggered.

- [ ] Confirm: `content_recommendations` rows are written with `status=pending` and await Phase 3 approval flow

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| Keyword agent clusters 20 mock keywords into ≥2 intent groups | Unit | Returns valid `keyword_clusters` list |
| Keyword agent respects SerpAPI daily rate limit | Unit | Raises `RateLimitError` before 101st call |
| Content agent generates embeddings for mock page HTML | Unit | Returns 384-dim vector (MiniLM model) |
| Content agent detects gap between page and keyword cluster | Unit | Returns ≥1 recommendation for under-covered page |
| Orchestrator advances state after agent completion event | Unit | State transitions from `running` → `complete` |
| Orchestrator logs `started` and `completed` to audit_log | Unit | Two rows present with correct `agent_name` |
| pgvector cosine similarity query returns top-5 similar pages | Integration | Results ordered by similarity score descending |

---

## Environment Variables Added

```
# Phase 2 — Analysis Agents

# Embedding model (local — no API key needed)
EMBEDDING_MODEL=all-MiniLM-L6-v2   # sentence-transformers model name

# LLM (optional — only used for intent refinement if enabled)
OPENAI_API_KEY=                     # Leave blank to use rule-based intent only (free)

# Scheduler
KEYWORD_ANALYSIS_CRON=0 2 * * 1    # Default: Mondays at 2 AM
CONTENT_ANALYSIS_CRON=0 3 1 * *    # Default: 1st of each month at 3 AM
```

---

## Rollback Plan

- Run `alembic downgrade -1` to remove Phase 2 migration
- Deregister `KeywordResearchAgent` and `ContentAnalysisAgent` from `agents/__init__.py`
- Stop scheduler jobs (remove `scheduler/jobs.py`)

---

## Completion Criteria

- [ ] Orchestrator state machine transitions correctly through all states
- [ ] Keyword agent produces clusters for at least one live site
- [ ] Content agent produces at least one `content_recommendations` row per site
- [ ] All embeddings stored in `page_embeddings` with correct vector dimensions
- [ ] `pytest -v` — all tests green
- [ ] No LLM API calls made unless `OPENAI_API_KEY` explicitly set
- [ ] `audit_log` populated for every agent run
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-12 | Use local `sentence-transformers` for embeddings (not OpenAI embeddings API) | Eliminates per-embedding API cost; sufficient quality for content analysis |
| 2026-04-12 | Rule-based intent classification first; LLM optional | Keeps Phase 2 at zero LLM cost; can upgrade in Phase 6 |
| 2026-04-12 | APScheduler (not Celery Beat) for job scheduling | Lower overhead; sufficient for 2–3 sites |
