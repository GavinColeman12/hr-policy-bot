"""CURATE stage — Claude composes the EveningGuide and tags events with a tier.

Given scored events, asks Claude to:
- pick a single ``top_pick``
- order 3-5 events into an itinerary (chronologically/spatially sensible)
- nominate 2-3 ``hidden_gem`` picks
- list ``skip`` IDs (low-quality or off-target)
- write a ~80-word summary plus a one-line demographic note

Mutates each Event's ``curation_tier`` and ``suggested_itinerary_position``
in place.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

import anthropic
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..models import Event, EveningGuide, EventVibe
from .score import composite_score

logger = logging.getLogger(__name__)


_CURATE_SYSTEM = """You are a tastemaker writing an evening guide for a 20-30 year old.

Given a scored list of upcoming Instagram-discovered events, produce:
- summary_text: ~80 words, second-person, evocative but specific
- demographic_note: one short line (e.g. "Best for techno-curious locals")
- top_pick_id: the single biggest, most-buzzy event of the night. Prefer
  events with high popularity scores and strong engagement (likes,
  comments, attendee signal) — readers want to be where the action is. Only
  override popularity for top_pick when an event is conspicuously stronger
  on quality + fun_factor + demographic_fit combined.
- itinerary_ids: 3-5 events ordered as a feasible night out (early → late).
  The list MUST include the top_pick. Mix headliners with at least one
  early/light option so the night has shape.
- hidden_gem_ids: 2-3 under-the-radar picks worth highlighting — events
  with lower popularity but strong quality and fun_factor. Do NOT include
  the top_pick or anything in skip_ids.
- skip_ids: events you'd actively recommend skipping (weak data, off-target,
  obvious filler, low scores across the board) — empty list is fine.

Use only event IDs that appear in the input. Be opinionated. The itinerary
should feel like a curated evening, not a list of unrelated highlights."""


class _GuideOut(BaseModel):
    summary_text: str
    demographic_note: str
    top_pick_id: str | None = None
    itinerary_ids: list[str] = []
    hidden_gem_ids: list[str] = []
    skip_ids: list[str] = []


def _event_brief(event: Event) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "date": event.date.isoformat() if event.date else None,
        "venue": event.venue_name,
        "vibes": [v.value for v in event.vibes],
        "account_handle": event.account_handle,
        "score_breakdown": event.score_breakdown,
        "composite": composite_score(event),
        "engagement_score": event.engagement_score,
    }


def _apply_guide(events: list[Event], guide: EveningGuide) -> None:
    """Tag events with curation_tier + itinerary position based on the guide."""
    by_id = {e.id: e for e in events}

    skip_set = {sid for sid in guide.skip_ids if sid in by_id}
    gem_set = {gid for gid in guide.hidden_gem_ids if gid in by_id and gid not in skip_set}
    top_id = guide.top_pick_id if guide.top_pick_id in by_id else None
    if top_id and (top_id in skip_set or top_id in gem_set):
        # don't double-tier
        gem_set.discard(top_id)
        skip_set.discard(top_id)

    for ev in events:
        if ev.id == top_id:
            ev.curation_tier = "top_pick"
        elif ev.id in skip_set:
            ev.curation_tier = "skip"
        elif ev.id in gem_set:
            ev.curation_tier = "hidden_gem"
        else:
            ev.curation_tier = "standard"

    for pos, eid in enumerate(guide.itinerary_ids[:5]):
        if eid in by_id:
            by_id[eid].suggested_itinerary_position = pos


async def compose_guide(
    events: list[Event],
    city: str,
    vibes: Iterable[EventVibe] | None = None,
) -> EveningGuide | None:
    """Run CURATE Claude call. Mutates *events* with tier assignments.

    Returns None when there's nothing to curate or the API call fails.
    """
    if not events:
        return None

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — falling back to score-based curation")
        return _fallback_guide(events, city, vibes)

    payload = {
        "city": city,
        "vibes_requested": [v.value for v in (vibes or [])] or None,
        "events": [_event_brief(e) for e in events],
    }

    schema = {
        "type": "object",
        "properties": {
            "summary_text": {"type": "string"},
            "demographic_note": {"type": "string"},
            "top_pick_id": {"type": ["string", "null"]},
            "itinerary_ids": {"type": "array", "items": {"type": "string"}},
            "hidden_gem_ids": {"type": "array", "items": {"type": "string"}},
            "skip_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "summary_text", "demographic_note", "itinerary_ids",
            "hidden_gem_ids", "skip_ids",
        ],
        "additionalProperties": False,
    }

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=settings.CURATE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": schema},
            },
            system=_CURATE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
    except anthropic.APIError as exc:
        logger.warning("CURATE Claude call failed: %s", exc)
        return _fallback_guide(events, city, vibes)

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        parsed = _GuideOut.model_validate_json(text)
    except ValidationError as exc:
        logger.warning("CURATE response failed validation: %s", exc)
        return _fallback_guide(events, city, vibes)

    guide = EveningGuide(
        summary_text=parsed.summary_text.strip(),
        demographic_note=parsed.demographic_note.strip(),
        top_pick_id=parsed.top_pick_id,
        itinerary_ids=parsed.itinerary_ids,
        hidden_gem_ids=parsed.hidden_gem_ids,
        skip_ids=parsed.skip_ids,
    )
    _apply_guide(events, guide)
    logger.info("CURATE: top=%s, itinerary=%d, gems=%d, skips=%d",
                guide.top_pick_id, len(guide.itinerary_ids),
                len(guide.hidden_gem_ids), len(guide.skip_ids))
    return guide


def _fallback_guide(
    events: list[Event],
    city: str,
    vibes: Iterable[EventVibe] | None,
) -> EveningGuide:
    """Rule-based curation used when Claude is unavailable."""
    ranked = sorted(events, key=composite_score, reverse=True)
    top = ranked[0] if ranked else None
    itinerary = sorted(ranked[:5], key=lambda e: e.date or e.id)
    hidden = ranked[5:8]

    guide = EveningGuide(
        summary_text=(
            f"Here are the most interesting events surfaced from local Instagram "
            f"accounts in {city}. Sorted by quality, popularity, and fit."
        ),
        demographic_note=(
            "Selection tuned for 20-30 year olds, prioritising "
            + (", ".join(v.value for v in vibes) if vibes else "varied vibes")
            + "."
        ),
        top_pick_id=top.id if top else None,
        itinerary_ids=[e.id for e in itinerary],
        hidden_gem_ids=[e.id for e in hidden],
        skip_ids=[],
    )
    _apply_guide(events, guide)
    return guide
