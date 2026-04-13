"""
Shared utility helpers for the City Event Crawler.

Provides distance calculation, engagement scoring, date normalisation,
HTML cleaning, and event deduplication used across crawlers and services.
"""

from __future__ import annotations

import hashlib
import html
import math
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional, Sequence

from dateutil import parser as dateutil_parser

from ..models import Event


# ---------------------------------------------------------------------------
# Geo / distance helpers
# ---------------------------------------------------------------------------

_EARTH_RADIUS_KM = 6371.0


def calculate_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return the great-circle distance in kilometres between two points.

    Uses the haversine formula.

    Args:
        lat1: Latitude of point A (degrees).
        lon1: Longitude of point A (degrees).
        lat2: Latitude of point B (degrees).
        lon2: Longitude of point B (degrees).

    Returns:
        Distance in kilometres, rounded to two decimal places.
    """
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return round(_EARTH_RADIUS_KM * c, 2)


# ---------------------------------------------------------------------------
# Engagement scoring
# ---------------------------------------------------------------------------

def compute_engagement_score(
    likes: int | None = None,
    comments: int | None = None,
    attendees: int | None = None,
    interested: int | None = None,
) -> float:
    """Compute a weighted engagement score from available social signals.

    Weights (tuned to favour real-world attendance intent):
        * attendees  -> 3.0
        * interested -> 1.5
        * comments   -> 2.0
        * likes      -> 1.0

    Args:
        likes: Number of likes / reactions.
        comments: Number of comments / replies.
        attendees: Confirmed attendee or RSVP count.
        interested: "Interested" / "maybe" count.

    Returns:
        Non-negative float score rounded to two decimals.
    """
    score = 0.0
    if attendees:
        score += attendees * 3.0
    if interested:
        score += interested * 1.5
    if likes:
        score += likes * 1.0
    if comments:
        score += comments * 2.0
    return round(score, 2)


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

def normalize_date(date_str: str | None) -> datetime | None:
    """Parse a variety of human and machine date formats into a datetime.

    Handles ISO-8601, RFC 2822, natural language dates via ``dateutil``,
    and common European formats (DD.MM.YYYY, DD/MM/YYYY).

    Args:
        date_str: Raw date string to parse.

    Returns:
        A ``datetime`` instance, or ``None`` if parsing fails.
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Try dateutil first (handles the vast majority of formats)
    try:
        return dateutil_parser.parse(date_str, fuzzy=True)
    except (ValueError, OverflowError):
        pass

    # Fallback: try common European DD.MM.YYYY / DD/MM/YYYY
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# HTML / text cleaning
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(html_str: str | None, max_length: int = 5000) -> str | None:
    """Strip HTML tags, decode entities, normalise whitespace, and truncate.

    Args:
        html_str: Raw HTML string (may be ``None``).
        max_length: Maximum character length for the result.

    Returns:
        Cleaned plain-text string, or ``None`` if input was falsy.
    """
    if not html_str:
        return None

    # Decode HTML entities
    text = html.unescape(html_str)
    # Remove tags
    text = _TAG_RE.sub(" ", text)
    # Normalise unicode
    text = unicodedata.normalize("NFKC", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text if text else None


# ---------------------------------------------------------------------------
# Event deduplication
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    """Return a 0-1 similarity ratio between two strings (case-insensitive)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _event_fingerprint(event: Event) -> str:
    """Create a coarse fingerprint for grouping likely duplicates."""
    title_norm = re.sub(r"\W+", "", event.title.lower())
    date_str = event.date.strftime("%Y-%m-%d") if event.date else ""
    venue_norm = re.sub(r"\W+", "", (event.venue_name or "").lower())
    return f"{title_norm}|{date_str}|{venue_norm}"


def _event_richness(event: Event) -> int:
    """Score how much data an event record carries (higher = more complete)."""
    score = 0
    if event.description:
        score += len(event.description)
    if event.venue_name:
        score += 50
    if event.address:
        score += 30
    if event.latitude is not None:
        score += 40
    if event.image_url:
        score += 20
    if event.attendee_count:
        score += event.attendee_count
    if event.interested_count:
        score += event.interested_count
    if event.likes:
        score += event.likes
    if event.comments:
        score += event.comments
    if event.price:
        score += 10
    if event.organizer:
        score += 15
    score += len(event.vibes) * 5
    score += len(event.tags) * 3
    return score


def deduplicate_events(events: Sequence[Event], threshold: float = 0.80) -> list[Event]:
    """Remove near-duplicate events, keeping the richest version of each.

    Two events are considered duplicates when:
    1. They share the same date (YYYY-MM-DD), **and**
    2. Their titles have a similarity ratio >= ``threshold``, **and**
    3. Either both have no venue or their venue names are similar.

    For each cluster of duplicates the version with the highest "richness"
    score (most populated fields, highest engagement) is kept.

    Args:
        events: Sequence of events to deduplicate.
        threshold: Minimum title similarity to consider a duplicate.

    Returns:
        Deduplicated list, preserving the original order of kept events.
    """
    if not events:
        return []

    # Group by coarse fingerprint for O(n) fast-path matches
    fingerprint_groups: dict[str, list[Event]] = {}
    for ev in events:
        fp = _event_fingerprint(ev)
        fingerprint_groups.setdefault(fp, []).append(ev)

    kept: list[Event] = []
    seen_ids: set[str] = set()

    for group in fingerprint_groups.values():
        if len(group) == 1:
            kept.append(group[0])
            seen_ids.add(group[0].id)
            continue

        # Within a fingerprint group, do pairwise similarity clustering
        clusters: list[list[Event]] = []
        for ev in group:
            merged = False
            for cluster in clusters:
                representative = cluster[0]
                # Same date check
                if ev.date.date() != representative.date.date():
                    continue
                # Title similarity
                if _similarity(ev.title, representative.title) < threshold:
                    continue
                # Venue similarity (if both have one)
                if ev.venue_name and representative.venue_name:
                    if _similarity(ev.venue_name, representative.venue_name) < 0.6:
                        continue
                cluster.append(ev)
                merged = True
                break
            if not merged:
                clusters.append([ev])

        # Pick the richest event from each cluster
        for cluster in clusters:
            best = max(cluster, key=_event_richness)
            if best.id not in seen_ids:
                kept.append(best)
                seen_ids.add(best.id)

    # Now do a second pass across all kept events for cross-fingerprint dupes
    # (catches cases where fingerprints differ slightly)
    final: list[Event] = []
    for ev in kept:
        is_dup = False
        for existing in final:
            if ev.date.date() != existing.date.date():
                continue
            if _similarity(ev.title, existing.title) >= threshold:
                if ev.venue_name and existing.venue_name:
                    if _similarity(ev.venue_name, existing.venue_name) < 0.6:
                        continue
                # Keep the richer one
                if _event_richness(ev) > _event_richness(existing):
                    final.remove(existing)
                    final.append(ev)
                is_dup = True
                break
        if not is_dup:
            final.append(ev)

    return final


# ---------------------------------------------------------------------------
# Aliases used by crawlers
# ---------------------------------------------------------------------------

def clean_text(text: str | None, max_length: int = 5000) -> str | None:
    """Alias for clean_html for backwards compatibility."""
    return clean_html(text, max_length=max_length)


def parse_date(date_str: str | None, fallback: str | None = None) -> datetime | None:
    """Parse a date string, falling back to another string if needed."""
    result = normalize_date(date_str)
    if result is not None:
        return result
    if fallback:
        return normalize_date(fallback)
    return None


def generate_event_id(source: str, *parts: str) -> str:
    """Generate a deterministic event ID from source + parts."""
    key = ":".join(str(p) for p in parts if p)
    digest = hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:16]
    return f"{source}_{digest}"
