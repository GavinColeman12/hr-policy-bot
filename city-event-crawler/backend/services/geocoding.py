"""
Geocoding Service.

Provides city geocoding (config lookup -> Google Maps -> Nominatim fallback),
haversine distance calculations, and reverse geocoding.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import httpx

from backend.config import CITY_COORDINATES, get_settings

logger = logging.getLogger(__name__)

# Earth radius in kilometres
_EARTH_RADIUS_KM = 6371.0


class GeocodingService:
    """Resolve city names to coordinates and compute distances."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------ #
    # City geocoding
    # ------------------------------------------------------------------ #

    async def geocode_city(self, city_name: str) -> Optional[dict]:
        """Return ``{"lat": float, "lon": float}`` for *city_name*.

        Resolution order:
        1. Pre-configured ``CITY_COORDINATES`` lookup.
        2. Google Maps Geocoding API (if ``GOOGLE_MAPS_API_KEY`` is set).
        3. OpenStreetMap Nominatim (public, rate-limited).

        Returns ``None`` when all strategies fail.
        """
        key = city_name.lower().strip()

        # 1. Config lookup
        if key in CITY_COORDINATES:
            entry = CITY_COORDINATES[key]
            logger.debug("Geocoded '%s' from config: %s", city_name, entry)
            return {"lat": entry["lat"], "lon": entry["lon"]}

        # 2. Google Maps Geocoding API
        if self._settings.GOOGLE_MAPS_API_KEY:
            result = await self._google_geocode(city_name)
            if result:
                return result

        # 3. Nominatim fallback
        return await self._nominatim_geocode(city_name)

    # ------------------------------------------------------------------ #
    # Distance helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_distance(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Haversine distance between two points, returned in kilometres."""
        lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
        lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return round(_EARTH_RADIUS_KM * c, 2)

    def add_distances(
        self,
        events: list[dict],
        user_lat: float,
        user_lon: float,
    ) -> list[dict]:
        """Add ``distance_km`` to each event dict that has lat/lon."""
        for event in events:
            lat = event.get("latitude")
            lon = event.get("longitude")
            if lat is not None and lon is not None:
                event["distance_km"] = self.calculate_distance(
                    user_lat, user_lon, lat, lon,
                )
            else:
                event["distance_km"] = None
        return events

    # ------------------------------------------------------------------ #
    # Reverse geocoding
    # ------------------------------------------------------------------ #

    async def reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        """Get a human-readable address from coordinates.

        Tries Google first, falls back to Nominatim.
        """
        if self._settings.GOOGLE_MAPS_API_KEY:
            result = await self._google_reverse(lat, lon)
            if result:
                return result

        return await self._nominatim_reverse(lat, lon)

    # ------------------------------------------------------------------ #
    # Google Maps helpers
    # ------------------------------------------------------------------ #

    async def _google_geocode(self, city_name: str) -> Optional[dict]:
        """Geocode via Google Maps Geocoding API."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={
                        "address": city_name,
                        "key": self._settings.GOOGLE_MAPS_API_KEY,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                result = {"lat": loc["lat"], "lon": loc["lng"]}
                logger.info("Google geocoded '%s' -> %s", city_name, result)
                return result
        except Exception:
            logger.warning("Google geocoding failed for '%s'", city_name, exc_info=True)
        return None

    async def _google_reverse(self, lat: float, lon: float) -> Optional[str]:
        """Reverse-geocode via Google Maps."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={
                        "latlng": f"{lat},{lon}",
                        "key": self._settings.GOOGLE_MAPS_API_KEY,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") == "OK" and data.get("results"):
                return data["results"][0].get("formatted_address")
        except Exception:
            logger.warning("Google reverse geocode failed", exc_info=True)
        return None

    # ------------------------------------------------------------------ #
    # Nominatim (OpenStreetMap) helpers
    # ------------------------------------------------------------------ #

    async def _nominatim_geocode(self, city_name: str) -> Optional[dict]:
        """Geocode via Nominatim (free, rate-limited)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": city_name,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={"User-Agent": "CityEventCrawler/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

            if data:
                result = {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
                logger.info("Nominatim geocoded '%s' -> %s", city_name, result)
                return result
        except Exception:
            logger.warning("Nominatim geocoding failed for '%s'", city_name, exc_info=True)
        return None

    async def _nominatim_reverse(self, lat: float, lon: float) -> Optional[str]:
        """Reverse-geocode via Nominatim."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={
                        "lat": lat,
                        "lon": lon,
                        "format": "json",
                    },
                    headers={"User-Agent": "CityEventCrawler/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

            return data.get("display_name")
        except Exception:
            logger.warning("Nominatim reverse geocode failed", exc_info=True)
        return None
