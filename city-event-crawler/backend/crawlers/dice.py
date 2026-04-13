"""Dice.fm crawler for live music, club nights, and cultural events.

Uses SearchAPI.io Google to find Dice events since their API requires auth.
URL format: https://dice.fm/venue/{venue-slug} or https://dice.fm/event/{slug}
"""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

DICE_CITIES = {
    "london": "london", "berlin": "berlin", "paris": "paris",
    "barcelona": "barcelona", "amsterdam": "amsterdam", "lisbon": "lisbon",
    "madrid": "madrid", "milan": "milan", "rome": "rome",
    "budapest": "budapest", "prague": "prague", "vienna": "vienna",
    "dublin": "dublin", "copenhagen": "copenhagen", "stockholm": "stockholm",
    "brussels": "brussels", "hamburg": "hamburg", "munich": "munich",
    "warsaw": "warsaw", "athens": "athens", "istanbul": "istanbul",
}


class DiceCrawler(BaseCrawler):
    source = EventSource.DICE
    name = "Dice.fm"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        city_lower = city.lower().strip()
        dice_slug = DICE_CITIES.get(city_lower, city_lower)

        events = []
        seen = set()

        # Strategy 1: Use SearchAPI to find Dice events via Google
        settings = get_settings()
        if settings.SERPAPI_KEY:
            events.extend(await self._search_via_google(city_lower, dice_slug, date, settings.SERPAPI_KEY, seen))

        # Strategy 2: Try Dice API
        api_events = await self._fetch_api(dice_slug, date, seen)
        events.extend(api_events)

        # Auto-tag music for Dice events
        for ev in events:
            if EventVibe.MUSIC not in ev.vibes:
                ev.vibes.append(EventVibe.MUSIC)

        self._log_info("Found %d events from Dice.fm for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_via_google(self, city, dice_slug, date, api_key, seen):
        """Use SearchAPI.io to find Dice.fm events for this city."""
        queries = [
            f"site:dice.fm {city} event",
            f"site:dice.fm {city} venue",
            f"dice.fm {city} club night tickets",
        ]

        results = []
        for q in queries:
            resp = await self._get("https://www.searchapi.io/api/v1/search", params={
                "engine": "google", "q": q, "hl": "en", "num": 15, "api_key": api_key,
            })
            if not resp:
                continue
            try:
                data = resp.json()
            except Exception:
                continue

            for item in data.get("organic_results", []):
                title = item.get("title", "")
                link = item.get("link", "")

                if "dice.fm" not in link:
                    continue

                eid = generate_event_id(self.source.value, title, link)
                if eid in seen:
                    continue
                seen.add(eid)

                desc = clean_text(item.get("snippet"))

                # Extract venue name from title patterns like "Event at Venue"
                venue_name = None
                if " at " in title:
                    venue_name = title.split(" at ")[-1].strip()
                    # Clean trailing " | Dice" or similar
                    venue_name = venue_name.split(" | ")[0].split(" · ")[0].strip()

                results.append(Event(
                    id=eid, title=title.split(" | ")[0].split(" · ")[0].strip(),
                    description=desc,
                    date=parse_date(date),
                    source=self.source, source_url=link,
                    venue_name=venue_name,
                    vibes=self.classify_vibes(title, desc),
                    tags=["dice.fm"],
                    raw_data=item,
                ))

        return results

    async def _fetch_api(self, city_slug, date, seen):
        """Try fetching from Dice's API."""
        resp = await self._get(
            f"https://api.dice.fm/v1/events",
            params={
                "filter[venues][city]": city_slug,
                "filter[date]": date,
                "page[size]": 50,
            },
            headers={"Accept": "application/json", "x-dice-version": "3.0"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        items = data if isinstance(data, list) else data.get("data", [])
        for item in items:
            dice_id = str(item.get("id", ""))
            eid = generate_event_id(self.source.value, dice_id)
            if eid in seen:
                continue
            seen.add(eid)

            attrs = item.get("attributes", item)
            venue = attrs.get("venue", {}) or {}

            results.append(Event(
                id=eid,
                title=attrs.get("name", attrs.get("title", "")),
                description=clean_text(attrs.get("description")),
                date=parse_date(attrs.get("date") or attrs.get("starts_at"), fallback=date),
                source=self.source,
                source_url=attrs.get("url") or f"https://dice.fm/event/{dice_id}",
                venue_name=venue.get("name"),
                address=venue.get("address"),
                latitude=venue.get("latitude"),
                longitude=venue.get("longitude"),
                image_url=attrs.get("image_url"),
                attendee_count=attrs.get("sales_count"),
                vibes=self.classify_vibes(attrs.get("name", ""), attrs.get("description"), attrs.get("genres", [])),
                tags=attrs.get("genres", []) or [],
                raw_data=item,
            ))

        return results
