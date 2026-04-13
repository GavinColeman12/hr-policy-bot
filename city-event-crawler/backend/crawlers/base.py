"""
Abstract base class for all platform crawlers.

Provides shared functionality: HTTP session management, vibe classification,
rate limiting, and structured error logging.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from datetime import datetime
from types import TracebackType
from typing import Any, Optional

import httpx

from ..models import Event, EventSource, EventVibe
from ..utils.helpers import normalize_date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword-to-vibe mapping
# ---------------------------------------------------------------------------

VIBE_KEYWORDS: dict[EventVibe, list[str]] = {
    EventVibe.KINKY: [
        "kink", "fetish", "bdsm", "shibari", "rope", "dungeon", "play party",
        "munch", "leather", "latex", "dom", "sub", "switch", "polyamory",
        "poly", "swinger", "burlesque", "erotic", "sensual", "tantric",
        "adult party",
    ],
    EventVibe.DATING: [
        "speed dating", "singles", "mixer", "matchmaking", "dating",
        "meet singles", "blind date", "romance",
    ],
    EventVibe.NIGHTLIFE: [
        "club", "party", "dj", "rave", "techno", "house music", "dance floor",
        "nightclub", "afterparty", "after-party", "bass", "electronic",
        "disco", "warehouse party", "rooftop party", "bar crawl", "pub crawl",
    ],
    EventVibe.SOCIAL: [
        "meetup", "social", "hangout", "gathering", "brunch", "picnic",
        "board game", "trivia", "quiz night", "karaoke", "open mic",
        "language exchange", "expat", "international", "community",
    ],
    EventVibe.MUSIC: [
        "concert", "live music", "gig", "festival", "jazz", "rock", "indie",
        "acoustic", "orchestra", "symphony", "opera", "band", "singer",
        "dj set", "music",
    ],
    EventVibe.ART_CULTURE: [
        "exhibition", "gallery", "museum", "art", "theater", "theatre",
        "cinema", "film", "poetry", "literary", "book club", "photography",
        "painting", "sculpture", "workshop", "craft",
    ],
    EventVibe.FOOD_DRINK: [
        "food", "wine", "beer", "cocktail", "tasting", "cooking class",
        "dinner", "supper club", "food market", "street food", "restaurant",
        "culinary", "brewery", "distillery",
    ],
    EventVibe.WELLNESS: [
        "yoga", "meditation", "breathwork", "sound bath", "retreat",
        "wellness", "spa", "healing", "mindfulness", "holistic",
        "cacao ceremony", "ecstatic dance",
    ],
    EventVibe.ADVENTURE: [
        "hiking", "cycling", "kayak", "climbing", "outdoor", "adventure",
        "tour", "walking tour", "escape room", "day trip", "excursion",
        "boat", "sailing",
    ],
    EventVibe.NETWORKING: [
        "startup", "tech", "professional", "networking", "conference",
        "workshop", "seminar", "hackathon", "pitch", "entrepreneur",
        "business", "coworking",
    ],
    EventVibe.LGBTQ: [
        "pride", "lgbtq", "gay", "lesbian", "queer", "drag", "drag show",
        "rainbow", "trans", "nonbinary",
    ],
    EventVibe.UNDERGROUND: [
        "underground", "secret", "popup", "pop-up", "speakeasy", "hidden",
        "invite-only", "exclusive", "warehouse", "squat",
    ],
    EventVibe.FESTIVAL: [
        "festival", "carnival", "street party", "block party", "celebration",
        "fair", "fête", "market", "christmas market", "summer fest",
    ],
    EventVibe.SPORT_FITNESS: [
        "run", "marathon", "football", "soccer", "basketball", "tennis",
        "swimming", "crossfit", "gym", "fitness", "sports", "workout",
        "boxing", "martial arts",
    ],
}

# Pre-sorted so longer phrases are matched first (avoids partial hits).
_SORTED_VIBE_KEYWORDS: dict[EventVibe, list[str]] = {
    vibe: sorted(keywords, key=len, reverse=True)
    for vibe, keywords in VIBE_KEYWORDS.items()
}

# Default HTTP headers shared by all crawlers.
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "CityEventCrawler/1.0 "
        "(+https://github.com/city-event-crawler; contact@example.com)"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Default request timeout in seconds.
DEFAULT_TIMEOUT = 15.0


class BaseCrawler(abc.ABC):
    """
    Abstract base for every platform crawler.

    Subclasses MUST set ``source`` and ``name`` class attributes and implement
    the ``crawl`` coroutine.
    """

    source: EventSource
    name: str

    # Minimum seconds between successive HTTP requests (per crawler instance).
    _rate_limit_interval: float = 0.25

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # Async context manager (session lifecycle)
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseCrawler":
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
            follow_redirects=True,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the active HTTP client, raising if the context manager was not used."""
        if self._client is None:
            raise RuntimeError(
                f"{self.name} crawler must be used as an async context manager "
                "(async with crawler: ...)"
            )
        return self._client

    # ------------------------------------------------------------------
    # Abstract crawl method
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def crawl(
        self,
        city: str,
        date: str,
        lat: float,
        lon: float,
        radius_km: float,
        vibes: list[EventVibe] | None = None,
    ) -> list[Event]:
        """
        Fetch events for *city* on *date* within *radius_km* of (*lat*, *lon*).

        Parameters
        ----------
        city:
            Human-readable city name (e.g. "Berlin").
        date:
            Target date in ``YYYY-MM-DD`` format.
        lat, lon:
            Centre-point coordinates for the search.
        radius_km:
            Search radius in kilometres.
        vibes:
            Optional filter — only return events matching these vibes.
            ``None`` means return everything.

        Returns
        -------
        list[Event]
            Discovered events.  An empty list on failure (errors are logged).
        """
        ...

    # ------------------------------------------------------------------
    # Vibe classification
    # ------------------------------------------------------------------

    def classify_vibes(
        self,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> list[EventVibe]:
        """
        Assign :class:`EventVibe` categories using keyword matching.

        Searches through *title*, *description*, and *tags* for known keywords
        and returns the deduplicated list of matching vibes.
        """
        text_parts: list[str] = []
        if title:
            text_parts.append(title)
        if description:
            text_parts.append(description)
        if tags:
            text_parts.extend(tags)

        combined = " ".join(text_parts).lower()
        if not combined.strip():
            return []

        matched: set[EventVibe] = set()
        for vibe, keywords in _SORTED_VIBE_KEYWORDS.items():
            for kw in keywords:
                if kw in combined:
                    matched.add(vibe)
                    break  # one hit per vibe is enough

        return sorted(matched, key=lambda v: v.value)

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_datetime(value: str | None, fallback_date: str | None = None) -> datetime:
        """Parse a date/time string into a ``datetime`` object.

        Falls back to midnight on *fallback_date* (``YYYY-MM-DD``) when
        *value* cannot be parsed.  If all else fails, returns ``datetime.utcnow()``.
        """
        if value:
            dt = normalize_date(value)
            if dt is not None:
                return dt

        if fallback_date:
            dt = normalize_date(fallback_date)
            if dt is not None:
                return dt

        return datetime.utcnow()

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Sleep if necessary to respect ``_rate_limit_interval``."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit_interval:
            await asyncio.sleep(self._rate_limit_interval - elapsed)
        self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # Safe HTTP helpers
    # ------------------------------------------------------------------

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        """Perform a rate-limited GET request, returning *None* on error."""
        await self._rate_limit()
        try:
            resp = self.client.build_request("GET", url, params=params, headers=headers)
            response = await self.client.send(resp)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            self._logger.warning(
                "%s GET %s returned HTTP %s: %s",
                self.name, url, exc.response.status_code, exc.response.text[:300],
            )
        except httpx.RequestError as exc:
            self._logger.error("%s GET %s failed: %s", self.name, url, exc)
        return None

    async def _post(
        self,
        url: str,
        *,
        json: Any | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        """Perform a rate-limited POST request, returning *None* on error."""
        await self._rate_limit()
        try:
            response = await self.client.post(
                url, json=json, data=data, headers=headers,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            self._logger.warning(
                "%s POST %s returned HTTP %s: %s",
                self.name, url, exc.response.status_code, exc.response.text[:300],
            )
        except httpx.RequestError as exc:
            self._logger.error("%s POST %s failed: %s", self.name, url, exc)
        return None

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_info(self, msg: str, *args: Any) -> None:
        self._logger.info("[%s] " + msg, self.name, *args)

    def _log_warning(self, msg: str, *args: Any) -> None:
        self._logger.warning("[%s] " + msg, self.name, *args)

    def _log_error(self, msg: str, *args: Any) -> None:
        self._logger.error("[%s] " + msg, self.name, *args)

    # ------------------------------------------------------------------
    # Filtering helper
    # ------------------------------------------------------------------

    def _filter_by_vibes(
        self,
        events: list[Event],
        vibes: list[EventVibe] | None,
    ) -> list[Event]:
        """Return only events whose vibes overlap with *vibes* (if provided)."""
        if not vibes:
            return events
        target = set(vibes)
        return [e for e in events if target & set(e.vibes)]
