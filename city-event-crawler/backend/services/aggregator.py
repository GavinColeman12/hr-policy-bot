"""
Event Aggregator Service.

Collects events from all crawlers, deduplicates via fuzzy matching,
merges duplicate entries, computes engagement scores, and applies
vibe filters.
"""

from __future__ import annotations

import hashlib
import logging
from difflib import SequenceMatcher
from typing import Optional

from backend.models import Event, EventVibe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engagement-score weights
# ---------------------------------------------------------------------------
WEIGHT_ATTENDEES = 2.0
WEIGHT_INTERESTED = 1.5
WEIGHT_LIKES = 1.0
WEIGHT_COMMENTS = 3.0

# ---------------------------------------------------------------------------
# Deduplication thresholds
# ---------------------------------------------------------------------------
TITLE_SIMILARITY_THRESHOLD = 0.80
LOCATION_SIMILARITY_THRESHOLD = 0.75


class EventAggregator:
    """Aggregate, deduplicate, score, and filter crawled events."""

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def aggregate(
        self,
        events: list[Event],
        vibes: Optional[list[EventVibe]] = None,
    ) -> list[Event]:
        """Full aggregation pipeline.

        1. Deduplicate events with fuzzy matching.
        2. Calculate engagement score for every event.
        3. Filter by requested vibes (if any).
        4. Sort by engagement_score descending.

        Returns the cleaned, scored, sorted list of events.
        """
        logger.info("Aggregating %d raw events", len(events))

        deduped = self._deduplicate(events)
        logger.info("After dedup: %d events", len(deduped))

        scored = [self._score_event(e) for e in deduped]

        if vibes:
            scored = self._filter_vibes(scored, vibes)
            logger.info("After vibe filter (%s): %d events", vibes, len(scored))

        scored.sort(key=lambda e: e.get("__engagement_score", 0), reverse=True)

        # Strip internal scoring key before returning
        for e in scored:
            e.pop("__engagement_score", None)

        return scored

    # --------------------------------------------------------------------- #
    # Deduplication
    # --------------------------------------------------------------------- #

    def _deduplicate(self, events: list[Event]) -> list[Event]:
        """Remove duplicate events using fuzzy title + same date + similar location."""
        clusters: list[list[Event]] = []

        for event in events:
            placed = False
            for cluster in clusters:
                representative = cluster[0]
                if self._is_duplicate(event, representative):
                    cluster.append(event)
                    placed = True
                    break
            if not placed:
                clusters.append([event])

        merged: list[Event] = []
        for cluster in clusters:
            merged.append(self._merge_cluster(cluster))

        return merged

    def _is_duplicate(self, a: Event, b: Event) -> bool:
        """Determine whether two events are duplicates."""
        # Must share the same date
        if a.date != b.date:
            return False

        # Fuzzy title match
        title_sim = SequenceMatcher(
            None,
            self._normalise(a.title),
            self._normalise(b.title),
        ).ratio()
        if title_sim < TITLE_SIMILARITY_THRESHOLD:
            return False

        # Location similarity (venue or address)
        loc_a = self._location_string(a)
        loc_b = self._location_string(b)
        if loc_a and loc_b:
            loc_sim = SequenceMatcher(None, loc_a, loc_b).ratio()
            if loc_sim < LOCATION_SIMILARITY_THRESHOLD:
                return False

        return True

    def _merge_cluster(self, cluster: list[Event]) -> Event:
        """Merge a cluster of duplicate events into a single event.

        Keep the event with the most non-None fields as the base and fold in
        engagement metrics from all copies.
        """
        if len(cluster) == 1:
            return cluster[0]

        # Pick the richest event as the base
        cluster.sort(key=lambda e: self._richness(e), reverse=True)
        base = cluster[0].model_copy()

        total_attending = 0
        total_interested = 0
        sources_seen: set[str] = set()

        for event in cluster:
            total_attending += event.attending_count or 0
            total_interested += event.interested_count or 0
            sources_seen.add(event.source)

            # Fill missing fields from other copies
            if not base.description and event.description:
                base.description = event.description
            if not base.image_url and event.image_url:
                base.image_url = event.image_url
            if not base.venue and event.venue:
                base.venue = event.venue
            if not base.address and event.address:
                base.address = event.address
            if not base.latitude and event.latitude:
                base.latitude = event.latitude
                base.longitude = event.longitude
            if not base.price and event.price:
                base.price = event.price
            if base.is_free is None and event.is_free is not None:
                base.is_free = event.is_free
            if not base.start_time and event.start_time:
                base.start_time = event.start_time
            if not base.end_time and event.end_time:
                base.end_time = event.end_time
            if not base.organizer and event.organizer:
                base.organizer = event.organizer

            # Merge vibes and tags
            for v in event.vibes:
                if v not in base.vibes:
                    base.vibes.append(v)
            for t in event.tags:
                if t not in base.tags:
                    base.tags.append(t)

        base.attending_count = total_attending or None
        base.interested_count = total_interested or None

        return base

    # --------------------------------------------------------------------- #
    # Scoring
    # --------------------------------------------------------------------- #

    def _score_event(self, event: Event) -> Event:
        """Calculate and attach an engagement score to *event*.

        Score = (attendees * 2) + (interested * 1.5) + (likes * 1) + (comments * 3)

        ``likes`` and ``comments`` are not first-class fields on Event, so we
        read them from ``raw_data`` if available.
        """
        attendees = event.attending_count or 0
        interested = event.interested_count or 0

        likes = 0
        comments = 0
        if event.raw_data:
            likes = event.raw_data.get("likes", 0) or 0
            comments = event.raw_data.get("comments", 0) or 0

        score = (
            attendees * WEIGHT_ATTENDEES
            + interested * WEIGHT_INTERESTED
            + likes * WEIGHT_LIKES
            + comments * WEIGHT_COMMENTS
        )

        # Attach the score via a dict round-trip so we can sort later
        data = event.model_dump()
        data["engagement_score"] = round(score, 2)
        data["__engagement_score"] = score  # internal, stripped before return
        return data  # type: ignore[return-value]

    # --------------------------------------------------------------------- #
    # Filtering
    # --------------------------------------------------------------------- #

    @staticmethod
    def _filter_vibes(
        events: list[dict],
        vibes: list[EventVibe],
    ) -> list[dict]:
        """Keep only events whose vibes overlap with the requested set."""
        vibe_values = {v.value if isinstance(v, EventVibe) else v for v in vibes}
        return [
            e
            for e in events
            if any(v in vibe_values for v in (e.get("vibes") or []))
        ]

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _normalise(text: str) -> str:
        """Lower-case and strip non-alphanumeric chars for comparison."""
        return "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").strip()

    @staticmethod
    def _location_string(event: Event) -> str:
        """Build a comparable location string from venue / address."""
        parts = []
        if event.venue:
            parts.append(event.venue.lower().strip())
        if event.address:
            parts.append(event.address.lower().strip())
        return " ".join(parts)

    @staticmethod
    def _richness(event: Event) -> int:
        """Count how many non-None, non-empty fields an event has."""
        count = 0
        for field_name in event.model_fields:
            val = getattr(event, field_name, None)
            if val is not None and val != [] and val != "":
                count += 1
        return count

    @staticmethod
    def make_search_key(city: str, date: str) -> str:
        """Deterministic hash for a search query (used by the cache layer)."""
        raw = f"{city.lower().strip()}:{date}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
