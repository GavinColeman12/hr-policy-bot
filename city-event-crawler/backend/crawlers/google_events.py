"""Google Events crawler powered by SerpAPI."""

from __future__ import annotations

import logging
from typing import Any

from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search.json"

_SEARCH_TEMPLATES = [
    "{city} events {date}",
    "{city} things to do {date}",
    "{city} nightlife {date}",
    "{city} parties {date}",
]


class GoogleEventsCrawler(BaseCrawler):
    source = EventSource.GOOGLE
    name = "Google Events"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.SERPAPI_KEY:
            self._log_warning("SERPAPI_KEY not configured — skipping")
            return []

        events = []
        seen = set()

        events.extend(await self._google_events_engine(city, date, settings.SERPAPI_KEY, seen))
        for tpl in _SEARCH_TEMPLATES:
            events.extend(await self._google_search(tpl.format(city=city, date=date), settings.SERPAPI_KEY, city, date, seen))

        return self._filter_by_vibes(events, vibes)

    async def _google_events_engine(self, city, date, api_key, seen):
        resp = await self._get(SERPAPI_BASE, params={"engine": "google_events", "q": f"events in {city}", "hl": "en", "api_key": api_key})
        if not resp:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        for item in data.get("events_results", []):
            title = item.get("title", "")
            eid = generate_event_id(self.source.value, title, city, date)
            if eid in seen:
                continue
            seen.add(eid)

            desc = clean_text(item.get("description"))
            venue_info = item.get("venue", {}) or {}
            addr = item.get("address", [])
            addr_str = ", ".join(addr) if isinstance(addr, list) else str(addr) if addr else None

            date_info = item.get("date", {})
            event_dt = parse_date(
                date_info.get("start_date") if isinstance(date_info, dict) else str(date_info),
                fallback=date,
            )

            tags = item.get("tags", []) or []
            vibes = self.classify_vibes(title, desc, tags)

            results.append(Event(
                id=eid, title=title, description=desc,
                date=event_dt or parse_date(date),
                source=self.source, source_url=item.get("link", f"https://www.google.com/search?q={title}"),
                venue_name=venue_info.get("name"), address=addr_str,
                image_url=item.get("thumbnail"),
                vibes=vibes, tags=tags if isinstance(tags, list) else [],
                raw_data=item,
            ))
        self._log_info("Google Events engine: %d events for %s", len(results), city)
        return results

    async def _google_search(self, query, api_key, city, date, seen):
        resp = await self._get(SERPAPI_BASE, params={"engine": "google", "q": query, "hl": "en", "num": 20, "api_key": api_key})
        if not resp:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        for item in data.get("organic_results", []):
            title = item.get("title", "")
            link = item.get("link", "")
            eid = generate_event_id(self.source.value, title, link)
            if eid in seen:
                continue
            seen.add(eid)

            desc = clean_text(item.get("snippet"))
            vibes = self.classify_vibes(title, desc)
            results.append(Event(
                id=eid, title=title, description=desc,
                date=parse_date(date),
                source=self.source, source_url=link,
                image_url=item.get("thumbnail"),
                vibes=vibes, raw_data=item,
            ))
        return results
