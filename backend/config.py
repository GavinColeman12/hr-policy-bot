"""
Configuration for the v2 Instagram-only deep discovery + Claude curation pipeline.

Three core API keys: SERPAPI_KEY, INSTAGRAM_APIFY_TOKEN, ANTHROPIC_API_KEY.
Optional DATABASE_URL enables the scrape cache + cost log.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    SERPAPI_KEY: str = Field(default="")
    INSTAGRAM_APIFY_TOKEN: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")
    DATABASE_URL: str = Field(default="")

    CLAUDE_MODEL: str = Field(default="claude-opus-4-7")
    TRIAGE_MAX_TOKENS: int = Field(default=4000)
    EXTRACT_MAX_TOKENS: int = Field(default=8000)
    SCORE_MAX_TOKENS: int = Field(default=4000)
    CURATE_MAX_TOKENS: int = Field(default=4000)

    # Apify actors + pricing (per actor; verify on each actor's Apify page).
    APIFY_POSTS_ACTOR: str = Field(default="apify/instagram-api-scraper")
    APIFY_STORIES_ACTOR: str = Field(default="louisdeconinck/instagram-stories-scraper")
    APIFY_POSTS_USD_PER_1K: float = Field(default=2.30)
    APIFY_STORIES_USD_PER_1K: float = Field(default=2.30)

    # Scrape volume — wider, shallower than v1.
    MAX_ACCOUNTS_PER_SEARCH: int = Field(default=60)
    MAX_POSTS_PER_ACCOUNT: int = Field(default=2)
    MAX_STORIES_PER_ACCOUNT: int = Field(default=5)
    SCRAPE_INCLUDE_STORIES: bool = Field(default=True)
    SCRAPE_INCLUDE_HASHTAGS: bool = Field(default=False)
    APIFY_DATE_FILTER_DAYS: int = Field(default=14)
    MAX_DISCOVERY_QUERIES: int = Field(default=8)

    # Cache TTLs.
    POSTS_CACHE_TTL_HOURS: int = Field(default=24)
    STORIES_CACHE_TTL_HOURS: int = Field(default=24)

    # Cost cutoff. SCRAPE is skipped (cache-only) if this month's spend ≥ this.
    MONTHLY_BUDGET_USD: float = Field(default=25.0)

    DEFAULT_RADIUS_KM: float = Field(default=15.0)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


CITY_COORDINATES: dict[str, dict] = {
    "budapest": {"lat": 47.4979, "lon": 19.0402, "tz": "Europe/Budapest", "country": "Hungary"},
    "berlin": {"lat": 52.5200, "lon": 13.4050, "tz": "Europe/Berlin", "country": "Germany"},
    "prague": {"lat": 50.0755, "lon": 14.4378, "tz": "Europe/Prague", "country": "Czech Republic"},
    "vienna": {"lat": 48.2082, "lon": 16.3738, "tz": "Europe/Vienna", "country": "Austria"},
    "warsaw": {"lat": 52.2297, "lon": 21.0122, "tz": "Europe/Warsaw", "country": "Poland"},
    "krakow": {"lat": 50.0647, "lon": 19.9450, "tz": "Europe/Warsaw", "country": "Poland"},
    "belgrade": {"lat": 44.7866, "lon": 20.4489, "tz": "Europe/Belgrade", "country": "Serbia"},
    "bucharest": {"lat": 44.4268, "lon": 26.1025, "tz": "Europe/Bucharest", "country": "Romania"},
    "sofia": {"lat": 42.6977, "lon": 23.3219, "tz": "Europe/Sofia", "country": "Bulgaria"},
    "zagreb": {"lat": 45.8150, "lon": 15.9819, "tz": "Europe/Zagreb", "country": "Croatia"},
    "ljubljana": {"lat": 46.0569, "lon": 14.5058, "tz": "Europe/Ljubljana", "country": "Slovenia"},
    "bratislava": {"lat": 48.1486, "lon": 17.1077, "tz": "Europe/Bratislava", "country": "Slovakia"},
    "tallinn": {"lat": 59.4370, "lon": 24.7536, "tz": "Europe/Tallinn", "country": "Estonia"},
    "riga": {"lat": 56.9496, "lon": 24.1052, "tz": "Europe/Riga", "country": "Latvia"},
    "vilnius": {"lat": 54.6872, "lon": 25.2797, "tz": "Europe/Vilnius", "country": "Lithuania"},
    "helsinki": {"lat": 60.1699, "lon": 24.9384, "tz": "Europe/Helsinki", "country": "Finland"},
    "stockholm": {"lat": 59.3293, "lon": 18.0686, "tz": "Europe/Stockholm", "country": "Sweden"},
    "copenhagen": {"lat": 55.6761, "lon": 12.5683, "tz": "Europe/Copenhagen", "country": "Denmark"},
    "oslo": {"lat": 59.9139, "lon": 10.7522, "tz": "Europe/Oslo", "country": "Norway"},
    "dublin": {"lat": 53.3498, "lon": -6.2603, "tz": "Europe/Dublin", "country": "Ireland"},
    "edinburgh": {"lat": 55.9533, "lon": -3.1883, "tz": "Europe/London", "country": "United Kingdom"},
    "london": {"lat": 51.5074, "lon": -0.1278, "tz": "Europe/London", "country": "United Kingdom"},
    "paris": {"lat": 48.8566, "lon": 2.3522, "tz": "Europe/Paris", "country": "France"},
    "rome": {"lat": 41.9028, "lon": 12.4964, "tz": "Europe/Rome", "country": "Italy"},
    "milan": {"lat": 45.4642, "lon": 9.1900, "tz": "Europe/Rome", "country": "Italy"},
    "florence": {"lat": 43.7696, "lon": 11.2558, "tz": "Europe/Rome", "country": "Italy"},
    "naples": {"lat": 40.8518, "lon": 14.2681, "tz": "Europe/Rome", "country": "Italy"},
    "barcelona": {"lat": 41.3851, "lon": 2.1734, "tz": "Europe/Madrid", "country": "Spain"},
    "madrid": {"lat": 40.4168, "lon": -3.7038, "tz": "Europe/Madrid", "country": "Spain"},
    "seville": {"lat": 37.3891, "lon": -5.9845, "tz": "Europe/Madrid", "country": "Spain"},
    "valencia": {"lat": 39.4699, "lon": -0.3763, "tz": "Europe/Madrid", "country": "Spain"},
    "lisbon": {"lat": 38.7223, "lon": -9.1393, "tz": "Europe/Lisbon", "country": "Portugal"},
    "porto": {"lat": 41.1579, "lon": -8.6291, "tz": "Europe/Lisbon", "country": "Portugal"},
    "athens": {"lat": 37.9838, "lon": 23.7275, "tz": "Europe/Athens", "country": "Greece"},
    "thessaloniki": {"lat": 40.6401, "lon": 22.9444, "tz": "Europe/Athens", "country": "Greece"},
    "istanbul": {"lat": 41.0082, "lon": 28.9784, "tz": "Europe/Istanbul", "country": "Turkey"},
    "amsterdam": {"lat": 52.3676, "lon": 4.9041, "tz": "Europe/Amsterdam", "country": "Netherlands"},
    "brussels": {"lat": 50.8503, "lon": 4.3517, "tz": "Europe/Brussels", "country": "Belgium"},
    "antwerp": {"lat": 51.2194, "lon": 4.4025, "tz": "Europe/Brussels", "country": "Belgium"},
    "munich": {"lat": 48.1351, "lon": 11.5820, "tz": "Europe/Berlin", "country": "Germany"},
    "hamburg": {"lat": 53.5511, "lon": 9.9937, "tz": "Europe/Berlin", "country": "Germany"},
    "frankfurt": {"lat": 50.1109, "lon": 8.6821, "tz": "Europe/Berlin", "country": "Germany"},
    "cologne": {"lat": 50.9375, "lon": 6.9603, "tz": "Europe/Berlin", "country": "Germany"},
    "geneva": {"lat": 46.2044, "lon": 6.1432, "tz": "Europe/Zurich", "country": "Switzerland"},
    "zurich": {"lat": 47.3769, "lon": 8.5417, "tz": "Europe/Zurich", "country": "Switzerland"},
}


def get_settings() -> Settings:
    return Settings()
