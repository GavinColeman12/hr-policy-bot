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
