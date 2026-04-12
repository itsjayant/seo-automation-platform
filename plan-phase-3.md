# Implementation Plan — Phase 3: CMS Integration & Approval Dashboard

## Plan Metadata

| Field | Value |
|-------|-------|
| Plan ID | `plan-phase-3` |
| Phase | 3 — CMS Integration & Approval Dashboard |
| Status | `Draft` |
| Owner | Developer Agent — CMS & Web |
| Start Date | TBD (after Phase 2 complete) |
| Target Date | TBD |
| Related PRODUCT.md Phase | Phase 3 — WordPress connector + approval dashboard |

---

## Objective

Connect the automation pipeline to WordPress (and a generic custom CMS webhook template), implement the full human approval gate, and ship the Next.js dashboard. Stakeholders can now review AI-generated recommendations and approve/reject publishing with a single click — the first end-to-end loop from insight to live website change.

---

## Scope

### In Scope
- [ ] WordPress REST API connector (create/update drafts, update Yoast SEO meta fields)
- [ ] Custom CMS webhook connector template (`integrations/cms/custom_webhook.py`)
- [ ] Full NATS approval gate — publish → wait → approve/reject → execute or discard
- [ ] `approval_queue` table for persisting pending approvals
- [ ] Next.js 14 web application scaffold (app router, shadcn/ui)
- [ ] Authentication via NextAuth.js (credentials provider — single user, local)
- [ ] Approval inbox page: list pending items, diff view, approve/reject actions
- [ ] Activity log page: all `audit_log` entries paginated
- [ ] Multi-site switcher component
- [ ] Server actions with Zod validation for all form submissions
- [ ] TanStack Query for client-side data fetching on dashboard pages

### Out of Scope
- Technical SEO agent (Phase 4)
- Reporting / KPI charts (Phase 5)
- Bulk publishing without approval

---

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Phase 2 complete | Internal | Prerequisite | `content_recommendations` rows must exist |
| WordPress site with REST API enabled | External | Required | Application password for auth |
| Node.js 20 LTS | Runtime | Required | Next.js 14 |
| `nats.py` 2.x | Python package | Required | NATS async client |
| NextAuth.js 5.x | npm package | Required | Session management |
| Zod 3.x | npm package | Required | Server action validation |
| TanStack Query 5.x | npm package | Required | Client data fetching |

---

## Technical Design

### Components Touched

```
integrations/cms/wordpress.py                 — create
integrations/cms/custom_webhook.py            — create
integrations/cms/__init__.py                  — create
notifications/publisher.py                    — modify (add approval wait logic)
notifications/subscriber.py                   — create
db/migrations/versions/0003_approvals.py      — create
db/models.py                                  — modify (add approval_queue table)
web/                                          — create (full Next.js app)
web/app/layout.tsx                            — create
web/app/page.tsx                              — create (redirect to /dashboard)
web/app/dashboard/page.tsx                    — create
web/app/approvals/page.tsx                    — create
web/app/approvals/[id]/page.tsx               — create (diff view)
web/app/activity/page.tsx                     — create
web/app/api/approvals/[id]/route.ts           — create (approve/reject endpoint)
web/components/SiteSwitcher.tsx               — create
web/components/ApprovalCard.tsx               — create
web/components/DiffViewer.tsx                 — create
tests/integrations/test_wordpress.py          — create
tests/notifications/test_approval_gate.py     — create
```

### Data Model Changes

| Table | Change | Reason |
|-------|--------|--------|
| `approval_queue` | New table | Durable store for pending approval requests |
| `content_recommendations` | Add `approved_at`, `rejected_at`, `cms_post_id` | Track approval outcome and CMS reference |

**Key columns — `approval_queue`**: `id`, `task_id`, `site_id`, `action_type`, `payload` (JSONB), `diff` (JSONB), `status` (`pending/approved/rejected/timed_out`), `expires_at`, `created_at`, `updated_at`

### Agent / Service Logic

**`integrations/cms/wordpress.py`**
1. Authenticates with WordPress REST API using Application Password from env
2. `create_draft(title, content, meta)` — creates post with `status=draft`, returns `post_id`
3. `update_meta(post_id, yoast_meta)` — updates SEO title, meta description via Yoast REST endpoint
4. All calls pass through rate limiter (max 1 publish/hour enforced)
5. Raises `CMSPublishError` if WordPress returns non-2xx — logged to `audit_log`
6. **Never called directly** — always invoked by NATS subscriber after approval

**Approval Gate Flow**
1. Agent generates recommendation → writes to `content_recommendations` (`status=pending`)
2. `notifications/publisher.py` publishes to `approvals.content` on NATS
3. Row inserted into `approval_queue` with `expires_at = now() + 48h`
4. Next.js dashboard fetches `approval_queue` and renders inbox
5. User clicks Approve → Next.js server action calls `/api/approvals/[id]` with action=`approved`
6. API route updates `approval_queue.status` and publishes `approvals.response` on NATS
7. `notifications/subscriber.py` receives response → calls `wordpress.create_draft()`
8. Outcome written to `audit_log` (`status=approved` or `rejected`)
9. If `expires_at` passes with no response → `status=timed_out`, logged, no CMS action

---

## Approval Gate Checklist

- [ ] `wordpress.create_draft()` — requires approval: content publishing
- [ ] `wordpress.update_meta()` — requires approval: meta field changes
- [ ] `custom_webhook.send()` — requires approval: any outbound write to custom CMS

---

## Testing Plan

| Test | Type | Pass Criteria |
|------|------|---------------|
| WordPress connector creates draft with mocked WP API | Unit | Returns valid `post_id` |
| WordPress connector raises `CMSPublishError` on 403 | Unit | Error raised, logged to audit_log |
| Approval gate blocks direct CMS write without approval | Unit | Raises `ApprovalRequiredError` |
| NATS subscriber executes CMS action after approval event | Unit | Draft created after `approved` message received |
| Timed-out approval sets status and takes no CMS action | Unit | `audit_log` has `status=timed_out`, no WP call |
| Next.js approvals page renders pending items | E2E (Playwright) | Approval card visible with correct diff |
| Approve button triggers CMS draft creation | E2E (Playwright) | `audit_log` has `status=approved` after click |

---

## Environment Variables Added

```
# Phase 3 — CMS Integration & Dashboard

# WordPress
WP_SITE_URL=              # e.g. https://mysite.com
WP_USERNAME=              # WordPress username
WP_APP_PASSWORD=          # WordPress Application Password (not login password)

# Custom CMS webhook (if used)
CUSTOM_CMS_WEBHOOK_URL=   # Endpoint to POST content changes to
CUSTOM_CMS_SECRET=        # HMAC secret to sign webhook payloads

# Approval settings
APPROVAL_TIMEOUT_HOURS=48  # Default: 48 — hours before approval expires

# NextAuth
NEXTAUTH_SECRET=           # Random 32-char string
NEXTAUTH_URL=http://localhost:3000

# Dashboard admin
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=        # Bcrypt hash of dashboard password
```

---

## Rollback Plan

- Run `alembic downgrade -1` to remove `approval_queue` table additions
- Stop Next.js service (`docker compose stop web`)
- Remove `web/` directory from Docker Compose
- Revert `notifications/publisher.py` to Phase 1 state

---

## Completion Criteria

- [ ] WordPress connector creates a draft on a real test site
- [ ] Approval gate blocks all direct CMS writes — verified by unit test
- [ ] Full approval flow tested end-to-end: recommendation → inbox → approve → WP draft
- [ ] Timeout scenario tested: expired approval logs `timed_out`, no CMS action
- [ ] Next.js dashboard accessible at `http://localhost:3000`
- [ ] Login, approvals inbox, and activity log pages working
- [ ] `pytest -v` and `npm test` — all tests green
- [ ] No secrets in committed code
- [ ] This plan status updated to `Complete`

---

## Notes & Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-12 | WordPress Application Password (not OAuth) | Simpler setup for self-hosted WP; OAuth overkill for 1 site |
| 2026-04-12 | NextAuth credentials provider (not social OAuth) | Single-user personal project — no external auth dependency |
| 2026-04-12 | 48-hour approval default with `timed_out` state (not auto-approve) | Conservative approach — never auto-publish on timeout |
