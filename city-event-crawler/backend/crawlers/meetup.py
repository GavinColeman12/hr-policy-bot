"""Meetup crawler using GraphQL API."""

from __future__ import annotations

import logging
from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)

SEARCH_QUERY = """
query($filter: SearchConnectionFilter!) {
  searchByFilter(filter: $filter) {
    count
    edges {
      node {
        id
        result {
          ... on Event {
            id title description dateTime endTime eventUrl going maxTickets
            venue { name address city lat lng }
            fee { amount currency }
            group { name memberships { count } }
            images { baseUrl }
            topics { edges { node { name } } }
          }
        }
      }
    }
  }
}
"""


class MeetupCrawler(BaseCrawler):
    source = EventSource.MEETUP
    name = "Meetup"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        events, seen = [], set()
        results = await self._search_events(city, date, lat, lon, radius_km, seen)
        events.extend(results)
        self._log_info("Found %d events from Meetup for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _search_events(self, city, date, lat, lon, radius_km, seen):
        variables = {
            "filter": {
                "query": city, "lat": lat, "lon": lon,
                "radius": int(radius_km),
                "startDateRange": f"{date}T00:00:00-00:00",
                "endDateRange": f"{date}T23:59:59-00:00",
                "eventType": "PHYSICAL",
                "numberOfEventsVisibleToGuest": 50,
            }
        }

        resp = await self._post(
            "https://api.meetup.com/gql",
            json={"query": SEARCH_QUERY, "variables": variables},
            headers={"Content-Type": "application/json"},
        )
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        results = []
        search_data = (data.get("data") or {}).get("searchByFilter") or {}
        for edge in search_data.get("edges", []):
            node = (edge.get("node") or {}).get("result", {})
            if not node or not node.get("title"):
                continue

            mu_id = str(node.get("id", ""))
            eid = generate_event_id(self.source.value, mu_id)
            if eid in seen:
                continue
            seen.add(eid)

            venue = node.get("venue") or {}
            fee = node.get("fee") or {}
            group = node.get("group") or {}
            images = node.get("images") or []
            topics = [e.get("node", {}).get("name", "") for e in (node.get("topics", {}) or {}).get("edges", [])]

            is_free = not fee.get("amount") or fee["amount"] == 0
            price_str = "Free" if is_free else f"{fee['amount']} {fee.get('currency', 'EUR')}"

            results.append(Event(
                id=eid, title=node.get("title", ""),
                description=clean_text(node.get("description")),
                date=parse_date(node.get("dateTime"), fallback=date),
                end_date=parse_date(node.get("endTime")),
                source=self.source, source_url=node.get("eventUrl", ""),
                venue_name=venue.get("name"), address=venue.get("address"),
                latitude=venue.get("lat"), longitude=venue.get("lng"),
                image_url=images[0].get("baseUrl") if images else None,
                price=price_str, is_free=is_free,
                attendee_count=node.get("going"),
                organizer=group.get("name"),
                vibes=self.classify_vibes(node.get("title", ""), node.get("description"), topics),
                tags=topics, raw_data=node,
            ))

        return results
