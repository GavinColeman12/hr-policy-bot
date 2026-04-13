"""Agent Orchestrator - coordinates the multi-agent pipeline for event discovery.

Pipeline:
  1. Researcher Agent  -> Discovers city-specific sources, hashtags, venues
  2. Crawler Agent     -> Fetches events from all platforms in parallel
  3. Classifier Agent  -> Categorizes events by vibe
  4. Quality Agent     -> Deduplicates, validates, enriches
  5. Ranker Agent      -> Ranks by popularity/engagement
"""

import asyncio
import logging
import time
from typing import Any

from .base_agent import AgentResult
from .researcher import ResearcherAgent
from .crawler_agent import CrawlerAgent
from .classifier_agent import ClassifierAgent
from .quality_agent import QualityAgent
from .ranker_agent import RankerAgent

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Coordinates the multi-agent event discovery pipeline.

    Usage:
        orchestrator = AgentOrchestrator(crawlers=get_all_crawlers())
        result = await orchestrator.run(
            city="Budapest", date="2026-04-13",
            latitude=47.4979, longitude=19.0402,
            radius_km=15, vibes=None
        )
        events = result["events"]
    """

    def __init__(self, crawlers: dict | None = None):
        self.researcher = ResearcherAgent()
        self.crawler = CrawlerAgent(crawlers)
        self.classifier = ClassifierAgent()
        self.quality = QualityAgent()
        self.ranker = RankerAgent()

    async def run(
        self,
        city: str,
        date: str,
        latitude: float,
        longitude: float,
        radius_km: float = 15,
        vibes: list | None = None,
        platforms: list | None = None,
        sort_by: str = "engagement",
        max_concurrent: int = 10,
    ) -> dict[str, Any]:
        """Run the full multi-agent pipeline and return aggregated results."""
        t0 = time.time()
        pipeline_meta = {"agents": {}, "errors": []}

        # --- Stage 1: Research ---
        logger.info("=== Stage 1: Research ===")
        research_result = await self.researcher.safe_execute({
            "city": city, "date": date, "vibes": vibes or [],
        })
        pipeline_meta["agents"]["researcher"] = {
            "success": research_result.success,
            "duration": research_result.duration_seconds,
        }
        research_data = research_result.data or {}

        # --- Stage 2: Crawl ---
        logger.info("=== Stage 2: Crawl ===")
        crawl_result = await self.crawler.safe_execute({
            "city": city, "date": date,
            "latitude": latitude, "longitude": longitude,
            "radius_km": radius_km, "vibes": vibes,
            "platforms": platforms, "research": research_data,
            "max_concurrent": max_concurrent,
        })
        pipeline_meta["agents"]["crawler"] = {
            "success": crawl_result.success,
            "duration": crawl_result.duration_seconds,
            "metadata": crawl_result.metadata,
        }
        if crawl_result.errors:
            pipeline_meta["errors"].extend(crawl_result.errors)

        crawl_data = crawl_result.data or {}
        raw_events = crawl_data.get("events", [])
        sources_searched = crawl_data.get("sources_searched", [])
        sources_with_results = crawl_data.get("sources_with_results", [])

        if not raw_events:
            logger.info("No events found from any crawler")
            return {
                "events": [],
                "total_count": 0,
                "sources_searched": sources_searched,
                "sources_with_results": sources_with_results,
                "errors": pipeline_meta["errors"],
                "pipeline_meta": pipeline_meta,
                "duration_seconds": round(time.time() - t0, 3),
            }

        # --- Stage 3: Classify ---
        logger.info("=== Stage 3: Classify ===")
        classify_result = await self.classifier.safe_execute({"events": raw_events})
        pipeline_meta["agents"]["classifier"] = {
            "success": classify_result.success,
            "duration": classify_result.duration_seconds,
            "metadata": classify_result.metadata,
        }
        classified_events = classify_result.data if classify_result.success else raw_events

        # --- Stage 4: Quality ---
        logger.info("=== Stage 4: Quality ===")
        quality_result = await self.quality.safe_execute({"events": classified_events})
        pipeline_meta["agents"]["quality"] = {
            "success": quality_result.success,
            "duration": quality_result.duration_seconds,
            "metadata": quality_result.metadata,
        }
        quality_events = quality_result.data if quality_result.success else classified_events

        # --- Stage 5: Rank ---
        logger.info("=== Stage 5: Rank ===")
        rank_result = await self.ranker.safe_execute({
            "events": quality_events,
            "vibes": vibes, "sort_by": sort_by,
            "latitude": latitude, "longitude": longitude,
        })
        pipeline_meta["agents"]["ranker"] = {
            "success": rank_result.success,
            "duration": rank_result.duration_seconds,
            "metadata": rank_result.metadata,
        }
        final_events = rank_result.data if rank_result.success else quality_events

        total_duration = round(time.time() - t0, 3)
        logger.info(
            "Pipeline complete: %d events in %.3fs (research=%.1fs, crawl=%.1fs, classify=%.1fs, quality=%.1fs, rank=%.1fs)",
            len(final_events), total_duration,
            research_result.duration_seconds, crawl_result.duration_seconds,
            classify_result.duration_seconds, quality_result.duration_seconds,
            rank_result.duration_seconds,
        )

        return {
            "events": final_events,
            "total_count": len(final_events),
            "sources_searched": sources_searched,
            "sources_with_results": sources_with_results,
            "errors": pipeline_meta["errors"],
            "pipeline_meta": pipeline_meta,
            "duration_seconds": total_duration,
        }
