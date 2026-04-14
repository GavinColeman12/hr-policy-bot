"""Meetup crawler - uses SearchAPI Google since Meetup API is locked down."""

from __future__ import annotations

import logging
import re

from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class MeetupCrawler(BaseCrawler):
    source = EventSource.MEETUP
    name = "Meetup"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.SERPAPI_KEY:
            self._log_warning("SearchAPI key not configured — skipping Meetup")
            return []

        import asyncio
        events, seen = [], set()

        queries = [
            f"site:meetup.com {city} events",
            f"site:meetup.com {city} social expat",
            f"site:meetup.com {city} tech startup",
            f"site:meetup.com {city} wellness yoga hiking",
        ]

        async def run_query(q):
            return await self._get(
                "https://www.searchapi.io/api/v1/search",
                params={"engine": "google", "q": q, "hl": "en", "num": 10, "api_key": settings.SERPAPI_KEY},
            )

        responses = await asyncio.gather(*[run_query(q) for q in queries])
        for resp in responses:
            if not resp:
                continue
            try:
                data = resp.json()
            except Exception:
                continue

            for item in data.get("organic_results", []):
                title = item.get("title", "")
                link = item.get("link", "")
                if "meetup.com" not in link:
                    continue

                eid = generate_event_id(self.source.value, title, link)
                if eid in seen:
                    continue
                seen.add(eid)

                desc = clean_text(item.get("snippet"))

                # Extract member count if present
                member_count = None
                if desc:
                    member_match = re.search(r"(\d[\d,]*)\s*members?", desc, re.IGNORECASE)
                    if member_match:
                        try:
                            member_count = int(member_match.group(1).replace(",", ""))
                        except ValueError:
                            pass

                clean_title = re.split(r"\s*[|·]\s*", title)[0].strip()
                results_vibes = self.classify_vibes(title, desc)
                if not results_vibes:
                    continue

                events.append(Event(
                    id=eid,
                    title=clean_title[:200],
                    description=desc,
                    date=parse_date(date),
                    source=self.source,
                    source_url=link,
                    attendee_count=member_count,
                    vibes=results_vibes,
                    tags=["meetup"],
                    raw_data=item,
                ))

        self._log_info("Found %d events from Meetup for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)
