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
# override=True forces .env values to win over an empty shell ANTHROPIC_API_KEY etc.
load_dotenv(REPO_ROOT / ".env", override=True)


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
