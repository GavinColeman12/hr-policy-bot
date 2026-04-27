"""EXTRACT stage — Claude turns raw IG posts into Event structs.

Input: list of Apify post dicts from SCRAPE.
Output: list of Event objects with title, description, date, venue, vibes.

Uses structured outputs to constrain Claude's response to a fixed schema.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..models import Event, EventSource, EventVibe

logger = logging.getLogger(__name__)


_VIBE_VALUES = [v.value for v in EventVibe]

_EXTRACT_SYSTEM = """You parse Instagram items (posts and stories) into structured event records.

Each input item has a ``content_type`` of either ``post`` or ``story``. Stories
are short-lived (24h) and often used for last-minute "tonight only"
announcements; treat them as authoritative when they describe an event.
Posts may be more polished but can be older.

For each item, decide whether the content describes a specific upcoming event
that someone could attend. If yes, extract:
- title: short event name (≤120 chars, no emojis or hashtags)
- description: cleaned-up summary (≤400 chars, plain text)
- date_iso: best guess of the event date in YYYY-MM-DD format. Use the
  reference_date provided unless the content clearly states another date.
- start_time: HH:MM 24h, or null if not stated
- venue_name: physical venue / location, or null
- vibes: 1-3 from this exact list: """ + ", ".join(_VIBE_VALUES) + """
  Definitions:
    open_air    — daytime / outdoor / open-air DJ sets, rooftop sessions, park events
    club_night  — late-night club nights (typically doors after 22:00, indoor)
    mingle      — events where the goal is meeting people: mixers, language
                  exchanges, expat meetups, singles events, social brunches
    headliner   — big concerts or marquee DJ sets with a recognised headline act,
                  festival mainstages, sold-out arena-scale shows
    play_party  — kink scene events: play parties, fetish nights, munches,
                  shibari workshops, kink-friendly social events
    other       — anything that doesn't fit the above
- end_time: HH:MM 24h end / close time, or null. For overnight events,
  use the closing hour (e.g. 06:00 if it goes till morning).
- min_age: integer minimum age (18, 21, etc.) if explicitly stated, else null.
- lineup: list of headliner names — DJs, bands, performers, in billing order if
  apparent. Empty list if none mentioned. Strip "feat.", "presents", etc.
- crowd_note: one short line (max 80 chars) describing who'd dig this. Examples:
  "Techno-curious locals", "First-Friday gallery crowd", "Queer dancefloor regulars".
  Null if you can't infer it confidently.
- is_event: true if it's a real upcoming attendable event, false otherwise
- confidence: 0.0-1.0 — how sure are you this is a real event with the data above

Skip merch posts, throwback photos, generic vibe shots, and "follow us"
posts. For stories, accept terse content ("doors at 22 tonight") if the venue
context is clear. Be conservative: when in doubt, set is_event=false."""


class _ExtractedEvent(BaseModel):
    post_index: int
    is_event: bool
    confidence: float
    title: str
    description: str | None = None
    date_iso: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    venue_name: str | None = None
    vibes: list[str] = []
    min_age: int | None = None
    lineup: list[str] = []
    crowd_note: str | None = None


class _ExtractBatch(BaseModel):
    events: list[_ExtractedEvent]


def _post_summary(item: dict[str, Any], idx: int) -> dict[str, Any]:
    """Reduce a raw Apify item (post or story) to fields the model needs."""
    origin = item.get("_origin", "profile")
    content_type = "story" if origin == "story" else "post"

    caption = item.get("caption") or item.get("text") or ""
    location = item.get("locationName") or ""
    if not location and isinstance(item.get("location"), dict):
        location = item["location"].get("name", "")
    owner = (
        item.get("ownerUsername")
        or item.get("username")
        or (item.get("owner") or {}).get("username")
        or (item.get("user") or {}).get("username")
        or ""
    )
    return {
        "index": idx,
        "content_type": content_type,
        "owner": owner,
        "caption": caption[:1500],
        "location_hint": location or None,
        "timestamp": item.get("timestamp") or item.get("takenAt") or item.get("posted_at"),
        "shortcode": item.get("shortCode") or item.get("shortcode") or item.get("id"),
    }


def _to_event(parsed: _ExtractedEvent, item: dict[str, Any], reference_date: str) -> Event | None:
    """Build an Event from Claude's parsed record + the original item."""
    if not parsed.is_event or parsed.confidence < 0.4:
        return None

    shortcode = item.get("shortCode") or item.get("shortcode") or item.get("id") or ""
    owner = (
        item.get("ownerUsername")
        or item.get("username")
        or (item.get("owner") or {}).get("username")
        or (item.get("user") or {}).get("username")
        or ""
    )

    raw_date = (parsed.date_iso or reference_date).strip()
    raw_time = (parsed.start_time or "20:00").strip()
    try:
        dt = datetime.fromisoformat(f"{raw_date}T{raw_time}")
    except ValueError:
        try:
            dt = datetime.fromisoformat(reference_date + "T20:00")
        except ValueError:
            return None

    # End time: if it's earlier than start_time it means the event runs past
    # midnight, so roll to the next day.
    end_dt: datetime | None = None
    if parsed.end_time:
        try:
            end_dt = datetime.fromisoformat(f"{raw_date}T{parsed.end_time.strip()}")
            if end_dt <= dt:
                end_dt = end_dt + timedelta(days=1)
        except ValueError:
            end_dt = None

    def _safe_int(v):
        try:
            n = int(v) if v is not None else None
            return n if n is not None and n >= 0 else None
        except (ValueError, TypeError):
            return None

    vibes: list[EventVibe] = []
    for v in parsed.vibes:
        try:
            vibes.append(EventVibe(v))
        except ValueError:
            continue

    eid = Event.generate_id(EventSource.INSTAGRAM, shortcode or f"{owner}-{parsed.title[:40]}")
    origin = item.get("_origin", "profile")
    if origin == "story":
        scrape_source = "story"
        source_url = (
            f"https://www.instagram.com/stories/{owner}/{shortcode}/"
            if owner else "https://www.instagram.com/"
        )
    else:
        scrape_source = "profile"
        source_url = (
            f"https://www.instagram.com/p/{shortcode}/"
            if shortcode else f"https://www.instagram.com/{owner}/"
        )

    # Strip + dedupe lineup, cap at 8 to avoid wall-of-names cards.
    seen_artists: set[str] = set()
    lineup: list[str] = []
    for raw_name in parsed.lineup or []:
        name = raw_name.strip()
        key = name.lower()
        if name and key not in seen_artists:
            seen_artists.add(key)
            lineup.append(name)
        if len(lineup) >= 8:
            break

    return Event(
        id=eid,
        title=parsed.title.strip()[:200],
        description=parsed.description,
        date=dt,
        end_date=end_dt,
        source=EventSource.INSTAGRAM,
        source_url=source_url,
        venue_name=parsed.venue_name,
        image_url=item.get("displayUrl") or item.get("imageUrl") or item.get("media_url") or item.get("url"),
        likes=_safe_int(item.get("likesCount") or item.get("likes")),
        comments=_safe_int(item.get("commentsCount") or item.get("comments")),
        vibes=vibes,
        organizer=f"@{owner}" if owner else None,
        account_handle=owner or None,
        scrape_source=scrape_source,
        tags=[f"@{owner}"] if owner else [],
        min_age=parsed.min_age,
        lineup=lineup,
        crowd_note=(parsed.crowd_note or "").strip()[:120] or None,
        raw_data={
            "shortcode": shortcode,
            "origin": origin,
            "extract_confidence": parsed.confidence,
        },
    )


async def parse_events(posts: list[dict[str, Any]], reference_date: str) -> list[Event]:
    """Run Claude EXTRACT over *posts*, return parsed Events.

    Posts are sent in a single batch via the structured-outputs API. If the
    Anthropic key is missing or the call errors, returns []. The pipeline
    upstream short-circuits gracefully when this returns nothing.
    """
    if not posts:
        return []

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — skipping EXTRACT")
        return []

    summaries = [_post_summary(p, i) for i, p in enumerate(posts)]
    user_payload = json.dumps({"reference_date": reference_date, "posts": summaries}, indent=2)

    schema = {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "post_index": {"type": "integer"},
                        "is_event": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "title": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "date_iso": {"type": ["string", "null"]},
                        "start_time": {"type": ["string", "null"]},
                        "end_time": {"type": ["string", "null"]},
                        "venue_name": {"type": ["string", "null"]},
                        "vibes": {"type": "array", "items": {"type": "string"}},
                        "min_age": {"type": ["integer", "null"]},
                        "lineup": {"type": "array", "items": {"type": "string"}},
                        "crowd_note": {"type": ["string", "null"]},
                    },
                    "required": [
                        "post_index", "is_event", "confidence", "title", "vibes",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["events"],
        "additionalProperties": False,
    }

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=settings.EXTRACT_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": schema},
            },
            system=_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": user_payload}],
        )
    except anthropic.APIError as exc:
        logger.warning("EXTRACT Claude call failed: %s", exc)
        return []

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        batch = _ExtractBatch.model_validate_json(text)
    except ValidationError as exc:
        logger.warning("EXTRACT response failed validation: %s", exc)
        return []

    events: list[Event] = []
    for parsed in batch.events:
        if 0 <= parsed.post_index < len(posts):
            ev = _to_event(parsed, posts[parsed.post_index], reference_date)
            if ev:
                events.append(ev)

    logger.info("EXTRACT: %d posts → %d events", len(posts), len(events))
    return events
