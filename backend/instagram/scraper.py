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
    for posts in cached.values():
        for p in posts:
            p.setdefault("_origin", "profile")
        items.extend(posts)

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
    for stories in cached.values():
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
