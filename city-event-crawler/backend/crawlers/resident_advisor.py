"""Resident Advisor crawler for club/music events."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

# RA area IDs for major European cities
RA_AREAS = {
    "budapest": 59, "berlin": 34, "prague": 178, "barcelona": 44,
    "amsterdam": 29, "lisbon": 110, "vienna": 169, "warsaw": 170,
    "krakow": 171, "belgrade": 183, "london": 13, "paris": 44,
    "rome": 182, "athens": 175, "dublin": 69, "copenhagen": 74,
    "munich": 73, "milan": 108, "istanbul": 186, "hamburg": 42,
    "brussels": 51, "helsinki": 163, "zagreb": 188, "bucharest": 184,
}


class ResidentAdvisorCrawler(BaseCrawler):
    source = EventSource.RESIDENT_ADVISOR
    name = "Resident Advisor"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        city_lower = city.lower().strip()
        area_id = RA_AREAS.get(city_lower)

        events = []
        seen = set()

        # Try GraphQL API
        gql_events = await self._fetch_via_graphql(city_lower, date, area_id, seen)
        events.extend(gql_events)

        # Also try scraping the listing page
        scrape_events = await self._fetch_via_scrape(city_lower, date, seen)
        events.extend(scrape_events)

        # Auto-tag nightlife + music vibes
        for ev in events:
            if EventVibe.NIGHTLIFE not in ev.vibes:
                ev.vibes.append(EventVibe.NIGHTLIFE)
            if EventVibe.MUSIC not in ev.vibes:
                ev.vibes.append(EventVibe.MUSIC)

        self._log_info("Found %d events from RA for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _fetch_via_graphql(self, city, date, area_id, seen):
        if not area_id:
            return []

        query = """
        query GET_EVENTS($filters: FilterInputDtoInput, $page: Int) {
            listing(filters: $filters, page: $page, pageSize: 50) {
                data { id title date venue { name address } contentUrl
                       flyerFront attending }
            }
        }"""
        variables = {
            "filters": {"areas": {"eq": area_id}, "listingDate": {"gte": date, "lte": date}},
            "page": 1,
        }

        resp = await self._post(
            "https://ra.co/graphql",
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json", "Referer": "https://ra.co/"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        listings = (data.get("data") or {}).get("listing") or {}
        for item in listings.get("data", []):
            ra_id = str(item.get("id", ""))
            eid = generate_event_id(self.source.value, ra_id)
            if eid in seen:
                continue
            seen.add(eid)

            venue = item.get("venue") or {}
            content_url = item.get("contentUrl", "")
            source_url = f"https://ra.co{content_url}" if content_url else f"https://ra.co/events/{ra_id}"

            results.append(Event(
                id=eid, title=item.get("title", ""),
                date=parse_date(item.get("date"), fallback=date),
                source=self.source, source_url=source_url,
                venue_name=venue.get("name"), address=venue.get("address"),
                image_url=item.get("flyerFront"),
                attendee_count=item.get("attending"),
                vibes=self.classify_vibes(item.get("title", ""), None),
                raw_data=item,
            ))

        return results

    async def _fetch_via_scrape(self, city, date, seen):
        """Fallback: scrape the RA events listing page."""
        url = f"https://ra.co/events/{city}/{date}"
        resp = await self._get(url, headers={"Accept": "text/html"})
        if not resp:
            return []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
        except ImportError:
            self._log_warning("beautifulsoup4 not installed, skipping RA scrape")
            return []

        results = []
        # RA uses data attributes on event cards
        for card in soup.select("[data-testid='event-item'], .event-item, li[class*='event']"):
            title_el = card.select_one("h3, h4, [class*='title'], a[href*='/events/']")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "") if title_el.name == "a" else ""
            if not link:
                link_el = card.select_one("a[href*='/events/']")
                link = link_el.get("href", "") if link_el else ""

            eid = generate_event_id(self.source.value, title, date)
            if eid in seen:
                continue
            seen.add(eid)

            venue_el = card.select_one("[class*='venue'], span:nth-of-type(2)")
            venue_name = venue_el.get_text(strip=True) if venue_el else None

            source_url = f"https://ra.co{link}" if link.startswith("/") else (link or f"https://ra.co/events/{city}")

            results.append(Event(
                id=eid, title=title,
                date=parse_date(date),
                source=self.source, source_url=source_url,
                venue_name=venue_name,
                vibes=self.classify_vibes(title),
                raw_data={"scraped": True},
            ))

        return results
