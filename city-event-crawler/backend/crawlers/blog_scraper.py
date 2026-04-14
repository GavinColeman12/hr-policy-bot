"""Blog and local event site scraper - expanded with many European event sites."""

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
        "https://funzine.hu/en/",
        "https://www.xceed.me/en/budapest/events--clubs",
    ],
    "berlin": [
        "https://www.timeout.com/berlin/things-to-do",
        "https://www.exberliner.com/events/",
        "https://www.xceed.me/en/berlin/events--clubs",
        "https://www.visitberlin.de/en/events",
        "https://www.berlinagenda.com/",
    ],
    "prague": [
        "https://www.timeout.com/prague/things-to-do",
        "https://goout.net/en/prague/events/",
        "https://www.prague.eu/en/events",
        "https://expats.cz/prague/events",
        "https://www.xceed.me/en/prague/events--clubs",
    ],
    "barcelona": [
        "https://www.timeout.com/barcelona/things-to-do",
        "https://www.xceed.me/en/barcelona/events--clubs",
        "https://www.barcelona-life.com/events",
    ],
    "amsterdam": [
        "https://www.timeout.com/amsterdam/things-to-do",
        "https://www.iamsterdam.com/en/see-and-do/whats-on",
        "https://www.xceed.me/en/amsterdam/events--clubs",
    ],
    "lisbon": [
        "https://www.timeout.com/lisbon/things-to-do",
        "https://www.visitlisboa.com/en/events",
        "https://www.xceed.me/en/lisbon/events--clubs",
    ],
    "vienna": [
        "https://www.timeout.com/vienna/things-to-do",
        "https://events.wien.info/en/",
        "https://www.falter.at/events",
    ],
    "london": [
        "https://www.timeout.com/london/things-to-do",
        "https://www.visitlondon.com/things-to-do/whats-on",
        "https://www.xceed.me/en/london/events--clubs",
        "https://www.songkick.com/metro-areas/24426-uk-london",
    ],
    "paris": [
        "https://www.timeout.com/paris/en/things-to-do",
        "https://en.parisinfo.com/what-to-do-in-paris/info/guides/best-things-to-do",
        "https://www.xceed.me/en/paris/events--clubs",
    ],
    "madrid": [
        "https://www.timeout.com/madrid/en/things-to-do",
        "https://www.xceed.me/en/madrid/events--clubs",
    ],
    "rome": [
        "https://www.timeout.com/rome/things-to-do",
        "https://www.turismoroma.it/en/events",
    ],
    "milan": [
        "https://www.timeout.com/milan/things-to-do",
        "https://www.xceed.me/en/milan/events--clubs",
    ],
    "copenhagen": [
        "https://www.timeout.com/copenhagen/things-to-do",
        "https://www.visitcopenhagen.com/copenhagen/events",
    ],
    "dublin": [
        "https://www.timeout.com/dublin/things-to-do",
        "https://www.visitdublin.com/see-do/whats-on/",
    ],
    "warsaw": [
        "https://warsawlocal.com/events",
        "https://www.timeout.com/warsaw",
        "https://www.xceed.me/en/warsaw/events--clubs",
    ],
    "krakow": [
        "https://www.timeout.com/krakow",
        "https://lovekrakow.pl/en/events/",
    ],
    "belgrade": [
        "https://belgradenight.com/events",
        "https://www.timeout.com/belgrade",
    ],
    "athens": [
        "https://www.timeout.com/athens/things-to-do",
        "https://www.thisisathens.org/events",
    ],
    "istanbul": [
        "https://www.timeout.com/istanbul/things-to-do",
        "https://biletix.com/anasayfa/EN",
    ],
    "munich": [
        "https://www.timeout.com/munich",
        "https://www.muenchen.de/int/en/events.html",
    ],
    "stockholm": [
        "https://www.timeout.com/stockholm/things-to-do",
        "https://www.visitstockholm.com/events/",
    ],
    "oslo": [
        "https://www.visitoslo.com/en/whats-on/events/",
    ],
    "helsinki": [
        "https://www.myhelsinki.fi/en/events",
    ],
    "brussels": [
        "https://www.timeout.com/brussels",
        "https://visit.brussels/en/agenda",
    ],
}

# Global event aggregator sites (work for any city)
GLOBAL_EVENT_SITES = [
    "https://www.bandsintown.com/c/{city}",
    "https://www.songkick.com/search?query={city}",
    "https://www.xceed.me/en/{city}/events--clubs",
    "https://dice.fm/browse/{city}",
]


class BlogScraperCrawler(BaseCrawler):
    source = EventSource.BLOG
    name = "Blog Scraper"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        city_lower = city.lower().strip()
        events, seen = [], set()

        # Scrape known local event sites
        sites = CITY_EVENT_SITES.get(city_lower, [])
        for site_url in sites[:6]:  # Scrape up to 6 sites
            results = await self._scrape_event_site(site_url, city, date, seen)
            events.extend(results)

        # Google search for more event sources via SearchAPI
        if settings.SERPAPI_KEY:
            blog_results = await self._search_blogs(city, date, settings.SERPAPI_KEY, seen)
            events.extend(blog_results)

        self._log_info("Found %d events from blogs/guides for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _scrape_event_site(self, url, city, date, seen):
        resp = await self._get(url, headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        })
        if not resp:
            return []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
        except ImportError:
            return []

        results = []
        selectors = [
            "article", "[class*='event']", "[class*='listing']",
            "[class*='card']", "[data-testid*='event']", "[class*='post']",
            ".event-card", ".agenda-item", ".program-item",
        ]

        for selector in selectors:
            for card in soup.select(selector)[:25]:
                try:
                    title_el = card.select_one("h1, h2, h3, h4, [class*='title'], [class*='heading']")
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

                    desc_el = card.select_one("p, [class*='desc'], [class*='summary'], [class*='excerpt']")
                    desc = clean_text(desc_el.get_text(strip=True)) if desc_el else None

                    img_el = card.select_one("img")
                    img_url = None
                    if img_el:
                        img_url = img_el.get("src") or img_el.get("data-src")
                        if img_url and not img_url.startswith("http"):
                            from urllib.parse import urljoin
                            img_url = urljoin(url, img_url)

                    # Only keep if it has classifiable vibes
                    vibes = self.classify_vibes(title, desc)
                    if not vibes:
                        continue

                    # Extract domain for tag
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc.replace("www.", "")

                    results.append(Event(
                        id=eid, title=title, description=desc,
                        date=parse_date(date),
                        source=self.source, source_url=link or url,
                        image_url=img_url,
                        vibes=vibes,
                        tags=[domain],
                        raw_data={"scraped_from": url},
                    ))
                except Exception as e:
                    continue

        return results

    async def _search_blogs(self, city, date, api_key, seen):
        from datetime import datetime
        month_year = datetime.strptime(date, "%Y-%m-%d").strftime("%B %Y")

        # Multiple search queries for diverse coverage
        queries = [
            f"{city} events {month_year} blog",
            f"{city} things to do this week",
            f"best {city} events guide {month_year}",
            f"{city} hidden gems events underground",
            f"{city} cultural calendar {month_year}",
        ]

        results = []
        for q in queries[:3]:
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
                eid = generate_event_id(self.source.value, title, link)
                if eid in seen:
                    continue
                seen.add(eid)

                snippet = clean_text(item.get("snippet"))
                vibes = self.classify_vibes(title, snippet)
                if vibes:
                    from urllib.parse import urlparse
                    domain = urlparse(link).netloc.replace("www.", "")
                    results.append(Event(
                        id=eid, title=title, description=snippet,
                        date=parse_date(date),
                        source=self.source, source_url=link,
                        vibes=vibes, tags=["blog", domain],
                        raw_data=item,
                    ))

        return results
