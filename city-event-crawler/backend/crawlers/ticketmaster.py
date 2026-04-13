"""Ticketmaster crawler using Discovery API v2."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class TicketmasterCrawler(BaseCrawler):
    source = EventSource.TICKETMASTER
    name = "Ticketmaster"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.TICKETMASTER_API_KEY:
            self._log_warning("TICKETMASTER_API_KEY not configured — skipping")
            return []

        events, seen = [], set()
        page = 0
        while page < 3:
            page_events, total_pages = await self._fetch_page(
                city, date, lat, lon, radius_km, settings.TICKETMASTER_API_KEY, page, seen
            )
            events.extend(page_events)
            page += 1
            if page >= total_pages:
                break

        self._log_info("Found %d events from Ticketmaster for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _fetch_page(self, city, date, lat, lon, radius_km, api_key, page, seen):
        radius_mi = int(radius_km * 0.621371)
        resp = await self._get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params={
                "apikey": api_key,
                "latlong": f"{lat},{lon}",
                "radius": str(radius_mi), "unit": "miles",
                "startDateTime": f"{date}T00:00:00Z",
                "endDateTime": f"{date}T23:59:59Z",
                "size": 50, "page": page,
                "sort": "relevance,desc",
            },
        )
        if not resp:
            return [], 0

        try:
            data = resp.json()
        except Exception:
            return [], 0

        embedded = data.get("_embedded", {})
        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)

        results = []
        for item in embedded.get("events", []):
            tm_id = item.get("id", "")
            eid = generate_event_id(self.source.value, tm_id)
            if eid in seen:
                continue
            seen.add(eid)

            title = item.get("name", "")
            # Get venue
            venues = (item.get("_embedded", {}) or {}).get("venues", [])
            venue = venues[0] if venues else {}
            venue_name = venue.get("name")
            address_obj = venue.get("address", {})
            address = address_obj.get("line1")
            loc = venue.get("location", {})

            # Get price
            price_ranges = item.get("priceRanges", [])
            price_str = None
            if price_ranges:
                pr = price_ranges[0]
                currency = pr.get("currency", "EUR")
                price_str = f"{pr.get('min', '?')}-{pr.get('max', '?')} {currency}"

            # Get images
            images = item.get("images", [])
            image_url = images[0].get("url") if images else None

            # Get genre for vibes
            classifications = item.get("classifications", [])
            genre = ""
            subgenre = ""
            if classifications:
                c = classifications[0]
                genre = (c.get("genre", {}) or {}).get("name", "")
                subgenre = (c.get("subGenre", {}) or {}).get("name", "")

            # Dates
            dates = item.get("dates", {})
            start = dates.get("start", {})

            results.append(Event(
                id=eid, title=title,
                description=clean_text(item.get("info") or item.get("pleaseNote")),
                date=parse_date(start.get("dateTime") or start.get("localDate"), fallback=date),
                source=self.source,
                source_url=item.get("url", ""),
                venue_name=venue_name, address=address,
                latitude=float(loc["latitude"]) if loc.get("latitude") else None,
                longitude=float(loc["longitude"]) if loc.get("longitude") else None,
                image_url=image_url, price=price_str,
                vibes=self.classify_vibes(title, genre, [genre, subgenre]),
                tags=[t for t in [genre, subgenre] if t and t != "Undefined"],
                raw_data=item,
            ))

        return results, total_pages
