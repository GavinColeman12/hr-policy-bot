"""Tests for backend.db.cost."""

from __future__ import annotations

import pytest

from backend.db import cost


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
    posts = 120
    stories = 180
    cost_usd = cost.compute_apify_cost(posts, stories, posts_per_1k=2.30, stories_per_1k=2.30)
    assert cost_usd == pytest.approx((120 + 180) * 2.30 / 1000, abs=0.0001)


def test_apify_cost_with_different_actor_pricing():
    cost_usd = cost.compute_apify_cost(100, 100, posts_per_1k=2.30, stories_per_1k=4.00)
    expected = (100 * 2.30 + 100 * 4.00) / 1000
    assert cost_usd == pytest.approx(expected, abs=0.0001)
