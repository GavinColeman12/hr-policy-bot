"""Instagram crawler using Apify scraper for event discovery."""

from __future__ import annotations

import logging
import re
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

CITY_HASHTAGS = {
    "budapest": ["budapestevents", "budapestnightlife", "budapestparty", "budapesttonight", "ruinbar", "budapestclub"],
    "berlin": ["berlinevents", "berlinnightlife", "berlintechno", "berlinparty", "berlinrave", "berlinclub"],
    "prague": ["pragueevents", "praguenightlife", "pragueparty", "praguetonight"],
    "barcelona": ["barcelonaevents", "barcelonanightlife", "barcelonaparty", "barcelonatonight"],
    "amsterdam": ["amsterdamevents", "amsterdamnightlife", "amsterdamparty", "amsterdamtonight"],
    "lisbon": ["lisbonevents", "lisbonnightlife", "lisbonparty"],
    "vienna": ["viennaevents", "viennanightlife", "viennaparty"],
    "warsaw": ["warsawevents", "warsawnightlife", "warsawparty"],
    "london": ["londonevents", "londonnightlife", "londonparty", "londontonight"],
    "paris": ["parisevents", "parisnightlife", "parisparty"],
}


class InstagramCrawler(BaseCrawler):
    source = EventSource.INSTAGRAM
    name = "Instagram"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.INSTAGRAM_APIFY_TOKEN:
            self._log_warning("INSTAGRAM_APIFY_TOKEN not configured — skipping")
            return []

        city_lower = city.lower().strip()
        city_tag = city_lower.replace(" ", "").replace("-", "")
        hashtags = CITY_HASHTAGS.get(city_lower, [f"{city_tag}events", f"{city_tag}nightlife", f"{city_tag}party"])

        events, seen = [], set()
        for tag in hashtags[:6]:
            results = await self._search_hashtag(tag, city, date, settings.INSTAGRAM_APIFY_TOKEN, seen)
            events.extend(results)

        self._log_info("Found %d events from Instagram for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_hashtag(self, hashtag, city, date, token, seen):
        resp = await self._post(
            "https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/run-sync-get-dataset-items",
            params={"token": token},
            json={"hashtags": [hashtag], "resultsLimit": 30, "resultsType": "posts"},
        )
        if not resp:
            return []

        try:
            posts = resp.json()
        except Exception:
            return []

        if not isinstance(posts, list):
            return []

        results = []
        for post in posts:
            caption = post.get("caption", "") or ""
            if not self._looks_like_event(caption):
                continue

            shortcode = post.get("shortCode", post.get("id", ""))
            eid = generate_event_id(self.source.value, shortcode)
            if eid in seen:
                continue
            seen.add(eid)

            event_title = self._extract_title(caption)
            location = post.get("locationName") or (post.get("location", {}).get("name") if isinstance(post.get("location"), dict) else None)

            results.append(Event(
                id=eid, title=event_title,
                description=clean_text(caption[:1000]),
                date=parse_date(post.get("timestamp"), fallback=date),
                source=self.source,
                source_url=f"https://www.instagram.com/p/{shortcode}/" if shortcode else "https://www.instagram.com",
                venue_name=location,
                image_url=post.get("displayUrl") or post.get("imageUrl"),
                likes=post.get("likesCount", 0),
                comments=post.get("commentsCount", 0),
                vibes=self.classify_vibes(event_title, caption),
                tags=[f"#{hashtag}"],
                organizer=post.get("ownerUsername"),
                raw_data={"shortcode": shortcode, "hashtag": hashtag},
            ))

        return results

    def _looks_like_event(self, caption):
        event_indicators = [
            r'\b\d{1,2}[./]\d{1,2}\b', r'\b\d{1,2}:\d{2}\b',
            r'tickets?\b', r'entry\b', r'doors?\s*(open|at)',
            r'tonight\b', r'this\s+(friday|saturday|sunday|weekend)',
            r'lineup\b', r'line-up\b', r'featuring\b',
            r'rsvp\b', r'free\s+entry', r'guestlist',
            r'join\s+us', r'come\s+(join|party|dance)',
            r'event\b', r'party\b', r'club\s+night',
            r'dj\s+set', r'live\s+music', r'concert',
        ]
        caption_lower = caption.lower()
        return sum(1 for p in event_indicators if re.search(p, caption_lower)) >= 2

    def _extract_title(self, caption):
        for line in caption.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("@"):
                title = re.sub(r'^[\U0001F000-\U0001FFFF\s]+', '', line)
                if title and len(title) > 3:
                    return title[:150]
        return caption[:100]
