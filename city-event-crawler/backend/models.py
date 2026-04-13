"""
Pydantic models for the City Event Crawler.

Defines the canonical Event schema, request/response envelopes, and
supporting enumerations used across all crawlers and API endpoints.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventVibe(str, Enum):
    """High-level mood / category tags for events."""

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
    """Platform from which an event was discovered."""

    GOOGLE = "google"
    EVENTBRITE = "eventbrite"
    MEETUP = "meetup"
    INSTAGRAM = "instagram"
    REDDIT = "reddit"
    TWITTER = "twitter"
    FACEBOOK = "facebook"
    RESIDENT_ADVISOR = "resident_advisor"
    FETLIFE = "fetlife"
    TICKETMASTER = "ticketmaster"
    YELP = "yelp"
    DICE = "dice"
    BLOG = "blog"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Core Event model
# ---------------------------------------------------------------------------

class Event(BaseModel):
    """Canonical representation of a single event from any source."""

    id: str = Field(
        ...,
        description="Unique event identifier (typically source-prefixed hash).",
    )
    title: str = Field(..., description="Event title / name.")
    description: Optional[str] = Field(
        default=None,
        description="Full-text description of the event.",
    )
    date: datetime = Field(..., description="Start date/time of the event.")
    end_date: Optional[datetime] = Field(
        default=None,
        description="End date/time (if known).",
    )

    # Source metadata
    source: EventSource = Field(..., description="Platform that sourced this event.")
    source_url: str = Field(..., description="Canonical URL on the originating platform.")

    # Location
    venue_name: Optional[str] = Field(default=None, description="Name of the venue.")
    address: Optional[str] = Field(default=None, description="Human-readable address.")
    latitude: Optional[float] = Field(default=None, description="Venue latitude.")
    longitude: Optional[float] = Field(default=None, description="Venue longitude.")
    distance_km: Optional[float] = Field(
        default=None,
        description="Distance in km from the searcher's position.",
    )

    # Categorisation
    vibes: list[EventVibe] = Field(
        default_factory=list,
        description="Mood / category tags.",
    )

    # Pricing
    price: Optional[str] = Field(
        default=None,
        description="Human-readable price string (e.g. '10 EUR', 'Free').",
    )
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code.")
    is_free: Optional[bool] = Field(default=None, description="Whether the event is free.")

    # Media
    image_url: Optional[str] = Field(default=None, description="Primary image / flyer URL.")

    # Engagement metrics
    attendee_count: Optional[int] = Field(default=None, ge=0)
    interested_count: Optional[int] = Field(default=None, ge=0)
    likes: Optional[int] = Field(default=None, ge=0)
    comments: Optional[int] = Field(default=None, ge=0)

    @computed_field  # type: ignore[misc]
    @property
    def engagement_score(self) -> float:
        """Weighted engagement score derived from available metrics.

        Formula (weights chosen to reward real attendance signals):
            attendees * 3.0
          + interested * 1.5
          + likes      * 1.0
          + comments   * 2.0
        """
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

    # Organiser
    organizer: Optional[str] = Field(default=None, description="Organiser name or handle.")

    # Free-form tags
    tags: list[str] = Field(default_factory=list, description="Arbitrary keyword tags.")

    # Age restriction
    min_age: Optional[int] = Field(default=None, ge=0, description="Minimum age requirement.")

    # Escape hatch for crawler-specific data
    raw_data: Optional[dict] = Field(
        default=None,
        description="Raw payload from the originating platform.",
    )

    @staticmethod
    def generate_id(source: EventSource, unique_key: str) -> str:
        """Create a deterministic event ID from source + unique key."""
        digest = hashlib.sha256(f"{source.value}:{unique_key}".encode()).hexdigest()[:16]
        return f"{source.value}_{digest}"


# ---------------------------------------------------------------------------
# Request / Response envelopes
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    """Payload accepted by the POST /api/search endpoint."""

    city: str = Field(
        ...,
        min_length=1,
        description="City name (must match a key in CITY_COORDINATES or supply lat/lon).",
    )
    date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Target date in YYYY-MM-DD format.",
    )
    vibes: Optional[list[EventVibe]] = Field(
        default=None,
        description="Filter results to these vibes. None = all vibes.",
    )
    latitude: Optional[float] = Field(
        default=None,
        description="Override latitude (instead of city lookup).",
    )
    longitude: Optional[float] = Field(
        default=None,
        description="Override longitude (instead of city lookup).",
    )
    radius_km: float = Field(
        default=15.0,
        gt=0,
        le=100,
        description="Search radius in kilometres.",
    )
    platforms: Optional[list[EventSource]] = Field(
        default=None,
        description="Restrict search to these platforms. None = all available.",
    )
    max_results: int = Field(
        default=200,
        gt=0,
        le=1000,
        description="Maximum number of events to return.",
    )


class SearchResponse(BaseModel):
    """Envelope returned by the POST /api/search endpoint."""

    events: list[Event] = Field(default_factory=list)
    total_count: int = Field(default=0, description="Number of events in this response.")
    city: str = Field(..., description="City that was searched.")
    date: str = Field(..., description="Date that was searched (YYYY-MM-DD).")
    search_duration_seconds: float = Field(
        ...,
        description="Wall-clock time for the entire search.",
    )
    sources_searched: list[EventSource] = Field(
        default_factory=list,
        description="All sources that were queried.",
    )
    sources_with_results: list[EventSource] = Field(
        default_factory=list,
        description="Sources that returned at least one event.",
    )
    errors: list[dict] = Field(
        default_factory=list,
        description="Per-source error details for any crawler that failed.",
    )


class CityInfo(BaseModel):
    """Public representation of a supported city."""

    name: str = Field(..., description="Display name of the city.")
    country: str = Field(..., description="Country the city belongs to.")
    latitude: float
    longitude: float
    timezone: str
