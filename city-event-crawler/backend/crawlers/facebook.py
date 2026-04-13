"""Facebook Events crawler using Meta Graph API."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class FacebookCrawler(BaseCrawler):
    source = EventSource.FACEBOOK
    name = "Facebook Events"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.FACEBOOK_ACCESS_TOKEN:
            self._log_warning("FACEBOOK_ACCESS_TOKEN not configured — skipping")
            return []

        events, seen = [], set()

        # Search for events via Graph API
        search_terms = [f"{city} events", f"{city} nightlife", f"{city} party"]
        for term in search_terms:
            results = await self._search_events(term, city, date, lat, lon, radius_km, settings.FACEBOOK_ACCESS_TOKEN, seen)
            events.extend(results)

        self._log_info("Found %d events from Facebook for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_events(self, query, city, date, lat, lon, radius_km, token, seen):
        resp = await self._get(
            "https://graph.facebook.com/v18.0/search",
            params={
                "q": query, "type": "event",
                "center": f"{lat},{lon}", "distance": int(radius_km * 1000),
                "fields": "name,description,place,start_time,end_time,attending_count,interested_count,cover,is_online,ticket_uri",
                "access_token": token, "limit": 50,
            },
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        for item in data.get("data", []):
            fb_id = item.get("id", "")
            eid = generate_event_id(self.source.value, fb_id)
            if eid in seen:
                continue
            seen.add(eid)

            title = item.get("name", "")
            desc = clean_text(item.get("description"))
            place = item.get("place", {}) or {}
            location = place.get("location", {}) or {}
            cover = item.get("cover", {}) or {}

            results.append(Event(
                id=eid, title=title, description=desc,
                date=parse_date(item.get("start_time"), fallback=date),
                end_date=parse_date(item.get("end_time")),
                source=self.source, source_url=f"https://www.facebook.com/events/{fb_id}",
                venue_name=place.get("name"), address=location.get("street"),
                latitude=location.get("latitude"), longitude=location.get("longitude"),
                image_url=cover.get("source"),
                attendee_count=item.get("attending_count"),
                interested_count=item.get("interested_count"),
                vibes=self.classify_vibes(title, desc),
                raw_data=item,
            ))

        return results
