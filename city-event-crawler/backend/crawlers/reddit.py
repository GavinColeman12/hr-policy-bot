"""Reddit crawler using Reddit API (OAuth2)."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

# City-specific subreddit mappings
CITY_SUBREDDITS = {
    "budapest": ["budapest", "hungary"],
    "berlin": ["berlin", "berlinsocialclub", "berlintechno"],
    "prague": ["prague", "czech"],
    "barcelona": ["barcelona"],
    "amsterdam": ["amsterdam", "amsterdamsocialclub"],
    "lisbon": ["lisbon", "portugal"],
    "vienna": ["vienna", "wien"],
    "warsaw": ["warsaw", "poland"],
    "krakow": ["krakow"],
    "belgrade": ["belgrade", "serbia"],
    "london": ["london", "londonsocialclub"],
    "paris": ["paris", "socialparis"],
    "rome": ["rome"],
    "athens": ["athens"],
    "dublin": ["dublin", "ireland"],
    "copenhagen": ["copenhagen"],
    "munich": ["munich"],
    "milan": ["milan"],
}

SEARCH_QUERIES = [
    "events this week",
    "things to do",
    "nightlife",
    "party tonight",
    "what's happening",
    "meetup",
    "social event",
]


class RedditCrawler(BaseCrawler):
    source = EventSource.REDDIT
    name = "Reddit"

    _access_token: str | None = None

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
            self._log_warning("Reddit credentials not configured — skipping")
            return []

        await self._authenticate(settings)
        if not self._access_token:
            return []

        city_lower = city.lower().strip()
        subreddits = CITY_SUBREDDITS.get(city_lower, [city_lower])
        subreddits.append("solotravel")

        events = []
        seen = set()

        for sub in subreddits[:4]:
            for query in SEARCH_QUERIES[:3]:
                results = await self._search_subreddit(sub, query, city, date, seen)
                events.extend(results)

        self._log_info("Found %d events from Reddit for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _authenticate(self, settings):
        import base64
        auth = base64.b64encode(
            f"{settings.REDDIT_CLIENT_ID}:{settings.REDDIT_CLIENT_SECRET}".encode()
        ).decode()
        resp = await self._post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": settings.REDDIT_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp:
            try:
                self._access_token = resp.json().get("access_token")
            except Exception:
                pass

    async def _search_subreddit(self, subreddit, query, city, date, seen):
        if not self._access_token:
            return []

        resp = await self._get(
            f"https://oauth.reddit.com/r/{subreddit}/search",
            params={"q": query, "sort": "new", "t": "week", "limit": 25, "restrict_sr": "true"},
            headers={"Authorization": f"Bearer {self._access_token}", "User-Agent": "CityEventCrawler/1.0"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        children = data.get("data", {}).get("children", [])
        for child in children:
            post = child.get("data", {})
            title = post.get("title", "")
            eid = generate_event_id(self.source.value, post.get("id", title))
            if eid in seen:
                continue
            seen.add(eid)

            body = clean_text(post.get("selftext", ""))
            permalink = post.get("permalink", "")
            source_url = f"https://www.reddit.com{permalink}" if permalink else ""
            vibes = self.classify_vibes(title, body)

            if not vibes:
                continue

            results.append(Event(
                id=eid, title=title, description=body,
                date=parse_date(date),
                source=self.source, source_url=source_url,
                likes=post.get("ups", 0),
                comments=post.get("num_comments", 0),
                vibes=vibes,
                tags=[f"r/{subreddit}"],
                organizer=f"u/{post.get('author', 'unknown')}",
                raw_data={"subreddit": subreddit, "post_id": post.get("id")},
            ))

        return results
