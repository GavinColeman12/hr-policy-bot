"""Ranker Agent - ranks events by popularity and engagement."""

import logging
import math
from .base_agent import BaseAgent, AgentRole, AgentResult

logger = logging.getLogger(__name__)


class RankerAgent(BaseAgent):
    """Ranks events by popularity using weighted engagement scoring.

    Scoring formula:
    - Attendee count:  weight 3.0 (people committed to going)
    - Interested count: weight 1.5 (people considering)
    - Comments:         weight 2.0 (active discussion = high interest)
    - Likes:            weight 1.0 (passive interest)

    Bonuses:
    - Has image:        +5 (better curated event)
    - Has description:  +3 (more info = more legit)
    - Has price info:   +2 (organized event)
    - Multiple sources: +10 per additional source (cross-platform validation)
    - Data quality:     multiplied by quality_score

    Uses log scaling so a 10k-person festival doesn't completely drown out
    a cool 20-person meetup.
    """

    role = AgentRole.RANKER
    name = "Ranker"

    # Engagement weights
    WEIGHT_ATTENDEES = 3.0
    WEIGHT_INTERESTED = 1.5
    WEIGHT_COMMENTS = 2.0
    WEIGHT_LIKES = 1.0

    # Bonus points
    BONUS_IMAGE = 5.0
    BONUS_DESCRIPTION = 3.0
    BONUS_PRICE_INFO = 2.0
    BONUS_VENUE = 3.0

    async def execute(self, context: dict) -> AgentResult:
        events = context.get("events", [])
        vibes_filter = context.get("vibes")
        sort_by = context.get("sort_by", "engagement")
        user_lat = context.get("latitude")
        user_lon = context.get("longitude")

        if not events:
            return AgentResult(agent=self.role, success=True, data=[], metadata={"ranked": 0})

        logger.info(f"Ranking {len(events)} events by {sort_by}")

        # Score each event
        for event in events:
            event.engagement_score = self._compute_engagement_score(event)

        # Filter by vibes if specified
        if vibes_filter:
            vibe_values = {v.value if hasattr(v, 'value') else str(v) for v in vibes_filter}
            events = [
                e for e in events
                if any(
                    (v.value if hasattr(v, 'value') else str(v)) in vibe_values
                    for v in (e.vibes or [])
                )
            ]

        # Sort
        if sort_by == "engagement":
            events.sort(key=lambda e: e.engagement_score or 0, reverse=True)
        elif sort_by == "distance" and user_lat and user_lon:
            events.sort(key=lambda e: e.distance_km if e.distance_km is not None else float('inf'))
        elif sort_by == "date":
            events.sort(key=lambda e: e.date or "9999")
        elif sort_by == "price":
            events.sort(key=lambda e: (0 if e.is_free else 1, e.price or "zzz"))
        else:
            events.sort(key=lambda e: e.engagement_score or 0, reverse=True)

        # Assign rank
        for i, event in enumerate(events):
            if event.raw_data is None:
                event.raw_data = {}
            event.raw_data["rank"] = i + 1

        score_distribution = {
            "max": max((e.engagement_score or 0) for e in events) if events else 0,
            "min": min((e.engagement_score or 0) for e in events) if events else 0,
            "avg": sum((e.engagement_score or 0) for e in events) / len(events) if events else 0,
        }

        return AgentResult(
            agent=self.role,
            success=True,
            data=events,
            metadata={
                "ranked": len(events),
                "sort_by": sort_by,
                "score_distribution": score_distribution,
            },
        )

    def _compute_engagement_score(self, event) -> float:
        """Compute a weighted engagement score for ranking."""
        score = 0.0

        # Engagement metrics (log-scaled to prevent mega-events from dominating)
        if event.attendee_count and event.attendee_count > 0:
            score += self.WEIGHT_ATTENDEES * math.log1p(event.attendee_count) * 10
        if event.interested_count and event.interested_count > 0:
            score += self.WEIGHT_INTERESTED * math.log1p(event.interested_count) * 10
        if event.comments and event.comments > 0:
            score += self.WEIGHT_COMMENTS * math.log1p(event.comments) * 10
        if event.likes and event.likes > 0:
            score += self.WEIGHT_LIKES * math.log1p(event.likes) * 10

        # Completeness bonuses
        if event.image_url:
            score += self.BONUS_IMAGE
        if event.description and len(event.description) > 50:
            score += self.BONUS_DESCRIPTION
        if event.price is not None:
            score += self.BONUS_PRICE_INFO
        if event.venue_name:
            score += self.BONUS_VENUE

        # Quality multiplier
        quality = 1.0
        if event.raw_data and "quality_score" in event.raw_data:
            quality = 0.5 + event.raw_data["quality_score"] * 0.5  # Range: 0.5 - 1.0
        score *= quality

        return round(score, 2)
