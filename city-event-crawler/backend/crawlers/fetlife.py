"""FetLife events crawler."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

CITY_FETLIFE_LOCATIONS = {
    "budapest": "Budapest, Hungary", "berlin": "Berlin, Germany",
    "prague": "Prague, Czech Republic", "barcelona": "Barcelona, Spain",
    "amsterdam": "Amsterdam, Netherlands", "lisbon": "Lisbon, Portugal",
    "vienna": "Vienna, Austria", "warsaw": "Warsaw, Poland",
    "london": "London, United Kingdom", "paris": "Paris, France",
    "rome": "Rome, Italy", "munich": "Munich, Germany",
    "dublin": "Dublin, Ireland", "copenhagen": "Copenhagen, Denmark",
}


class FetLifeCrawler(BaseCrawler):
    """Crawls FetLife for kink/fetish events.

    Note: FetLife requires authentication. Set FETLIFE_SESSION_COOKIE env var
    with a valid _fl_sessionid cookie value, or this crawler returns empty.
    """

    source = EventSource.FETLIFE
    name = "FetLife"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        city_lower = city.lower().strip()
        location = CITY_FETLIFE_LOCATIONS.get(city_lower, f"{city.title()}")

        events = []
        seen = set()

        # Search FetLife events page
        search_results = await self._search_events(location, city, date, seen)
        events.extend(search_results)

        # Auto-tag all FetLife events as KINKY
        for ev in events:
            if EventVibe.KINKY not in ev.vibes:
                ev.vibes.insert(0, EventVibe.KINKY)

        self._log_info("Found %d events from FetLife for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_events(self, location, city, date, seen):
        """Search FetLife events near a location."""
        resp = await self._get(
            "https://fetlife.com/events/search",
            params={"q": location, "type": "events"},
            headers={
                "Accept": "text/html",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        if not resp:
            return []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
        except ImportError:
            self._log_warning("beautifulsoup4 not installed, skipping FetLife scrape")
            return []

        results = []
        for card in soup.select(".event_listing, .event-card, [class*='EventCard']"):
            title_el = card.select_one("h3 a, .event-title a, [class*='title'] a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            eid = generate_event_id(self.source.value, title, city, date)
            if eid in seen:
                continue
            seen.add(eid)

            desc_el = card.select_one(".event-description, p")
            desc = clean_text(desc_el.get_text(strip=True)) if desc_el else None

            venue_el = card.select_one(".event-location, .location")
            venue = venue_el.get_text(strip=True) if venue_el else None

            rsvp_el = card.select_one(".rsvp-count, .attending-count, [class*='rsvp']")
            rsvp_count = None
            if rsvp_el:
                import re
                nums = re.findall(r'\d+', rsvp_el.get_text())
                rsvp_count = int(nums[0]) if nums else None

            source_url = f"https://fetlife.com{link}" if link.startswith("/") else (link or "https://fetlife.com/events")

            results.append(Event(
                id=eid, title=title, description=desc,
                date=parse_date(date),
                source=self.source, source_url=source_url,
                venue_name=venue,
                attendee_count=rsvp_count,
                vibes=self.classify_vibes(title, desc),
                tags=["kink", "fetish"],
                raw_data={"scraped": True},
            ))

        return results
