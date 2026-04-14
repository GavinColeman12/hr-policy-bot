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

    # High-signal free event sites - prioritized by usefulness
    # Only the best ones kept to make searches fast (<30s)
    TARGET_SITES = [
        # Top priority - general event aggregators
        ("songkick.com", ["MUSIC"]),
        ("bandsintown.com", ["MUSIC"]),
        ("allevents.in", ["SOCIAL"]),
        ("xceed.me", ["NIGHTLIFE", "MUSIC"]),
        ("timeout.com", ["SOCIAL", "ART_CULTURE", "FOOD_DRINK"]),

        # Festivals
        ("festicket.com", ["FESTIVAL", "MUSIC"]),

        # Alternative / kinky / dating
        ("skirtclub.com", ["KINKY", "DATING"]),

        # Vibe-specific
        ("eater.com", ["FOOD_DRINK"]),
        ("them.us", ["LGBTQ"]),
        ("classpass.com", ["WELLNESS", "SPORT_FITNESS"]),

        # City-specific (loaded dynamically based on city)
        ("goout.net", ["MUSIC", "NIGHTLIFE", "ART_CULTURE"]),
        ("welovebudapest.com", ["SOCIAL", "ART_CULTURE"]),
        ("exberliner.com", ["ART_CULTURE"]),
        ("expats.cz", ["SOCIAL"]),
    ]

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        import asyncio
        settings = get_settings()
        if not settings.SERPAPI_KEY:
            self._log_warning("SERPAPI_KEY not configured — skipping event guides")
            return []

        seen = set()

        # Filter sites by requested vibes to conserve API calls
        target_sites = self.TARGET_SITES
        if vibes:
            requested = {(v.value if hasattr(v, 'value') else str(v)).upper() for v in vibes}
            target_sites = [
                (site, defaults) for site, defaults in self.TARGET_SITES
                if any(d in requested for d in defaults) or not defaults
            ]
            # Always include top general sites
            general_sites = {"songkick.com", "timeout.com", "allevents.in", "xceed.me"}
            for s, d in self.TARGET_SITES:
                if s in general_sites and (s, d) not in target_sites:
                    target_sites.append((s, d))

        self._log_info("Searching %d event guide sites for %s", len(target_sites), city)

        # Run all site searches concurrently with a semaphore to avoid overload
        semaphore = asyncio.Semaphore(8)

        async def bounded_search(site, defaults):
            async with semaphore:
                try:
                    return await self._search_site(site, city, date, defaults, settings.SERPAPI_KEY, seen)
                except Exception as e:
                    self._log_warning("Site %s failed: %s", site, e)
                    return []

        tasks = [bounded_search(site, defaults) for site, defaults in target_sites]
        results_lists = await asyncio.gather(*tasks, return_exceptions=False)

        events = []
        for site_events in results_lists:
            events.extend(site_events)

        self._log_info("Found %d events from event guides for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_site(self, site, city, date, default_vibes, api_key, seen):
        """Use SearchAPI to find events on a specific guide site."""
        # Single query per site to keep searches fast
        query = f"site:{site} {city} events"

        resp = await self._get(
            "https://www.searchapi.io/api/v1/search",
            params={"engine": "google", "q": query, "hl": "en", "num": 10, "api_key": api_key},
        )
        if not resp:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

        results = []
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
