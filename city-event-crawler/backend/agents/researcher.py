"""Researcher Agent - discovers relevant sources, accounts, and search terms for a city."""

import logging
from .base_agent import BaseAgent, AgentRole, AgentResult

logger = logging.getLogger(__name__)

# Pre-researched city-specific data for major European cities
CITY_RESEARCH_DATA = {
    "budapest": {
        "subreddits": ["budapest", "hungary", "budapestNightlife", "solotravel"],
        "instagram_hashtags": [
            "budapestevents", "budapestnightlife", "budapestparty", "budapestnight",
            "ruinbar", "ruinpub", "szimplakert", "instantdrinkbar", "akvarium",
            "budapestunderground", "budapestclub", "budapestlife", "budapestfood",
            "budapestwine", "budapestbath", "budapestculture", "budapesttechno",
            "budapestrave", "budapestdating", "budapestexpat", "budapesttonight",
            "romkocsma", "budapestfestival", "szigetfestival",
        ],
        "ra_area_id": 59,
        "ra_slug": "budapest",
        "known_venues": [
            "Szimpla Kert", "Instant-Fogas", "Akvárium Klub", "A38",
            "Doboz", "Ötkert", "Corvintető", "Dürer Kert", "Lärm",
            "Aether", "Toldi", "Központ", "Bobek", "Flashback",
        ],
        "meetup_topics": ["nightlife", "social", "expats", "language-exchange", "hiking", "tech"],
        "twitter_accounts": ["@budapest", "@BudapestGuide", "@WeloveBudapest"],
        "local_event_sites": [
            "https://welovebudapest.com/en/programmes",
            "https://www.timeout.com/budapest/things-to-do",
            "https://funzine.hu/en/",
        ],
        "dice_city_slug": "budapest",
        "fetlife_location": "Budapest, Hungary",
    },
    "berlin": {
        "subreddits": ["berlin", "berlinsocialclub", "berghain", "berlintechno"],
        "instagram_hashtags": [
            "berlinevents", "berlinnightlife", "berlintechno", "berlinparty",
            "berghain", "tresor", "kitkatclub", "aboutblank", "berlinrave",
            "berlinunderground", "berlinclub", "berlinlife", "berlinmusic",
            "berlinart", "berlinfood", "berlinexpat", "berlintonight",
            "sisyphos", "berlinculture", "berlinqueer", "berlinkinky",
        ],
        "ra_area_id": 34,
        "ra_slug": "berlin",
        "known_venues": [
            "Berghain", "Tresor", "KitKatClub", "About Blank", "Sisyphos",
            "Watergate", "Wilde Renate", "RSO.Berlin", "Griessmuehle",
            "://about blank", "Kater Blau", "Holzmarkt", "Salon zur Wilden Renate",
            "OHM", "Anomalie", "Else", "Ritter Butzke",
        ],
        "meetup_topics": ["techno", "social", "expats", "startup", "queer", "kink"],
        "twitter_accounts": ["@berlaborede", "@VisitBerlin", "@BerlinTechno"],
        "local_event_sites": [
            "https://www.residentadvisor.net/events/de/berlin",
            "https://www.timeout.com/berlin/things-to-do",
            "https://www.exberliner.com/events/",
        ],
        "dice_city_slug": "berlin",
        "fetlife_location": "Berlin, Germany",
    },
    "prague": {
        "subreddits": ["prague", "czech", "czechrepublic"],
        "instagram_hashtags": [
            "pragueevents", "praguenightlife", "pragueparty", "praguenight",
            "pragueclub", "praguelife", "praguefood", "pragueexpat",
            "praguetonight", "praguebar", "praguetechno", "pragueculture",
            "pragueunderground", "crossclubprague", "karlovylazne",
        ],
        "ra_area_id": 178,
        "ra_slug": "prague",
        "known_venues": [
            "Cross Club", "Roxy", "SaSaZu", "Karlovy Lazne", "Duplex",
            "Lucerna Music Bar", "Chapeau Rouge", "Ankali", "Fuchs2",
            "Storm Club", "Meet Factory", "Palac Akropolis",
        ],
        "meetup_topics": ["social", "expats", "language", "tech", "hiking"],
        "twitter_accounts": ["@Prague_CZ", "@PragueEvents"],
        "local_event_sites": [
            "https://www.timeout.com/prague/things-to-do",
            "https://goout.net/en/prague/events/",
        ],
        "dice_city_slug": "prague",
        "fetlife_location": "Prague, Czech Republic",
    },
    "barcelona": {
        "subreddits": ["barcelona", "spain", "barcelonaexpats"],
        "instagram_hashtags": [
            "barcelonaevents", "barcelonanightlife", "barcelonaparty",
            "barcelonanight", "barcelonaclub", "barcelonalife", "barcelonafood",
            "barcelonabeach", "barcelonatonight", "barcelonatechno",
            "ravalbarcelona", "barcelonaunderground", "raboreal",
        ],
        "ra_area_id": 44,
        "ra_slug": "barcelona",
        "known_venues": [
            "Razzmatazz", "Moog", "Sala Apolo", "Pacha Barcelona",
            "Nitsa Club", "Input", "Laut", "Macarena Club",
            "La Terrrazza", "Red58", "Upload", "City Hall",
        ],
        "meetup_topics": ["social", "expats", "language-exchange", "beach", "tech", "salsa"],
        "twitter_accounts": ["@Barcelona_cat", "@bcaboreal"],
        "local_event_sites": [
            "https://www.timeout.com/barcelona/things-to-do",
            "https://www.barcelonanavigator.com/events",
        ],
        "dice_city_slug": "barcelona",
        "fetlife_location": "Barcelona, Spain",
    },
    "amsterdam": {
        "subreddits": ["amsterdam", "netherlands", "amsterdamsocialclub"],
        "instagram_hashtags": [
            "amsterdamevents", "amsterdamnightlife", "amsterdamparty",
            "amsterdamclub", "amsterdamlife", "amsterdamfood",
            "amsterdamtonight", "amsterdamtechno", "amsterdamrave",
            "amsterdamunderground", "deSchool", "shelteramsterdam",
        ],
        "ra_area_id": 29,
        "ra_slug": "amsterdam",
        "known_venues": [
            "De School", "Shelter", "Paradiso", "Melkweg",
            "AIR Amsterdam", "Claire", "Marktkantine", "Thuishaven",
            "Garage Noord", "Lofi", "Radion", "NDSM",
        ],
        "meetup_topics": ["social", "expats", "tech", "startup", "cycling", "art"],
        "twitter_accounts": ["@iaboredamsterdam", "@Amsterdam"],
        "local_event_sites": [
            "https://www.timeout.com/amsterdam/things-to-do",
            "https://www.iamsterdam.com/en/see-and-do/whats-on",
        ],
        "dice_city_slug": "amsterdam",
        "fetlife_location": "Amsterdam, Netherlands",
    },
    "lisbon": {
        "subreddits": ["lisbon", "portugal", "lisbonexpats"],
        "instagram_hashtags": [
            "lisbonevents", "lisbonnightlife", "lisbonparty", "lisbonnight",
            "lisbonclub", "lisbonlife", "lisbonfood", "lisbontonight",
            "lisbontechno", "luxfragil", "lisbonunderground", "bairroalto",
        ],
        "ra_area_id": 110,
        "ra_slug": "lisbon",
        "known_venues": [
            "Lux Frágil", "Ministerium", "Village Underground",
            "Music Box", "Titanic Sur Mer", "Pensão Amor",
            "Damas", "Valsa", "Rive Rouge", "ZDB",
        ],
        "meetup_topics": ["social", "expats", "digital-nomad", "surf", "tech", "fado"],
        "twitter_accounts": ["@visitlisboa"],
        "local_event_sites": [
            "https://www.timeout.com/lisbon/things-to-do",
            "https://www.visitlisboa.com/en/events",
        ],
        "dice_city_slug": "lisbon",
        "fetlife_location": "Lisbon, Portugal",
    },
    "vienna": {
        "subreddits": ["vienna", "wien", "austria"],
        "instagram_hashtags": [
            "viennaevents", "viennanightlife", "viennaparty", "viennatonight",
            "viennaclub", "viennafood", "viennaculture", "viennamusic",
            "viennatechno", "grellforte", "pratersouna",
        ],
        "ra_area_id": 169,
        "ra_slug": "vienna",
        "known_venues": [
            "Grelle Forelle", "Pratersauna", "Flex", "Fluc",
            "Das Werk", "Sass", "Volksgarten", "Camera Club",
            "Dual", "Celeste", "Horst",
        ],
        "meetup_topics": ["social", "expats", "classical-music", "tech", "hiking"],
        "twitter_accounts": ["@Vienna_en"],
        "local_event_sites": [
            "https://www.timeout.com/vienna/things-to-do",
            "https://events.wien.info/en/",
        ],
        "dice_city_slug": "vienna",
        "fetlife_location": "Vienna, Austria",
    },
    "warsaw": {
        "subreddits": ["warsaw", "poland", "polska"],
        "instagram_hashtags": [
            "warsawevents", "warsawnightlife", "warsawparty", "warsawtonight",
            "warsawclub", "warsawlife", "warsawfood", "warsawtechno",
            "smolna", "jasnapolar", "warsawunderground",
        ],
        "ra_area_id": 170,
        "ra_slug": "warsaw",
        "known_venues": [
            "Smolna", "Jasna 1", "Pogłos", "Luzztro",
            "Prozak 2.0", "Klubokawiarnia", "Hydrozagadka", "1500m2",
        ],
        "meetup_topics": ["social", "expats", "tech", "startup", "language"],
        "twitter_accounts": ["@Warsaw"],
        "local_event_sites": [
            "https://www.timeout.com/warsaw",
            "https://warsawlocal.com/events",
        ],
        "dice_city_slug": "warsaw",
        "fetlife_location": "Warsaw, Poland",
    },
    "krakow": {
        "subreddits": ["krakow", "poland"],
        "instagram_hashtags": [
            "krakowevents", "krakownightlife", "krakowparty",
            "krakowclub", "krakowlife", "krakowfood", "krakowtonight",
        ],
        "ra_area_id": 171,
        "ra_slug": "krakow",
        "known_venues": [
            "Prozak", "Szpitalna 1", "Frantic", "Forum Przestrzenie",
            "Bunkier Sztuki", "Klub re", "Hive",
        ],
        "meetup_topics": ["social", "expats", "language", "hiking"],
        "twitter_accounts": [],
        "local_event_sites": [
            "https://www.timeout.com/krakow",
        ],
        "dice_city_slug": "krakow",
        "fetlife_location": "Krakow, Poland",
    },
    "belgrade": {
        "subreddits": ["belgrade", "serbia"],
        "instagram_hashtags": [
            "belgradeevents", "belgradenightlife", "belgraduparty",
            "belgradeclub", "belgradelife", "belgradefood", "belgradetonight",
            "belgradeunderground", "drugstore_belgrade", "belgradesplavovi",
        ],
        "ra_area_id": 183,
        "ra_slug": "belgrade",
        "known_venues": [
            "Drugstore", "20/44", "Klub Mladih", "Hangar",
            "Splavovi (river clubs)", "Lasta", "Brankow", "Tube",
            "KC Grad", "Mikser House",
        ],
        "meetup_topics": ["social", "expats", "nightlife", "tech"],
        "twitter_accounts": [],
        "local_event_sites": [],
        "dice_city_slug": "belgrade",
        "fetlife_location": "Belgrade, Serbia",
    },
}

# Default research data for cities not in the pre-researched list
DEFAULT_RESEARCH = {
    "subreddits": [],
    "instagram_hashtags": [],
    "ra_area_id": None,
    "ra_slug": None,
    "known_venues": [],
    "meetup_topics": ["social", "expats", "nightlife"],
    "twitter_accounts": [],
    "local_event_sites": [],
    "dice_city_slug": None,
    "fetlife_location": None,
}


class ResearcherAgent(BaseAgent):
    """Discovers relevant sources, accounts, hashtags, and search terms for a city.

    This agent acts as the intelligence gatherer - it figures out WHERE to look
    for events in a given city. It provides city-specific context that the
    Crawler Agent uses to know which subreddits, hashtags, venues, and local
    sites to search.
    """

    role = AgentRole.RESEARCHER
    name = "Researcher"

    async def execute(self, context: dict) -> AgentResult:
        city = context["city"].lower().strip()
        date = context["date"]
        vibes = context.get("vibes", [])

        logger.info(f"Researching sources for {city} on {date}")

        # Look up pre-researched data or build dynamic research
        research = dict(CITY_RESEARCH_DATA.get(city, DEFAULT_RESEARCH))

        # Dynamically generate city-specific hashtags if not pre-researched
        if not research["instagram_hashtags"]:
            city_tag = city.replace(" ", "").replace("-", "")
            research["instagram_hashtags"] = [
                f"{city_tag}events", f"{city_tag}nightlife", f"{city_tag}party",
                f"{city_tag}tonight", f"{city_tag}club", f"{city_tag}life",
                f"{city_tag}food", f"{city_tag}music", f"{city_tag}culture",
            ]

        if not research["subreddits"]:
            research["subreddits"] = [city.replace(" ", ""), "solotravel", "travel"]

        if not research["dice_city_slug"]:
            research["dice_city_slug"] = city.replace(" ", "-")

        if not research["fetlife_location"]:
            country = context.get("country", "")
            research["fetlife_location"] = f"{city.title()}, {country}"

        if not research["ra_slug"]:
            research["ra_slug"] = city.replace(" ", "-")

        # Add vibe-specific search terms
        vibe_search_terms = self._generate_vibe_searches(city, date, vibes)
        research["vibe_search_terms"] = vibe_search_terms

        # Generate platform-specific search queries
        research["google_queries"] = self._build_google_queries(city, date, vibes)
        research["twitter_queries"] = self._build_twitter_queries(city, date)

        return AgentResult(
            agent=self.role,
            success=True,
            data=research,
            metadata={"city": city, "date": date, "vibes_requested": [v.value if hasattr(v, 'value') else v for v in vibes]},
        )

    def _generate_vibe_searches(self, city: str, date: str, vibes: list) -> dict[str, list[str]]:
        """Generate vibe-specific search terms."""
        vibe_terms = {
            "SOCIAL": ["meetup", "social gathering", "hangout", "game night", "trivia", "language exchange"],
            "DATING": ["speed dating", "singles mixer", "singles night", "dating event"],
            "KINKY": ["kink party", "munch", "play party", "fetish night", "bdsm", "shibari workshop"],
            "NIGHTLIFE": ["club night", "dj set", "techno party", "rave", "afterparty", "bar crawl"],
            "MUSIC": ["live music", "concert", "gig", "jazz night", "open mic"],
            "ART_CULTURE": ["exhibition opening", "gallery night", "theater", "film screening", "poetry"],
            "FOOD_DRINK": ["food market", "wine tasting", "supper club", "street food", "cocktail"],
            "WELLNESS": ["yoga", "meditation", "sound bath", "ecstatic dance", "breathwork"],
            "ADVENTURE": ["walking tour", "bike tour", "day trip", "hiking", "escape room"],
            "NETWORKING": ["startup meetup", "tech event", "hackathon", "networking"],
            "LGBTQ": ["pride", "queer party", "drag show", "lgbtq event"],
            "UNDERGROUND": ["underground party", "popup", "warehouse", "secret event"],
            "FESTIVAL": ["festival", "street party", "carnival", "market"],
            "SPORT_FITNESS": ["run club", "yoga class", "sports event", "fitness"],
        }
        result = {}
        for vibe_name, terms in vibe_terms.items():
            result[vibe_name] = [f"{city} {term}" for term in terms]
        return result

    def _build_google_queries(self, city: str, date: str, vibes: list) -> list[str]:
        """Build targeted Google search queries."""
        base_queries = [
            f"{city} events {date}",
            f"{city} things to do {date}",
            f"{city} nightlife {date}",
            f"{city} parties this week",
            f"what's on in {city} {date}",
            f"{city} event calendar",
            f"{city} club night {date}",
            f"{city} live events today",
        ]
        for vibe in vibes:
            vibe_name = vibe.value if hasattr(vibe, 'value') else vibe
            base_queries.append(f"{city} {vibe_name.lower().replace('_', ' ')} events {date}")
        return base_queries

    def _build_twitter_queries(self, city: str, date: str) -> list[str]:
        """Build targeted Twitter/X search queries."""
        return [
            f"{city} event tonight",
            f"{city} party tonight",
            f"#{city.replace(' ', '')}events",
            f"#{city.replace(' ', '')}nightlife",
            f"things to do {city}",
            f"{city} club tonight",
        ]
