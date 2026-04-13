"""
Vibe Classifier Service.

Enhanced event classification using weighted keyword scoring and
source-specific heuristics.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from backend.models import EventSource, EventVibe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword dictionaries  (keyword -> weight)
# Higher weight = stronger signal for that vibe.
# ---------------------------------------------------------------------------
_VIBE_KEYWORDS: dict[EventVibe, dict[str, float]] = {
    EventVibe.KINKY: {
        "kink": 3.0, "kinky": 3.0, "fetish": 3.0, "bdsm": 3.0,
        "dungeon": 2.5, "play party": 2.5, "munch": 2.5, "rope": 1.5,
        "shibari": 2.5, "leather": 1.5, "latex": 2.0, "dom": 1.5,
        "sub": 1.0, "slave": 2.0, "mistress": 2.0, "master": 1.0,
        "swing": 1.5, "swinger": 2.5, "polyamory": 1.5, "poly": 1.0,
        "erotic": 2.0, "sensual": 1.5, "bondage": 3.0, "spanking": 2.5,
        "dominatrix": 3.0, "fetlife": 2.5, "adult": 1.0,
    },
    EventVibe.DATING: {
        "dating": 3.0, "singles": 3.0, "speed dating": 3.0, "matchmaking": 2.5,
        "singles night": 3.0, "meet singles": 3.0, "blind date": 2.5,
        "mixer": 2.0, "mingle": 2.0, "love": 1.0, "romance": 2.0,
        "flirt": 2.0, "date night": 2.5, "couples": 1.5,
    },
    EventVibe.NIGHTLIFE: {
        "club": 2.0, "nightclub": 3.0, "party": 2.0, "dj": 2.5,
        "rave": 3.0, "afterparty": 3.0, "after party": 3.0, "night out": 2.5,
        "nightlife": 3.0, "dance floor": 2.5, "bottle service": 2.0,
        "vip": 1.5, "lounge": 1.5, "bar crawl": 2.5, "pub crawl": 2.5,
        "dance": 1.5, "clubbing": 3.0, "techno": 2.0, "house music": 2.0,
    },
    EventVibe.SOCIAL: {
        "social": 2.0, "meetup": 2.5, "meet up": 2.5, "hangout": 2.0,
        "hang out": 2.0, "gathering": 2.0, "get together": 2.0,
        "community": 2.0, "brunch": 1.5, "happy hour": 2.0,
        "drinks": 1.5, "board games": 2.0, "game night": 2.0,
        "trivia": 2.0, "karaoke": 2.0, "picnic": 2.0, "bbq": 1.5,
        "potluck": 2.0, "welcome": 1.0, "friends": 1.5,
    },
    EventVibe.MUSIC: {
        "concert": 3.0, "live music": 3.0, "gig": 2.5, "band": 2.0,
        "singer": 2.0, "orchestra": 3.0, "jazz": 2.5, "blues": 2.0,
        "rock": 1.5, "hip hop": 2.0, "rap": 1.5, "electronic": 2.0,
        "techno": 2.0, "house": 1.0, "trance": 2.5, "drum and bass": 2.5,
        "dnb": 2.0, "acoustic": 2.0, "open mic": 2.5, "festival": 1.5,
        "dj set": 2.5, "vinyl": 1.5, "music": 2.0, "opera": 2.5,
        "symphony": 2.5, "philharmonic": 2.5, "recital": 2.0,
    },
    EventVibe.ART_CULTURE: {
        "art": 2.0, "gallery": 2.5, "exhibition": 3.0, "museum": 2.5,
        "theater": 2.5, "theatre": 2.5, "play": 1.0, "performance": 1.5,
        "poetry": 2.5, "spoken word": 2.5, "comedy": 2.0, "stand up": 2.0,
        "standup": 2.0, "film": 2.0, "cinema": 2.0, "screening": 2.0,
        "dance": 1.0, "ballet": 2.5, "culture": 2.0, "creative": 1.5,
        "workshop": 1.0, "craft": 1.5, "painting": 2.0, "sculpture": 2.0,
        "photography": 2.0, "literary": 2.0, "book": 1.5, "reading": 1.5,
    },
    EventVibe.FOOD_DRINK: {
        "food": 2.5, "wine": 2.5, "beer": 2.0, "cocktail": 2.5,
        "tasting": 3.0, "culinary": 3.0, "dinner": 2.0, "supper": 2.0,
        "brunch": 2.5, "cooking": 2.5, "chef": 2.0, "restaurant": 2.0,
        "gastro": 2.5, "street food": 2.5, "food truck": 2.0,
        "market": 1.5, "farmers market": 2.0, "brewery": 2.5,
        "winery": 2.5, "distillery": 2.5, "sommelier": 2.5,
    },
    EventVibe.WELLNESS: {
        "yoga": 3.0, "meditation": 3.0, "mindfulness": 3.0, "wellness": 3.0,
        "spa": 2.5, "retreat": 2.5, "healing": 2.0, "holistic": 2.5,
        "breathwork": 3.0, "sound bath": 3.0, "reiki": 2.5,
        "pilates": 2.5, "tai chi": 2.5, "qigong": 2.5, "mental health": 2.5,
        "self care": 2.0, "therapy": 1.5, "wellbeing": 2.5,
    },
    EventVibe.ADVENTURE: {
        "adventure": 3.0, "hiking": 3.0, "climbing": 2.5, "kayaking": 2.5,
        "outdoor": 2.0, "nature": 2.0, "camping": 2.5, "trek": 2.5,
        "explore": 1.5, "tour": 1.5, "bike": 2.0, "cycling": 2.0,
        "surfing": 2.5, "diving": 2.5, "skydiving": 3.0, "bungee": 3.0,
        "escape room": 2.5, "scavenger hunt": 2.5, "road trip": 2.0,
    },
    EventVibe.NETWORKING: {
        "networking": 3.0, "professional": 2.0, "startup": 2.5,
        "entrepreneur": 2.5, "business": 2.0, "conference": 2.5,
        "seminar": 2.0, "talk": 1.5, "panel": 2.0, "pitch": 2.0,
        "hackathon": 2.5, "workshop": 1.5, "coworking": 2.0,
        "career": 2.0, "industry": 1.5, "tech": 1.5, "meetup": 1.0,
    },
    EventVibe.LGBTQ: {
        "lgbtq": 3.0, "lgbt": 3.0, "gay": 2.5, "lesbian": 2.5,
        "queer": 3.0, "trans": 2.0, "bisexual": 2.5, "pride": 3.0,
        "drag": 2.5, "drag show": 3.0, "drag queen": 3.0,
        "drag brunch": 3.0, "rainbow": 1.5, "non-binary": 2.0,
        "lgbtqia": 3.0, "sapphic": 2.5,
    },
    EventVibe.UNDERGROUND: {
        "underground": 3.0, "secret": 2.5, "hidden": 2.0,
        "warehouse": 2.5, "pop up": 2.0, "popup": 2.0, "speakeasy": 3.0,
        "invite only": 2.5, "exclusive": 1.5, "after hours": 2.5,
        "illegal": 1.5, "squat": 2.0, "alternative": 2.0, "subculture": 2.5,
        "off the grid": 2.0, "secret location": 3.0, "renegade": 2.5,
    },
    EventVibe.FESTIVAL: {
        "festival": 3.0, "fest": 2.0, "carnival": 2.5, "fair": 1.5,
        "fete": 2.0, "celebration": 1.5, "block party": 2.5,
        "street party": 2.5, "open air": 2.0, "multi-day": 2.0,
        "lineup": 2.0, "mainstage": 2.5, "camping": 1.0,
    },
    EventVibe.SPORT_FITNESS: {
        "sport": 2.5, "fitness": 2.5, "gym": 2.0, "crossfit": 2.5,
        "run": 1.5, "running": 2.5, "marathon": 3.0, "race": 2.0,
        "football": 2.5, "soccer": 2.5, "basketball": 2.5,
        "volleyball": 2.5, "tennis": 2.5, "swimming": 2.0,
        "boxing": 2.5, "martial arts": 2.5, "mma": 2.5, "workout": 2.5,
        "boot camp": 2.5, "5k": 2.0, "10k": 2.0, "triathlon": 3.0,
    },
}

# ---------------------------------------------------------------------------
# Source-based automatic vibe hints
# ---------------------------------------------------------------------------
_SOURCE_HINTS: dict[str, list[tuple[EventVibe, float]]] = {
    EventSource.FETLIFE: [
        (EventVibe.KINKY, 5.0),
        (EventVibe.SOCIAL, 1.0),
    ],
    EventSource.RESIDENT_ADVISOR: [
        (EventVibe.NIGHTLIFE, 4.0),
        (EventVibe.MUSIC, 4.0),
    ],
    EventSource.TICKETMASTER: [
        (EventVibe.MUSIC, 2.0),
    ],
    EventSource.MEETUP: [
        (EventVibe.SOCIAL, 1.5),
        (EventVibe.NETWORKING, 1.0),
    ],
    EventSource.EVENTBRITE: [
        (EventVibe.SOCIAL, 1.0),
    ],
}

# Classification threshold -- a vibe must accumulate at least this score
_THRESHOLD = 3.0

# Maximum number of vibes to assign to a single event
_MAX_VIBES = 5


class VibeClassifier:
    """Classify events into vibes using weighted keyword scoring
    with source-specific hints."""

    def classify(
        self,
        title: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        source: Optional[str] = None,
        venue_name: Optional[str] = None,
    ) -> list[EventVibe]:
        """Return the top matching vibes for an event.

        Parameters
        ----------
        title:
            Event title (required).
        description:
            Full event description text.
        tags:
            Freeform tags / keywords already attached to the event.
        source:
            The ``EventSource`` value string (e.g. ``"fetlife"``).
        venue_name:
            Name of the venue where the event takes place.

        Returns
        -------
        list[EventVibe]
            The vibes that scored above the threshold, sorted by
            score descending, capped at ``_MAX_VIBES``.
        """
        scores: dict[EventVibe, float] = {v: 0.0 for v in EventVibe}

        # Build the text corpus to scan
        corpus = self._build_corpus(title, description, tags, venue_name)

        # Keyword scoring
        for vibe, keywords in _VIBE_KEYWORDS.items():
            for keyword, weight in keywords.items():
                if self._keyword_in_corpus(keyword, corpus):
                    scores[vibe] += weight

        # Source-specific hints
        if source:
            source_val = source.value if isinstance(source, EventSource) else source
            for hint_vibe, hint_weight in _SOURCE_HINTS.get(source_val, []):
                scores[hint_vibe] += hint_weight

        # Filter and rank
        above_threshold = [
            (vibe, score)
            for vibe, score in scores.items()
            if score >= _THRESHOLD
        ]
        above_threshold.sort(key=lambda x: x[1], reverse=True)

        result = [vibe for vibe, _ in above_threshold[:_MAX_VIBES]]

        if not result:
            # Default to SOCIAL if nothing matched
            result = [EventVibe.SOCIAL]

        logger.debug(
            "Classified '%s' (source=%s) -> %s  (raw scores: %s)",
            title,
            source,
            result,
            {v.value: s for v, s in scores.items() if s > 0},
        )
        return result

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_corpus(
        title: str,
        description: Optional[str],
        tags: Optional[list[str]],
        venue_name: Optional[str],
    ) -> str:
        """Build a single lowercase text blob for keyword matching."""
        parts = [title]
        if description:
            parts.append(description)
        if tags:
            parts.append(" ".join(tags))
        if venue_name:
            parts.append(venue_name)
        return " ".join(parts).lower()

    @staticmethod
    def _keyword_in_corpus(keyword: str, corpus: str) -> bool:
        """Check if *keyword* appears as a word boundary match in *corpus*."""
        pattern = r"\b" + re.escape(keyword) + r"\b"
        return bool(re.search(pattern, corpus))
