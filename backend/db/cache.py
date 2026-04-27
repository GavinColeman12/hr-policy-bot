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
