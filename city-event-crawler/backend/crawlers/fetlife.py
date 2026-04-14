"""FetLife crawler - uses SearchAPI Google to find public FetLife event pages.

FetLife requires login for direct access, but many event pages are indexed
by Google and can be discovered via site: search.
"""

from __future__ import annotations

import logging
import re

from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class FetLifeCrawler(BaseCrawler):
    source = EventSource.FETLIFE
    name = "FetLife"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.SERPAPI_KEY:
            self._log_warning("SearchAPI key not configured — skipping FetLife")
            return []

        events, seen = [], set()

        # FetLife has public event pages indexed by Google
        queries = [
            f"site:fetlife.com {city} event",
            f"site:fetlife.com {city} munch",
            f"site:fetlife.com {city} play party",
            f"site:fetlife.com {city} workshop",
            f"site:fetlife.com {city} kink event",
            f"site:fetlife.com {city} fetish",
        ]

        for q in queries:
            resp = await self._get(
                "https://www.searchapi.io/api/v1/search",
                params={"engine": "google", "q": q, "hl": "en", "num": 10, "api_key": settings.SERPAPI_KEY},
            )
            if not resp:
                continue
            try:
                data = resp.json()
            except Exception:
                continue

            for item in data.get("organic_results", []):
                title = item.get("title", "")
                link = item.get("link", "")
                if "fetlife.com" not in link:
                    continue

                eid = generate_event_id(self.source.value, title, link)
                if eid in seen:
                    continue
                seen.add(eid)

                desc = clean_text(item.get("snippet"))
                clean_title = re.split(r"\s*[|·]\s*", title)[0].strip()

                # Extract RSVP count
                rsvp_count = None
                if desc:
                    rsvp_match = re.search(r"(\d+)\s*(rsvp|going|attend)", desc, re.IGNORECASE)
                    if rsvp_match:
                        try:
                            rsvp_count = int(rsvp_match.group(1))
                        except ValueError:
                            pass

                # Extract venue from title/snippet (often "Event at Venue, City")
                venue = None
                if " at " in clean_title:
                    venue = clean_title.split(" at ")[-1].split(",")[0].strip()

                # All FetLife events auto-tag as KINKY
                results_vibes = self.classify_vibes(title, desc)
                if EventVibe.KINKY not in results_vibes:
                    results_vibes.insert(0, EventVibe.KINKY)

                events.append(Event(
                    id=eid,
                    title=clean_title[:200],
                    description=desc,
                    date=parse_date(date),
                    source=self.source,
                    source_url=link,
                    venue_name=venue,
                    attendee_count=rsvp_count,
                    vibes=results_vibes,
                    tags=["kink", "fetish", "fetlife"],
                    raw_data=item,
                ))

        self._log_info("Found %d events from FetLife for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)
