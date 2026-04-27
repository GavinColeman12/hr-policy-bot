"""SCORE stage — Claude rates each event on quality / popularity / fun / fit.

Inputs: list[Event] from EXTRACT (already deduped).
Output: same events with score_breakdown populated.

Scoring rubric (0.0-1.0 each):
  - quality: data completeness + coherence
  - popularity: engagement signal (likes/comments) normalized
  - fun_factor: how interesting/exciting for the target audience
  - demographic_fit: 20-30 yo locals + travellers
"""

from __future__ import annotations

import json
import logging
import math
from typing import Iterable

import anthropic
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..models import Event, EventVibe

logger = logging.getLogger(__name__)


_SCORE_SYSTEM = """You score upcoming events for a 20-30 year old audience.

For each event, return four scores (0.0 = bad, 1.0 = excellent):
- quality: how complete and trustworthy the event description is
- popularity: how big and buzzy the event is. The provided
  ``engagement_baseline`` (log-scaled likes + comments) is your primary
  signal — use it as the floor and adjust up/down based on whether the
  account_handle looks like a major venue/promoter, whether the lineup is
  recognisable, and whether the description suggests a flagship / sold-out
  show. Big crowds, recognisable venues, and headline acts deserve high
  popularity scores even when raw engagement is moderate.
- fun_factor: how interesting / fun / talked-about it is likely to be
- demographic_fit: how well it fits the 20-30 yo target

Be calibrated, not generous. A score of 0.9+ should be rare. Most events
land in 0.4-0.7. Generic listings or things that look like ads get <0.3."""


class _Score(BaseModel):
    event_id: str
    quality: float
    popularity: float
    fun_factor: float
    demographic_fit: float


class _ScoreBatch(BaseModel):
    scores: list[_Score]


def _engagement_baseline(event: Event) -> float:
    """Log-scaled engagement signal in [0, 1] used as a hint for popularity."""
    raw = (event.likes or 0) + 2 * (event.comments or 0)
    if raw <= 0:
        return 0.0
    return min(1.0, math.log10(raw + 1) / 5.0)  # 100k -> ~1.0


def _event_summary(event: Event) -> dict:
    return {
        "event_id": event.id,
        "title": event.title,
        "description": (event.description or "")[:300],
        "date": event.date.isoformat() if event.date else None,
        "venue": event.venue_name,
        "vibes": [v.value for v in event.vibes],
        "account_handle": event.account_handle,
        "likes": event.likes,
        "comments": event.comments,
        "engagement_baseline": round(_engagement_baseline(event), 3),
    }


async def rate_events(
    events: list[Event],
    vibes: Iterable[EventVibe] | None = None,
) -> list[Event]:
    """Score *events* in place and return them. No-op if API key missing."""
    if not events:
        return []

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — using engagement baseline as score")
        for ev in events:
            base = _engagement_baseline(ev)
            ev.score_breakdown = {
                "quality": 0.5,
                "popularity": base,
                "fun_factor": 0.5,
                "demographic_fit": 0.5,
            }
        return events

    payload = {
        "vibes_requested": [v.value for v in (vibes or [])] or None,
        "events": [_event_summary(e) for e in events],
    }

    schema = {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "quality": {"type": "number"},
                        "popularity": {"type": "number"},
                        "fun_factor": {"type": "number"},
                        "demographic_fit": {"type": "number"},
                    },
                    "required": [
                        "event_id", "quality", "popularity", "fun_factor", "demographic_fit",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["scores"],
        "additionalProperties": False,
    }

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=settings.SCORE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": schema},
            },
            system=_SCORE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
    except anthropic.APIError as exc:
        logger.warning("SCORE Claude call failed: %s", exc)
        return events

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        batch = _ScoreBatch.model_validate_json(text)
    except ValidationError as exc:
        logger.warning("SCORE response failed validation: %s", exc)
        return events

    by_id = {e.id: e for e in events}
    for s in batch.scores:
        ev = by_id.get(s.event_id)
        if ev is None:
            continue
        ev.score_breakdown = {
            "quality": round(max(0.0, min(1.0, s.quality)), 3),
            "popularity": round(max(0.0, min(1.0, s.popularity)), 3),
            "fun_factor": round(max(0.0, min(1.0, s.fun_factor)), 3),
            "demographic_fit": round(max(0.0, min(1.0, s.demographic_fit)), 3),
        }

    logger.info("SCORE: rated %d events", len(batch.scores))
    return events


def composite_score(event: Event) -> float:
    """Weighted average of the four sub-scores; 0 if missing.

    Tuned to favour bigger, more-attended events: popularity gets the
    largest single weight so well-known venues + sold-out shows surface
    above interesting-but-niche picks.
    """
    sb = event.score_breakdown
    if not sb:
        return 0.0
    return round(
        0.20 * sb.get("quality", 0)
        + 0.35 * sb.get("popularity", 0)
        + 0.25 * sb.get("fun_factor", 0)
        + 0.20 * sb.get("demographic_fit", 0),
        3,
    )
