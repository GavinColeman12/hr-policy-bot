"""Dice.fm crawler for live music, club nights, and cultural events."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

# Dice.fm city slugs
DICE_CITIES = {
    "london": "london", "berlin": "berlin", "paris": "paris",
    "barcelona": "barcelona", "amsterdam": "amsterdam", "lisbon": "lisbon",
    "madrid": "madrid", "milan": "milan", "rome": "rome",
    "budapest": "budapest", "prague": "prague", "vienna": "vienna",
    "dublin": "dublin", "copenhagen": "copenhagen", "stockholm": "stockholm",
    "brussels": "brussels", "hamburg": "hamburg", "munich": "munich",
    "warsaw": "warsaw", "athens": "athens", "istanbul": "istanbul",
}


class DiceCrawler(BaseCrawler):
    """Crawls Dice.fm for live music and club events.

    Dice.fm is particularly strong for electronic music, live performances,
    and curated club nights across European cities.
    """

    source = EventSource.DICE
    name = "Dice.fm"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        city_lower = city.lower().strip()
        dice_slug = DICE_CITIES.get(city_lower, city_lower)

        events = []
        seen = set()

        # Try the Dice API
        api_events = await self._fetch_api(dice_slug, date, seen)
        events.extend(api_events)

        # Fallback: scrape the Dice website
        if not events:
            scrape_events = await self._fetch_scrape(dice_slug, date, seen)
            events.extend(scrape_events)

        # Auto-tag music/nightlife for Dice events
        for ev in events:
            if EventVibe.MUSIC not in ev.vibes:
                ev.vibes.append(EventVibe.MUSIC)

        self._log_info("Found %d events from Dice.fm for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _fetch_api(self, city_slug, date, seen):
        """Try fetching from Dice's internal API."""
        resp = await self._get(
            f"https://api.dice.fm/v1/events",
            params={
                "filter[venues][city]": city_slug,
                "filter[date]": date,
                "page[size]": 50,
            },
            headers={
                "Accept": "application/json",
                "x-dice-version": "3.0",
            },
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        for item in data if isinstance(data, list) else data.get("data", []):
            dice_id = str(item.get("id", ""))
            eid = generate_event_id(self.source.value, dice_id)
            if eid in seen:
                continue
            seen.add(eid)

            attrs = item.get("attributes", item)
            venue = attrs.get("venue", {}) or {}

            # Get ticket info
            price_str = None
            ticket_info = attrs.get("ticket_types", []) or attrs.get("tickets", [])
            if ticket_info:
                prices = [t.get("price", {}).get("total") for t in ticket_info if isinstance(t, dict) and t.get("price")]
                if prices:
                    min_p = min(p for p in prices if p)
                    price_str = f"From {min_p/100:.2f} EUR" if min_p else None

            results.append(Event(
                id=eid,
                title=attrs.get("name", attrs.get("title", "")),
                description=clean_text(attrs.get("description") or attrs.get("raw_description")),
                date=parse_date(attrs.get("date") or attrs.get("starts_at"), fallback=date),
                end_date=parse_date(attrs.get("ends_at")),
                source=self.source,
                source_url=attrs.get("url") or f"https://dice.fm/event/{dice_id}",
                venue_name=venue.get("name"),
                address=venue.get("address"),
                latitude=venue.get("latitude"),
                longitude=venue.get("longitude"),
                image_url=attrs.get("image_url") or attrs.get("cover_image"),
                price=price_str,
                attendee_count=attrs.get("sales_count") or attrs.get("going_count"),
                vibes=self.classify_vibes(
                    attrs.get("name", ""),
                    attrs.get("description"),
                    attrs.get("genres", []),
                ),
                tags=attrs.get("genres", []) or [],
                raw_data=item,
            ))

        return results

    async def _fetch_scrape(self, city_slug, date, seen):
        """Fallback: scrape the Dice.fm website."""
        url = f"https://dice.fm/browse/{city_slug}?date={date}"
        resp = await self._get(url, headers={"Accept": "text/html"})
        if not resp:
            return []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
        except ImportError:
            return []

        results = []
        for card in soup.select("[class*='EventCard'], [class*='event-card'], a[href*='/event/']"):
            title_el = card.select_one("h3, h4, [class*='title'], [class*='name']")
            if not title_el:
                if card.name == "a" and card.get_text(strip=True):
                    title = card.get_text(strip=True)[:120]
                else:
                    continue
            else:
                title = title_el.get_text(strip=True)

            eid = generate_event_id(self.source.value, title, date)
            if eid in seen:
                continue
            seen.add(eid)

            link = card.get("href", "") if card.name == "a" else ""
            if not link:
                link_el = card.select_one("a[href]")
                link = link_el.get("href", "") if link_el else ""
            if link and not link.startswith("http"):
                link = f"https://dice.fm{link}"

            venue_el = card.select_one("[class*='venue'], [class*='location']")
            venue_name = venue_el.get_text(strip=True) if venue_el else None

            results.append(Event(
                id=eid, title=title,
                date=parse_date(date),
                source=self.source, source_url=link or url,
                venue_name=venue_name,
                vibes=self.classify_vibes(title),
                tags=["dice.fm"],
                raw_data={"scraped": True},
            ))

        return results
