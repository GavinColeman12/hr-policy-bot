"""Tests for backend.db.cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.db import cache


async def test_write_then_read_returns_items(pg_pool, clean_tables):
    items = [{"shortCode": "abc", "caption": "hello"}]
    await cache.write_scrape_cache(
        pg_pool, "berghain.official", "posts", items, results_billed=1, ttl_hours=24
    )
    got = await cache.read_scrape_cache(pg_pool, ["berghain.official"], "posts")
    assert got == {"berghain.official": items}


async def test_read_skips_expired_rows(pg_pool, clean_tables):
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
