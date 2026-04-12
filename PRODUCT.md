# SEO Automation Platform — Product Document

## Vision

Eliminate manual SEO guesswork by deploying a team of AI agents that continuously research, plan, execute, and monitor search engine optimization — 24/7 — across multiple websites, with human oversight only where it matters.

## Target User

Solo founders, indie makers, or small agencies managing 1–3 websites who want enterprise-grade SEO execution without the cost of a full-time SEO team or unreliable freelancers.

## Core Feature Set

### 1. Intelligent Keyword Research
- Automated keyword discovery using Google Trends (free), Google Search Console, and SerpAPI
- Intent classification: informational / navigational / commercial / transactional
- Keyword clustering into topic silos with priority scoring
- SERP gap analysis comparing your site vs. top 10 competitors

### 2. On-Page Content Optimization
- Semantic content scoring using vector embeddings (pgvector)
- Missing topic detection and content brief generation
- Title tag, meta description, and heading structure optimization
- Internal linking opportunity mapping across all site pages
- Automated draft suggestions queued for human review before publishing

### 3. Technical SEO Audits
- Scheduled Lighthouse CI audits for Core Web Vitals (CWS, LCP, FID, CLS)
- Broken link detection and redirect chain analysis
- Canonicalization and hreflang validation
- Sitemap and robots.txt health monitoring
- Schema markup validation and auto-generation (JSON-LD)

### 4. Performance Tracking
- Daily rank tracking for target keywords via SerpAPI
- Google Search Console click / impression / CTR trend analysis
- Automated alert when ranking drops >3 positions for a priority keyword
- Month-over-month organic traffic reporting

### 5. CMS Publishing Integration
- WordPress REST API: automated draft creation, meta field updates
- Custom CMS: webhook-based connector template for non-WordPress sites
- All content changes go through the human approval gate before publish
- Rollback capability with version history stored in PostgreSQL

### 6. Human Approval Dashboard (Next.js)
- Unified inbox for all pending approvals (content, redirects, structural changes)
- Side-by-side diff view for content modifications
- One-click approve / reject / request revision
- Activity log showing every automated action taken
- Multi-site switcher to manage 2–3 projects from one screen

### 7. Reporting & Insights
- Weekly automated SEO health report e-mailed or pushed to dashboard
- KPI cards: organic sessions, keyword positions, backlink count, CWV scores
- AI-generated executive summary explaining ranking changes in plain English

## What the Platform Does NOT Do

- Paid search / PPC management
- Link building outreach (planned for future iteration)
- Social media content (out of scope)

## User Journey

```
1. Connect your website (WordPress or custom CMS)
2. Add Google Search Console & GA4 credentials
3. Set target keywords and competitor URLs
4. Agents run initial audit and populate the dashboard (~24 hrs first run)
5. Review and approve the first batch of recommendations
6. System enters continuous optimization cycle:
   · Daily rank tracking
   · Weekly content gap analysis
   · Monthly full technical audit
7. Receive weekly summary report
```

## Constraints & Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Websites supported | 2–3 concurrent |
| Monthly infra cost | < $30 (single VPS) |
| API calls budget | Free tiers first (GSC, GA4, Trends); SerpAPI micro plan ≈ $50/mo |
| Data retention | 12 months rolling in PostgreSQL |
| Uptime target | 99% (monitored via Grafana + Prometheus) |
| Human approval SLA | User-configurable; default 48 hrs before auto-skip |
| Conservative rate limiting | Max 1 CMS publish per hour; max 100 SERP queries/day |

## Roadmap

| Phase | Deliverable | Status |
|-------|------------|--------|
| Phase 1 — Foundation | Data layer, GSC/GA4 ingestion, rank tracking | Planned |
| Phase 2 — Analysis Agents | Keyword research + content gap agents | Planned |
| Phase 3 — CMS Integration | WordPress connector + approval dashboard | Planned |
| Phase 4 — Technical SEO | Lighthouse CI agent + schema generation | Planned |
| Phase 5 — Reporting | Weekly digest + KPI dashboard | Planned |
| Phase 6 — Optimization | Feedback loop ML, link prospect discovery | Future |
