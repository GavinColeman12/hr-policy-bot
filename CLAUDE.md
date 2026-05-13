# City Event Crawler — Handoff (CLAUDE.md)

_Last updated: 2026-04-29 (end of build session)._

This file is the single source of truth for the City Event Crawler project.
It lives at the repo root with the conventional name `CLAUDE.md` so it
auto-loads at the start of any Claude Code session.

Read it top-to-bottom before touching anything; every load-bearing piece
of context is here.

---

## 1. What this is

A personal event-discovery tool for a 20-30 yo audience. Pick a city + date +
vibes; the app trawls a curated set of Instagram accounts, parses posts and
stories with Claude, scores them, and presents a curated "evening guide" plus
a ranked list of events with rich detail (lineup, time, crowd notes,
score breakdown).

**Primary surface:** A Streamlit dashboard deployed on Streamlit Community
Cloud. It runs the entire pipeline in-process and reads/writes a Neon
Postgres cache. There is no separate backend service.

**Secondary surface:** A FastAPI app under `backend/main.py` that exposes the
same pipeline over HTTP. Useful for local dev and curl-style testing.
Currently unhosted.

**Legacy surface:** A React + Vite frontend under `frontend/`. Was the
original user-facing app; superseded by Streamlit. Still works locally if
you `npm run dev` against the FastAPI backend, but not deployed anywhere.

---

## 2. The pipeline

```
DISCOVER → TRIAGE → SCRAPE → EXTRACT → SCORE → CURATE
   │           │       │        │        │       │
SerpAPI     Claude   Apify    Claude   Claude  Claude
+ seeds     filters  posts +  parses   rates   writes
+ listicle  bad-fit  stories  captions  each   EveningGuide
HTML scrape accounts (cached) into     event   (top pick,
                              Events            itinerary,
                                                gems, skips)
```

| Stage    | Module                                | Notes |
|----------|---------------------------------------|-------|
| DISCOVER | `backend/instagram/discover.py`       | SerpAPI Google + city seeds + listicle HTML fetch. Surfaces ~150 candidate handles per big city. |
| TRIAGE   | `backend/instagram/triage.py`         | Single Claude call. Filters to ≤60 fit accounts. |
| SCRAPE   | `backend/instagram/scraper.py`        | Two Apify actors. Cache-first. |
| EXTRACT  | `backend/extraction/extract.py`       | One Claude call per batch. Pulls title/date/time/venue/lineup/min_age/crowd_note. |
| SCORE    | `backend/extraction/score.py`         | One Claude call. 4-axis breakdown per event. |
| CURATE   | `backend/extraction/curate.py`        | One Claude call. Composes `EveningGuide` and tags events. |

The single entry point is `backend.pipeline.run_search(SearchRequest) -> SearchResponse`. Both Streamlit and FastAPI call it directly.

### Apify actors used

| Actor                                      | What | Pricing model |
|--------------------------------------------|------|---------------|
| `apify/instagram-api-scraper`              | Posts | Pay-per-result, ~$2.30/1k |
| `muhammetakkurtt/instagram-scraper`        | Stories (`resultsType: "stories"`) | Pay-per-result, no rental fee |

Both actors are pay-per-result; both come out of the same platform credit
balance. Earlier attempts used `louisdeconinck/instagram-stories-scraper`
which required a separate paid rental — swapped out because it kept hitting
trial-expired errors.

### Vibe taxonomy

Six values (`backend/models.py::EventVibe`):

- `open_air` — daytime / outdoor DJ sets
- `club_night` — late-night clubs
- `mingle` — meet-people events (mixers, language exchanges)
- `headliner` — big concerts, marquee DJ sets
- `play_party` — kink scene
- `other` — fallback

---

## 3. Current deploy state

### Streamlit Community Cloud (primary)

- **URL**: `city-event-crawler-<short-id>.streamlit.app` (find via
  https://share.streamlit.io)
- **Repo**: https://github.com/GavinColeman12/city-event-crawler
- **Branch**: `main`
- **Main file**: `streamlit_app/app.py`
- **Python**: 3.11 (pinned via `runtime.txt`)
- **Deps**: `streamlit_app/requirements.txt` (bundles both Streamlit and
  backend pipeline deps because Streamlit Cloud prefers the file adjacent
  to the main file over the root one)

**Secrets that must be set in Streamlit Cloud → Settings → Secrets:**

```toml
DATABASE_URL          = "postgresql://…@…neon.tech/neondb?sslmode=require&channel_binding=require"
ANTHROPIC_API_KEY     = "sk-ant-api03-…"
INSTAGRAM_APIFY_TOKEN = "apify_api_…"
SERPAPI_KEY           = "…"
MONTHLY_BUDGET_USD    = "25.0"
```

The Streamlit app hoists these into `os.environ` on startup
(`_hoist_secrets_to_env()` in `app.py`) so that `pydantic-settings` in
`backend.config` picks them up the same way it does locally.

### Neon Postgres

- Project: city-event-crawler / neondb
- Two tables, defined in `backend/db/init.sql`:
  - `scrape_cache` — keyed by `(account_handle, content_type)`. 24h TTL on
    both posts and stories.
  - `cost_log` — one row per `/api/search` run. Powers the Cost / Runs
    dashboards and the monthly budget cutoff.

To migrate the schema (idempotent, safe to re-run):
```bash
backend/.venv/bin/python -c "
import asyncio, asyncpg
from dotenv import dotenv_values
async def main():
    conn = await asyncpg.connect(dotenv_values('.env')['DATABASE_URL'])
    await conn.execute(open('backend/db/init.sql').read())
asyncio.run(main())
"
```

### FastAPI backend

Not deployed. Lives in `backend/main.py`. If you ever want to host it (e.g.
to expose a public API or run the React frontend on top), Render free tier
or Fly.io are the cheapest options — both have first-class FastAPI support.

---

## 4. Running locally

### One-time setup

```bash
git clone https://github.com/GavinColeman12/city-event-crawler.git
cd city-event-crawler
cp .env.example .env
# Fill in: SERPAPI_KEY, INSTAGRAM_APIFY_TOKEN, ANTHROPIC_API_KEY, DATABASE_URL

# Backend venv
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

# Streamlit venv (separate so deploy stays clean)
python3 -m venv streamlit_app/.venv
streamlit_app/.venv/bin/pip install -r streamlit_app/requirements.txt
```

### Run Streamlit (primary)

```bash
streamlit_app/.venv/bin/streamlit run streamlit_app/app.py
# → http://localhost:8501
```

**Important**: if your shell exports `ANTHROPIC_API_KEY=""` (Claude Code
does this), Streamlit will read the empty string and the pipeline will fail
TRIAGE/EXTRACT/SCORE/CURATE with an auth error. Run
`unset ANTHROPIC_API_KEY` first, or `env -u ANTHROPIC_API_KEY streamlit run …`.

### Run FastAPI (optional)

```bash
unset ANTHROPIC_API_KEY
backend/.venv/bin/uvicorn backend.main:app --reload --port 8000
# → http://localhost:8000/api/health
# → http://localhost:8000/docs (Swagger UI)
```

### Run React (legacy, optional)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
# requires FastAPI backend on 8000
```

---

## 5. Repo structure

```
.
├── backend/
│   ├── pipeline.py        # SINGLE ENTRY POINT. Both Streamlit and FastAPI call run_search().
│   ├── main.py            # FastAPI HTTP wrapper around pipeline.py
│   ├── config.py          # All settings (API keys, caps, pricing, budget)
│   ├── models.py          # Pydantic models: Event, EveningGuide, SearchRequest/Response
│   ├── instagram/
│   │   ├── discover.py    # SerpAPI + listicle HTML fetch → IG handles
│   │   ├── triage.py      # Claude filter on accounts
│   │   └── scraper.py     # Two Apify actors with cache integration
│   ├── extraction/
│   │   ├── extract.py     # Claude: posts/stories → Event[]
│   │   ├── score.py       # Claude: per-event 4-axis scores
│   │   └── curate.py      # Claude: EveningGuide composition
│   ├── db/
│   │   ├── __init__.py    # asyncpg pool factory (legacy — pipeline.py owns its own pool now)
│   │   ├── cache.py       # scrape_cache table I/O
│   │   ├── cost.py        # cost_log table I/O + monthly_spend_usd query
│   │   └── init.sql       # Schema migration
│   ├── utils/helpers.py   # haversine distance only
│   └── requirements.txt
├── streamlit_app/
│   ├── app.py             # Dashboard (Search / Runs / Cost / Cache tabs)
│   ├── db.py              # Sync psycopg pool for dashboard tabs (separate from pipeline's async pool)
│   ├── requirements.txt   # Streamlit + pipeline deps (Cloud installs from this)
│   └── .streamlit/config.toml
├── frontend/              # Legacy React UI — not deployed
├── tests/backend/
│   ├── test_db_cache.py        # 6 tests, live Neon
│   ├── test_db_cost.py         # 7 tests, live Neon
│   ├── test_scraper_unit.py    # 5 tests, apify-client mocked
│   └── test_pipeline_integration.py  # 1 live test, costs ~$0.05 in Apify credits
├── docs/
│   ├── HANDOFF.md         # THIS FILE
│   └── superpowers/
│       ├── specs/2026-04-27-postgres-streamlit-apify-cost-control-design.md
│       └── plans/2026-04-27-postgres-streamlit-apify-cost-control.md
├── requirements.txt       # Root — Streamlit Cloud fallback (ignored when streamlit_app/requirements.txt exists)
├── runtime.txt            # Pins Python 3.11 for Streamlit Cloud
└── pyproject.toml         # pytest config (pythonpath, asyncio mode)
```

---

## 6. The four Streamlit tabs

| Tab     | What it does | DB access |
|---------|--------------|-----------|
| Search  | Drives the full pipeline. Picks city + date + vibes, posts to `run_search()` in-process, renders EveningGuide + rich event cards. | Pipeline writes scrape_cache + cost_log via asyncpg |
| Runs    | Paginated table of recent `cost_log` rows, filterable by city. | Sync psycopg read |
| Cost    | MTD spend gauge, daily spend chart, runway estimate, cache hit rate. | Sync psycopg reads |
| Cache   | Browse `scrape_cache` rows; purge individual handles or all expired. | Sync psycopg read + delete |

The sidebar shows the always-visible MTD spend gauge against `MONTHLY_BUDGET_USD`.

### Rich event card fields

Every card shows:
- Relative time (`Tonight · 11 PM` / `In 3h · 8 PM` / `Sat 23:00`)
- End-time arrow (`→ 8:00 AM`)
- 1-2 line blurb from the description
- Lineup chip (first 4 names + overflow)
- Min-age badge (18+ / 21+) when set
- Crowd note (italic) — Claude's one-liner about who'd dig it
- Vibe tags
- Likes + comments
- 4-axis score breakdown with bars
- Curation reason (top score axis) when ≥0.7
- ⚡ "Just dropped" pill on story-sourced events

---

## 7. Cost model

Defaults in `backend/config.py`:

| Setting                  | Default | Notes |
|--------------------------|---------|-------|
| `MAX_ACCOUNTS_PER_SEARCH`| 60      | TRIAGE cap |
| `MAX_POSTS_PER_ACCOUNT`  | 2       | Wider, shallower than v1 |
| `MAX_STORIES_PER_ACCOUNT`| 5       | Most accounts have 0-3 active |
| `SCRAPE_INCLUDE_STORIES` | true    | Stories carry tonight-only drops |
| `SCRAPE_INCLUDE_HASHTAGS`| false   | Skipped by default |
| `POSTS_CACHE_TTL_HOURS`  | 24      |       |
| `STORIES_CACHE_TTL_HOURS`| 24      |       |
| `MONTHLY_BUDGET_USD`     | 25.0    | Cuts off SCRAPE; cache-only fallback |
| `APIFY_POSTS_USD_PER_1K` | 2.30    | Verify on actor page |
| `APIFY_STORIES_USD_PER_1K`| 2.30   | Verify on actor page |

**Fresh search cost (cache miss):** ~60 × 2 posts + ~60 × ~3 stories ≈ 300 results ≈ $0.69.

**Cached search:** $0.

**Monthly capacity at $25 budget:** ~36 fresh searches, unlimited cached.

When `monthly_spend_usd >= MONTHLY_BUDGET_USD`, the pipeline returns
`budget_blocked: true` and skips Apify entirely — it serves whatever's in
the cache for the requested accounts. The UI surfaces a warning.

Claude costs are not currently tracked in the cost_log (tokens are recorded
as 0). At Opus 4.7 prices, a single search is roughly $0.10-0.30 in Claude
spend on top of the Apify cost.

---

## 8. Known issues / gotchas

### Apify actor reliability

`apify/instagram-api-scraper` is being aggressively rate-limited by
Instagram. It returns "Page Not Found" for major venues during peak hours
even when the accounts are valid. There's no fix at our layer — it's an
upstream issue.

**Workaround options** if this becomes a real problem:
1. Swap posts actor to `apify/instagram-scraper` (different actor, may have
   different success rate). Change `APIFY_POSTS_ACTOR` in config.
2. Add retry-with-different-actor logic in `scraper.py`.
3. Lean on stories (which use a different actor and have been more reliable).

### Cross-event-loop bug (fixed)

`backend.db.__init__.get_pool()` is a module-global pool factory. Streamlit
clicks each create a fresh asyncio loop via `asyncio.run()`. Previously
the global pool persisted across loops and crashed with "Event loop is
closed" on the second click. Fixed by having `backend/pipeline.py::run_search`
own its own pool (create + close inside one `asyncio.run`). The module
global is still there but unused by the pipeline; FastAPI lifespan still
references it, harmlessly.

### Streamlit Cloud requirements file priority

If you ever add a dependency, **add it to `streamlit_app/requirements.txt`**,
not the root `requirements.txt`. Cloud prefers the one adjacent to the main
file and ignores the root one. The root one is kept only as a fallback for
other deploy targets that don't have that quirk.

### Empty ANTHROPIC_API_KEY in shell

The Claude Code harness exports `ANTHROPIC_API_KEY=""` (empty string).
Pydantic-settings treats that as set-and-empty, overriding the value in
`.env`. Always `unset ANTHROPIC_API_KEY` before running locally, or use
`env -u ANTHROPIC_API_KEY …`.

### Berlin play-party seeds are best-guess

The seed list in `backend/instagram/discover.py::CITY_SEED_DATA["berlin"]`
includes `kinkyevents.berlin`, `insomnia.berlin`, `klubverboten`,
`quaelgeist.berlin`, `karadahouse` as play-party hints. These were
educated guesses based on venue names; TRIAGE will silently drop any that
don't resolve to real IG accounts.

Also: **the central Berlin play-party listings live on Fetlife (events
tab) and private Telegram channels** — those aren't on Instagram and are
fundamentally out of scope for this IG-only pipeline.

---

## 9. Tests

```bash
unset ANTHROPIC_API_KEY
backend/.venv/bin/pytest tests/backend/ -v --ignore=tests/backend/test_pipeline_integration.py
```

18 tests, ~10-30 seconds:

- `test_db_cache.py` — 6 tests, hit live Neon. Cache write/read, expiry,
  upsert, posts vs stories independence.
- `test_db_cost.py` — 7 tests. record_run insert, monthly_spend_usd
  aggregation, compute_apify_cost formulas, pool=None graceful paths.
- `test_scraper_unit.py` — 5 tests. apify-client is mocked. Verifies
  two-actor invocation, error-row filtering, story cap, stories-disabled
  path.

The integration test (`test_pipeline_integration.py`) is excluded by
default because it hits live Apify (~$0.05 per run). Run explicitly with:

```bash
backend/.venv/bin/pytest tests/backend/test_pipeline_integration.py -v -s
```

---

## 10. Decision log

**Why Streamlit-only instead of React + FastAPI?**
Originally the user-facing app was a React SPA pointing at FastAPI. After
the user shifted to wanting a Streamlit deploy on Community Cloud, we hit
a wall: Streamlit Cloud can't reach `localhost:8000`. Two paths:
- Host FastAPI publicly (~$5-7/mo on Render).
- Collapse FastAPI into Streamlit — pipeline runs in-process.

Picked option B. Cheaper, simpler, single source of secrets. Trade-off is
Streamlit Cloud's 1GB RAM ceiling and single-worker model; for a
single-user admin tool, fine.

**Why per-call asyncpg pool instead of module-global?**
The module-global approach assumed a single long-lived event loop (the
FastAPI lifespan model). Streamlit's `asyncio.run()` per click breaks that
assumption — second-click pool is bound to a closed loop. Per-call pool
in `run_search` eliminates the cross-loop dependency entirely.

**Why swap stories actor from louisdeconinck to muhammetakkurtt?**
`louisdeconinck/instagram-stories-scraper` required a paid actor rental
on top of the Apify platform plan. Hit "trial expired" errors during
testing. `muhammetakkurtt/instagram-scraper` is pay-per-result only —
covered by the same Starter plan with no extra fee.

**Why 6 vibes instead of 15?**
The original 15-vibe taxonomy was too broad (kinky/dating/music/wellness/
adventure/networking/lgbtq/underground/festival/sport_fitness/etc.). The
user explicitly scoped it to a 20-30 yo nightlife/social audience with 5
core vibes + other.

**Why two Streamlit DB modules (pipeline async pool + dashboard sync pool)?**
The dashboard tabs (Runs/Cost/Cache) need sync DB access for fast
streamlit rerenders. The pipeline is async-first and uses asyncpg. Sharing
one pool across sync and async contexts is fiddly; keeping them
independent is cleaner.

---

## 11. Open work / next steps

In rough priority order:

1. **Track Claude tokens in cost_log.** Currently `claude_input_tokens` /
   `claude_output_tokens` are always 0. Each of the four Claude calls
   returns a `usage` object with token counts — propagate them up through
   the pipeline and add to the cost_log insert.

2. **Render and Fly backend hosting**, if you ever want the React UI back
   or need a public API. Out of scope for current setup.

3. **Better posts actor**, if `apify/instagram-api-scraper` continues to
   return Page-Not-Found at scale. Try `apify/instagram-scraper` or build
   in retry-with-fallback.

4. **Streamlit auth.** Cloud has built-in SSO but it's not configured.
   Right now anyone with the URL can run searches against your Apify and
   Anthropic credits.

5. **Cache invalidation on vibe-targeted searches.** Currently the cache
   is keyed only by `(handle, content_type)` — searching the same city
   with different vibes hits the same cache, which is fine because TRIAGE
   may select different accounts. But the EXTRACT call is still 100% fresh
   each time. Could add Claude-result caching keyed by post shortcode.

6. **Per-event cost log** for power-user analytics. Currently the cost_log
   aggregates per `/api/search` run. A second `event_log` table with one
   row per extracted event would unlock "best Berlin venues over time"
   style dashboards.

7. **Fetlife / Telegram scraping** for Berlin play-party coverage. Both
   are off-IG and require separate machinery. Out of current scope.

---

## 12. Security notes

**Rotate the Anthropic key now.** It was pasted in plaintext in two chat
sessions during the build. The key in your local `.env` and Streamlit
Cloud secrets should be replaced via console.anthropic.com → API keys.
Same for the Apify token and SerpAPI key, though they're less expensive
to leak.

After rotation:
1. Update Streamlit Cloud → Settings → Secrets.
2. Update local `.env`.
3. Restart Streamlit / uvicorn locally if running.

Streamlit Cloud secrets are private to your account and not visible in
the public app, but any key that was pasted into a chat with an AI
assistant should be treated as exposed.

---

## 13. References

- **Design spec**:
  [`docs/docs/superpowers/specs/2026-04-27-postgres-streamlit-apify-cost-control-design.md`](docs/superpowers/specs/2026-04-27-postgres-streamlit-apify-cost-control-design.md)
- **Implementation plan**:
  [`docs/docs/superpowers/plans/2026-04-27-postgres-streamlit-apify-cost-control.md`](docs/superpowers/plans/2026-04-27-postgres-streamlit-apify-cost-control.md)
- **README** at repo root — quick-start overview.
- **Apify pricing**: each actor's pricing tab on its Apify Store page.
  Verify against `APIFY_POSTS_USD_PER_1K` and `APIFY_STORIES_USD_PER_1K`
  in `backend/config.py`.
- **Anthropic API pricing**: https://www.anthropic.com/api → Pricing.

---

## 14. Quick troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Search failed: invalid x-api-key` | ANTHROPIC_API_KEY missing or wrong | Add valid key to Streamlit secrets. |
| `Search failed: Event loop is closed` | Stale code on Streamlit Cloud | Wait for Cloud redeploy (2-3 min) after last push. |
| `Missing secrets: …` warning | Secret not visible to backend | Add to Streamlit Cloud secrets in TOML format. |
| `Cannot assign requested address` to localhost:8000 | Old code; Streamlit was POSTing to FastAPI | Already fixed in current code — pipeline runs in-process. |
| `Page Not Found` for valid accounts | IG blocking the Apify actor | Try later; consider swapping `APIFY_POSTS_ACTOR`. |
| `You must rent a paid Actor` | Stories actor reverted to `louisdeconinck` | Check `APIFY_STORIES_ACTOR` is `muhammetakkurtt/instagram-scraper`. |
| Empty cache / no events | Apify token invalid or out of credits | Check apify.com balance; rotate token if needed. |
| Cost not updating in dashboard | Postgres connection issue | Check Neon dashboard; run schema migration. |
| Streamlit `ModuleNotFoundError: pydantic` | Cloud installed from wrong requirements.txt | Verify `streamlit_app/requirements.txt` is present and bundles backend deps. |

---

*End of handoff.*
