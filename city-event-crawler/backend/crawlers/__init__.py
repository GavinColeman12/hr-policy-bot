"""Platform crawlers for the City Event Crawler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import EventSource

if TYPE_CHECKING:
    from .base import BaseCrawler


def get_all_crawlers() -> dict[EventSource, "BaseCrawler"]:
    """Instantiate and return one crawler per supported platform."""
    from .blog_scraper import BlogScraperCrawler
    from .dice import DiceCrawler
    from .eventbrite import EventbriteCrawler
    from .facebook import FacebookCrawler
    from .fetlife import FetLifeCrawler
    from .google_events import GoogleEventsCrawler
    from .instagram import InstagramCrawler
    from .meetup import MeetupCrawler
    from .reddit import RedditCrawler
    from .resident_advisor import ResidentAdvisorCrawler
    from .ticketmaster import TicketmasterCrawler
    from .twitter import TwitterCrawler
    return {
        EventSource.GOOGLE: GoogleEventsCrawler(),
        EventSource.EVENTBRITE: EventbriteCrawler(),
        EventSource.MEETUP: MeetupCrawler(),
        EventSource.INSTAGRAM: InstagramCrawler(),
        EventSource.REDDIT: RedditCrawler(),
        EventSource.TWITTER: TwitterCrawler(),
        EventSource.FACEBOOK: FacebookCrawler(),
        EventSource.RESIDENT_ADVISOR: ResidentAdvisorCrawler(),
        EventSource.FETLIFE: FetLifeCrawler(),
        EventSource.TICKETMASTER: TicketmasterCrawler(),
        EventSource.DICE: DiceCrawler(),
        EventSource.BLOG: BlogScraperCrawler(),
    }


__all__ = ["get_all_crawlers"]
