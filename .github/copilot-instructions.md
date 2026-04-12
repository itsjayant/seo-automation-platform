# GitHub Copilot Instructions — SEO Automation Platform

## Project Context

This is a **multi-agent AI system** that automates SEO for 2–3 WordPress and custom CMS websites. It uses:
- **LangGraph** for agent orchestration (Python)
- **PostgreSQL 16 + pgvector** for data and vector storage
- **Redis 7 Streams** for task queuing
- **NATS.io** for human-approval notifications
- **Next.js 14 + shadcn/ui** for the web dashboard
- **Docker Compose** for local and production deployment

Refer to `ARCHITECTURE.md` for the full system diagram and component list.  
Refer to `PRODUCT.md` for feature scope and what is explicitly out of scope.

## Code Generation Principles

### General
- Prefer **explicit over implicit** — never use magic strings, hardcode configuration, or skip error handling at system boundaries
- All secrets and API keys must come from `os.getenv()` (Python) or `process.env` (TypeScript) only
- Conservative defaults: rate-limit all outbound API calls, never bulk-publish without approval

### Python (Agents & Integrations)
- Use **type hints on all function signatures**
- Format with **Black**, lint with **Ruff** — do not suggest code that would fail either
- Agent classes must implement the `BaseAgent` interface in `agents/base.py`
- All external API calls must go through the shared rate limiter in `integrations/utils/rate_limiter.py`
- Any write to PostgreSQL must use parameterised queries — no string interpolation in SQL
- Use `structlog` for logging, never bare `print()`

### TypeScript (Next.js Web Dashboard)
- Use **strict TypeScript** — no `any` types without justification
- Prefer **server components** by default; use `"use client"` only when interactivity requires it
- Fetch data via `TanStack Query` on the client or Next.js `fetch` in server components
- Form submissions must use **server actions** with Zod validation
- Use `shadcn/ui` components before building custom UI primitives

### Database
- All schema changes must be captured in an **Alembic migration** in `db/migrations/`
- New tables must include `created_at` and `updated_at` timestamps
- Every automated action must insert a row into the `audit_log` table
- Use `pgvector` for any semantic similarity queries — do not implement cosine similarity manually

### Human Approval Gate (Critical)
- Any action that writes to a CMS or fires an outbound request **must** publish to NATS `approvals.*` and wait for acknowledgement
- Never generate code that bypasses the approval gate
- Approval outcomes (approved / rejected / timed_out) must be written to `audit_log`

## Naming Conventions

| Scope | Convention | Example |
|-------|-----------|---------|
| Python files | `snake_case` | `keyword_agent.py` |
| Python classes | `PascalCase` | `KeywordResearchAgent` |
| DB tables | `snake_case` | `keyword_clusters` |
| Next.js pages | `kebab-case` in `/app` | `app/dashboard/page.tsx` |
| Environment variables | `SCREAMING_SNAKE_CASE` | `GSC_API_KEY` |

## File Layout Reminders

```
agents/          → LangGraph agent implementations
integrations/    → External API connectors (GSC, GA4, WordPress, SerpAPI)
db/              → Alembic migrations + schema definitions
queue/           → Redis Streams producers/consumers
notifications/   → NATS publishers and subscribers
web/             → Next.js 14 app
tests/           → pytest tests mirroring the source tree
```

## GitHub Workflow Conventions

### Governance
- **Only the Feature Builder agent may write to GitHub** (create issues, comment, open PRs, manage branches).
- All other agents are read-only against GitHub. Do not generate code or instructions that cause Developer, Planner, Architect, or Reviewer agents to write to GitHub directly.

### Branch Naming
| Type | Pattern | Example |
|------|---------|---------|
| Feature | `feature/<kebab-title>` | `feature/keyword-clustering-api` |
| Bug fix | `fix/<kebab-title>` | `fix/approval-gate-timeout` |
| Chore / refactor | `chore/<kebab-title>` | `chore/alembic-migration-cleanup` |
| Research / spike | `spike/<kebab-title>` | `spike/pgvector-performance` |

Always branch from `main`. Never commit directly to `main`.

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):
```
<type>(<scope>): <short summary>

feat(agents): add retry logic to keyword research agent
fix(queue): handle Redis stream consumer group race condition
chore(db): add index on keyword_clusters.site_id
test(integrations): add GSC connector unit tests
```
Types: `feat`, `fix`, `chore`, `test`, `docs`, `refactor`, `perf`  
Scope: match the top-level directory (`agents`, `integrations`, `db`, `queue`, `notifications`, `web`)

### Pull Requests
- Title must match the linked GitHub issue title
- Body must include `Closes #<issue-number>`
- Draft PRs are opened by Feature Builder — do not mark ready-for-review without human approval
- All PRs require at least one passing review before merge — never auto-merge

### Issue Labels (standard taxonomy)
| Label | Meaning |
|-------|---------|
| `feature` | New functionality |
| `bug` | Defect or regression |
| `chore` | Non-feature maintenance |
| `spike` | Research or investigation |
| `blocked` | Waiting on dependency or decision |
| `in-review` | Under Thorough Reviewer or human review |
| `ready-for-merge` | Review passed, awaiting human merge |
| `phase-1` / `phase-2` | Delivery phase |
| `agents` / `db` / `web` / `queue` / `notifications` / `integrations` | Area label |

## What Copilot Should NOT Do

- Do not suggest Kubernetes or Helm — Docker Compose is the target deployment
- Do not suggest paid third-party services beyond SerpAPI (micro plan) and GSC/GA4 (free tier)
- Do not generate code that writes to a CMS without routing through the approval gate
- Do not suggest `eval()`, `exec()`, or dynamic SQL string building
- Do not add features outside the phases defined in `plan-template.md`
- Do not write to GitHub (issues, PRs, branches, comments) from any agent other than Feature Builder
