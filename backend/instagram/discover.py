"""DISCOVER stage — find Instagram accounts for a city.

Three layers, each cheap to call and complementary:

  1. ``CITY_SEED_DATA``       — hand-curated baseline (no API cost).
  2. SerpAPI Google search    — broad query templates, parsed for handles in
                                snippets/titles/links of organic results.
  3. Listicle/blog body fetch — for top-ranked SerpAPI results that look like
                                listicles ("Top 20 Instagrams in Berlin"),
                                fetch the page HTML and extract every IG
                                handle in the body. This is where most of the
                                long-tail accounts come from.

Returns a deduplicated, ordered list of candidate handles. The TRIAGE stage
filters them. Designed to surface 100+ handles for big cities.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterable

import httpx

from ..models import EventVibe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hand-curated seeds (high signal, no API cost)
# ---------------------------------------------------------------------------

CITY_SEED_DATA: dict[str, dict[str, list[str]]] = {
    "budapest": {
        "instagram_seeds": [
            "szimplakert", "instantfogas", "akvariumklub", "a38hajo",
            "corvinteto", "durerkert", "larmbudapest", "aether.budapest",
            "dobozbudapest", "otkertbudapest", "flashbackbudapest",
            "budapestpark", "budapestflow", "welovebudapest",
        ],
    },
    "berlin": {
        "instagram_seeds": [
            "berghain.official", "kitkatclub_berlin", "aboutblank.berlin",
            "sisyphos_berlin", "watergateclub", "wilderenate", "holzmarkt25",
            "renate_berlin", "tresorberlin", "salonzursommerfrische",
        ],
    },
    "prague": {
        "instagram_seeds": [
            "crossclubprague", "ankali_prague", "fuchs2club", "roxyclubprague",
            "sasazuprague", "karlovylazne", "duplexprague", "meetfactory",
            "chapeau_rouge_prague", "epic_prague",
        ],
    },
    "barcelona": {
        "instagram_seeds": [
            "razzmatazzclubs", "salaapolob", "pachabcn",
            "nitsaclub", "inputhighfidelity", "lautbarcelona", "macarenaclub",
            "laterrrazza", "elrowofficial",
        ],
    },
    "amsterdam": {
        "instagram_seeds": [
            "deschoolamsterdam", "shelteramsterdam", "paradiso", "melkweg",
            "airamsterdam", "thuishavenamsterdam", "radion_amsterdam",
            "garagenoord",
        ],
    },
    "lisbon": {
        "instagram_seeds": [
            "luxfragil", "ministeriumclub", "musicboxlisboa",
            "villagunderground_lx", "damaslisboa", "pensaoamor",
        ],
    },
    "vienna": {
        "instagram_seeds": [
            "grelleforelle", "pratersauna", "flex_cafe", "fluc_vienna",
            "daswerkvienna", "sassvienna", "celeste.vienna",
        ],
    },
    "london": {
        "instagram_seeds": [
            "fabriclondon", "printworksldn", "thedrumsheds", "e1london",
            "egg_ldn", "xoyo_london", "corsicastudios", "villageunderground",
            "nighttalesldn",
        ],
    },
    "paris": {
        "instagram_seeds": [
            "rexclubparis", "concretemusic.paris", "machinedumoulinrouge",
            "djoonparis",
        ],
    },
}


# ---------------------------------------------------------------------------
# Query templates — broad coverage of nightlife / events / scenes
# ---------------------------------------------------------------------------

# General nightlife & venues
_GENERAL_QUERIES = [
    "{city} nightclub instagram",
    "{city} club promoter instagram",
    "{city} nightlife instagram pages to follow",
    "best {city} party instagram accounts",
    "best instagram accounts to follow in {city}",
    "must follow instagram accounts {city}",
    "{city} event organizers instagram",
    "{city} live music venue instagram",
    "{city} bar instagram",
    "{city} cocktail bar instagram",
    "{city} rooftop bar instagram",
    "{city} restaurant instagram",
    "{city} cafe instagram",
    "{city} food market events instagram",
]

# Genre / scene specific
_SCENE_QUERIES = [
    "{city} techno events instagram",
    "{city} house music instagram",
    "{city} drum and bass instagram",
    "{city} indie music instagram",
    "{city} jazz club instagram",
    "{city} electronic music instagram",
    "{city} underground events instagram",
    "{city} rave instagram",
    "{city} warehouse party instagram",
    "{city} after hours instagram",
    "{city} kink fetish events instagram",
    "{city} queer lgbtq events instagram",
    "{city} drag show instagram",
    "{city} burlesque instagram",
]

# Culture & arts
_CULTURE_QUERIES = [
    "{city} art gallery events instagram",
    "{city} museum instagram",
    "{city} theater instagram",
    "{city} comedy club instagram",
    "{city} bookshop events instagram",
    "{city} film screening instagram",
    "{city} poetry slam instagram",
]

# Listicle / publication queries — these surface aggregator pages
_LISTICLE_QUERIES = [
    "top instagram accounts {city} nightlife",
    "{city} time out instagram accounts to follow",
    "{city} resident advisor instagram",
    "{city} mixmag instagram",
    "{city} dj mag instagram",
    "{city} expat community instagram accounts",
    "what to do {city} this weekend instagram",
    "{city} secret events instagram",
    "site:reddit.com {city} instagram clubs nightlife",
    "site:medium.com {city} instagram nightlife",
    "site:timeout.com {city} instagram",
]

# Sport / wellness / lifestyle
_LIFESTYLE_QUERIES = [
    "{city} yoga studio instagram",
    "{city} run club instagram",
    "{city} climbing gym instagram",
    "{city} cycling crew instagram",
    "{city} hostel events instagram",
]

ALL_QUERY_TEMPLATES = (
    _GENERAL_QUERIES
    + _SCENE_QUERIES
    + _CULTURE_QUERIES
    + _LISTICLE_QUERIES
    + _LIFESTYLE_QUERIES
)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

EXCLUDED_ACCOUNTS = {
    # IG own routes
    "p", "explore", "reel", "reels", "stories", "accounts", "about",
    "developer", "instagram", "popular", "tags", "locations", "tv",
    "directory", "press",
    # generic large
    "instagramofficial", "instagramforbusiness",
    # platforms / aggregators (not local)
    "tiktok", "facebook", "twitter", "x", "youtube", "spotify",
    "soundcloud", "tripadvisor", "airbnb", "booking", "google",
    "wikipedia",
}

_GENERIC_SUBSTRINGS = ("gmail", "yahoo", "hotmail", "outlook", "support")

_HANDLE_PATTERN = re.compile(r"[a-z0-9_.]{3,30}")
_INSTAGRAM_URL_PATTERN = re.compile(
    r"(?:www\.|https?://)?instagram\.com/([a-zA-Z0-9_.]{3,30})",
    re.IGNORECASE,
)
_AT_MENTION_PATTERN = re.compile(r"@([a-zA-Z0-9_.]{3,30})")


def _normalize_handle(raw: str) -> str | None:
    handle = raw.lower().strip().lstrip("@").rstrip("./")
    if not handle or handle in EXCLUDED_ACCOUNTS:
        return None
    if not _HANDLE_PATTERN.fullmatch(handle):
        return None
    if any(s in handle for s in _GENERIC_SUBSTRINGS):
        return None
    # Reject anything that's a pure number or mostly digits
    if handle.isdigit():
        return None
    return handle


def _extract_handles(text: str) -> set[str]:
    """Pull IG handles from any text blob (links + @ mentions)."""
    handles: set[str] = set()
    for match in _INSTAGRAM_URL_PATTERN.findall(text):
        h = _normalize_handle(match)
        if h:
            handles.add(h)
    for match in _AT_MENTION_PATTERN.findall(text):
        h = _normalize_handle(match)
        if h:
            handles.add(h)
    return handles


# ---------------------------------------------------------------------------
# SerpAPI search — snippet-level extraction
# ---------------------------------------------------------------------------

async def _serpapi_search(
    query: str,
    api_key: str,
    http: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[set[str], list[str]]:
    """Run one SerpAPI Google query.

    Returns:
        (handles_from_snippets, top_result_urls_to_fetch)
    """
    async with sem:
        try:
            resp = await http.get(
                "https://www.searchapi.io/api/v1/search",
                params={
                    "engine": "google", "q": query, "hl": "en",
                    "num": 10, "api_key": api_key,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("SerpAPI %r → HTTP %d", query, resp.status_code)
                return set(), []
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("SerpAPI %r failed: %s", query, exc)
            return set(), []

    handles: set[str] = set()
    urls: list[str] = []
    for item in data.get("organic_results", []) or []:
        link = item.get("link", "") or ""
        snippet = item.get("snippet", "") or ""
        title = item.get("title", "") or ""
        bag = " ".join([link, snippet, title])
        handles |= _extract_handles(bag)
        if link and link.startswith(("http://", "https://")) and "instagram.com" not in link:
            urls.append(link)
    return handles, urls


# ---------------------------------------------------------------------------
# Page fetch — extract handles from listicle / blog HTML
# ---------------------------------------------------------------------------

# URL patterns that suggest a listicle worth fetching
_LISTICLE_URL_HINTS = re.compile(
    r"(top|best|guide|must|essential|follow|list|directory|round[\-\s]?up|"
    r"clubs|nightlife|venues|events|bars|where[\-\s]to)",
    re.IGNORECASE,
)

# Skip these — they're either anti-bot or rarely have handle lists
_BLOCKED_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "tiktok.com", "youtube.com", "spotify.com", "linkedin.com",
    "pinterest.com", "wikipedia.org",
}


def _is_useful_url(url: str) -> bool:
    """Decide whether a URL is worth fetching for handle extraction."""
    lower = url.lower()
    for blocked in _BLOCKED_DOMAINS:
        if blocked in lower:
            return False
    # Prefer URLs whose path or query suggests a listicle / aggregation page
    return bool(_LISTICLE_URL_HINTS.search(lower))


async def _fetch_handles_from_page(
    url: str,
    http: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> set[str]:
    """Fetch *url* and pull every IG handle out of the body."""
    async with sem:
        try:
            resp = await http.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
                timeout=12,
            )
            if resp.status_code != 200:
                return set()
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype.lower():
                return set()
            body = resp.text[:300_000]  # cap at ~300KB
        except (httpx.HTTPError, UnicodeDecodeError) as exc:
            logger.debug("Page fetch %s failed: %s", url, exc)
            return set()

    return _extract_handles(body)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def discover_accounts(
    city: str,
    serpapi_key: str,
    vibes: Iterable[EventVibe] | None = None,
    max_queries: int = 24,
    max_pages_to_fetch: int = 18,
    parallel_serpapi: int = 6,
    parallel_fetch: int = 6,
) -> list[str]:
    """Return candidate IG handles for *city*.

    Order: seeds first (highest signal), then SerpAPI snippet handles, then
    handles deep-extracted from top listicle pages. Deduplicated. Designed to
    surface 80-150+ handles for big cities; TRIAGE then prunes the list.
    """
    city_key = city.lower().strip()
    seed = CITY_SEED_DATA.get(city_key, {})
    handles: list[str] = list(seed.get("instagram_seeds", []))
    seen: set[str] = set(handles)

    if not serpapi_key:
        logger.warning(
            "DISCOVER: SERPAPI_KEY not set — using %d seed handles only", len(handles)
        )
        return handles

    # Build query list — generic + scene-specific + vibe-specific
    queries = [q.format(city=city_key) for q in ALL_QUERY_TEMPLATES]
    if vibes:
        for vibe in list(vibes)[:4]:
            vibe_name = vibe.value if hasattr(vibe, "value") else str(vibe)
            queries.append(f"{city_key} {vibe_name.replace('_', ' ')} events instagram")
            queries.append(f"best {city_key} {vibe_name.replace('_', ' ')} instagram accounts")
    queries = queries[:max_queries]

    serpapi_sem = asyncio.Semaphore(parallel_serpapi)
    fetch_sem = asyncio.Semaphore(parallel_fetch)

    async with httpx.AsyncClient(timeout=20) as http:
        # Step 1 — fan out SerpAPI calls
        serpapi_tasks = [_serpapi_search(q, serpapi_key, http, serpapi_sem) for q in queries]
        serpapi_results = await asyncio.gather(*serpapi_tasks, return_exceptions=True)

        snippet_handles: set[str] = set()
        candidate_urls: list[str] = []
        for result in serpapi_results:
            if isinstance(result, Exception):
                continue
            found_handles, found_urls = result
            snippet_handles |= found_handles
            candidate_urls.extend(found_urls)

        for h in sorted(snippet_handles):
            if h not in seen:
                seen.add(h)
                handles.append(h)

        # Step 2 — fetch promising pages and extract handles from full HTML
        # Dedup URLs preserving the order we encountered them in
        seen_urls: set[str] = set()
        ranked_urls: list[str] = []
        for url in candidate_urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            if _is_useful_url(url):
                ranked_urls.append(url)
        ranked_urls = ranked_urls[:max_pages_to_fetch]

        if ranked_urls:
            page_tasks = [_fetch_handles_from_page(u, http, fetch_sem) for u in ranked_urls]
            page_results = await asyncio.gather(*page_tasks, return_exceptions=True)
            page_count = 0
            for result in page_results:
                if isinstance(result, Exception):
                    continue
                page_count += 1
                for h in sorted(result):
                    if h not in seen:
                        seen.add(h)
                        handles.append(h)
            logger.info("DISCOVER: fetched %d pages", page_count)

    logger.info(
        "DISCOVER: %s → %d handles (seeds=%d, snippet=%d, pages=%d)",
        city_key,
        len(handles),
        len(seed.get("instagram_seeds", [])),
        len(snippet_handles),
        len(ranked_urls),
    )
    return handles
