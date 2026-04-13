"""Twitter/X crawler using API v2."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

SEARCH_TEMPLATES = [
    '"{city}" event tonight -is:retweet',
    '"{city}" party tonight -is:retweet',
    '#{city_tag}events -is:retweet',
    '"{city}" club night -is:retweet',
    '"{city}" things to do -is:retweet',
]


class TwitterCrawler(BaseCrawler):
    source = EventSource.TWITTER
    name = "Twitter/X"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.TWITTER_BEARER_TOKEN:
            self._log_warning("TWITTER_BEARER_TOKEN not configured — skipping")
            return []

        city_tag = city.lower().replace(" ", "").replace("-", "")
        events, seen = [], set()

        for tpl in SEARCH_TEMPLATES:
            query = tpl.format(city=city, city_tag=city_tag)
            results = await self._search_tweets(query, city, date, lat, lon, radius_km, settings.TWITTER_BEARER_TOKEN, seen)
            events.extend(results)

        self._log_info("Found %d events from Twitter for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_tweets(self, query, city, date, lat, lon, radius_km, token, seen):
        params = {
            "query": query,
            "max_results": 50,
            "tweet.fields": "created_at,public_metrics,entities,geo",
            "expansions": "author_id,geo.place_id",
            "user.fields": "username,name",
            "place.fields": "full_name,geo",
        }

        resp = await self._get(
            "https://api.twitter.com/2/tweets/search/recent",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        # Build user lookup
        includes = data.get("includes", {})
        users = {u["id"]: u for u in includes.get("users", [])}

        results = []
        for tweet in data.get("data", []):
            tid = tweet.get("id", "")
            eid = generate_event_id(self.source.value, tid)
            if eid in seen:
                continue
            seen.add(eid)

            text = tweet.get("text", "")
            vibes = self.classify_vibes(text)
            if not vibes:
                continue

            metrics = tweet.get("public_metrics", {})
            author_id = tweet.get("author_id", "")
            author = users.get(author_id, {})
            username = author.get("username", "")

            # Extract URLs from tweet
            entities = tweet.get("entities", {})
            urls = entities.get("urls", [])
            event_url = urls[0].get("expanded_url") if urls else f"https://twitter.com/i/web/status/{tid}"

            results.append(Event(
                id=eid, title=text[:120], description=text,
                date=parse_date(tweet.get("created_at"), fallback=date),
                source=self.source, source_url=f"https://twitter.com/{username}/status/{tid}" if username else f"https://twitter.com/i/web/status/{tid}",
                likes=metrics.get("like_count", 0),
                comments=metrics.get("reply_count", 0),
                vibes=vibes,
                organizer=f"@{username}" if username else None,
                tags=["twitter"],
                raw_data={"tweet_id": tid, "retweets": metrics.get("retweet_count", 0)},
            ))

        return results
