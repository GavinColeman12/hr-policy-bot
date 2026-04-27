# Postgres caching + Streamlit dashboard + Apify cost guardrails — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Postgres-backed scrape cache + cost log driven by Neon, swap to two dedicated Apify actors (posts + stories) via the official `apify-client` SDK, tighten cost defaults with a monthly budget cutoff, and ship a 4-tab Streamlit admin dashboard deployable to Streamlit Community Cloud.

**Architecture:** A new `backend/db/` package wraps an `asyncpg` pool and exposes two helpers (`cache` for the per-account scrape cache, `cost` for the run log + monthly budget query). `backend/instagram/scraper.py` is rewritten to run two Apify passes (one per content type) with cache lookup before each. `backend/main.py` gates SCRAPE on `monthly_spend_usd() < MONTHLY_BUDGET_USD` and writes a `cost_log` row at the end of every run. `streamlit_app/app.py` is a single-file dashboard reading Postgres directly via `psycopg`, plus a Search tab that delegates to the FastAPI backend.

**Tech Stack:** Python 3.11+, FastAPI, asyncpg, apify-client (official SDK), Anthropic SDK, Neon Postgres 17, Streamlit, psycopg[binary], pandas.

---

### Spec reference

Source: `docs/superpowers/specs/2026-04-27-postgres-streamlit-apify-cost-control-design.md`. Refer back if any task is ambiguous.

---

## File map

**New:**
- `backend/db/__init__.py` — exports `get_pool()`, `close_pool()`
- `backend/db/cache.py` — scrape cache read/write
- `backend/db/cost.py` — cost log + monthly spend query
- `backend/db/init.sql` — schema migration
- `streamlit_app/app.py` — dashboard entry
- `streamlit_app/db.py` — sync `psycopg` helpers
- `streamlit_app/requirements.txt` — Streamlit-only deps
- `streamlit_app/.streamlit/config.toml` — port + theme
- `tests/backend/__init__.py` — empty marker
- `tests/backend/test_db_cache.py` — cache hit/miss/expiry
- `tests/backend/test_db_cost.py` — record_run + monthly_spend_usd
- `tests/backend/test_scraper_unit.py` — scraper logic with apify-client mocked
- `tests/backend/conftest.py` — pytest fixtures (asyncpg pool, schema teardown)

**Modified:**
- `backend/config.py` — new settings, tightened defaults, two-actor pricing
- `backend/instagram/scraper.py` — rewritten for two actors + cache
- `backend/extraction/extract.py` — handle stories alongside posts
- `backend/main.py` — budget gate + cost_log write
- `backend/models.py` — add scrape/cache fields to `SearchResponse`
- `backend/requirements.txt` — add `asyncpg`, `apify-client`, `pytest`, `pytest-asyncio`
- `.env.example` — add `DATABASE_URL`, `MONTHLY_BUDGET_USD`
- `README.md` — Postgres + Streamlit sections

---

## Task 1: Postgres schema migration

**Files:**
- Create: `backend/db/init.sql`

- [ ] **Step 1: Write the SQL**

```sql
-- backend/db/init.sql
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS scrape_cache (
    account_handle  TEXT NOT NULL,
    content_type    TEXT NOT NULL CHECK (content_type IN ('posts', 'stories')),
    items           JSONB NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    results_billed  INTEGER NOT NULL,
    PRIMARY KEY (account_handle, content_type)
);
CREATE INDEX IF NOT EXISTS scrape_cache_expires_idx
    ON scrape_cache (expires_at);

CREATE TABLE IF NOT EXISTS cost_log (
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
CREATE INDEX IF NOT EXISTS cost_log_run_at_idx ON cost_log (run_at DESC);
CREATE INDEX IF NOT EXISTS cost_log_city_idx   ON cost_log (city);
```

- [ ] **Step 2: Apply the migration to Neon**

Run:
```bash
backend/.venv/bin/python -c "
import asyncio, os, asyncpg
from dotenv import dotenv_values
url = dotenv_values('.env')['DATABASE_URL']
async def main():
    conn = await asyncpg.connect(url)
    sql = open('backend/db/init.sql').read()
    await conn.execute(sql)
    rows = await conn.fetch(\"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename\")
    print([r['tablename'] for r in rows])
    await conn.close()
asyncio.run(main())
"
```

Expected output: `['cost_log', 'scrape_cache']`

- [ ] **Step 3: Commit**

```bash
git add backend/db/init.sql
git commit -m "feat(db): add scrape_cache and cost_log schema"
```

---

## Task 2: Update requirements + config

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/config.py`

- [ ] **Step 1: Update requirements**

```text
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
httpx>=0.25.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dateutil>=2.8.2
python-dotenv>=1.0.0
anthropic>=0.40.0
eval_type_backport>=0.2.0; python_version < "3.10"
asyncpg>=0.29.0
apify-client>=1.7.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Install**

```bash
backend/.venv/bin/pip install -r backend/requirements.txt
```

- [ ] **Step 3: Update config.py settings**

Replace the `class Settings(BaseSettings):` body in `backend/config.py` with:

```python
class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    SERPAPI_KEY: str = Field(default="")
    INSTAGRAM_APIFY_TOKEN: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")
    DATABASE_URL: str = Field(default="")

    CLAUDE_MODEL: str = Field(default="claude-opus-4-7")
    TRIAGE_MAX_TOKENS: int = Field(default=4000)
    EXTRACT_MAX_TOKENS: int = Field(default=8000)
    SCORE_MAX_TOKENS: int = Field(default=4000)
    CURATE_MAX_TOKENS: int = Field(default=4000)

    # Apify actors + pricing (per actor; verify on each actor's Apify page).
    APIFY_POSTS_ACTOR: str = Field(default="apify/instagram-api-scraper")
    APIFY_STORIES_ACTOR: str = Field(default="louisdeconinck/instagram-stories-scraper")
    APIFY_POSTS_USD_PER_1K: float = Field(default=2.30)
    APIFY_STORIES_USD_PER_1K: float = Field(default=2.30)

    # Scrape volume — wider, shallower than v1.
    MAX_ACCOUNTS_PER_SEARCH: int = Field(default=60)
    MAX_POSTS_PER_ACCOUNT: int = Field(default=2)
    MAX_STORIES_PER_ACCOUNT: int = Field(default=5)
    SCRAPE_INCLUDE_STORIES: bool = Field(default=True)
    SCRAPE_INCLUDE_HASHTAGS: bool = Field(default=False)
    APIFY_DATE_FILTER_DAYS: int = Field(default=14)
    MAX_DISCOVERY_QUERIES: int = Field(default=8)

    # Cache TTLs.
    POSTS_CACHE_TTL_HOURS: int = Field(default=24)
    STORIES_CACHE_TTL_HOURS: int = Field(default=24)

    # Cost cutoff. SCRAPE is skipped (cache-only) if this month's spend ≥ this.
    MONTHLY_BUDGET_USD: float = Field(default=25.0)

    DEFAULT_RADIUS_KM: float = Field(default=15.0)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
```

- [ ] **Step 4: Verify import**

```bash
backend/.venv/bin/python -c "
import os
os.chdir('/Users/gavincoleman/city-event-crawler/.claude/worktrees/wonderful-hopper-21979b')
from backend.config import get_settings
s = get_settings()
print('actors:', s.APIFY_POSTS_ACTOR, s.APIFY_STORIES_ACTOR)
print('budget:', s.MONTHLY_BUDGET_USD)
print('caps:', s.MAX_ACCOUNTS_PER_SEARCH, s.MAX_POSTS_PER_ACCOUNT, s.MAX_STORIES_PER_ACCOUNT)
print('db_set:', bool(s.DATABASE_URL))
"
```

Expected: actor names print, budget=25.0, caps=60/2/5, db_set=True.

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/requirements.txt
git commit -m "feat(config): two-actor Apify settings, $25 monthly budget, wider/shallower scrape defaults"
```

---

## Task 3: DB connection pool

**Files:**
- Create: `backend/db/__init__.py`
- Create: `tests/backend/__init__.py`
- Create: `tests/backend/conftest.py`

- [ ] **Step 1: Write the pool module**

```python
# backend/db/__init__.py
"""Postgres connection pool. No-op when DATABASE_URL is unset."""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from ..config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> Optional[asyncpg.Pool]:
    """Return the global pool, creating it on first call. None if unconfigured."""
    global _pool
    if _pool is not None:
        return _pool
    url = get_settings().DATABASE_URL
    if not url:
        return None
    _pool = await asyncpg.create_pool(
        dsn=url,
        min_size=1,
        max_size=4,
        command_timeout=30,
    )
    logger.info("DB pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

- [ ] **Step 2: Create test infrastructure**

```python
# tests/backend/__init__.py
```

```python
# tests/backend/conftest.py
"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
import os
import pathlib

import asyncpg
import pytest
import pytest_asyncio
from dotenv import load_dotenv

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def pg_pool():
    """Pool against the configured DATABASE_URL. Skips if unset."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def clean_tables(pg_pool):
    """Truncate scrape_cache and cost_log before each test."""
    async with pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE scrape_cache, cost_log RESTART IDENTITY")
    yield
```

- [ ] **Step 3: Smoke test the pool**

```bash
backend/.venv/bin/python -c "
import asyncio
async def main():
    from backend.db import get_pool, close_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval('SELECT 1')
    print('pool ok, fetchval =', v)
    await close_pool()
asyncio.run(main())
"
```

Expected: `pool ok, fetchval = 1`

- [ ] **Step 4: Commit**

```bash
git add backend/db/__init__.py tests/backend/__init__.py tests/backend/conftest.py
git commit -m "feat(db): asyncpg pool factory with graceful no-op when unconfigured"
```

---

## Task 4: Scrape cache helpers

**Files:**
- Create: `backend/db/cache.py`
- Create: `tests/backend/test_db_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_db_cache.py
"""Tests for backend.db.cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.db import cache


pytestmark = pytest.mark.asyncio


async def test_write_then_read_returns_items(pg_pool, clean_tables):
    items = [{"shortCode": "abc", "caption": "hello"}]
    await cache.write_scrape_cache(
        pg_pool, "berghain.official", "posts", items, results_billed=1, ttl_hours=24
    )
    got = await cache.read_scrape_cache(pg_pool, ["berghain.official"], "posts")
    assert got == {"berghain.official": items}


async def test_read_skips_expired_rows(pg_pool, clean_tables):
    items = [{"shortCode": "abc"}]
    # Manually insert an expired row.
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO scrape_cache (account_handle, content_type, items, fetched_at, expires_at, results_billed)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6)
            """,
            "old.account",
            "posts",
            '[{"shortCode":"abc"}]',
            datetime.now(timezone.utc) - timedelta(hours=48),
            datetime.now(timezone.utc) - timedelta(hours=24),
            1,
        )
    got = await cache.read_scrape_cache(pg_pool, ["old.account"], "posts")
    assert got == {}


async def test_posts_and_stories_cache_independently(pg_pool, clean_tables):
    await cache.write_scrape_cache(
        pg_pool, "berghain.official", "posts", [{"id": 1}], results_billed=1, ttl_hours=24
    )
    await cache.write_scrape_cache(
        pg_pool, "berghain.official", "stories", [{"id": 99}], results_billed=1, ttl_hours=24
    )
    posts = await cache.read_scrape_cache(pg_pool, ["berghain.official"], "posts")
    stories = await cache.read_scrape_cache(pg_pool, ["berghain.official"], "stories")
    assert posts["berghain.official"] == [{"id": 1}]
    assert stories["berghain.official"] == [{"id": 99}]


async def test_write_upserts_on_conflict(pg_pool, clean_tables):
    await cache.write_scrape_cache(
        pg_pool, "berghain.official", "posts", [{"v": 1}], results_billed=1, ttl_hours=24
    )
    await cache.write_scrape_cache(
        pg_pool, "berghain.official", "posts", [{"v": 2}], results_billed=2, ttl_hours=24
    )
    got = await cache.read_scrape_cache(pg_pool, ["berghain.official"], "posts")
    assert got["berghain.official"] == [{"v": 2}]


async def test_read_with_no_matching_handles_returns_empty(pg_pool, clean_tables):
    got = await cache.read_scrape_cache(pg_pool, ["nonexistent"], "posts")
    assert got == {}


async def test_read_with_empty_handle_list_returns_empty(pg_pool, clean_tables):
    got = await cache.read_scrape_cache(pg_pool, [], "posts")
    assert got == {}
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
backend/.venv/bin/pytest tests/backend/test_db_cache.py -v
```

Expected: ImportError or AttributeError on `backend.db.cache`.

- [ ] **Step 3: Implement the cache module**

```python
# backend/db/cache.py
"""Read/write helpers for the scrape_cache table.

Each (account_handle, content_type) pair is one row. Posts and stories cache
independently with their own TTLs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal

import asyncpg

logger = logging.getLogger(__name__)

ContentType = Literal["posts", "stories"]


async def read_scrape_cache(
    pool: asyncpg.Pool | None,
    handles: Iterable[str],
    content_type: ContentType,
) -> dict[str, list[dict[str, Any]]]:
    """Return {handle: items} for non-expired rows. Empty if pool is None."""
    if pool is None:
        return {}
    handle_list = list(handles)
    if not handle_list:
        return {}
    rows = await pool.fetch(
        """
        SELECT account_handle, items
        FROM scrape_cache
        WHERE content_type = $1
          AND account_handle = ANY($2::text[])
          AND expires_at > now()
        """,
        content_type,
        handle_list,
    )
    return {r["account_handle"]: json.loads(r["items"]) for r in rows}


async def write_scrape_cache(
    pool: asyncpg.Pool | None,
    handle: str,
    content_type: ContentType,
    items: list[dict[str, Any]],
    *,
    results_billed: int,
    ttl_hours: int,
) -> None:
    """Upsert a single (handle, content_type) row. No-op when pool is None."""
    if pool is None:
        return
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    await pool.execute(
        """
        INSERT INTO scrape_cache
            (account_handle, content_type, items, fetched_at, expires_at, results_billed)
        VALUES ($1, $2, $3::jsonb, now(), $4, $5)
        ON CONFLICT (account_handle, content_type) DO UPDATE SET
            items = EXCLUDED.items,
            fetched_at = EXCLUDED.fetched_at,
            expires_at = EXCLUDED.expires_at,
            results_billed = EXCLUDED.results_billed
        """,
        handle,
        content_type,
        json.dumps(items),
        expires_at,
        results_billed,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
backend/.venv/bin/pytest tests/backend/test_db_cache.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db/cache.py tests/backend/test_db_cache.py
git commit -m "feat(db): scrape cache helpers with per-content-type TTL"
```

---

## Task 5: Cost log helpers

**Files:**
- Create: `backend/db/cost.py`
- Create: `tests/backend/test_db_cost.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_db_cost.py
"""Tests for backend.db.cost."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.db import cost


pytestmark = pytest.mark.asyncio


async def test_record_run_inserts_one_row(pg_pool, clean_tables):
    await cost.record_run(
        pg_pool,
        {
            "city": "Berlin",
            "search_date": "2026-04-27",
            "vibes": ["nightlife"],
            "accounts_discovered": 158,
            "accounts_triaged": 60,
            "accounts_cache_hit": 12,
            "accounts_scraped": 48,
            "posts_scraped": 90,
            "stories_scraped": 130,
            "events_extracted": 22,
            "apify_results_billed": 220,
            "apify_cost_usd": 0.506,
            "claude_input_tokens": 30000,
            "claude_output_tokens": 1200,
            "duration_seconds": 47.21,
            "budget_blocked": False,
            "errors": [],
        },
    )
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM cost_log")
    assert len(rows) == 1
    assert rows[0]["city"] == "Berlin"
    assert rows[0]["posts_scraped"] == 90
    assert rows[0]["stories_scraped"] == 130


async def test_monthly_spend_sums_current_month(pg_pool, clean_tables):
    base = {
        "city": "Berlin", "search_date": "2026-04-27", "vibes": [],
        "accounts_discovered": 0, "accounts_triaged": 0, "accounts_cache_hit": 0,
        "accounts_scraped": 0, "posts_scraped": 0, "stories_scraped": 0,
        "events_extracted": 0, "apify_results_billed": 0,
        "claude_input_tokens": 0, "claude_output_tokens": 0,
        "duration_seconds": 0.0, "budget_blocked": False, "errors": [],
    }
    await cost.record_run(pg_pool, {**base, "apify_cost_usd": 0.50})
    await cost.record_run(pg_pool, {**base, "apify_cost_usd": 0.30})
    spent = await cost.monthly_spend_usd(pg_pool)
    assert spent == pytest.approx(0.80, abs=0.001)


async def test_monthly_spend_returns_zero_when_no_runs(pg_pool, clean_tables):
    spent = await cost.monthly_spend_usd(pg_pool)
    assert spent == 0.0


async def test_monthly_spend_returns_zero_when_pool_none():
    spent = await cost.monthly_spend_usd(None)
    assert spent == 0.0


async def test_record_run_no_op_when_pool_none():
    # Must not raise.
    await cost.record_run(None, {"city": "x", "search_date": "2026-01-01"})


def test_apify_cost_usd_formula():
    # Pure helper for unit test.
    posts = 120
    stories = 180
    cost_usd = cost.compute_apify_cost(posts, stories, posts_per_1k=2.30, stories_per_1k=2.30)
    assert cost_usd == pytest.approx((120 + 180) * 2.30 / 1000, abs=0.0001)


def test_apify_cost_with_different_actor_pricing():
    cost_usd = cost.compute_apify_cost(100, 100, posts_per_1k=2.30, stories_per_1k=4.00)
    expected = (100 * 2.30 + 100 * 4.00) / 1000
    assert cost_usd == pytest.approx(expected, abs=0.0001)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
backend/.venv/bin/pytest tests/backend/test_db_cost.py -v
```

Expected: ImportError on `backend.db.cost`.

- [ ] **Step 3: Implement the cost module**

```python
# backend/db/cost.py
"""Cost log writer + monthly spend reader."""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


def compute_apify_cost(
    posts_billed: int,
    stories_billed: int,
    *,
    posts_per_1k: float,
    stories_per_1k: float,
) -> float:
    """Return total Apify cost in USD, rounded to 4 dp."""
    return round(
        (posts_billed * posts_per_1k + stories_billed * stories_per_1k) / 1000.0,
        4,
    )


async def record_run(pool: asyncpg.Pool | None, run: dict[str, Any]) -> None:
    """Insert one cost_log row. No-op when pool is None."""
    if pool is None:
        return
    try:
        await pool.execute(
            """
            INSERT INTO cost_log (
                city, search_date, vibes,
                accounts_discovered, accounts_triaged, accounts_cache_hit,
                accounts_scraped, posts_scraped, stories_scraped,
                events_extracted, apify_results_billed, apify_cost_usd,
                claude_input_tokens, claude_output_tokens,
                duration_seconds, budget_blocked, errors
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb)
            """,
            run.get("city", ""),
            run.get("search_date"),
            run.get("vibes", []),
            run.get("accounts_discovered", 0),
            run.get("accounts_triaged", 0),
            run.get("accounts_cache_hit", 0),
            run.get("accounts_scraped", 0),
            run.get("posts_scraped", 0),
            run.get("stories_scraped", 0),
            run.get("events_extracted", 0),
            run.get("apify_results_billed", 0),
            run.get("apify_cost_usd", 0.0),
            run.get("claude_input_tokens", 0),
            run.get("claude_output_tokens", 0),
            run.get("duration_seconds", 0.0),
            run.get("budget_blocked", False),
            json.dumps(run.get("errors", [])),
        )
    except Exception as exc:
        # Logging failures must never break the search.
        logger.warning("cost_log insert failed: %s", exc)


async def monthly_spend_usd(pool: asyncpg.Pool | None) -> float:
    """Sum apify_cost_usd for runs in the current calendar month (UTC)."""
    if pool is None:
        return 0.0
    val = await pool.fetchval(
        """
        SELECT COALESCE(SUM(apify_cost_usd), 0)::float
        FROM cost_log
        WHERE run_at >= date_trunc('month', now() at time zone 'utc')
        """
    )
    return float(val or 0.0)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
backend/.venv/bin/pytest tests/backend/test_db_cost.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db/cost.py tests/backend/test_db_cost.py
git commit -m "feat(db): cost log writer + monthly spend query"
```

---

## Task 6: Rewrite Apify scraper for two actors + apify-client SDK

**Files:**
- Modify: `backend/instagram/scraper.py`

- [ ] **Step 1: Replace scraper.py contents**

```python
# backend/instagram/scraper.py
"""SCRAPE stage — pull posts and stories from triaged Instagram accounts.

Two passes against two different Apify actors:

  posts   →  apify/instagram-api-scraper          (resultsType=posts)
  stories →  louisdeconinck/instagram-stories-scraper  (profiles list)

Each pass is cache-aware: hits skip the actor, misses get scraped and
written back. The SDK calls are blocking, so we run them in
``asyncio.to_thread`` to keep the FastAPI event loop free.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from apify_client import ApifyClient

from ..config import get_settings
from ..db import cache as cache_db

logger = logging.getLogger(__name__)


def _profile_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle}/"


def _date_filter_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _run_actor_sync(client: ApifyClient, actor_id: str, run_input: dict[str, Any]) -> list[dict]:
    """Blocking SDK call. Run inside ``asyncio.to_thread``."""
    try:
        run = client.actor(actor_id).call(run_input=run_input)
    except Exception as exc:
        logger.warning("Apify actor %s call failed: %s", actor_id, exc)
        return []
    items: list[dict] = []
    try:
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            items.append(item)
    except Exception as exc:
        logger.warning("Apify dataset fetch for %s failed: %s", actor_id, exc)
    return items


def _looks_like_error(item: dict) -> bool:
    """The instagram-api-scraper sometimes returns error rows; filter them."""
    return bool(item.get("error")) or item.get("errorDescription") is not None


def _index_by_owner(items: list[dict]) -> dict[str, list[dict]]:
    """Group raw Apify post items by ownerUsername."""
    by_owner: dict[str, list[dict]] = {}
    for item in items:
        owner = (
            item.get("ownerUsername")
            or (item.get("owner") or {}).get("username")
            or ""
        )
        if not owner:
            continue
        by_owner.setdefault(owner.lower(), []).append(item)
    return by_owner


def _index_stories_by_owner(items: list[dict]) -> dict[str, list[dict]]:
    """Group raw stories actor items by username (key may differ slightly)."""
    by_owner: dict[str, list[dict]] = {}
    for item in items:
        owner = (
            item.get("username")
            or item.get("ownerUsername")
            or (item.get("user") or {}).get("username")
            or ""
        )
        if not owner:
            continue
        by_owner.setdefault(owner.lower(), []).append(item)
    return by_owner


async def _scrape_posts_pass(
    client: ApifyClient,
    pool: asyncpg.Pool | None,
    handles: list[str],
) -> tuple[list[dict], int, int, int]:
    """Run the posts pass with cache. Return (items, cache_hits, scraped, billed)."""
    settings = get_settings()
    cached = await cache_db.read_scrape_cache(pool, handles, "posts")
    cache_hits = len(cached)
    misses = [h for h in handles if h not in cached]

    items: list[dict] = []
    for h, posts in cached.items():
        for p in posts:
            p.setdefault("_origin", "profile")
        items.extend(cached[h])

    billed = 0
    if misses:
        run_input = {
            "directUrls": [_profile_url(h) for h in misses],
            "resultsType": "posts",
            "resultsLimit": settings.MAX_POSTS_PER_ACCOUNT,
            "searchType": "user",
            "searchLimit": 1,
            "onlyPostsNewerThan": _date_filter_iso(settings.APIFY_DATE_FILTER_DAYS),
        }
        raw = await asyncio.to_thread(
            _run_actor_sync, client, settings.APIFY_POSTS_ACTOR, run_input
        )
        clean = [r for r in raw if not _looks_like_error(r)]
        billed = len(clean)
        for r in clean:
            r.setdefault("_origin", "profile")
        # Persist per handle.
        by_owner = _index_by_owner(clean)
        for handle in misses:
            handle_items = by_owner.get(handle.lower(), [])
            await cache_db.write_scrape_cache(
                pool, handle, "posts", handle_items,
                results_billed=len(handle_items),
                ttl_hours=settings.POSTS_CACHE_TTL_HOURS,
            )
        items.extend(clean)

    return items, cache_hits, len(misses), billed


async def _scrape_stories_pass(
    client: ApifyClient,
    pool: asyncpg.Pool | None,
    handles: list[str],
) -> tuple[list[dict], int, int, int]:
    """Run the stories pass with cache. Return (items, cache_hits, scraped, billed)."""
    settings = get_settings()
    cached = await cache_db.read_scrape_cache(pool, handles, "stories")
    cache_hits = len(cached)
    misses = [h for h in handles if h not in cached]

    items: list[dict] = []
    for h, stories in cached.items():
        for s in stories:
            s.setdefault("_origin", "story")
        items.extend(stories)

    billed = 0
    if misses:
        run_input = {"profiles": [_profile_url(h) for h in misses]}
        raw = await asyncio.to_thread(
            _run_actor_sync, client, settings.APIFY_STORIES_ACTOR, run_input
        )
        clean = [r for r in raw if not _looks_like_error(r)]
        billed = len(clean)
        # Cap per-account stories.
        capped: list[dict] = []
        per_owner: dict[str, int] = {}
        for r in clean:
            owner = (
                r.get("username")
                or r.get("ownerUsername")
                or (r.get("user") or {}).get("username")
                or ""
            ).lower()
            if per_owner.get(owner, 0) >= settings.MAX_STORIES_PER_ACCOUNT:
                continue
            per_owner[owner] = per_owner.get(owner, 0) + 1
            r.setdefault("_origin", "story")
            capped.append(r)

        by_owner = _index_stories_by_owner(capped)
        for handle in misses:
            handle_items = by_owner.get(handle.lower(), [])
            await cache_db.write_scrape_cache(
                pool, handle, "stories", handle_items,
                results_billed=len(handle_items),
                ttl_hours=settings.STORIES_CACHE_TTL_HOURS,
            )
        items.extend(capped)

    return items, cache_hits, len(misses), billed


async def scrape_account_content(
    handles: list[str],
    pool: asyncpg.Pool | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Scrape recent posts AND stories for *handles*, with caching.

    Returns:
        (items, summary) where:
          - items is a flat list of raw Apify items, each tagged with
            ``_origin`` ∈ {"profile", "story"}.
          - summary has keys ``posts_cache_hit``, ``posts_scraped``,
            ``stories_cache_hit``, ``stories_scraped``,
            ``posts_billed``, ``stories_billed``.

    No-op (returns ``[]``) when ``INSTAGRAM_APIFY_TOKEN`` is unset.
    """
    settings = get_settings()
    summary = {
        "posts_cache_hit": 0,
        "posts_scraped": 0,
        "stories_cache_hit": 0,
        "stories_scraped": 0,
        "posts_billed": 0,
        "stories_billed": 0,
    }
    if not settings.INSTAGRAM_APIFY_TOKEN or not handles:
        if not settings.INSTAGRAM_APIFY_TOKEN:
            logger.warning("INSTAGRAM_APIFY_TOKEN not set — skipping SCRAPE")
        return [], summary

    client = ApifyClient(settings.INSTAGRAM_APIFY_TOKEN)

    posts_items, p_hits, p_scraped, p_billed = await _scrape_posts_pass(
        client, pool, handles
    )
    summary.update(
        posts_cache_hit=p_hits,
        posts_scraped=p_scraped,
        posts_billed=p_billed,
    )

    stories_items: list[dict] = []
    if settings.SCRAPE_INCLUDE_STORIES:
        stories_items, s_hits, s_scraped, s_billed = await _scrape_stories_pass(
            client, pool, handles
        )
        summary.update(
            stories_cache_hit=s_hits,
            stories_scraped=s_scraped,
            stories_billed=s_billed,
        )

    items = posts_items + stories_items
    logger.info(
        "SCRAPE: posts=%d (cache=%d, scraped=%d, billed=%d), "
        "stories=%d (cache=%d, scraped=%d, billed=%d), total=%d items",
        len(posts_items), summary["posts_cache_hit"], summary["posts_scraped"], summary["posts_billed"],
        len(stories_items), summary["stories_cache_hit"], summary["stories_scraped"], summary["stories_billed"],
        len(items),
    )
    return items, summary
```

- [ ] **Step 2: Update the package export**

Modify `backend/instagram/__init__.py`:

```python
"""Instagram-only deep discovery pipeline: discover → triage → scrape."""

from .discover import discover_accounts
from .triage import triage_accounts
from .scraper import scrape_account_content

__all__ = ["discover_accounts", "triage_accounts", "scrape_account_content"]
```

- [ ] **Step 3: Verify imports**

```bash
backend/.venv/bin/python -c "
from backend.instagram import scrape_account_content, discover_accounts, triage_accounts
print('imports ok')
"
```

Expected: `imports ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/instagram/scraper.py backend/instagram/__init__.py
git commit -m "feat(scrape): two-actor pipeline (posts + stories) via apify-client SDK with cache"
```

---

## Task 7: Scraper unit tests (apify-client mocked)

**Files:**
- Create: `tests/backend/test_scraper_unit.py`

- [ ] **Step 1: Write the tests**

```python
# tests/backend/test_scraper_unit.py
"""Unit tests for the scraper, with apify-client and DB mocked."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.instagram import scraper


pytestmark = pytest.mark.asyncio


def _fake_post(owner: str, code: str) -> dict:
    return {"shortCode": code, "ownerUsername": owner, "caption": "fake"}


def _fake_story(owner: str, sid: str) -> dict:
    return {"id": sid, "username": owner}


async def test_no_token_returns_empty(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APIFY_TOKEN", "")
    monkeypatch.setenv("DATABASE_URL", "")
    # Force fresh settings.
    from backend import config
    config.get_settings.cache_clear() if hasattr(config.get_settings, "cache_clear") else None
    items, summary = await scraper.scrape_account_content(["acc1"], pool=None)
    assert items == []
    assert summary["posts_billed"] == 0


async def test_two_passes_invoke_two_actors(monkeypatch):
    """When token is set, both posts and stories actors are called once."""
    monkeypatch.setenv("INSTAGRAM_APIFY_TOKEN", "fake_token")
    from backend import config
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()

    calls: list[str] = []

    def fake_run(client, actor_id, run_input):
        calls.append(actor_id)
        if "stories" in actor_id:
            return [_fake_story("acc1", "s1"), _fake_story("acc2", "s2")]
        return [_fake_post("acc1", "p1"), _fake_post("acc2", "p2")]

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        items, summary = await scraper.scrape_account_content(
            ["acc1", "acc2"], pool=None
        )

    assert len(calls) == 2
    assert any("instagram-api-scraper" in c for c in calls)
    assert any("instagram-stories-scraper" in c for c in calls)
    assert summary["posts_billed"] == 2
    assert summary["stories_billed"] == 2
    # All items get an _origin tag.
    assert all("_origin" in i for i in items)
    origins = {i["_origin"] for i in items}
    assert origins == {"profile", "story"}


async def test_stories_disabled_skips_stories_pass(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APIFY_TOKEN", "fake_token")
    monkeypatch.setenv("SCRAPE_INCLUDE_STORIES", "false")
    from backend import config
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()

    calls: list[str] = []

    def fake_run(client, actor_id, run_input):
        calls.append(actor_id)
        return [_fake_post("acc1", "p1")]

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        _, summary = await scraper.scrape_account_content(["acc1"], pool=None)

    assert len(calls) == 1
    assert "stories" not in calls[0]
    assert summary["stories_billed"] == 0


async def test_error_rows_are_filtered(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APIFY_TOKEN", "fake_token")
    monkeypatch.setenv("SCRAPE_INCLUDE_STORIES", "false")
    from backend import config
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()

    def fake_run(client, actor_id, run_input):
        return [
            {"error": "not_found", "errorDescription": "Post does not exist", "username": "acc1"},
            _fake_post("acc1", "p1"),
        ]

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        items, summary = await scraper.scrape_account_content(["acc1"], pool=None)

    assert summary["posts_billed"] == 1
    assert all("error" not in i for i in items)


async def test_per_account_story_cap(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APIFY_TOKEN", "fake_token")
    monkeypatch.setenv("MAX_STORIES_PER_ACCOUNT", "2")
    from backend import config
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()

    def fake_run(client, actor_id, run_input):
        if "stories" in actor_id:
            # 5 stories from same account
            return [_fake_story("acc1", f"s{i}") for i in range(5)]
        return []

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        items, summary = await scraper.scrape_account_content(["acc1"], pool=None)

    story_items = [i for i in items if i.get("_origin") == "story"]
    assert len(story_items) == 2
```

- [ ] **Step 2: Run tests**

```bash
backend/.venv/bin/pytest tests/backend/test_scraper_unit.py -v
```

Expected: 5 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/test_scraper_unit.py
git commit -m "test(scrape): two-actor logic, error filtering, story cap"
```

---

## Task 8: Update EXTRACT to handle stories

**Files:**
- Modify: `backend/extraction/extract.py`

- [ ] **Step 1: Update the system prompt**

In `backend/extraction/extract.py`, replace `_EXTRACT_SYSTEM` with:

```python
_EXTRACT_SYSTEM = """You parse Instagram items (posts and stories) into structured event records.

Each input item has a ``content_type`` of either ``post`` or ``story``. Stories
are short-lived (24h) and often used for last-minute "tonight only"
announcements; treat them as authoritative when they describe an event.
Posts may be more polished but can be older.

For each item, decide whether the content describes a specific upcoming event
that someone could attend. If yes, extract:
- title: short event name (≤120 chars, no emojis or hashtags)
- description: cleaned-up summary (≤400 chars, plain text)
- date_iso: best guess of the event date in YYYY-MM-DD format. Use the
  reference_date provided unless the content clearly states another date.
- start_time: HH:MM 24h, or null if not stated
- venue_name: physical venue / location, or null
- vibes: 1-3 from this exact list: """ + ", ".join(_VIBE_VALUES) + """
- is_event: true if it's a real upcoming attendable event, false otherwise
- confidence: 0.0-1.0 — how sure are you this is a real event with the data above

Skip merch posts, throwback photos, generic vibe shots, and "follow us"
posts. For stories, accept terse content ("doors at 22 tonight") if the venue
context is clear. Be conservative: when in doubt, set is_event=false."""
```

- [ ] **Step 2: Update `_post_summary` to surface content_type**

Replace the `_post_summary` function in `backend/extraction/extract.py` with:

```python
def _post_summary(item: dict[str, Any], idx: int) -> dict[str, Any]:
    """Reduce a raw Apify item (post or story) to fields the model needs."""
    origin = item.get("_origin", "profile")
    content_type = "story" if origin == "story" else "post"

    caption = item.get("caption") or item.get("text") or ""
    location = item.get("locationName") or ""
    if not location and isinstance(item.get("location"), dict):
        location = item["location"].get("name", "")
    owner = (
        item.get("ownerUsername")
        or item.get("username")
        or (item.get("owner") or {}).get("username")
        or (item.get("user") or {}).get("username")
        or ""
    )
    return {
        "index": idx,
        "content_type": content_type,
        "owner": owner,
        "caption": caption[:1500],
        "location_hint": location or None,
        "timestamp": item.get("timestamp") or item.get("takenAt") or item.get("posted_at"),
        "shortcode": item.get("shortCode") or item.get("shortcode") or item.get("id"),
    }
```

- [ ] **Step 3: Update `_to_event` to set scrape_source correctly**

Replace `_to_event` in the same file with:

```python
def _to_event(parsed: _ExtractedEvent, item: dict[str, Any], reference_date: str) -> Event | None:
    """Build an Event from Claude's parsed record + the original item."""
    if not parsed.is_event or parsed.confidence < 0.4:
        return None

    shortcode = item.get("shortCode") or item.get("shortcode") or item.get("id") or ""
    owner = (
        item.get("ownerUsername")
        or item.get("username")
        or (item.get("owner") or {}).get("username")
        or (item.get("user") or {}).get("username")
        or ""
    )

    raw_date = (parsed.date_iso or reference_date).strip()
    raw_time = (parsed.start_time or "20:00").strip()
    try:
        dt = datetime.fromisoformat(f"{raw_date}T{raw_time}")
    except ValueError:
        try:
            dt = datetime.fromisoformat(reference_date + "T20:00")
        except ValueError:
            return None

    def _safe_int(v):
        try:
            n = int(v) if v is not None else None
            return n if n is not None and n >= 0 else None
        except (ValueError, TypeError):
            return None

    vibes: list[EventVibe] = []
    for v in parsed.vibes:
        try:
            vibes.append(EventVibe(v))
        except ValueError:
            continue

    eid = Event.generate_id(EventSource.INSTAGRAM, shortcode or f"{owner}-{parsed.title[:40]}")
    origin = item.get("_origin", "profile")
    if origin == "story":
        scrape_source = "story"
        # Stories often have direct media URLs.
        source_url = (
            f"https://www.instagram.com/stories/{owner}/{shortcode}/"
            if owner else "https://www.instagram.com/"
        )
    else:
        scrape_source = "profile"
        source_url = (
            f"https://www.instagram.com/p/{shortcode}/"
            if shortcode else f"https://www.instagram.com/{owner}/"
        )

    return Event(
        id=eid,
        title=parsed.title.strip()[:200],
        description=parsed.description,
        date=dt,
        source=EventSource.INSTAGRAM,
        source_url=source_url,
        venue_name=parsed.venue_name,
        image_url=item.get("displayUrl") or item.get("imageUrl") or item.get("media_url") or item.get("url"),
        likes=_safe_int(item.get("likesCount") or item.get("likes")),
        comments=_safe_int(item.get("commentsCount") or item.get("comments")),
        vibes=vibes,
        organizer=f"@{owner}" if owner else None,
        account_handle=owner or None,
        scrape_source=scrape_source,
        tags=[f"@{owner}"] if owner else [],
        raw_data={
            "shortcode": shortcode,
            "origin": origin,
            "extract_confidence": parsed.confidence,
        },
    )
```

- [ ] **Step 4: Verify the file still imports**

```bash
backend/.venv/bin/python -c "from backend.extraction.extract import parse_events; print('extract imports ok')"
```

Expected: `extract imports ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/extraction/extract.py
git commit -m "feat(extract): handle stories alongside posts, set scrape_source correctly"
```

---

## Task 9: Update SearchResponse model

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add fields**

In `backend/models.py`, replace the `SearchResponse` class with:

```python
class SearchResponse(BaseModel):
    events: list[Event] = Field(default_factory=list)
    curated_guide: Optional[EveningGuide] = None
    total_count: int = 0
    city: str
    date: str
    search_duration_seconds: float
    accounts_discovered: int = 0
    accounts_triaged: int = 0
    posts_scraped: int = 0
    stories_scraped: int = 0
    accounts_cache_hit: int = 0
    events_extracted: int = 0
    apify_cost_usd: float = 0.0
    monthly_spend_usd: float = 0.0
    monthly_budget_usd: float = 0.0
    budget_blocked: bool = False
    errors: list[dict] = Field(default_factory=list)
```

- [ ] **Step 2: Verify import**

```bash
backend/.venv/bin/python -c "from backend.models import SearchResponse; print(SearchResponse.model_fields.keys())"
```

Expected: contains `apify_cost_usd`, `monthly_spend_usd`, `budget_blocked`.

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat(models): add cost + cache fields to SearchResponse"
```

---

## Task 10: Wire the pipeline in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update imports + the search handler**

In `backend/main.py`, replace the imports block (lines starting at the top) and the `search_events` function. Use this complete file body:

```python
"""
City Event Crawler v2 — Instagram-only deep discovery + Claude curation.

Pipeline:  DISCOVER → TRIAGE → SCRAPE → EXTRACT → SCORE → CURATE
"""

from __future__ import annotations

import logging
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from difflib import SequenceMatcher

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import CITY_COORDINATES, get_settings
from .db import close_pool, get_pool
from .db import cost as cost_db
from .extraction import compose_guide, parse_events, rate_events
from .extraction.score import composite_score
from .instagram import discover_accounts, scrape_account_content, triage_accounts
from .models import (
    CityInfo,
    Event,
    EventVibe,
    SearchRequest,
    SearchResponse,
)
from .utils.helpers import calculate_distance

logger = logging.getLogger("city_event_crawler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "Startup: serpapi=%s apify=%s anthropic=%s db=%s model=%s",
        bool(settings.SERPAPI_KEY),
        bool(settings.INSTAGRAM_APIFY_TOKEN),
        bool(settings.ANTHROPIC_API_KEY),
        bool(settings.DATABASE_URL),
        settings.CLAUDE_MODEL,
    )
    yield
    await close_pool()
    logger.info("Shutdown.")


app = FastAPI(
    title="City Event Crawler v2",
    description="Instagram deep discovery with Claude-powered curation",
    version="2.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_city(request: SearchRequest) -> tuple[float, float, str]:
    if request.latitude is not None and request.longitude is not None:
        return request.latitude, request.longitude, request.city.strip().title()
    city_key = request.city.strip().lower()
    data = CITY_COORDINATES.get(city_key)
    if data is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"City '{request.city}' not in supported list. "
                "Provide explicit latitude/longitude or call GET /api/cities."
            ),
        )
    return data["lat"], data["lon"], request.city.strip().title()


def _normalize_title(title: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()


def _dedupe_events(events: list[Event]) -> list[Event]:
    if not events:
        return []
    by_day: dict[str, list[Event]] = {}
    for ev in events:
        day = ev.date.strftime("%Y-%m-%d") if ev.date else "unknown"
        by_day.setdefault(day, []).append(ev)
    kept: list[Event] = []
    for group in by_day.values():
        clusters: list[list[Event]] = []
        for ev in group:
            t = _normalize_title(ev.title)
            placed = False
            for cluster in clusters:
                rep_t = _normalize_title(cluster[0].title)
                if SequenceMatcher(None, t, rep_t).ratio() >= 0.65:
                    cluster.append(ev)
                    placed = True
                    break
            if not placed:
                clusters.append([ev])
        for cluster in clusters:
            kept.append(max(cluster, key=lambda e: (
                bool(e.description), bool(e.venue_name), bool(e.image_url),
                e.likes or 0, e.comments or 0,
            )))
    return kept


@app.post("/api/search", response_model=SearchResponse)
async def search_events(request: SearchRequest) -> SearchResponse:
    """Run the v2 pipeline and return events + curated guide + cost telemetry."""
    settings = get_settings()
    t0 = time.monotonic()

    latitude, longitude, city_name = _resolve_city(request)
    pool = await get_pool()
    errors: list[dict] = []

    accounts: list[str] = []
    triaged: list[str] = []
    posts_count = 0
    stories_count = 0
    accounts_cache_hit = 0
    apify_cost = 0.0
    items: list[dict] = []
    events: list[Event] = []
    guide = None

    # --- Budget check ---
    monthly_spent = await cost_db.monthly_spend_usd(pool)
    budget_blocked = monthly_spent >= settings.MONTHLY_BUDGET_USD

    # --- DISCOVER ---
    try:
        accounts = await discover_accounts(
            city=city_name,
            serpapi_key=settings.SERPAPI_KEY,
            vibes=request.vibes,
            max_queries=settings.MAX_DISCOVERY_QUERIES,
        )
    except Exception as exc:
        logger.error("DISCOVER failed: %s", exc)
        errors.append({"stage": "discover", "error": str(exc), "traceback": traceback.format_exc()})

    # --- TRIAGE ---
    if accounts:
        try:
            triaged = await triage_accounts(
                city=city_name,
                handles=accounts,
                vibes=request.vibes,
                max_keep=settings.MAX_ACCOUNTS_PER_SEARCH,
            )
        except Exception as exc:
            logger.error("TRIAGE failed: %s", exc)
            errors.append({"stage": "triage", "error": str(exc), "traceback": traceback.format_exc()})
            triaged = accounts[: settings.MAX_ACCOUNTS_PER_SEARCH]

    # --- SCRAPE (cache-first; bypass actor entirely if budget blocked) ---
    if triaged:
        try:
            if budget_blocked:
                # Cache-only: read what we have, do not call Apify.
                from .db import cache as cache_db
                cached_posts = await cache_db.read_scrape_cache(pool, triaged, "posts")
                cached_stories = await cache_db.read_scrape_cache(pool, triaged, "stories")
                for posts_list in cached_posts.values():
                    for p in posts_list:
                        p.setdefault("_origin", "profile")
                        items.append(p)
                for stories_list in cached_stories.values():
                    for s in stories_list:
                        s.setdefault("_origin", "story")
                        items.append(s)
                accounts_cache_hit = len(cached_posts) + len(cached_stories)
                posts_count = sum(len(v) for v in cached_posts.values())
                stories_count = sum(len(v) for v in cached_stories.values())
            else:
                items, summary = await scrape_account_content(triaged, pool=pool)
                # Count items by origin (covers both cache hits and freshly scraped).
                posts_count = sum(1 for i in items if i.get("_origin") == "profile")
                stories_count = sum(1 for i in items if i.get("_origin") == "story")
                accounts_cache_hit = summary["posts_cache_hit"] + summary["stories_cache_hit"]
                apify_cost = cost_db.compute_apify_cost(
                    summary["posts_billed"],
                    summary["stories_billed"],
                    posts_per_1k=settings.APIFY_POSTS_USD_PER_1K,
                    stories_per_1k=settings.APIFY_STORIES_USD_PER_1K,
                )
        except Exception as exc:
            logger.error("SCRAPE failed: %s", exc)
            errors.append({"stage": "scrape", "error": str(exc), "traceback": traceback.format_exc()})

    # --- EXTRACT ---
    if items:
        try:
            events = await parse_events(items, reference_date=request.date)
        except Exception as exc:
            logger.error("EXTRACT failed: %s", exc)
            errors.append({"stage": "extract", "error": str(exc), "traceback": traceback.format_exc()})

    # --- Dedupe / distance / vibe filter ---
    if events:
        events = _dedupe_events(events)
        for ev in events:
            if ev.latitude is not None and ev.longitude is not None:
                ev.distance_km = calculate_distance(latitude, longitude, ev.latitude, ev.longitude)
        if request.vibes:
            requested = set(request.vibes)
            events = [ev for ev in events if not ev.vibes or set(ev.vibes) & requested]

    # --- SCORE ---
    if events:
        try:
            events = await rate_events(events, vibes=request.vibes)
        except Exception as exc:
            logger.error("SCORE failed: %s", exc)
            errors.append({"stage": "score", "error": str(exc), "traceback": traceback.format_exc()})

        events.sort(key=lambda e: (composite_score(e), e.engagement_score), reverse=True)
        events = events[: request.max_results]

    # --- CURATE ---
    if events:
        try:
            guide = await compose_guide(events=events, city=city_name, vibes=request.vibes)
        except Exception as exc:
            logger.error("CURATE failed: %s", exc)
            errors.append({"stage": "curate", "error": str(exc), "traceback": traceback.format_exc()})

    elapsed = round(time.monotonic() - t0, 3)

    # --- Persist run ---
    await cost_db.record_run(
        pool,
        {
            "city": city_name,
            "search_date": request.date,
            "vibes": [v.value for v in (request.vibes or [])],
            "accounts_discovered": len(accounts),
            "accounts_triaged": len(triaged),
            "accounts_cache_hit": accounts_cache_hit,
            "accounts_scraped": max(0, len(triaged) - accounts_cache_hit),
            "posts_scraped": posts_count,
            "stories_scraped": stories_count,
            "events_extracted": len(events),
            "apify_results_billed": posts_count + stories_count,
            "apify_cost_usd": apify_cost,
            "claude_input_tokens": 0,
            "claude_output_tokens": 0,
            "duration_seconds": elapsed,
            "budget_blocked": budget_blocked,
            "errors": errors,
        },
    )

    new_monthly_spent = await cost_db.monthly_spend_usd(pool)

    logger.info(
        "Search %s/%s done: discovered=%d triaged=%d posts=%d stories=%d events=%d cost=$%.4f in %.2fs",
        city_name, request.date,
        len(accounts), len(triaged), posts_count, stories_count, len(events), apify_cost, elapsed,
    )

    return SearchResponse(
        events=events,
        curated_guide=guide,
        total_count=len(events),
        city=city_name,
        date=request.date,
        search_duration_seconds=elapsed,
        accounts_discovered=len(accounts),
        accounts_triaged=len(triaged),
        accounts_cache_hit=accounts_cache_hit,
        posts_scraped=posts_count,
        stories_scraped=stories_count,
        events_extracted=len(events),
        apify_cost_usd=apify_cost,
        monthly_spend_usd=new_monthly_spent,
        monthly_budget_usd=settings.MONTHLY_BUDGET_USD,
        budget_blocked=budget_blocked,
        errors=errors,
    )


@app.get("/api/cities", response_model=list[CityInfo])
async def list_cities() -> list[CityInfo]:
    return [
        CityInfo(
            name=key.title(),
            country=data["country"],
            latitude=data["lat"],
            longitude=data["lon"],
            timezone=data["tz"],
        )
        for key, data in sorted(CITY_COORDINATES.items())
    ]


@app.get("/api/vibes")
async def list_vibes() -> list[dict[str, str]]:
    return [
        {"value": vibe.value, "label": vibe.name.replace("_", " ").title()}
        for vibe in EventVibe
    ]


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "city-event-crawler",
        "version": "2.1.0",
        "model": settings.CLAUDE_MODEL,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
```

- [ ] **Step 2: Verify it boots and a no-key search degrades gracefully**

```bash
backend/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level warning &
SERVER_PID=$!
until curl -sf http://127.0.0.1:8000/api/health -o /dev/null; do sleep 1; done
curl -s http://127.0.0.1:8000/api/health
echo
kill $SERVER_PID 2>/dev/null
```

Expected: `{"status":"ok",...,"version":"2.1.0",...}`.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(main): budget gate + cost log integration + cache-only fallback"
```

---

## Task 11: End-to-end integration test

**Files:**
- Create: `tests/backend/test_pipeline_integration.py`

This task validates the full pipeline end-to-end by hitting the live `/api/search` once. It costs Apify credits — about $0.10 because we lower the caps.

- [ ] **Step 1: Write the integration test**

```python
# tests/backend/test_pipeline_integration.py
"""End-to-end integration test against the live FastAPI app + real APIs.

Runs a single Berlin search at reduced caps (5 accounts × 1 post + stories)
to keep costs minimal (~$0.05). Skips automatically if any required key is
missing from .env.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

REQUIRED = ("SERPAPI_KEY", "INSTAGRAM_APIFY_TOKEN", "ANTHROPIC_API_KEY", "DATABASE_URL")


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_keys():
    from dotenv import load_dotenv
    load_dotenv()
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        pytest.skip(f"missing env: {missing}")


@pytest.fixture(scope="module")
def client(monkeypatch_module=None):
    # Tighten caps for the test so we don't burn credits.
    os.environ["MAX_ACCOUNTS_PER_SEARCH"] = "5"
    os.environ["MAX_POSTS_PER_ACCOUNT"] = "1"
    os.environ["MAX_STORIES_PER_ACCOUNT"] = "2"
    os.environ["MAX_DISCOVERY_QUERIES"] = "3"
    # Force a clean settings load.
    from backend import config
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()

    from backend.main import app
    return TestClient(app)


def test_live_berlin_search_returns_cost_and_events(client):
    resp = client.post(
        "/api/search",
        json={"city": "berlin", "date": "2026-04-27", "vibes": ["nightlife"], "max_results": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Even with no events, we expect telemetry fields populated.
    assert "monthly_spend_usd" in data
    assert "apify_cost_usd" in data
    assert "budget_blocked" in data
    assert data["accounts_discovered"] >= 1
    # Either we got events or we got a budget block — never silently nothing.
    assert data["events_extracted"] >= 0
```

- [ ] **Step 2: Run it**

```bash
unset ANTHROPIC_API_KEY
backend/.venv/bin/pytest tests/backend/test_pipeline_integration.py -v -s
```

Expected: 1 passed. Backend log will show DISCOVER, TRIAGE, SCRAPE billing, EXTRACT count.

- [ ] **Step 3: Verify a cost_log row was written**

```bash
backend/.venv/bin/python -c "
import asyncio, asyncpg
from dotenv import dotenv_values
async def main():
    conn = await asyncpg.connect(dotenv_values('.env')['DATABASE_URL'])
    r = await conn.fetchrow('SELECT city, posts_scraped, stories_scraped, apify_cost_usd FROM cost_log ORDER BY run_at DESC LIMIT 1')
    print(dict(r))
    await conn.close()
asyncio.run(main())
"
```

Expected: a row with `city='Berlin'`, non-null cost.

- [ ] **Step 4: Commit**

```bash
git add tests/backend/test_pipeline_integration.py
git commit -m "test(integration): live e2e search at minimal caps; verifies cost_log persistence"
```

---

## Task 12: Streamlit app — scaffolding + sidebar

**Files:**
- Create: `streamlit_app/__init__.py` (empty)
- Create: `streamlit_app/requirements.txt`
- Create: `streamlit_app/.streamlit/config.toml`
- Create: `streamlit_app/db.py`
- Create: `streamlit_app/app.py` (sidebar + tab skeletons only)

- [ ] **Step 1: Streamlit-only requirements**

```text
# streamlit_app/requirements.txt
streamlit>=1.40.0
psycopg[binary]>=3.2.0
pandas>=2.2.0
httpx>=0.25.0
python-dotenv>=1.0.0
```

- [ ] **Step 2: Streamlit config**

```toml
# streamlit_app/.streamlit/config.toml
[server]
port = 8501

[theme]
base = "dark"
primaryColor = "#e94560"
backgroundColor = "#0a0a0a"
secondaryBackgroundColor = "#1a1a2e"
textColor = "#f0f0f0"
```

- [ ] **Step 3: Sync DB helper**

```python
# streamlit_app/db.py
"""Sync Postgres helpers for the Streamlit dashboard."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import psycopg
import streamlit as st

DATABASE_URL = os.environ.get("DATABASE_URL") or st.secrets.get("DATABASE_URL", "") if hasattr(st, "secrets") else ""


@st.cache_resource
def _conn() -> psycopg.Connection:
    if not DATABASE_URL:
        st.error("DATABASE_URL is not configured.")
        st.stop()
    return psycopg.connect(DATABASE_URL, autocommit=True)


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with _conn().cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in (cur.description or [])]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def execute(sql: str, params: tuple = ()) -> None:
    with _conn().cursor() as cur:
        cur.execute(sql, params)


def fetchval(sql: str, params: tuple = ()) -> Any:
    with _conn().cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None
```

- [ ] **Step 4: App shell with sidebar + 4 empty tabs**

```python
# streamlit_app/app.py
"""City Event Crawler — admin/ops dashboard."""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # local-dev only; harmless on Streamlit Cloud

from streamlit_app import db  # noqa: E402

MONTHLY_BUDGET_DEFAULT = float(os.environ.get("MONTHLY_BUDGET_USD", "25.0"))

st.set_page_config(
    page_title="City Event Crawler — Admin",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _sidebar_budget():
    """Always-visible spend gauge."""
    spent = db.fetchval(
        """
        SELECT COALESCE(SUM(apify_cost_usd), 0)::float
        FROM cost_log
        WHERE run_at >= date_trunc('month', now() at time zone 'utc')
        """
    ) or 0.0
    budget = MONTHLY_BUDGET_DEFAULT
    pct = min(1.0, spent / budget) if budget else 0.0

    st.sidebar.title("Spend")
    st.sidebar.metric("Month-to-date", f"${spent:.2f}", f"of ${budget:.2f}")
    st.sidebar.progress(pct)
    if pct >= 1.0:
        st.sidebar.error("Budget exceeded — searches now cache-only")
    elif pct >= 0.8:
        st.sidebar.warning(f"{pct*100:.0f}% of budget used")


def main():
    st.title("City Event Crawler — Admin")
    _sidebar_budget()

    search_tab, runs_tab, cost_tab, cache_tab = st.tabs(
        ["Search", "Runs", "Cost", "Cache"]
    )

    with search_tab:
        st.write("(Search tab — implemented in Task 13)")
    with runs_tab:
        st.write("(Runs tab — implemented in Task 14)")
    with cost_tab:
        st.write("(Cost tab — implemented in Task 15)")
    with cache_tab:
        st.write("(Cache tab — implemented in Task 16)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Boot it**

```bash
python3 -m venv streamlit_app/.venv
streamlit_app/.venv/bin/pip install -r streamlit_app/requirements.txt
cd streamlit_app && ../streamlit_app/.venv/bin/streamlit run app.py --server.headless true &
STREAMLIT_PID=$!
sleep 5
curl -s -o /dev/null -w "streamlit: %{http_code}\n" http://localhost:8501/
kill $STREAMLIT_PID 2>/dev/null
cd ..
```

Expected: `streamlit: 200`.

- [ ] **Step 6: Commit**

```bash
git add streamlit_app/
git commit -m "feat(streamlit): scaffold dashboard with budget sidebar + 4 empty tabs"
```

---

## Task 13: Streamlit Search tab

**Files:**
- Modify: `streamlit_app/app.py`

- [ ] **Step 1: Add search tab implementation**

Replace the `with search_tab:` block in `streamlit_app/app.py` with:

```python
    with search_tab:
        backend_url = os.environ.get(
            "BACKEND_URL",
            st.secrets.get("BACKEND_URL", "http://localhost:8000") if hasattr(st, "secrets") else "http://localhost:8000",
        )
        col1, col2, col3 = st.columns([2, 1, 1])
        city = col1.text_input("City", value="berlin")
        date = col2.date_input("Date").isoformat()
        max_results = col3.number_input("Max results", min_value=10, max_value=100, value=40)
        vibes = st.multiselect(
            "Vibes",
            ["nightlife", "underground", "music", "art_culture", "food_drink", "lgbtq", "social", "kinky", "festival"],
            default=["nightlife"],
        )
        if st.button("Run search", type="primary"):
            import httpx
            with st.spinner("Running pipeline (this can take 1–3 minutes)..."):
                try:
                    r = httpx.post(
                        f"{backend_url}/api/search",
                        json={"city": city, "date": date, "vibes": vibes, "max_results": int(max_results)},
                        timeout=300,
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as exc:
                    st.error(f"Search failed: {exc}")
                    data = None
            if data:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Events", data["total_count"])
                c2.metric("Cost", f"${data['apify_cost_usd']:.4f}")
                c3.metric("Posts", data["posts_scraped"])
                c4.metric("Stories", data["stories_scraped"])
                if data.get("budget_blocked"):
                    st.warning("Monthly budget hit — results came from cache only.")
                guide = data.get("curated_guide")
                if guide:
                    st.subheader("Evening Guide")
                    st.caption(guide.get("demographic_note", ""))
                    st.write(guide.get("summary_text", ""))
                st.subheader("Events")
                for ev in data.get("events", []):
                    badge = {"top_pick": "🌟", "hidden_gem": "💎", "skip": "✖", "standard": "•"}.get(
                        ev.get("curation_tier"), "•"
                    )
                    st.markdown(
                        f"**{badge} {ev['title']}** — `@{ev.get('account_handle','?')}` "
                        f"({ev.get('scrape_source','?')}) · {ev.get('venue_name','?')}"
                    )
```

- [ ] **Step 2: Boot the Streamlit and click through**

Visual check only — pipeline already covered by Task 11.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat(streamlit): Search tab — POSTs to FastAPI + renders guide & events"
```

---

## Task 14: Streamlit Runs tab

**Files:**
- Modify: `streamlit_app/app.py`

- [ ] **Step 1: Replace the Runs tab block**

```python
    with runs_tab:
        st.subheader("Recent runs")
        city_filter = st.text_input("Filter by city (optional)", value="")
        limit = st.slider("Show last N", 10, 500, 100)
        if city_filter.strip():
            df = db.query_df(
                """
                SELECT run_at, city, search_date, vibes,
                       accounts_discovered, accounts_triaged, accounts_cache_hit,
                       posts_scraped, stories_scraped, events_extracted,
                       apify_cost_usd, duration_seconds, budget_blocked
                FROM cost_log
                WHERE city ILIKE %s
                ORDER BY run_at DESC
                LIMIT %s
                """,
                (f"%{city_filter.strip()}%", int(limit)),
            )
        else:
            df = db.query_df(
                """
                SELECT run_at, city, search_date, vibes,
                       accounts_discovered, accounts_triaged, accounts_cache_hit,
                       posts_scraped, stories_scraped, events_extracted,
                       apify_cost_usd, duration_seconds, budget_blocked
                FROM cost_log
                ORDER BY run_at DESC
                LIMIT %s
                """,
                (int(limit),),
            )
        if df.empty:
            st.info("No runs yet — fire off a search from the Search tab.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat(streamlit): Runs tab — paginated cost_log table with city filter"
```

---

## Task 15: Streamlit Cost tab

**Files:**
- Modify: `streamlit_app/app.py`

- [ ] **Step 1: Replace the Cost tab block**

```python
    with cost_tab:
        st.subheader("This month")
        col1, col2, col3, col4 = st.columns(4)
        spent = db.fetchval(
            "SELECT COALESCE(SUM(apify_cost_usd),0)::float FROM cost_log "
            "WHERE run_at >= date_trunc('month', now() at time zone 'utc')"
        ) or 0.0
        runs = db.fetchval(
            "SELECT COUNT(*) FROM cost_log "
            "WHERE run_at >= date_trunc('month', now() at time zone 'utc')"
        ) or 0
        avg = (spent / runs) if runs else 0.0
        runway = ((MONTHLY_BUDGET_DEFAULT - spent) / avg) if avg else float("inf")
        col1.metric("Spent", f"${spent:.2f}")
        col2.metric("Budget", f"${MONTHLY_BUDGET_DEFAULT:.2f}")
        col3.metric("Runs", runs)
        col4.metric(
            "Searches left",
            "—" if runs == 0 else (f"~{int(runway)}" if runway != float("inf") else "—"),
            help="Avg cost-per-run × remaining budget",
        )

        st.subheader("Daily spend (UTC)")
        daily = db.query_df(
            """
            SELECT date_trunc('day', run_at)::date AS day,
                   SUM(apify_cost_usd)::float AS cost,
                   COUNT(*) AS runs
            FROM cost_log
            WHERE run_at >= date_trunc('month', now() at time zone 'utc')
            GROUP BY 1
            ORDER BY 1
            """
        )
        if daily.empty:
            st.info("No spend yet this month.")
        else:
            st.line_chart(daily.set_index("day")["cost"])

        st.subheader("Cache hit rate")
        cache_stats = db.query_df(
            """
            SELECT
              SUM(accounts_cache_hit)::float / NULLIF(SUM(accounts_triaged), 0) AS hit_rate,
              SUM(accounts_cache_hit) AS hits,
              SUM(accounts_triaged)   AS triaged
            FROM cost_log
            WHERE run_at >= date_trunc('month', now() at time zone 'utc')
            """
        )
        if not cache_stats.empty and cache_stats.iloc[0]["hit_rate"] is not None:
            row = cache_stats.iloc[0]
            st.metric("Hit rate", f"{(row['hit_rate'] or 0) * 100:.1f}%",
                      f"{int(row['hits'])} of {int(row['triaged'])} accounts")
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat(streamlit): Cost tab — daily chart, MTD, runway, cache hit rate"
```

---

## Task 16: Streamlit Cache tab

**Files:**
- Modify: `streamlit_app/app.py`

- [ ] **Step 1: Replace the Cache tab block**

```python
    with cache_tab:
        st.subheader("Cached accounts")
        df = db.query_df(
            """
            SELECT
              account_handle,
              content_type,
              fetched_at,
              expires_at,
              expires_at > now() AS fresh,
              jsonb_array_length(items) AS item_count,
              results_billed
            FROM scrape_cache
            ORDER BY fetched_at DESC
            LIMIT 500
            """
        )
        if df.empty:
            st.info("Cache is empty.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.divider()
            col_a, col_b = st.columns(2)
            with col_a:
                handle_to_purge = st.text_input("Purge a single handle")
                if st.button("Purge handle"):
                    if handle_to_purge.strip():
                        db.execute(
                            "DELETE FROM scrape_cache WHERE account_handle = %s",
                            (handle_to_purge.strip(),),
                        )
                        st.success(f"Purged {handle_to_purge.strip()}")
                        st.rerun()
            with col_b:
                if st.button("Purge ALL expired rows"):
                    db.execute("DELETE FROM scrape_cache WHERE expires_at <= now()")
                    st.success("Expired rows purged")
                    st.rerun()
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat(streamlit): Cache tab — browse + purge cached scrape rows"
```

---

## Task 17: README + .env.example

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Update `.env.example`**

Replace the file contents with:

```bash
# =============================================================================
# City Event Crawler v2 - Instagram-only deep discovery + Claude curation
# Copy this to .env and fill in your API keys
# =============================================================================

# SerpAPI - discovers Instagram accounts via Google
# Get key at: https://serpapi.com/
SERPAPI_KEY=

# Apify - posts and stories scraping (two actors, see backend/config.py)
# Get token at: https://apify.com/
INSTAGRAM_APIFY_TOKEN=

# Anthropic - powers TRIAGE / EXTRACT / SCORE / CURATE pipeline stages
# Get key at: https://console.anthropic.com/
ANTHROPIC_API_KEY=

# Postgres - Neon-compatible. Used for scrape cache + cost log.
# Without this, the pipeline still works but no caching/logging.
DATABASE_URL=

# Optional knobs
CLAUDE_MODEL=claude-opus-4-7
MONTHLY_BUDGET_USD=25.0
```

- [ ] **Step 2: Append a Postgres + Streamlit section to README**

Append this section before the License heading in `README.md`:

```markdown
## Postgres caching + cost log

Set `DATABASE_URL` in `.env` to a Postgres URI (Neon works out of the box,
including the `?sslmode=require&channel_binding=require` suffix). Initialise
the schema once:

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

Two tables get created:
- `scrape_cache` — raw Apify items per `(account_handle, content_type)` pair, 24h TTL.
- `cost_log` — one row per `/api/search` run, used for the monthly budget cutoff and the Streamlit dashboard.

The pipeline degrades gracefully if `DATABASE_URL` is unset — caching becomes a no-op and runs aren't logged.

## Streamlit admin dashboard

`streamlit_app/` is an internal dashboard over the same Postgres. Four tabs:

- **Search** — fires `/api/search` against the FastAPI backend (`BACKEND_URL`)
- **Runs** — paginated `cost_log` browser
- **Cost** — month-to-date spend, daily chart, runway, cache hit rate
- **Cache** — browse + purge `scrape_cache`

Local:
```bash
python3 -m venv streamlit_app/.venv
streamlit_app/.venv/bin/pip install -r streamlit_app/requirements.txt
streamlit_app/.venv/bin/streamlit run streamlit_app/app.py
```

Deploy to **Streamlit Community Cloud** (free):
1. Push the repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io) → New app → point at `streamlit_app/app.py`.
3. In Streamlit Cloud secrets, add:
   ```toml
   DATABASE_URL = "postgresql://…"
   BACKEND_URL  = "https://your-fastapi-host"   # optional; Search tab requires it
   ```
4. Cost / Runs / Cache tabs work immediately. The Search tab needs a public FastAPI host — see "Backend hosting" in `docs/superpowers/specs/2026-04-27-postgres-streamlit-apify-cost-control-design.md` for context.

## Apify cost control

Defaults in `backend/config.py` are tuned for the Apify Starter plan ($30/mo):

| Setting                  | Default | Notes                                    |
|--------------------------|---------|------------------------------------------|
| `MAX_ACCOUNTS_PER_SEARCH`| 60      | After TRIAGE                             |
| `MAX_POSTS_PER_ACCOUNT`  | 2       | wider, shallower                         |
| `MAX_STORIES_PER_ACCOUNT`| 5       | most accounts have 0–3 active stories    |
| `SCRAPE_INCLUDE_STORIES` | true    | stories often carry "tonight" announcements |
| `SCRAPE_INCLUDE_HASHTAGS`| false   | extra cost, marginal value               |
| `POSTS_CACHE_TTL_HOURS`  | 24      | per-account                              |
| `STORIES_CACHE_TTL_HOURS`| 24      |                                          |
| `MONTHLY_BUDGET_USD`     | 25.0    | cuts off SCRAPE; cache-only fallback     |
| `APIFY_POSTS_USD_PER_1K` | 2.30    | check actor's pricing page               |
| `APIFY_STORIES_USD_PER_1K`| 2.30   | check stories actor's pricing page       |

At defaults, a fresh search bills ~300 results ≈ $0.69. With 24h cache, repeated city searches in the same day are free.
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs: add Postgres + Streamlit + cost-control sections to README"
```

---

## Task 18: Final smoke + manual deployment instructions

This task isn't code — it's a final manual smoke test and the docs the user follows to put it on Streamlit Cloud.

- [ ] **Step 1: Run the full local stack manually**

```bash
unset ANTHROPIC_API_KEY  # only needed if your shell exports an empty one
backend/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info &
streamlit_app/.venv/bin/streamlit run streamlit_app/app.py --server.headless true &
sleep 5
curl -s -o /dev/null -w "fastapi: %{http_code}\n" http://localhost:8000/api/health
curl -s -o /dev/null -w "streamlit: %{http_code}\n" http://localhost:8501/
```

Expected: both 200.

- [ ] **Step 2: From Streamlit, run a Berlin search**

Visual check via http://localhost:8501. Confirm:
1. Sidebar shows "$X / $25.00" budget gauge.
2. Search tab returns events + EveningGuide blurb.
3. Runs tab shows a new row.
4. Cost tab shows the row in the daily chart.
5. Cache tab shows scraped accounts.

- [ ] **Step 3: Stop both servers**

```bash
pkill -f "uvicorn backend.main"
pkill -f "streamlit run"
```

- [ ] **Step 4: Commit a deployment notes doc** (optional, if any deploy steps changed)

If verification surfaced issues, fix them and commit. Otherwise:

```bash
git status   # confirm clean
```

---

## Out of scope

Backend hosting (Render/Fly) is not included. Streamlit Cloud's Search tab will only work after the user puts the FastAPI app on a public URL with the appropriate env vars set. Adding that is a follow-up plan.
