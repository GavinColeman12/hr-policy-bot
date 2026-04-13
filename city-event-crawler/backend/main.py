"""
City Event Crawler -- FastAPI application.

Central orchestrator that exposes REST endpoints for searching events
across multiple platforms (Google, Eventbrite, Meetup, Instagram, Reddit,
Twitter/X, Facebook, Resident Advisor, FetLife, Ticketmaster, Yelp, blogs).

The main ``/api/search`` endpoint spins up all relevant crawlers in
parallel (guarded by an asyncio.Semaphore), aggregates results, computes
distances, deduplicates, and returns a sorted response.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import CITY_COORDINATES, Settings, get_settings
from .crawlers import get_all_crawlers
from .models import (
    CityInfo,
    Event,
    EventSource,
    EventVibe,
    SearchRequest,
    SearchResponse,
)
from .utils.helpers import calculate_distance, deduplicate_events

logger = logging.getLogger("city_event_crawler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

_settings: Settings | None = None
_crawlers: dict[EventSource, Any] | None = None
_semaphore: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared resources on startup and tear down on shutdown."""
    global _settings, _crawlers, _semaphore

    _settings = get_settings()
    _crawlers = get_all_crawlers()
    _semaphore = asyncio.Semaphore(_settings.MAX_CONCURRENT_CRAWLERS)

    logger.info(
        "Startup complete -- %d crawlers loaded, semaphore=%d",
        len(_crawlers),
        _settings.MAX_CONCURRENT_CRAWLERS,
    )
    yield

    # Cleanup (if crawlers hold connections, close them here)
    _crawlers = None
    _semaphore = None
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="City Event Crawler",
    description=(
        "Aggregates events from 11+ platforms for European cities. "
        "Supports filtering by vibe, date, radius, and platform."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helper: resolve city to coordinates
# ---------------------------------------------------------------------------

def _resolve_city(request: SearchRequest) -> tuple[float, float, str]:
    """Return (latitude, longitude, canonical_city_name) for a request.

    If the request supplies explicit lat/lon those take precedence.
    Otherwise the city name is looked up in ``CITY_COORDINATES``.

    Raises:
        HTTPException: If the city is not found and no coordinates given.
    """
    if request.latitude is not None and request.longitude is not None:
        return request.latitude, request.longitude, request.city

    city_key = request.city.strip().lower()
    city_data = CITY_COORDINATES.get(city_key)
    if city_data is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"City '{request.city}' is not in the supported city list. "
                "Provide explicit latitude/longitude or use GET /api/cities "
                "to see available cities."
            ),
        )
    return city_data["lat"], city_data["lon"], request.city.strip().title()


# ---------------------------------------------------------------------------
# Helper: run a single crawler with semaphore + error handling
# ---------------------------------------------------------------------------

async def _run_crawler(
    source: EventSource,
    crawler: Any,
    city: str,
    date: str,
    latitude: float,
    longitude: float,
    radius_km: float,
) -> tuple[EventSource, list[Event], dict | None]:
    """Execute one crawler inside the semaphore.

    Returns:
        A 3-tuple of (source, events, error_dict_or_none).
    """
    assert _semaphore is not None
    async with _semaphore:
        try:
            logger.info("Starting crawler: %s for %s on %s", source.value, city, date)
            events = await crawler.crawl(
                city=city,
                date=date,
                lat=latitude,
                lon=longitude,
                radius_km=radius_km,
            )
            logger.info(
                "Crawler %s returned %d events", source.value, len(events)
            )
            return source, events, None
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Crawler %s failed: %s\n%s", source.value, exc, tb)
            return source, [], {
                "source": source.value,
                "error": str(exc),
                "traceback": tb,
            }


# ---------------------------------------------------------------------------
# POST /api/search
# ---------------------------------------------------------------------------

@app.post("/api/search", response_model=SearchResponse)
async def search_events(request: SearchRequest) -> SearchResponse:
    """Search for events across all (or selected) platforms.

    Runs crawlers concurrently, aggregates and deduplicates results,
    computes distance from the user's position, filters by vibe if
    requested, and returns events sorted by engagement score (descending).
    """
    assert _settings is not None
    assert _crawlers is not None

    t0 = time.monotonic()

    # 1. Resolve coordinates
    latitude, longitude, city_name = _resolve_city(request)

    # 2. Determine which crawlers to run
    if request.platforms:
        sources_to_search = {
            src: crawler
            for src, crawler in _crawlers.items()
            if src in request.platforms
        }
    else:
        sources_to_search = dict(_crawlers)

    sources_searched = list(sources_to_search.keys())

    # 2.5. Run Researcher Agent to discover Instagram accounts
    research_data = {}
    try:
        from .agents.researcher import ResearcherAgent
        researcher = ResearcherAgent()
        research_result = await researcher.safe_execute({
            "city": city_name,
            "date": request.date,
            "vibes": request.vibes or [],
            "searchapi_key": _settings.SERPAPI_KEY,
        })
        if research_result.success and research_result.data:
            research_data = research_result.data
            logger.info(
                "Researcher found %d Instagram accounts for %s",
                len(research_data.get("instagram_accounts", [])),
                city_name,
            )
    except Exception as exc:
        logger.warning("Researcher agent failed: %s", exc)

    # Inject research context into crawlers that support it
    for crawler in sources_to_search.values():
        if hasattr(crawler, "set_research_context"):
            crawler.set_research_context({
                "research": research_data,
                "city": city_name,
                "date": request.date,
            })

    # 3. Launch all crawlers concurrently
    tasks = [
        _run_crawler(
            source=source,
            crawler=crawler,
            city=city_name,
            date=request.date,
            latitude=latitude,
            longitude=longitude,
            radius_km=request.radius_km,
        )
        for source, crawler in sources_to_search.items()
    ]

    results = await asyncio.gather(*tasks)

    # 4. Collect events and errors
    all_events: list[Event] = []
    sources_with_results: list[EventSource] = []
    errors: list[dict] = []

    for source, events, error in results:
        if error:
            errors.append(error)
        if events:
            sources_with_results.append(source)
            all_events.extend(events)

    # 5. Compute distance for every event that has coordinates
    for event in all_events:
        if event.latitude is not None and event.longitude is not None:
            event.distance_km = calculate_distance(
                latitude, longitude, event.latitude, event.longitude
            )

    # 6. Filter by radius (only events with known location)
    filtered_events: list[Event] = []
    for event in all_events:
        if event.distance_km is not None:
            if event.distance_km <= request.radius_km:
                filtered_events.append(event)
        else:
            # Keep events without coordinates (we can't filter them out)
            filtered_events.append(event)

    # 7. Filter by vibes (if specified)
    if request.vibes:
        requested_vibes = set(request.vibes)
        filtered_events = [
            ev for ev in filtered_events
            if not ev.vibes or set(ev.vibes) & requested_vibes
        ]

    # 8. Deduplicate
    filtered_events = deduplicate_events(filtered_events)

    # 9. Sort by engagement score (descending), then by date
    filtered_events.sort(
        key=lambda ev: (ev.engagement_score, ev.date),
        reverse=True,
    )

    # 10. Truncate to max_results
    filtered_events = filtered_events[: request.max_results]

    elapsed = round(time.monotonic() - t0, 3)

    logger.info(
        "Search complete for %s on %s: %d events from %d sources in %.3fs",
        city_name,
        request.date,
        len(filtered_events),
        len(sources_with_results),
        elapsed,
    )

    return SearchResponse(
        events=filtered_events,
        total_count=len(filtered_events),
        city=city_name,
        date=request.date,
        search_duration_seconds=elapsed,
        sources_searched=sources_searched,
        sources_with_results=sources_with_results,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# GET /api/cities
# ---------------------------------------------------------------------------

@app.get("/api/cities", response_model=list[CityInfo])
async def list_cities() -> list[CityInfo]:
    """Return all supported cities with their coordinates and timezone."""
    cities: list[CityInfo] = []
    for key, data in sorted(CITY_COORDINATES.items()):
        cities.append(
            CityInfo(
                name=key.title(),
                country=data["country"],
                latitude=data["lat"],
                longitude=data["lon"],
                timezone=data["tz"],
            )
        )
    return cities


# ---------------------------------------------------------------------------
# GET /api/vibes
# ---------------------------------------------------------------------------

@app.get("/api/vibes")
async def list_vibes() -> list[dict[str, str]]:
    """Return all available event vibe categories."""
    return [
        {"value": vibe.value, "label": vibe.name.replace("_", " ").title()}
        for vibe in EventVibe
    ]


# ---------------------------------------------------------------------------
# GET /api/sources
# ---------------------------------------------------------------------------

@app.get("/api/sources")
async def list_sources() -> list[dict[str, str]]:
    """Return all available event source platforms."""
    return [
        {"value": source.value, "label": source.name.replace("_", " ").title()}
        for source in EventSource
    ]


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """Basic health / liveness probe."""
    return {"status": "ok", "service": "city-event-crawler"}


# ---------------------------------------------------------------------------
# Entrypoint (for direct ``python -m backend.main`` usage)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
