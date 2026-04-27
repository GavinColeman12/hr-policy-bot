"""Cost log writer + monthly spend reader."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
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


def _coerce_date(value: Any) -> date | None:
    """Accept str or date; return a date object."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    raise TypeError(f"Unsupported search_date type: {type(value)}")


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
            _coerce_date(run.get("search_date")),
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
