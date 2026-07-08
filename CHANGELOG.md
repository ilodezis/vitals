# Changelog

All notable changes to Vitals are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.1.0] — 2026-07-09

### Added — Timeline

- **Timeline** (13th module) — cross-domain event feed: manual annotations (life events, illness, travel, protocol changes) merged with events derived live from other domains' own rows (GLP-1 dose changes, lab draws, BIA scans, achieved milestones, noisy weight periods)
- Manual annotation flags rendered as Chart.js overlays on the weight chart and any custom chart whose series touch an annotated domain
- MCP: `get_timeline` (read) and `log_event` (write) — 37 tools total (22 read + 15 write)
- Optional module (`timeline`), toggleable in Settings; migration `0018_timeline_annotations` seeds it ON
- `export_llm` gained a `timeline_annotations` block; full backup/restore picks up the new `annotations` table automatically

---

## [1.0.0] — 2026-06-27

### Initial public release

**Core infrastructure**
- FastAPI application with Jinja2 + HTMX + Alpine.js frontend
- PostgreSQL 15 + SQLAlchemy 2 async ORM + Alembic migrations
- Redis for scheduler locks and Garmin session caching
- Docker Compose setup with loopback-only port binding (`127.0.0.1:8000`)
- APScheduler for background jobs
- Atomic database backup & restore

**Authentication & Security**
- Single-user bcrypt password authentication
- Signed session cookies (itsdangerous)
- CSRF protection via Origin header validation
- CSP headers
- MCP OAuth 2.0 + PKCE for Claude.ai integration

**Health Domains (12 modules)**
1. **Weight & Body Composition** — WeightLog, BodyMeasurement, ProgressPhoto; US Navy body fat formula; 7-day moving average; linear regression + goal projection; Garmin import with manual override
2. **GLP-1 Protocol** — Injection log (Semaglutide / Tirzepatide); dose phase overlays; plateau detection (>14 days, <100g/week trend)
3. **Garmin Connect** — Auto-sync via garth: HRV, sleep, resting HR, stress, Body Battery, Training Readiness; Health Auto Export JSON fallback
4. **Hevy Workouts** — API sync: exercises, sets, reps, weight; cross-reference with Garmin recovery
5. **Nutrition** — Meal logging with calories + macros; configurable daily targets; included in AI digests
6. **Supplements Catalog** — Evidence-tier catalog (A/B/C); Conflict Engine integration
7. **Skincare Log** — Morning/evening routine; skin status; acid + retinoid conflict warnings
8. **Lab Results & OCR** — PDF/image upload → LLM extraction; out-of-range flagging; history charts
9. **Genetics (VCF)** — VCF parser → health-relevant SNPs; feeds Conflict Engine
10. **Milestones & Goals** — Numeric targets + deadlines; real-time progress %
11. **Weekly AI Digests** — LLM narrative via OpenRouter; configurable model; cross-domain correlations
12. **MCP Integration** — 25 FastMCP tools (14 read + 11 write) for Claude.ai via OAuth 2.0 + PKCE

**Architecture**
- `vitals/` core layer: zero web dependencies, importable in scripts and tests
- `web/` delivery layer: FastAPI, auth, CSRF, Jinja2; zero business logic
- `InsightsMixin` shared interface across all 12 domain models
- `raw_payloads` JSONB table: all API responses preserved for future re-parsing
- Conflict Engine: soft/hard warnings with override audit trail

**Developer experience**
- `python run_local.py` — SQLite + FakeRedis, no Docker needed
- 20 test modules, 100+ tests
- Integration test suite against real Postgres (`scripts/test_postgres.sh`)
- `.env.example` with full documentation
- PWA: installable on iOS/Android Home Screen
