"""TRIAGE stage — Claude filters discovered IG accounts for fit.

Given a city + vibe filter + raw handle list from DISCOVER, asks Claude to
keep only accounts likely to post real local events for the target audience
(20–30 yo). Falls back to the full list if the API key is missing or the call fails.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

import anthropic

from ..config import get_settings
from ..models import EventVibe

logger = logging.getLogger(__name__)


_TRIAGE_SYSTEM = """You are a local-events scout helping curate Instagram accounts.

For each candidate account handle, decide whether it is likely to post real,
upcoming, attendable events (parties, gigs, club nights, art openings, food
events, queer nights, etc.) in the target city and is appropriate for a
20-30 year old audience.

Reject:
- Generic city/tourism marketing accounts ("welovecity", "visit_X")
- News, media, magazines (unless explicitly events-focused)
- Personal accounts of public figures
- Accounts whose handle clearly suggests something unrelated (real estate,
  fitness influencers, food delivery, etc.)
- Suspected dead/spam accounts

Keep:
- Venues (clubs, bars, cafés, galleries with ongoing programming)
- Promoters and collectives
- Recurring event series
- Niche scenes that match the requested vibes

Respond with a JSON object: {"keep": ["handle1", "handle2", ...]}.
Order kept handles by your confidence, highest first. No prose."""


def _build_user_prompt(city: str, vibes: Iterable[EventVibe] | None, handles: list[str]) -> str:
    vibe_str = ", ".join(v.value for v in vibes) if vibes else "any vibe"
    handle_block = "\n".join(f"- @{h}" for h in handles)
    return (
        f"City: {city}\n"
        f"Requested vibes: {vibe_str}\n"
        f"Target audience: 20-30 year olds, locals + travellers\n\n"
        f"Candidate accounts ({len(handles)}):\n{handle_block}"
    )


async def triage_accounts(
    city: str,
    handles: list[str],
    vibes: Iterable[EventVibe] | None = None,
    max_keep: int = 25,
) -> list[str]:
    """Return the subset of *handles* Claude judges relevant.

    No-op (returns first ``max_keep``) when ANTHROPIC_API_KEY is unset, the
    handle list is short enough to be obviously safe, or the call errors.
    """
    if not handles:
        return []
    if len(handles) <= max_keep:
        logger.info("TRIAGE: %d ≤ %d handles, skipping Claude filter", len(handles), max_keep)
        return handles

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — passing through top %d handles", max_keep)
        return handles[:max_keep]

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=settings.TRIAGE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "low",
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "keep": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["keep"],
                        "additionalProperties": False,
                    },
                },
            },
            system=_TRIAGE_SYSTEM,
            messages=[{"role": "user", "content": _build_user_prompt(city, vibes, handles)}],
        )
    except anthropic.APIError as exc:
        logger.warning("TRIAGE Claude call failed (%s) — passing through top %d", exc, max_keep)
        return handles[:max_keep]

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        parsed = json.loads(text)
        kept_raw = parsed.get("keep", [])
    except (json.JSONDecodeError, AttributeError):
        logger.warning("TRIAGE returned unparseable JSON — passing through top %d", max_keep)
        return handles[:max_keep]

    candidate_set = {h.lower() for h in handles}
    kept: list[str] = []
    seen: set[str] = set()
    for raw in kept_raw:
        h = str(raw).lstrip("@").lower().strip()
        if h in candidate_set and h not in seen:
            kept.append(h)
            seen.add(h)
        if len(kept) >= max_keep:
            break

    logger.info("TRIAGE: %d → %d accounts kept", len(handles), len(kept))
    return kept or handles[:max_keep]
