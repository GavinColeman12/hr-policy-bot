"""Researcher Agent - auto-discovers Instagram accounts, venues, and sources for a city.

Phase 1: Uses pre-researched data + SearchAPI Google to find:
  - Instagram accounts (clubs, promoters, venues, event pages)
  - Relevant subreddits and hashtags
  - Local event listing sites
  - Known venues and their social handles

This data feeds into the Crawler Agent so it knows WHERE to look.
"""

import asyncio
import logging
import re

import httpx

from .base_agent import BaseAgent, AgentRole, AgentResult

logger = logging.getLogger(__name__)

# Pre-researched city-specific seed data
CITY_SEED_DATA = {
    "budapest": {
        "instagram_seeds": [
            "szimplakert", "instantfogas", "akvariumklub", "a38hajo",
            "corvinteto", "durerkert", "larmbudapest", "aether.budapest",
            "dobozbudapest", "otkertbudapest", "flashbackbudapest",
            "budapestpark", "budapestflow", "welovebudapest",
        ],
        "subreddits": ["budapest", "hungary", "solotravel"],
        "known_venues": [
            "Szimpla Kert", "Instant-Fogas", "Akvárium Klub", "A38",
            "Corvintető", "Dürer Kert", "Lärm", "Aether", "Doboz", "Ötkert",
        ],
    },
    "berlin": {
        "instagram_seeds": [
            "beraboredein", "berghain.official", "treaborerlin", "kitkatclub_berlin",
            "aboutblank.berlin", "sisyphos_berlin", "kaboreerblau", "watergateclub",
            "wilderenate", "raboreerlin.official", "holzmarkt25",
        ],
        "subreddits": ["berlin", "berlinsocialclub", "berlintechno"],
        "known_venues": [
            "Berghain", "Tresor", "KitKatClub", "About Blank", "Sisyphos",
            "Watergate", "Wilde Renate", "Kater Blau", "Holzmarkt", "OHM",
        ],
    },
    "prague": {
        "instagram_seeds": [
            "crossclubprague", "ankali_prague", "fuchs2club", "roxyclubprague",
            "sasazuprague", "karlovylazne", "duplexprague", "meetfactory",
            "chapeau_rouge_prague", "epic_prague",
        ],
        "subreddits": ["prague", "czech"],
        "known_venues": [
            "Cross Club", "Ankali", "Fuchs2", "Roxy", "SaSaZu",
            "Karlovy Lazne", "Duplex", "MeetFactory", "Chapeau Rouge",
        ],
    },
    "barcelona": {
        "instagram_seeds": [
            "razzmatazzclubs", "salaapolob", "maborercelona_club", "pachabcn",
            "nitsaclub", "inputhighfidelity", "lautbarcelona", "macarenaclub",
            "laterrrazza", "elrowofficial",
        ],
        "subreddits": ["barcelona"],
        "known_venues": [
            "Razzmatazz", "Sala Apolo", "Moog", "Pacha Barcelona",
            "Nitsa Club", "Input", "Laut", "Macarena Club", "La Terrrazza",
        ],
    },
    "amsterdam": {
        "instagram_seeds": [
            "deschoolamsterdam", "shelteramsterdam", "paradiso", "melkweg",
            "airamsterdam", "thuishavenamsterdam", "radion_amsterdam",
            "garagenoord", "dekering",
        ],
        "subreddits": ["amsterdam", "amsterdamsocialclub"],
        "known_venues": [
            "De School", "Shelter", "Paradiso", "Melkweg", "AIR",
            "Thuishaven", "Radion", "Garage Noord",
        ],
    },
    "lisbon": {
        "instagram_seeds": [
            "luxfragil", "ministeriumclub", "musicboxlisboa",
            "villagunderground_lx", "damaslisboa", "pensaoamor",
        ],
        "subreddits": ["lisbon", "portugal"],
        "known_venues": [
            "Lux Frágil", "Ministerium", "Music Box", "Village Underground",
            "Damas", "Pensão Amor",
        ],
    },
    "vienna": {
        "instagram_seeds": [
            "grelleforelle", "pratersauna", "flex_cafe", "fluc_vienna",
            "daswerkvienna", "sassvienna", "celeste.vienna",
        ],
        "subreddits": ["vienna", "wien"],
        "known_venues": [
            "Grelle Forelle", "Pratersauna", "Flex", "Fluc", "Das Werk",
        ],
    },
    "london": {
        "instagram_seeds": [
            "fabriclondon", "printworksldn", "thedrumsheds", "e1london",
            "egg_ldn", "xoyo_london", "corsicastudios", "villageunderground",
            "nighttalesldn", "thejaguar.ldn",
        ],
        "subreddits": ["london", "londonsocialclub"],
        "known_venues": [
            "Fabric", "Printworks", "Drumsheds", "E1", "EGG",
            "XOYO", "Corsica Studios", "Village Underground",
        ],
    },
}

# Google search queries to discover Instagram accounts for a city
DISCOVERY_QUERIES = [
    "{city} nightclub instagram",
    "{city} club promoter instagram",
    "{city} techno events instagram",
    "{city} nightlife instagram pages to follow",
    "best {city} party instagram accounts",
    "{city} underground events instagram",
    "{city} kink fetish events instagram",
    "{city} bar crawl pub events instagram",
    "{city} live music venue instagram",
    "{city} social events meetup instagram",
    "{city} expat community instagram",
    "{city} food market events instagram",
    "{city} art gallery events instagram",
    "{city} queer lgbtq events instagram",
]

# Accounts to always exclude (generic/irrelevant)
EXCLUDED_ACCOUNTS = {
    "p", "explore", "reel", "stories", "accounts", "about", "developer",
    "instagram", "popular", "tags", "locations", "tv", "reels",
}


class ResearcherAgent(BaseAgent):
    """Discovers relevant Instagram accounts, venues, and sources for a city.

    Uses a two-phase approach:
    1. Seed data: pre-researched accounts for major cities
    2. Discovery: SearchAPI Google to find MORE accounts automatically
    """

    role = AgentRole.RESEARCHER
    name = "Researcher"

    async def execute(self, context: dict) -> AgentResult:
        city = context["city"].lower().strip()
        date = context["date"]
        vibes = context.get("vibes", [])
        api_key = context.get("searchapi_key", "")

        logger.info(f"Researching sources for {city} on {date}")

        # Start with seed data
        seed = dict(CITY_SEED_DATA.get(city, {}))
        instagram_accounts = set(seed.get("instagram_seeds", []))
        subreddits = seed.get("subreddits", [city.replace(" ", ""), "solotravel"])
        known_venues = seed.get("known_venues", [])

        # Phase 2: Auto-discover more Instagram accounts via Google
        if api_key:
            discovered = await self._discover_instagram_accounts(city, api_key, vibes)
            instagram_accounts.update(discovered)
            logger.info(f"  Discovered {len(discovered)} new accounts, total: {len(instagram_accounts)}")

        # Also discover accounts from venue names
        if api_key and known_venues:
            venue_accounts = await self._discover_venue_accounts(known_venues, city, api_key)
            instagram_accounts.update(venue_accounts)

        # Generate hashtags
        city_tag = city.replace(" ", "").replace("-", "")
        instagram_hashtags = [
            f"{city_tag}events", f"{city_tag}nightlife", f"{city_tag}party",
            f"{city_tag}tonight", f"{city_tag}club", f"{city_tag}techno",
            f"{city_tag}rave", f"{city_tag}music", f"{city_tag}culture",
        ]

        # Add vibe-specific hashtags
        for vibe in vibes:
            vibe_name = vibe.value if hasattr(vibe, "value") else str(vibe)
            instagram_hashtags.append(f"{city_tag}{vibe_name.replace('_', '')}")

        research = {
            "instagram_accounts": sorted(instagram_accounts),
            "instagram_hashtags": instagram_hashtags,
            "subreddits": subreddits,
            "known_venues": known_venues,
            "google_queries": self._build_google_queries(city, date, vibes),
        }

        return AgentResult(
            agent=self.role,
            success=True,
            data=research,
            metadata={
                "city": city,
                "date": date,
                "instagram_accounts_count": len(instagram_accounts),
                "discovery_method": "seed+google" if api_key else "seed_only",
            },
        )

    async def _discover_instagram_accounts(self, city: str, api_key: str, vibes: list) -> set[str]:
        """Use SearchAPI Google to find Instagram accounts for this city."""
        accounts = set()

        # Select queries based on vibes
        queries = [q.format(city=city) for q in DISCOVERY_QUERIES]

        # Add vibe-specific queries
        for vibe in vibes:
            vibe_name = vibe.value if hasattr(vibe, "value") else str(vibe)
            queries.append(f"{city} {vibe_name.replace('_', ' ')} events instagram")

        async with httpx.AsyncClient(timeout=15) as client:
            for query in queries[:8]:  # Limit to 8 queries to conserve API credits
                try:
                    resp = await client.get(
                        "https://www.searchapi.io/api/v1/search",
                        params={"engine": "google", "q": query, "hl": "en", "num": 10, "api_key": api_key},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    for item in data.get("organic_results", []):
                        link = item.get("link", "")
                        snippet = item.get("snippet", "")
                        title = item.get("title", "")
                        text = f"{link} {snippet} {title}"

                        # Extract from instagram.com URLs
                        for match in re.findall(r"instagram\.com/([a-zA-Z0-9_.]{3,30})", text):
                            handle = match.lower().rstrip("./")
                            if handle not in EXCLUDED_ACCOUNTS:
                                accounts.add(handle)

                        # Extract @mentions
                        for match in re.findall(r"@([a-zA-Z0-9_.]{3,30})", text):
                            handle = match.lower()
                            if handle not in EXCLUDED_ACCOUNTS and not any(
                                x in handle for x in ("gmail", "email", "yahoo", "hotmail", "outlook")
                            ):
                                accounts.add(handle)

                except Exception as e:
                    logger.warning(f"Discovery query failed: {e}")

        return accounts

    async def _discover_venue_accounts(self, venues: list[str], city: str, api_key: str) -> set[str]:
        """Find Instagram accounts for known venues."""
        accounts = set()
        async with httpx.AsyncClient(timeout=15) as client:
            for venue in venues[:10]:  # Top 10 venues
                try:
                    resp = await client.get(
                        "https://www.searchapi.io/api/v1/search",
                        params={
                            "engine": "google",
                            "q": f"{venue} {city} instagram",
                            "hl": "en", "num": 5, "api_key": api_key,
                        },
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    for item in data.get("organic_results", []):
                        link = item.get("link", "")
                        for match in re.findall(r"instagram\.com/([a-zA-Z0-9_.]{3,30})", link):
                            handle = match.lower().rstrip("./")
                            if handle not in EXCLUDED_ACCOUNTS:
                                accounts.add(handle)

                except Exception as e:
                    logger.warning(f"Venue discovery failed for {venue}: {e}")

        return accounts

    def _build_google_queries(self, city, date, vibes):
        queries = [
            f"{city} events {date}",
            f"{city} things to do {date}",
            f"{city} nightlife {date}",
            f"{city} parties this week",
            f"what's on in {city} {date}",
        ]
        for vibe in vibes:
            vibe_name = vibe.value if hasattr(vibe, "value") else vibe
            queries.append(f"{city} {vibe_name.lower().replace('_', ' ')} events {date}")
        return queries
