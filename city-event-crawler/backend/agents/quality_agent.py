"""Quality Agent - deduplicates, validates, and enriches event data."""

import hashlib
import logging
import re
from difflib import SequenceMatcher
from datetime import datetime

from .base_agent import BaseAgent, AgentRole, AgentResult

logger = logging.getLogger(__name__)


class QualityAgent(BaseAgent):
    """Validates and deduplicates events across all sources.

    Performs:
    1. Data validation - removes events with missing critical fields
    2. Fuzzy deduplication - merges events that appear on multiple platforms
    3. Data enrichment - fills in missing fields from duplicate sources
    4. Quality scoring - assigns a data completeness score
    """

    role = AgentRole.QUALITY
    name = "Quality"

    SIMILARITY_THRESHOLD = 0.65  # Title similarity threshold for dedup

    async def execute(self, context: dict) -> AgentResult:
        events = context.get("events", [])
        if not events:
            return AgentResult(agent=self.role, success=True, data=[], metadata={"input": 0, "output": 0})

        logger.info(f"Quality checking {len(events)} events")

        # Step 1: Validate
        valid_events = self._validate_events(events)
        logger.info(f"  Validation: {len(events)} -> {len(valid_events)} events")

        # Step 2: Deduplicate
        deduped = self._deduplicate(valid_events)
        logger.info(f"  Deduplication: {len(valid_events)} -> {len(deduped)} events")

        # Step 3: Enrich - compute quality score
        enriched = [self._compute_quality_score(e) for e in deduped]

        return AgentResult(
            agent=self.role,
            success=True,
            data=enriched,
            metadata={
                "input_count": len(events),
                "after_validation": len(valid_events),
                "after_dedup": len(deduped),
                "output_count": len(enriched),
                "duplicates_merged": len(valid_events) - len(deduped),
                "invalid_removed": len(events) - len(valid_events),
            },
        )

    def _validate_events(self, events: list) -> list:
        """Remove events with missing critical data."""
        valid = []
        for event in events:
            # Must have at least a title and source URL
            if not event.title or not event.title.strip():
                continue
            if not event.source_url or not event.source_url.strip():
                continue
            # Clean up title
            event.title = event.title.strip()
            if event.description:
                event.description = event.description.strip()
            valid.append(event)
        return valid

    def _deduplicate(self, events: list) -> list:
        """Fuzzy-match events by title+date+venue and merge duplicates."""
        if not events:
            return events

        # Group by approximate date (same day)
        date_groups: dict[str, list] = {}
        for event in events:
            date_key = "unknown"
            if event.date:
                try:
                    if isinstance(event.date, datetime):
                        date_key = event.date.strftime("%Y-%m-%d")
                    elif isinstance(event.date, str):
                        date_key = event.date[:10]
                except (ValueError, AttributeError):
                    pass
            date_groups.setdefault(date_key, []).append(event)

        deduped = []
        for date_key, group in date_groups.items():
            deduped.extend(self._deduplicate_group(group))

        return deduped

    def _deduplicate_group(self, events: list) -> list:
        """Deduplicate within a date group using fuzzy title matching."""
        if len(events) <= 1:
            return events

        merged_indices = set()
        result = []

        for i, event_a in enumerate(events):
            if i in merged_indices:
                continue

            best = event_a
            for j in range(i + 1, len(events)):
                if j in merged_indices:
                    continue

                event_b = events[j]
                if self._are_duplicates(event_a, event_b):
                    best = self._merge_events(best, event_b)
                    merged_indices.add(j)

            result.append(best)

        return result

    def _are_duplicates(self, a, b) -> bool:
        """Check if two events are likely the same event."""
        title_a = self._normalize_title(a.title)
        title_b = self._normalize_title(b.title)

        # Direct title similarity
        similarity = SequenceMatcher(None, title_a, title_b).ratio()
        if similarity >= self.SIMILARITY_THRESHOLD:
            return True

        # Check if one title contains the other
        if len(title_a) > 5 and len(title_b) > 5:
            if title_a in title_b or title_b in title_a:
                return True

        # Same venue + similar time = likely same
        if a.venue_name and b.venue_name:
            venue_sim = SequenceMatcher(
                None,
                a.venue_name.lower().strip(),
                b.venue_name.lower().strip(),
            ).ratio()
            if venue_sim > 0.7 and similarity > 0.4:
                return True

        return False

    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        title = title.lower().strip()
        title = re.sub(r'[^\w\s]', '', title)
        title = re.sub(r'\s+', ' ', title)
        # Remove common prefixes
        for prefix in ["event:", "tonight:", "live:", "presents:"]:
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
        return title

    def _merge_events(self, primary, secondary):
        """Merge two duplicate events, keeping the most complete data."""
        # Keep whichever has more data as primary
        primary_score = self._completeness_score(primary)
        secondary_score = self._completeness_score(secondary)

        if secondary_score > primary_score:
            primary, secondary = secondary, primary

        # Fill missing fields from secondary
        if not primary.description and secondary.description:
            primary.description = secondary.description
        if not primary.venue_name and secondary.venue_name:
            primary.venue_name = secondary.venue_name
        if not primary.address and secondary.address:
            primary.address = secondary.address
        if not primary.latitude and secondary.latitude:
            primary.latitude = secondary.latitude
            primary.longitude = secondary.longitude
        if not primary.image_url and secondary.image_url:
            primary.image_url = secondary.image_url
        if not primary.price and secondary.price:
            primary.price = secondary.price
        if not primary.organizer and secondary.organizer:
            primary.organizer = secondary.organizer

        # Combine engagement metrics (take max)
        primary.attendee_count = max(primary.attendee_count or 0, secondary.attendee_count or 0) or None
        primary.interested_count = max(primary.interested_count or 0, secondary.interested_count or 0) or None
        primary.likes = max(primary.likes or 0, secondary.likes or 0) or None
        primary.comments = max(primary.comments or 0, secondary.comments or 0) or None

        # Merge vibes
        existing_vibes = set(v.value if hasattr(v, 'value') else v for v in (primary.vibes or []))
        for v in (secondary.vibes or []):
            vval = v.value if hasattr(v, 'value') else v
            if vval not in existing_vibes:
                primary.vibes.append(v)
                existing_vibes.add(vval)

        # Merge tags
        existing_tags = set(primary.tags or [])
        for t in (secondary.tags or []):
            if t not in existing_tags:
                primary.tags.append(t)
                existing_tags.add(t)

        return primary

    def _completeness_score(self, event) -> int:
        """Score how complete an event's data is."""
        score = 0
        if event.title:
            score += 2
        if event.description:
            score += 2
        if event.venue_name:
            score += 2
        if event.address:
            score += 1
        if event.latitude:
            score += 1
        if event.image_url:
            score += 1
        if event.price:
            score += 1
        if event.attendee_count:
            score += 1
        if event.interested_count:
            score += 1
        if event.likes:
            score += 1
        if event.organizer:
            score += 1
        if event.tags:
            score += 1
        return score

    def _compute_quality_score(self, event) -> Any:
        """Add a data quality score to the event."""
        score = self._completeness_score(event)
        max_score = 15
        if event.raw_data is None:
            event.raw_data = {}
        event.raw_data["quality_score"] = round(score / max_score, 2)
        return event
