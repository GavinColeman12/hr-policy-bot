"""
Pydantic models for the v2 City Event Crawler.

Instagram-only discovery + Claude-powered curation. Events are tagged with a
curation_tier and a score_breakdown; responses include a Claude-written
EveningGuide alongside the raw event list.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventVibe(str, Enum):
    SOCIAL = "social"
    DATING = "dating"
    KINKY = "kinky"
    NIGHTLIFE = "nightlife"
    MUSIC = "music"
    ART_CULTURE = "art_culture"
    FOOD_DRINK = "food_drink"
    WELLNESS = "wellness"
    ADVENTURE = "adventure"
    NETWORKING = "networking"
    LGBTQ = "lgbtq"
    UNDERGROUND = "underground"
    FESTIVAL = "festival"
    SPORT_FITNESS = "sport_fitness"
    OTHER = "other"


class EventSource(str, Enum):
    INSTAGRAM = "instagram"


CurationTier = Literal["top_pick", "hidden_gem", "standard", "skip"]
ScrapeOrigin = Literal["profile", "hashtag", "story", "reel"]


# ---------------------------------------------------------------------------
# Core Event model
# ---------------------------------------------------------------------------

class Event(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    date: datetime
    end_date: Optional[datetime] = None

    source: EventSource = EventSource.INSTAGRAM
    source_url: str

    venue_name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None

    vibes: list[EventVibe] = Field(default_factory=list)

    price: Optional[str] = None
    currency: Optional[str] = None
    is_free: Optional[bool] = None

    image_url: Optional[str] = None

    attendee_count: Optional[int] = Field(default=None, ge=0)
    interested_count: Optional[int] = Field(default=None, ge=0)
    likes: Optional[int] = Field(default=None, ge=0)
    comments: Optional[int] = Field(default=None, ge=0)

    organizer: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    min_age: Optional[int] = Field(default=None, ge=0)

    # v2 curation fields
    curation_tier: CurationTier = "standard"
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    account_handle: Optional[str] = None
    scrape_source: Optional[ScrapeOrigin] = None
    suggested_itinerary_position: Optional[int] = None

    raw_data: Optional[dict] = None

    @computed_field  # type: ignore[misc]
    @property
    def engagement_score(self) -> float:
        score = 0.0
        if self.attendee_count:
            score += self.attendee_count * 3.0
        if self.interested_count:
            score += self.interested_count * 1.5
        if self.likes:
            score += self.likes * 1.0
        if self.comments:
            score += self.comments * 2.0
        return round(score, 2)

    @staticmethod
    def generate_id(source: EventSource, unique_key: str) -> str:
        digest = hashlib.sha256(f"{source.value}:{unique_key}".encode()).hexdigest()[:16]
        return f"{source.value}_{digest}"


# ---------------------------------------------------------------------------
# Curation
# ---------------------------------------------------------------------------

class EveningGuide(BaseModel):
    """Claude-written guide produced by the CURATE stage."""

    summary_text: str = Field(..., description="~80-word narrative blurb")
    demographic_note: str = Field(..., description="Who this lineup is for")
    top_pick_id: Optional[str] = Field(default=None)
    itinerary_ids: list[str] = Field(default_factory=list)
    hidden_gem_ids: list[str] = Field(default_factory=list)
    skip_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Request / Response envelopes
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    city: str = Field(..., min_length=1)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    vibes: Optional[list[EventVibe]] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: float = Field(default=15.0, gt=0, le=100)
    max_results: int = Field(default=60, gt=0, le=200)


class SearchResponse(BaseModel):
    events: list[Event] = Field(default_factory=list)
    curated_guide: Optional[EveningGuide] = None
    total_count: int = 0
    city: str
    date: str
    search_duration_seconds: float
    accounts_discovered: int = 0
    accounts_triaged: int = 0
    accounts_cache_hit: int = 0
    posts_scraped: int = 0
    stories_scraped: int = 0
    events_extracted: int = 0
    apify_cost_usd: float = 0.0
    monthly_spend_usd: float = 0.0
    monthly_budget_usd: float = 0.0
    budget_blocked: bool = False
    errors: list[dict] = Field(default_factory=list)


class CityInfo(BaseModel):
    name: str
    country: str
    latitude: float
    longitude: float
    timezone: str
