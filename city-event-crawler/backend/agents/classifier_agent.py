"""Classifier Agent - categorizes events by vibe and scores relevance."""

import logging
import re
from .base_agent import BaseAgent, AgentRole, AgentResult

logger = logging.getLogger(__name__)

# Comprehensive keyword mappings for vibe classification
VIBE_KEYWORDS: dict[str, list[str]] = {
    "KINKY": [
        "kink", "fetish", "bdsm", "shibari", "rope", "dungeon", "play party",
        "munch", "leather", "latex", "domination", "submission", "switch",
        "polyamory", "poly", "swinger", "burlesque", "erotic", "sensual",
        "tantric", "adult party", "adult only", "18+", "sex positive",
        "sex-positive", "consent workshop", "intimacy", "pleasure",
        "fetish night", "rubber", "pup", "puppy play", "pet play",
    ],
    "DATING": [
        "speed dating", "singles", "mixer", "matchmaking", "dating",
        "meet singles", "blind date", "romance", "love", "flirt",
        "singles night", "singles event", "dating event", "speed meet",
    ],
    "NIGHTLIFE": [
        "club", "party", "dj", "rave", "techno", "house music",
        "dance floor", "nightclub", "afterparty", "after-party", "bass",
        "electronic", "disco", "warehouse party", "rooftop party",
        "bar crawl", "pub crawl", "club night", "dance party",
        "after hours", "late night", "till dawn", "all night",
        "minimal", "drum and bass", "dnb", "jungle", "garage",
        "dubstep", "trance", "psytrance", "hard techno",
    ],
    "SOCIAL": [
        "meetup", "social", "hangout", "gathering", "brunch",
        "picnic", "board game", "trivia", "quiz night", "karaoke",
        "open mic", "language exchange", "expat", "international",
        "community", "couchsurfing", "make friends", "hang out",
        "game night", "pub quiz", "beer pong", "social club",
    ],
    "MUSIC": [
        "concert", "live music", "gig", "festival", "jazz",
        "rock", "indie", "acoustic", "orchestra", "symphony",
        "opera", "band", "singer", "songwriter", "dj set",
        "vinyl", "record", "classical", "blues", "funk",
        "soul", "hip hop", "rap", "reggae", "ska", "punk",
        "metal", "folk", "world music", "afrobeat",
    ],
    "ART_CULTURE": [
        "exhibition", "gallery", "museum", "art", "theater",
        "theatre", "cinema", "film", "poetry", "literary",
        "book club", "photography", "painting", "sculpture",
        "workshop", "craft", "installation", "performance art",
        "street art", "mural", "cultural", "vernissage",
        "opening night", "premiere", "screening",
    ],
    "FOOD_DRINK": [
        "food", "wine", "beer", "cocktail", "tasting",
        "cooking class", "dinner", "supper club", "food market",
        "street food", "restaurant", "culinary", "brewery",
        "distillery", "wine bar", "tapas", "brunch",
        "food festival", "pop-up restaurant", "chef",
        "gastro", "foodie", "farm to table",
    ],
    "WELLNESS": [
        "yoga", "meditation", "breathwork", "sound bath",
        "retreat", "wellness", "spa", "healing", "mindfulness",
        "holistic", "cacao ceremony", "ecstatic dance",
        "kirtan", "reiki", "acro yoga", "thai massage",
        "ice bath", "cold plunge", "sauna", "float",
    ],
    "ADVENTURE": [
        "hiking", "cycling", "kayak", "climbing", "outdoor",
        "adventure", "tour", "walking tour", "escape room",
        "day trip", "excursion", "boat", "sailing", "rafting",
        "paragliding", "skydiving", "bungee", "road trip",
        "camping", "nature", "explore",
    ],
    "NETWORKING": [
        "startup", "tech", "professional", "networking",
        "conference", "workshop", "seminar", "hackathon",
        "pitch", "entrepreneur", "business", "coworking",
        "career", "industry", "panel", "fireside chat",
        "demo day", "investor", "founder", "developer",
    ],
    "LGBTQ": [
        "pride", "lgbtq", "gay", "lesbian", "queer",
        "drag", "drag show", "rainbow", "trans", "nonbinary",
        "bi", "bisexual", "queer party", "gay bar",
        "drag brunch", "ballroom", "vogue",
    ],
    "UNDERGROUND": [
        "underground", "secret", "popup", "pop-up", "speakeasy",
        "hidden", "invite-only", "exclusive", "warehouse",
        "squat", "illegal", "off-radar", "members only",
        "word of mouth", "unlisted", "private event",
    ],
    "FESTIVAL": [
        "festival", "carnival", "street party", "block party",
        "celebration", "fair", "fête", "market",
        "christmas market", "summer fest", "spring fest",
        "night market", "bazaar", "flea market",
    ],
    "SPORT_FITNESS": [
        "run", "marathon", "football", "soccer", "basketball",
        "tennis", "swimming", "crossfit", "gym", "fitness",
        "sports", "workout", "boxing", "martial arts",
        "run club", "cycling club", "5k", "10k",
        "obstacle course", "spartan", "triathlon",
    ],
}

# Source-specific vibe hints
SOURCE_VIBE_HINTS = {
    "FETLIFE": ["KINKY"],
    "RESIDENT_ADVISOR": ["NIGHTLIFE", "MUSIC"],
}

# Venue-specific vibe hints (known venues across European cities)
VENUE_VIBE_HINTS = {
    "kitkatclub": ["KINKY", "NIGHTLIFE", "LGBTQ"],
    "berghain": ["NIGHTLIFE", "UNDERGROUND", "LGBTQ"],
    "tresor": ["NIGHTLIFE", "UNDERGROUND", "MUSIC"],
    "sisyphos": ["NIGHTLIFE", "FESTIVAL"],
    "szimpla": ["SOCIAL", "NIGHTLIFE"],
    "cross club": ["NIGHTLIFE", "UNDERGROUND", "MUSIC"],
}


class ClassifierAgent(BaseAgent):
    """Categorizes events by vibe and assigns relevance scores.

    Uses multi-signal classification:
    1. Keyword matching in title/description with weighted scoring
    2. Source-based hints (e.g., FetLife -> KINKY, RA -> NIGHTLIFE)
    3. Venue-based hints for known clubs/venues
    4. Tag analysis
    """

    role = AgentRole.CLASSIFIER
    name = "Classifier"

    async def execute(self, context: dict) -> AgentResult:
        events = context.get("events", [])
        if not events:
            return AgentResult(agent=self.role, success=True, data=[], metadata={"classified": 0})

        logger.info(f"Classifying {len(events)} events by vibe")
        classified_events = []

        for event in events:
            classified = self._classify_event(event)
            classified_events.append(classified)

        vibes_found = {}
        for ev in classified_events:
            for v in (ev.vibes or []):
                vibe_val = v.value if hasattr(v, 'value') else str(v)
                vibes_found[vibe_val] = vibes_found.get(vibe_val, 0) + 1

        return AgentResult(
            agent=self.role,
            success=True,
            data=classified_events,
            metadata={
                "classified": len(classified_events),
                "vibe_distribution": vibes_found,
            },
        )

    def _classify_event(self, event) -> Any:
        """Classify a single event by analyzing multiple signals."""
        from ..models import EventVibe

        text = " ".join(filter(None, [
            event.title or "",
            event.description or "",
            " ".join(event.tags or []),
            event.venue_name or "",
            event.organizer or "",
        ])).lower()

        vibe_scores: dict[str, float] = {}

        # 1. Keyword matching with scoring
        for vibe_name, keywords in VIBE_KEYWORDS.items():
            score = 0.0
            for keyword in keywords:
                if keyword.lower() in text:
                    # Longer keywords are more specific, worth more
                    score += 1.0 + (len(keyword.split()) - 1) * 0.5
            if score > 0:
                vibe_scores[vibe_name] = score

        # 2. Source-based hints
        source_val = event.source.value if hasattr(event.source, 'value') else str(event.source)
        for source_key, hint_vibes in SOURCE_VIBE_HINTS.items():
            if source_key in source_val.upper():
                for v in hint_vibes:
                    vibe_scores[v] = vibe_scores.get(v, 0) + 3.0

        # 3. Venue-based hints
        if event.venue_name:
            venue_lower = event.venue_name.lower()
            for venue_key, hint_vibes in VENUE_VIBE_HINTS.items():
                if venue_key in venue_lower:
                    for v in hint_vibes:
                        vibe_scores[v] = vibe_scores.get(v, 0) + 5.0

        # 4. Select top vibes above threshold
        threshold = 1.0
        matched_vibes = [
            vibe_name for vibe_name, score in sorted(vibe_scores.items(), key=lambda x: -x[1])
            if score >= threshold
        ]

        # Convert to EventVibe enums
        vibe_enums = []
        for v in matched_vibes[:5]:  # Max 5 vibes per event
            try:
                vibe_enums.append(EventVibe(v))
            except (ValueError, KeyError):
                try:
                    vibe_enums.append(EventVibe[v])
                except (ValueError, KeyError):
                    pass

        # Default to OTHER if no vibes matched
        if not vibe_enums:
            vibe_enums = [EventVibe.OTHER]

        event.vibes = vibe_enums
        return event
