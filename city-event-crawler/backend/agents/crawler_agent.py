"""Crawler Agent - orchestrates parallel crawling across all platforms."""

import asyncio
import logging
from typing import Any

from .base_agent import BaseAgent, AgentRole, AgentResult

logger = logging.getLogger(__name__)


class CrawlerAgent(BaseAgent):
    """Executes data fetching across all platforms in parallel.

    Takes the research context from the Researcher Agent and dispatches
    crawlers for each platform simultaneously. Manages concurrency limits,
    timeouts, and error isolation so one failing source doesn't block others.
    """

    role = AgentRole.CRAWLER
    name = "Crawler"

    def __init__(self, crawlers: dict | None = None):
        super().__init__()
        self._crawlers = crawlers or {}

    def set_crawlers(self, crawlers: dict):
        self._crawlers = crawlers

    async def execute(self, context: dict) -> AgentResult:
        city = context["city"]
        date = context["date"]
        lat = context["latitude"]
        lon = context["longitude"]
        radius_km = context.get("radius_km", 15)
        vibes = context.get("vibes")
        platforms = context.get("platforms")
        research = context.get("research", {})
        max_concurrent = context.get("max_concurrent", 10)

        # Filter crawlers to requested platforms
        active_crawlers = self._crawlers
        if platforms:
            platform_values = {p.value if hasattr(p, 'value') else p for p in platforms}
            active_crawlers = {
                source: crawler
                for source, crawler in self._crawlers.items()
                if source.value in platform_values or source in platform_values
            }

        if not active_crawlers:
            return AgentResult(
                agent=self.role,
                success=False,
                errors=["No crawlers available for requested platforms"],
            )

        logger.info(f"Dispatching {len(active_crawlers)} crawlers for {city}")

        # Run all crawlers concurrently with a semaphore
        semaphore = asyncio.Semaphore(max_concurrent)
        all_events = []
        errors = []
        sources_with_results = []

        async def run_crawler(source, crawler):
            async with semaphore:
                try:
                    # Inject research context into crawler if it supports it
                    crawler_context = {
                        "research": research,
                        "city": city,
                        "date": date,
                    }
                    if hasattr(crawler, 'set_research_context'):
                        crawler.set_research_context(crawler_context)

                    events = await asyncio.wait_for(
                        crawler.crawl(
                            city=city,
                            date=date,
                            latitude=lat,
                            longitude=lon,
                            radius_km=radius_km,
                            vibes=vibes,
                        ),
                        timeout=30,
                    )
                    logger.info(f"  [{source.value}] returned {len(events)} events")
                    return source, events, None
                except asyncio.TimeoutError:
                    err = f"{source.value}: timeout after 30s"
                    logger.warning(f"  [{source.value}] {err}")
                    return source, [], err
                except Exception as e:
                    err = f"{source.value}: {type(e).__name__}: {e}"
                    logger.warning(f"  [{source.value}] {err}")
                    return source, [], err

        tasks = [run_crawler(source, crawler) for source, crawler in active_crawlers.items()]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for source, events, error in results:
            if error:
                errors.append({"source": source.value if hasattr(source, 'value') else source, "error": error})
            if events:
                all_events.extend(events)
                sources_with_results.append(source)

        return AgentResult(
            agent=self.role,
            success=True,
            data={
                "events": all_events,
                "sources_searched": list(active_crawlers.keys()),
                "sources_with_results": sources_with_results,
            },
            errors=[e["error"] for e in errors],
            metadata={
                "total_raw_events": len(all_events),
                "crawlers_dispatched": len(active_crawlers),
                "crawlers_succeeded": len(sources_with_results),
                "crawlers_failed": len(errors),
                "error_details": errors,
            },
        )
