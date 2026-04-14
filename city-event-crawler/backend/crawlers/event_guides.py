"""Event Guides crawler - scrapes Songkick, Bandsintown, GoOut, Xceed, TimeOut.

Uses SearchAPI.io to surface events from major event aggregator sites that
don't have open APIs (or have restricted ones).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class EventGuidesCrawler(BaseCrawler):
    """Discovers events from major European/global event guide sites."""

    source = EventSource.GUIDES
    name = "Event Guides"

    # Guide sites we target via site: searches
    TARGET_SITES = [
        ("songkick.com", ["MUSIC"]),
        ("bandsintown.com", ["MUSIC"]),
        ("goout.net", ["MUSIC", "NIGHTLIFE", "ART_CULTURE"]),
        ("xceed.me", ["NIGHTLIFE", "MUSIC"]),
        ("timeout.com", ["SOCIAL", "ART_CULTURE"]),
        ("visitlondon.com", ["ART_CULTURE"]),
        ("visitberlin.de", ["SOCIAL"]),
        ("visitlisboa.com", ["SOCIAL"]),
        ("iamsterdam.com", ["SOCIAL"]),
        ("expats.cz", ["SOCIAL"]),
        ("welovebudapest.com", ["SOCIAL", "ART_CULTURE"]),
        ("funzine.hu", ["SOCIAL"]),
        ("exberliner.com", ["ART_CULTURE"]),
        ("timeout.com/meetup", ["SOCIAL", "NETWORKING"]),
    ]

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.SERPAPI_KEY:
            self._log_warning("SERPAPI_KEY not configured — skipping event guides")
            return []

        events = []
        seen = set()

        for site, default_vibes in self.TARGET_SITES:
            results = await self._search_site(site, city, date, default_vibes, settings.SERPAPI_KEY, seen)
            events.extend(results)

        self._log_info("Found %d events from event guides for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_site(self, site, city, date, default_vibes, api_key, seen):
        """Use SearchAPI to find events on a specific guide site."""
        from datetime import datetime
        try:
            month_year = datetime.strptime(date, "%Y-%m-%d").strftime("%B %Y")
        except Exception:
            month_year = ""

        queries = [
            f"site:{site} {city} events",
            f"site:{site} {city} {month_year}" if month_year else f"site:{site} {city}",
        ]

        results = []
        for q in queries:
            resp = await self._get(
                "https://www.searchapi.io/api/v1/search",
                params={"engine": "google", "q": q, "hl": "en", "num": 10, "api_key": api_key},
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

                # Ensure the result is actually from the target site
                if site not in link:
                    continue

                eid = generate_event_id(self.source.value, title, link)
                if eid in seen:
                    continue
                seen.add(eid)

                snippet = clean_text(item.get("snippet"))

                # Combine keyword-detected vibes with site default vibes
                keyword_vibes = self.classify_vibes(title, snippet)

                # Convert default_vibes strings to EventVibe enums
                from ..models import EventVibe
                default_vibe_enums = []
                for v in default_vibes:
                    try:
                        default_vibe_enums.append(EventVibe[v])
                    except (KeyError, ValueError):
                        pass

                # Merge vibes
                all_vibes = list(set(keyword_vibes + default_vibe_enums))

                # Extract venue name from title patterns
                venue_name = None
                if " at " in title:
                    parts = title.split(" at ")
                    if len(parts) > 1:
                        venue_name = parts[-1].split(" | ")[0].split(" · ")[0].strip()

                # Clean the title (remove trailing "| SiteName")
                clean_title = re.split(r"\s*[|·]\s*", title)[0].strip()

                domain = urlparse(link).netloc.replace("www.", "")

                if not all_vibes:
                    continue

                results.append(Event(
                    id=eid,
                    title=clean_title[:200],
                    description=snippet,
                    date=parse_date(date),
                    source=self.source,
                    source_url=link,
                    venue_name=venue_name,
                    vibes=all_vibes,
                    tags=[domain],
                    raw_data={"site": site, "item": item},
                ))

        return results
