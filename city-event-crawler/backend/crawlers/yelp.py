"""Yelp crawler for events and nightlife venues."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class YelpCrawler(BaseCrawler):
    source = EventSource.YELP
    name = "Yelp"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.YELP_API_KEY:
            self._log_warning("YELP_API_KEY not configured — skipping")
            return []

        events, seen = [], set()

        # Search Yelp events
        event_results = await self._search_events(city, date, lat, lon, radius_km, settings.YELP_API_KEY, seen)
        events.extend(event_results)

        # Also search popular nightlife/entertainment venues
        venue_events = await self._search_venues(city, date, lat, lon, radius_km, settings.YELP_API_KEY, seen)
        events.extend(venue_events)

        self._log_info("Found %d entries from Yelp for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_events(self, city, date, lat, lon, radius_km, api_key, seen):
        resp = await self._get(
            "https://api.yelp.com/v3/events",
            params={
                "latitude": lat, "longitude": lon,
                "radius": int(min(radius_km * 1000, 40000)),
                "start_date": int(parse_date(date).timestamp()) if parse_date(date) else None,
                "limit": 50, "sort_on": "popularity", "sort_by": "desc",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        for item in data.get("events", []):
            yid = item.get("id", "")
            eid = generate_event_id(self.source.value, yid)
            if eid in seen:
                continue
            seen.add(eid)

            results.append(Event(
                id=eid, title=item.get("name", ""),
                description=item.get("description"),
                date=parse_date(item.get("time_start"), fallback=date),
                end_date=parse_date(item.get("time_end")),
                source=self.source, source_url=item.get("event_site_url", ""),
                venue_name=item.get("business_id"),
                address=item.get("location", {}).get("display_address", [""])[0] if item.get("location") else None,
                latitude=item.get("latitude"), longitude=item.get("longitude"),
                image_url=item.get("image_url"),
                attendee_count=item.get("attending_count"),
                interested_count=item.get("interested_count"),
                is_free=item.get("is_free"),
                vibes=self.classify_vibes(item.get("name", ""), item.get("description"), item.get("category")),
                tags=[item.get("category")] if item.get("category") else [],
                raw_data=item,
            ))

        return results

    async def _search_venues(self, city, date, lat, lon, radius_km, api_key, seen):
        """Search popular nightlife venues that likely have events tonight."""
        categories = ["nightlife", "danceclubs", "bars", "musicvenues"]
        results = []

        for cat in categories:
            resp = await self._get(
                "https://api.yelp.com/v3/businesses/search",
                params={
                    "latitude": lat, "longitude": lon,
                    "radius": int(min(radius_km * 1000, 40000)),
                    "categories": cat, "sort_by": "rating",
                    "limit": 10,
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if not resp:
                continue

            try:
                data = resp.json()
            except Exception:
                continue

            for biz in data.get("businesses", []):
                bid = biz.get("id", "")
                eid = generate_event_id(self.source.value, bid, date)
                if eid in seen:
                    continue
                seen.add(eid)

                loc = biz.get("location", {})
                coords = biz.get("coordinates", {})

                results.append(Event(
                    id=eid,
                    title=f"{biz.get('name', '')} - {cat.title()} Venue",
                    description=f"Popular {cat} venue rated {biz.get('rating', 'N/A')}/5 with {biz.get('review_count', 0)} reviews",
                    date=parse_date(date),
                    source=self.source, source_url=biz.get("url", ""),
                    venue_name=biz.get("name"),
                    address=", ".join(loc.get("display_address", [])),
                    latitude=coords.get("latitude"), longitude=coords.get("longitude"),
                    image_url=biz.get("image_url"),
                    likes=biz.get("review_count"),
                    vibes=self.classify_vibes(biz.get("name", ""), cat),
                    tags=biz.get("categories", []),
                    raw_data=biz,
                ))

        return results
