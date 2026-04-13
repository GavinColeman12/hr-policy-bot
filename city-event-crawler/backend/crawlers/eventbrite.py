"""Eventbrite crawler using API v3."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..config import get_settings
from ..models import Event, EventSource, EventVibe
from ..utils.helpers import clean_text, generate_event_id, parse_date
from .base import BaseCrawler

logger = logging.getLogger(__name__)


class EventbriteCrawler(BaseCrawler):
    source = EventSource.EVENTBRITE
    name = "Eventbrite"

    async def crawl(self, city, date, lat, lon, radius_km, vibes=None, **kw):
        settings = get_settings()
        if not settings.EVENTBRITE_TOKEN:
            self._log_warning("EVENTBRITE_TOKEN not configured — skipping")
            return []

        events, seen, page = [], set(), 1
        while page <= 5:
            page_events, has_more = await self._fetch_page(city, date, lat, lon, radius_km, settings.EVENTBRITE_TOKEN, page, seen)
            events.extend(page_events)
            if not has_more:
                break
            page += 1

        self._log_info("Found %d events for %s", len(events), city)
        return self._filter_by_vibes(events, vibes)

    async def _fetch_page(self, city, date, lat, lon, radius_km, token, page, seen):
        dt_start = datetime.strptime(date, "%Y-%m-%d")
        dt_end = dt_start + timedelta(days=1) - timedelta(seconds=1)
        radius_mi = f"{radius_km * 0.621371:.1f}mi"

        resp = await self._get(
            "https://www.eventbriteapi.com/v3/events/search/",
            params={
                "location.latitude": str(lat), "location.longitude": str(lon),
                "location.within": radius_mi,
                "start_date.range_start": dt_start.strftime("%Y-%m-%dT00:00:00"),
                "start_date.range_end": dt_end.strftime("%Y-%m-%dT23:59:59"),
                "expand": "venue,organizer,ticket_availability", "page": page,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if not resp:
            return [], False

        try:
            data = resp.json()
        except Exception:
            return [], False

        results = []
        for item in data.get("events", []):
            eb_id = item.get("id", "")
            eid = generate_event_id(self.source.value, eb_id)
            if eid in seen:
                continue
            seen.add(eid)

            title = item.get("name", {}).get("text", "")
            desc = clean_text(item.get("description", {}).get("text"))
            venue_data = item.get("venue") or {}
            addr_data = venue_data.get("address") or {}
            start_obj = item.get("start", {})
            end_obj = item.get("end", {})
            is_free = item.get("is_free", False)
            logo = item.get("logo") or {}
            organizer_data = item.get("organizer") or {}
            ticket_avail = item.get("ticket_availability") or {}
            min_price = ticket_avail.get("minimum_ticket_price", {})
            price_str = "Free" if is_free else (min_price.get("display") if min_price else None)

            cat_name = item.get("category", {}).get("name", "") if isinstance(item.get("category"), dict) else ""
            sub_name = item.get("subcategory", {}).get("name", "") if isinstance(item.get("subcategory"), dict) else ""

            results.append(Event(
                id=eid, title=title, description=desc,
                date=parse_date(start_obj.get("local"), fallback=date),
                end_date=parse_date(end_obj.get("local")),
                source=self.source, source_url=item.get("url", ""),
                venue_name=venue_data.get("name"), address=addr_data.get("localized_address_display"),
                latitude=_safe_float(addr_data.get("latitude")),
                longitude=_safe_float(addr_data.get("longitude")),
                image_url=logo.get("url"), price=price_str, is_free=is_free,
                attendee_count=item.get("capacity"),
                organizer=organizer_data.get("name"),
                vibes=self.classify_vibes(title, desc, [cat_name, sub_name]),
                tags=[t for t in [cat_name, sub_name] if t],
                raw_data=item,
            ))

        has_more = data.get("pagination", {}).get("has_more_items", False)
        return results, has_more


def _safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
