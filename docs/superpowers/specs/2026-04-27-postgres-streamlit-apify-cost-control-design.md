# Postgres caching, Streamlit dashboard, and Apify cost guardrails

## Context

The v2 pipeline (DISCOVER → TRIAGE → SCRAPE → EXTRACT → SCORE → CURATE) is functional but expensive: every `/api/search` invokes the Apify Instagram scraper at $2.30 / 1,000 results. With the previous defaults (25 accounts × 8 posts plus hashtag scrape on top), a Berlin search bills ~280 results ≈ $0.65. The user just bought the Apify Starter plan ($30 / month, ~13,000 results), and wants to:

1. Not burn through credits in a few searches.
2. Track what the pipeline is doing so they can iterate on it.
3. Have a deployable surface for that tracking.

The user also wants to **scrape Instagram stories** alongside posts — venues frequently announce "tonight only" events via stories without ever posting. This widens coverage but adds one Apify call per search.

The user already provisioned a Neon Postgres database and asked for a Streamlit page deployed to Streamlit Community Cloud. This spec wraps all asks into one coherent change because they share infrastructure: Postgres becomes the cache that drives cost control AND the data source the Streamlit dashboard reads from.

Outcome: at default settings (60 accounts × 2 posts + 60 accounts × ~3 stories), ~$0.69 per fresh search; repeated searches in the same 24h window are free; ops/dev visibility via a 4-tab Streamlit dashboard.

---

## Components

### A. Postgres schema (Neon)

Two tables. Keep it minimal — extend later if analytics need it.

```sql
-- One row per (account, content_type) pair. content_type ∈ ('posts', 'stories').
-- Posts and stories cache independently so they can have different TTLs and
-- be refreshed on different cadences.
CREATE TABLE scrape_cache (
  account_handle  TEXT NOT NULL,
  content_type    TEXT NOT NULL CHECK (content_type IN ('posts', 'stories')),
  items           JSONB NOT NULL,           -- raw Apify post or story list
  fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at      TIMESTAMPTZ NOT NULL,     -- fetched_at + per-type TTL
  results_billed  INTEGER NOT NULL,         -- Apify-billed count for this row
  PRIMARY KEY (account_handle, content_type)
);
CREATE INDEX scrape_cache_expires_idx ON scrape_cache (expires_at);

CREATE TABLE cost_log (
  id                    BIGSERIAL PRIMARY KEY,
  run_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  city                  TEXT NOT NULL,
  search_date           DATE NOT NULL,
  vibes                 TEXT[] NOT NULL DEFAULT '{}',
  accounts_discovered   INTEGER NOT NULL DEFAULT 0,
  accounts_triaged      INTEGER NOT NULL DEFAULT 0,
  accounts_cache_hit    INTEGER NOT NULL DEFAULT 0,
  accounts_scraped      INTEGER NOT NULL DEFAULT 0,
  posts_scraped         INTEGER NOT NULL DEFAULT 0,
  stories_scraped       INTEGER NOT NULL DEFAULT 0,
  events_extracted      INTEGER NOT NULL DEFAULT 0,
  apify_results_billed  INTEGER NOT NULL DEFAULT 0,
  apify_cost_usd        NUMERIC(10,4) NOT NULL DEFAULT 0,
  claude_input_tokens   INTEGER NOT NULL DEFAULT 0,
  claude_output_tokens  INTEGER NOT NULL DEFAULT 0,
  duration_seconds      NUMERIC(10,3) NOT NULL DEFAULT 0,
  budget_blocked        BOOLEAN NOT NULL DEFAULT FALSE,
  errors                JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX cost_log_run_at_idx ON cost_log (run_at DESC);
CREATE INDEX cost_log_city_idx   ON cost_log (city);
```

Migration applied via a one-shot SQL script (`backend/db/init.sql`) run once against `DATABASE_URL`. No ORM — small enough for raw `asyncpg`.

### B. Backend wiring

New module `backend/db/`:

- `backend/db/__init__.py` — exports `get_pool()` (cached `asyncpg.Pool`, lazy-initialised on first use).
- `backend/db/cache.py` — `read_scrape_cache(handles, content_type)` returns `dict[handle, items]` filtering on non-expired rows; `write_scrape_cache(handle, content_type, items, results_billed, ttl_hours)` upserts. Skips entirely if `DATABASE_URL` is unset (graceful degradation; the app keeps working without Postgres).
- `backend/db/cost.py` — `record_run(run_data: dict)` writes one row to `cost_log`; `monthly_spend_usd() -> float` sums `apify_cost_usd` for `run_at >= date_trunc('month', now())`.

Pipeline changes:

- `backend/instagram/scraper.py` — replace `scrape_posts` with `scrape_account_content(handles, city)` that runs **two independent passes** through the cache + Apify: one for `posts` (TTL 24h, 2 per account), one for `stories` (TTL 24h, up to 5 per account). Each pass: read cache for non-expired rows; for misses, call Apify with the appropriate `resultsType`; write each account's results to cache. Returns a flat list of items each tagged with `content_type` ∈ `{"posts","stories"}`, plus a `cache_summary` dict (`{posts_cache_hit, posts_scraped, stories_cache_hit, stories_scraped, results_billed}`).
- `backend/extraction/extract.py` — Claude prompt + post summary updated to handle both posts and stories. Story items have `media_url`, `posted_at`, optional overlay text — these are passed in the same shape so Claude can extract events regardless. The resulting `Event.scrape_source` is `"profile"`, `"hashtag"`, or `"story"` accordingly.
- `backend/main.py::search_events` — at the top, check `monthly_spend_usd() >= settings.MONTHLY_BUDGET_USD`. If exceeded, skip SCRAPE entirely (still runs DISCOVER + TRIAGE + reads cache only) and sets `budget_blocked=True` in the response. At the end, write a `cost_log` row.

### C. Apify cost guardrails (config + scraper changes)

In `backend/config.py`:

```python
MAX_POSTS_PER_ACCOUNT: int = 2            # was 8 — wider, shallower
MAX_STORIES_PER_ACCOUNT: int = 5          # cap; most accounts have 0-3 active
MAX_ACCOUNTS_PER_SEARCH: int = 60         # was 25
SCRAPE_INCLUDE_STORIES: bool = True       # new — stories on by default
SCRAPE_INCLUDE_HASHTAGS: bool = False     # was implicitly True
APIFY_DATE_FILTER_DAYS: int = 14          # passes onlyPostsNewerThan
APIFY_USD_PER_1K_RESULTS: float = 2.30    # for cost math
POSTS_CACHE_TTL_HOURS: int = 24
STORIES_CACHE_TTL_HOURS: int = 24         # user accepts trade-off
MONTHLY_BUDGET_USD: float = 25.0          # leaves $5 buffer on $30 plan
DATABASE_URL: str | None = None           # env-loaded
```

`backend/instagram/scraper.py`:

- Posts pass: Apify call with `resultsType="posts"`, `resultsLimit=MAX_POSTS_PER_ACCOUNT`, `onlyPostsNewerThan=(now - APIFY_DATE_FILTER_DAYS).isoformat()`.
- Stories pass (if `SCRAPE_INCLUDE_STORIES`): Apify call with `resultsType="stories"`, `resultsLimit=MAX_STORIES_PER_ACCOUNT`. No date filter — IG stories naturally expire at 24h.
- Hashtag scrape gated behind `SCRAPE_INCLUDE_HASHTAGS` (default off).
- After each Apify call, count `results_billed = len(items_returned)` — accounts with no active stories return 0 results and we don't get billed for them.

Per-search cost at new defaults (cache miss): 60 accounts × 2 posts ≈ 120 post results, plus 60 × ~3 active stories ≈ 180 story results = **~300 results ≈ $0.69**. Configured budget of $25/month (`MONTHLY_BUDGET_USD`, $5 buffer under the $30 plan) covers **~36 fresh searches/month**. With 24h cache for both, repeated city searches in the same day are free, so the practical ceiling is significantly higher.

### D. Streamlit dashboard (`streamlit_app/`)

Single-file `streamlit_app/app.py`, four tabs:

| Tab | Reads | Writes |
|---|---|---|
| **Search** | `BACKEND_URL/api/search` | n/a (search is via FastAPI so caching + cost logging engage) |
| **Runs**   | `cost_log` (last 100, filterable by city) | n/a |
| **Cost**   | `cost_log` aggregations (daily spend chart, MTD, runway) | n/a |
| **Cache**  | `scrape_cache` (handle list, ages, billed counts) | DELETE on user "purge" click |

Layout: sidebar shows monthly Apify spend + budget remaining (always visible). Tabs in main area. Chart is a single `st.line_chart` of daily $ for current month.

Connection: `streamlit_app/db.py` wraps an `psycopg[binary]` connection pool (sync — Streamlit is sync). `BACKEND_URL` defaults to `http://localhost:8000` for local dev.

Dependencies (`streamlit_app/requirements.txt`): `streamlit`, `psycopg[binary]`, `httpx`, `pandas`. Kept separate from backend so Streamlit Cloud only installs what it needs.

### E. Streamlit Community Cloud deployment

Steps the user runs (manual — Streamlit Cloud needs their account):

1. Push the repo to GitHub (private OK).
2. At share.streamlit.io: New app → repo → branch → `streamlit_app/app.py`.
3. In Streamlit secrets, add:
   ```toml
   DATABASE_URL = "postgresql://…"
   BACKEND_URL  = "https://…"          # optional, for Search tab
   ```
4. The Cost / Runs / Cache tabs work immediately. The Search tab works only if a public backend is reachable.

For the public backend: the spec leaves backend hosting **out of scope** for now (defer to a separate task). Streamlit Cloud → Postgres works regardless because Neon accepts external TLS connections.

---

## Data flow

```
User → /api/search (FastAPI)
        │
        ├─ check monthly budget (cost.monthly_spend_usd)
        │     └─ if over: budget_blocked=true, skip SCRAPE
        │
        ├─ DISCOVER (SerpAPI + listicles)             [no DB writes]
        ├─ TRIAGE  (Claude)                           [no DB writes]
        │
        ├─ SCRAPE with cache (two passes — posts and stories):
        │     posts pass:
        │       1. read_scrape_cache(handles, "posts")
        │       2. for cache misses → Apify (resultsType=posts, +date filter)
        │       3. write_scrape_cache(handle, "posts", items, billed, ttl=24h)
        │     stories pass (if SCRAPE_INCLUDE_STORIES):
        │       1. read_scrape_cache(handles, "stories")
        │       2. for cache misses → Apify (resultsType=stories)
        │       3. write_scrape_cache(handle, "stories", items, billed, ttl=24h)
        │
        ├─ EXTRACT / SCORE / CURATE (Claude)
        │
        └─ record_run(run_data) → cost_log
```

Streamlit dashboard reads `scrape_cache` and `cost_log` directly via `psycopg`.

---

## Critical files

- `backend/db/__init__.py`              — pool factory (new)
- `backend/db/cache.py`                 — scrape cache helpers (new)
- `backend/db/cost.py`                  — cost log helpers (new)
- `backend/db/init.sql`                 — schema migration (new)
- `backend/instagram/scraper.py`        — cache integration + date filter + hashtag gate
- `backend/main.py`                     — budget check + record_run call
- `backend/config.py`                   — new settings + tightened defaults
- `backend/requirements.txt`            — add `asyncpg`
- `streamlit_app/app.py`                — dashboard (new)
- `streamlit_app/db.py`                 — sync DB helpers (new)
- `streamlit_app/requirements.txt`      — Streamlit deps (new)
- `streamlit_app/.streamlit/config.toml` — port 8501, theme matched to React UI
- `.env.example`                        — add `DATABASE_URL`, `MONTHLY_BUDGET_USD`
- `README.md`                           — add Streamlit + Postgres sections

---

## Error handling & graceful degradation

- **No `DATABASE_URL`**: backend logs a one-time warning, all DB calls become no-ops, pipeline runs as before. Streamlit shows a "Database not configured" empty state.
- **Postgres unreachable**: per-call try/except around `read_scrape_cache` / `write_scrape_cache` / `record_run`. Failure → log + continue. Search succeeds; the run just isn't logged.
- **Budget exceeded**: SCRAPE returns the cached subset only. Response has `budget_blocked: true`; UI surfaces a banner. EXTRACT / SCORE / CURATE still run on whatever's there.
- **Streamlit Cloud cold start**: not addressed; first hit may take ~30s. Acceptable.

---

## Verification

1. **DB migration**: run `psql $DATABASE_URL -f backend/db/init.sql`, then `\dt` shows both tables.
2. **Cache cold + warm**: run the same Berlin search twice in a row. First run writes rows to `scrape_cache` for both `posts` and `stories` content types; second run logs `accounts_cache_hit > 0` and `apify_results_billed = 0` for the cached handles. `SELECT content_type, COUNT(*) FROM scrape_cache GROUP BY content_type` shows both types populated.
3. **Budget cap**: temporarily set `MONTHLY_BUDGET_USD = 0.01`, run a search. Response has `budget_blocked: true` and 0 events scraped (only cached). Reset.
4. **Cost numbers**: after a fresh search, `SELECT apify_cost_usd FROM cost_log ORDER BY run_at DESC LIMIT 1` should match `(posts_scraped + stories_scraped) * 2.30 / 1000` to 4 decimals.
5. **Story extraction**: a search that surfaces a story-only event (e.g., a venue's "doors at 22 tonight" story) should produce an `Event` with `scrape_source = "story"`. Verify by inspecting the `/api/search` response.
6. **Streamlit**: `cd streamlit_app && pip install -r requirements.txt && streamlit run app.py`. Verify all 4 tabs render. Run a search via the Search tab and watch a row appear in the Runs tab.
7. **Streamlit Cloud**: deploy, hit Cost tab, confirm chart renders against Neon. Search tab will error gracefully if `BACKEND_URL` isn't set.
8. **Graceful degradation**: temporarily set `DATABASE_URL=""` in the backend, restart, confirm `/api/search` still works (and logs a warning).

---

## Out of scope

- Backend hosting (Render/Fly). Search tab on Streamlit Cloud won't work end-to-end until this is done — flagged in the README as a known gap.
- Per-event audit table — `cost_log` covers aggregate analytics; per-event history can come later.
- Migrations framework (Alembic). One-shot SQL is enough for two tables.
- Authentication on Streamlit (Cloud has its own access control via the SSO option).
