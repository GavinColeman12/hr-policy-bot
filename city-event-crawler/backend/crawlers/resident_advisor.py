"""Resident Advisor crawler for club/music events.

Uses SearchAPI.io Google to find RA event listings since RA blocks
direct scraping with Cloudflare. Also attempts the GraphQL API.
"""

from __future__ import annotations

import logging
import re
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

# RA URL format: /events/{country_code}/{city}
RA_CITY_URLS = {
    "budapest": "hu/budapest", "berlin": "de/berlin", "prague": "cz/prague",
    "barcelona": "es/barcelona", "amsterdam": "nl/amsterdam", "lisbon": "pt/lisbon",
    "vienna": "at/vienna", "warsaw": "pl/warsaw", "krakow": "pl/krakow",
    "belgrade": "rs/belgrade", "london": "uk/london", "paris": "fr/paris",
    "rome": "it/rome", "athens": "gr/athens", "dublin": "ie/dublin",
    "copenhagen": "dk/copenhagen", "munich": "de/munich", "milan": "it/milan",
    "istanbul": "tr/istanbul", "hamburg": "de/hamburg", "brussels": "be/brussels",
    "helsinki": "fi/helsinki", "zagreb": "hr/zagreb", "bucharest": "ro/bucharest",
    "sofia": "bg/sofia", "stockholm": "se/stockholm", "oslo": "no/oslo",
    "tallinn": "ee/tallinn", "riga": "lv/riga", "vilnius": "lt/vilnius",
    "madrid": "es/madrid", "seville": "es/seville", "valencia": "es/valencia",
    "porto": "pt/porto", "florence": "it/florence", "naples": "it/naples",
    "cologne": "de/cologne", "frankfurt": "de/frankfurt",
    "edinburgh": "uk/edinburgh", "antwerp": "be/antwerp",
    "bratislava": "sk/bratislava", "ljubljana": "si/ljubljana",
    "geneva": "ch/geneva", "zurich": "ch/zurich",
}


class ResidentAdvisorCrawler(BaseCrawler):
    source = EventSource.RESIDENT_ADVISOR
    name = "Resident Advisor"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        city_lower = city.lower().strip()
        events = []
        seen = set()

        # Strategy 1: Use SearchAPI to find RA events via Google
        settings = get_settings()
        if settings.SERPAPI_KEY:
            events.extend(await self._search_via_google(city_lower, date, settings.SERPAPI_KEY, seen))

        # Strategy 2: Try RA GraphQL API directly
        gql_events = await self._fetch_via_graphql(city_lower, date, seen)
        events.extend(gql_events)

        # Auto-tag all RA events as nightlife + music
        for ev in events:
            if EventVibe.NIGHTLIFE not in ev.vibes:
                ev.vibes.append(EventVibe.NIGHTLIFE)
            if EventVibe.MUSIC not in ev.vibes:
                ev.vibes.append(EventVibe.MUSIC)

        self._log_info("Found %d events from RA for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_via_google(self, city, date, api_key, seen):
        """Use SearchAPI.io to find RA event pages for this city."""
        ra_path = RA_CITY_URLS.get(city, f"{city}")
        queries = [
            f"site:ra.co/events/{ra_path}",
            f"site:ra.co {city} club night event",
            f"ra.co {city} events techno house",
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

                # Only include actual RA event/club pages
                if "ra.co" not in link:
                    continue

                eid = generate_event_id(self.source.value, title, link)
                if eid in seen:
                    continue
                seen.add(eid)

                desc = clean_text(item.get("snippet"))

                # Extract venue from title or snippet
                venue_name = None
                if " at " in title:
                    venue_name = title.split(" at ")[-1].strip()
                elif " · " in title:
                    parts = title.split(" · ")
                    if len(parts) > 1:
                        venue_name = parts[0].strip()

                results.append(Event(
                    id=eid, title=title, description=desc,
                    date=parse_date(date),
                    source=self.source, source_url=link,
                    venue_name=venue_name,
                    vibes=self.classify_vibes(title, desc),
                    tags=["resident-advisor"],
                    raw_data=item,
                ))

        return results

    async def _fetch_via_graphql(self, city, date, seen):
        """Try RA's GraphQL API for event listings."""
        ra_path = RA_CITY_URLS.get(city)
        if not ra_path:
            return []

        query = """query GET_DEFAULT_EVENTS_LISTING($indices: [IndexType!], $pageSize: Int, $page: Int, $aggregations: [ListingAggregationType!], $filters: [FilterInput!]) {
            listing(indices: $indices, pageSize: $pageSize, page: $page, aggregations: $aggregations, filters: $filters) {
                data { ... on Event { id title date startTime contentUrl images { filename } venue { name address } attending } }
                totalResults
            }
        }"""

        country_code, city_slug = ra_path.split("/", 1)
        variables = {
            "indices": ["EVENT"],
            "pageSize": 30,
            "page": 1,
            "aggregations": [],
            "filters": [
                {"type": "AREA", "value": city_slug},
                {"type": "LISTING_DATE", "value": f'{{"gte":"{date}"}}'},
            ],
        }

        resp = await self._post(
            "https://ra.co/graphql",
            json={"operationName": "GET_DEFAULT_EVENTS_LISTING", "query": query, "variables": variables},
            headers={"Content-Type": "application/json", "Referer": f"https://ra.co/events/{ra_path}"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        if "errors" in data:
            self._log_warning("RA GraphQL returned errors: %s", data["errors"][0].get("message", ""))
            return []

        results = []
        listing = (data.get("data") or {}).get("listing") or {}
        for item in listing.get("data", []):
            ra_id = str(item.get("id", ""))
            eid = generate_event_id(self.source.value, ra_id)
            if eid in seen:
                continue
            seen.add(eid)

            venue = item.get("venue") or {}
            content_url = item.get("contentUrl", "")
            source_url = f"https://ra.co{content_url}" if content_url else f"https://ra.co/events/{ra_path}"
            images = item.get("images") or []
            image_url = f"https://ra.co/images/events/flyer/{images[0]['filename']}" if images else None

            results.append(Event(
                id=eid, title=item.get("title", ""),
                date=parse_date(item.get("date"), fallback=date),
                source=self.source, source_url=source_url,
                venue_name=venue.get("name"), address=venue.get("address"),
                image_url=image_url,
                attendee_count=item.get("attending"),
                vibes=self.classify_vibes(item.get("title", ""), None),
                raw_data=item,
            ))

        return results
