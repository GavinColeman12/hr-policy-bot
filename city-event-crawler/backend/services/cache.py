"""
In-memory cache for search results.

Uses ``cachetools.TTLCache`` to store search responses keyed by a
deterministic hash of the search parameters.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from cachetools import TTLCache

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _make_cache_key(
    city: str,
    date: str,
    vibes: Optional[list[str]] = None,
    platforms: Optional[list[str]] = None,
) -> str:
    """Build a deterministic cache key from search parameters."""
    normalised = {
        "city": city.lower().strip(),
        "date": date.strip(),
        "vibes": sorted(vibes) if vibes else [],
        "platforms": sorted(platforms) if platforms else [],
    }
    raw = json.dumps(normalised, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class SearchCache:
    """Simple TTL-based in-memory cache for event search results."""

    def __init__(self, maxsize: int = 256, ttl: Optional[int] = None) -> None:
        settings = get_settings()
        self._ttl = ttl or settings.CACHE_TTL_SECONDS
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=self._ttl)
        logger.info(
            "SearchCache initialised (maxsize=%d, ttl=%ds)", maxsize, self._ttl,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_cached_results(self, search_request: Any) -> Optional[dict]:
        """Look up cached results for *search_request*.

        Parameters
        ----------
        search_request:
            A ``SearchRequest`` pydantic model (or any object with
            ``.city``, ``.date``, ``.vibes`` attributes).

        Returns
        -------
        dict | None
            The cached response dict, or ``None`` on cache miss.
        """
        key = self._key_from_request(search_request)
        result = self._cache.get(key)
        if result is not None:
            logger.info("Cache HIT for key %s", key)
        else:
            logger.debug("Cache MISS for key %s", key)
        return result

    def cache_results(self, search_request: Any, response: dict) -> None:
        """Store *response* in the cache for *search_request*.

        Parameters
        ----------
        search_request:
            A ``SearchRequest`` pydantic model.
        response:
            The full API response dict to cache.
        """
        key = self._key_from_request(search_request)
        self._cache[key] = response
        logger.info("Cached results for key %s (ttl=%ds)", key, self._ttl)

    def invalidate(self, search_request: Any) -> None:
        """Remove a specific entry from the cache."""
        key = self._key_from_request(search_request)
        self._cache.pop(key, None)
        logger.info("Invalidated cache key %s", key)

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()
        logger.info("Cache cleared")

    @property
    def size(self) -> int:
        """Return the current number of cached entries."""
        return len(self._cache)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _key_from_request(self, search_request: Any) -> str:
        """Extract parameters from a SearchRequest and build a cache key."""
        city = getattr(search_request, "city", "")
        date = getattr(search_request, "date", "")

        vibes_raw = getattr(search_request, "vibes", None)
        vibes: Optional[list[str]] = None
        if vibes_raw:
            vibes = [
                v.value if hasattr(v, "value") else str(v) for v in vibes_raw
            ]

        platforms_raw = getattr(search_request, "platforms", None)
        platforms: Optional[list[str]] = None
        if platforms_raw:
            platforms = [
                p.value if hasattr(p, "value") else str(p) for p in platforms_raw
            ]

        return _make_cache_key(city, date, vibes, platforms)
