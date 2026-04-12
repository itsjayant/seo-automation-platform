# Contributing Guidelines

## Project Structure

```
/
├── agents/          # LangGraph agent definitions (one file per agent)
├── integrations/    # CMS, GSC, GA4 connectors
├── web/             # Next.js dashboard
├── db/              # Migrations (Alembic), seed data, pgvector schemas
├── queue/           # Redis Streams task definitions
├── notifications/   # NATS publishers and subscribers
├── tests/           # Unit + integration tests
├── docker-compose.yml
├── .env.example     # Template — never commit real .env
└── docs/            # Architecture, product, and planning docs
```

## Development Setup

1. Copy `.env.example` to `.env` and fill API credentials
2. Run `docker compose up -d` to start all services
3. Run `alembic upgrade head` to apply database migrations
4. Run `pytest` to verify baseline tests pass

## Branching Strategy

- `main` — production-ready code only; protected, requires PR
- `dev` — integration branch; all feature branches merge here first
- `feat/<scope>` — new feature (e.g., `feat/keyword-agent`)
- `fix/<scope>` — bug fix
- `chore/<scope>` — infra, deps, tooling

## Commit Style (Conventional Commits)

```
feat(agent): add keyword clustering to KW research agent
fix(cms): handle WordPress 403 on draft creation
chore(deps): bump LangGraph to 0.2
```

## Code Standards

- **Python** (agents, integrations): Black formatter, Ruff linter, type hints required
- **TypeScript** (Next.js web): ESLint + Prettier, strict mode enabled
- **Secrets**: All keys in `.env`; use `os.getenv()` / `process.env` only — no hardcoding
- **Tests**: Every new agent function must have a corresponding unit test in `tests/`
- **Rate limiting**: Every outbound API call must go through the shared rate limiter in `integrations/utils/rate_limiter.py`

## Adding a New Agent

1. Create `agents/<agent_name>.py` implementing the `BaseAgent` interface
2. Register the agent in `agents/__init__.py`
3. Add any new environment variables to `.env.example` with a description
4. Write at least one happy-path and one error-path test
5. Update `ARCHITECTURE.md` Component Breakdown table if the agent is new to the topology

## Human Approval Gate

Any action that **writes to a CMS or sends an external request** must:
1. Publish a task to the NATS `approvals.*` subject
2. Wait for an `approved` event before executing
3. Record the outcome (approved / rejected / timed-out) in the `audit_log` table

Never bypass the gate — this is the primary safety control in the system.

## Pull Request Checklist

- [ ] Tests pass (`pytest` + `npm test`)
- [ ] No secrets or API keys in diff
- [ ] Rate limiter used for all new external calls
- [ ] Approval gate respected for CMS writes
- [ ] `ARCHITECTURE.md` updated if topology changed
- [ ] PR description links to the relevant phase in `plan-template.md`
