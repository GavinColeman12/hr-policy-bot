"""Blog and local event site scraper."""

from __future__ import annotations

import logging
import re
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

# Known local event listing sites per city
CITY_EVENT_SITES = {
    "budapest": [
        "https://welovebudapest.com/en/programmes",
        "https://www.timeout.com/budapest/things-to-do",
    ],
    "berlin": [
        "https://www.timeout.com/berlin/things-to-do",
        "https://www.exberliner.com/events/",
    ],
    "prague": [
        "https://www.timeout.com/prague/things-to-do",
        "https://goout.net/en/prague/events/",
    ],
    "barcelona": [
        "https://www.timeout.com/barcelona/things-to-do",
    ],
    "amsterdam": [
        "https://www.timeout.com/amsterdam/things-to-do",
        "https://www.iamsterdam.com/en/see-and-do/whats-on",
    ],
    "lisbon": [
        "https://www.timeout.com/lisbon/things-to-do",
    ],
    "vienna": [
        "https://www.timeout.com/vienna/things-to-do",
    ],
    "london": [
        "https://www.timeout.com/london/things-to-do",
    ],
    "paris": [
        "https://www.timeout.com/paris/en/things-to-do",
    ],
}


class BlogScraperCrawler(BaseCrawler):
    source = EventSource.BLOG
    name = "Blog Scraper"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        city_lower = city.lower().strip()
        events, seen = [], set()

        # Scrape known local event sites
        sites = CITY_EVENT_SITES.get(city_lower, [])
        for site_url in sites[:3]:
            results = await self._scrape_event_site(site_url, city, date, seen)
            events.extend(results)

        # Google search for blog posts about events
        if settings.SERPAPI_KEY:
            blog_results = await self._search_blogs(city, date, settings.SERPAPI_KEY, seen)
            events.extend(blog_results)

        self._log_info("Found %d events from blogs for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _scrape_event_site(self, url, city, date, seen):
        resp = await self._get(url, headers={"Accept": "text/html"})
        if not resp:
            return []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
        except ImportError:
            return []

        results = []
        # Generic event card extraction
        selectors = [
            "article", "[class*='event']", "[class*='listing']",
            "[class*='card']", "[data-testid*='event']",
        ]

        for selector in selectors:
            for card in soup.select(selector)[:20]:
                title_el = card.select_one("h2, h3, h4, [class*='title']")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if len(title) < 5 or len(title) > 200:
                    continue

                eid = generate_event_id(self.source.value, title, url)
                if eid in seen:
                    continue
                seen.add(eid)

                link_el = card.select_one("a[href]")
                link = link_el.get("href", "") if link_el else ""
                if link and not link.startswith("http"):
                    from urllib.parse import urljoin
                    link = urljoin(url, link)

                desc_el = card.select_one("p, [class*='desc'], [class*='summary']")
                desc = clean_text(desc_el.get_text(strip=True)) if desc_el else None

                results.append(Event(
                    id=eid, title=title, description=desc,
                    date=parse_date(date),
                    source=self.source, source_url=link or url,
                    vibes=self.classify_vibes(title, desc),
                    tags=["local-blog"],
                    raw_data={"scraped_from": url},
                ))

        return results

    async def _search_blogs(self, city, date, api_key, seen):
        from datetime import datetime
        month_year = datetime.strptime(date, "%Y-%m-%d").strftime("%B %Y")

        resp = await self._get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google", "q": f"{city} events {month_year} blog",
                "hl": "en", "num": 10, "api_key": api_key,
            },
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
            eid = generate_event_id(self.source.value, title, link)
            if eid in seen:
                continue
            seen.add(eid)

            snippet = clean_text(item.get("snippet"))
            vibes = self.classify_vibes(title, snippet)
            if vibes:
                results.append(Event(
                    id=eid, title=title, description=snippet,
                    date=parse_date(date),
                    source=self.source, source_url=link,
                    vibes=vibes, tags=["blog"],
                    raw_data=item,
                ))

        return results
