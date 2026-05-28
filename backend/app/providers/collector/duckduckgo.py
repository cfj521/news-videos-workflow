import time

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.duckduckgo")

TIMELIMIT_MAP = {"1d": "d", "3d": "w", "7d": "w", "15d": "m", "1m": "m"}


class DuckDuckGoCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        source_name = source_config.get("name", "DuckDuckGo")
        query = source_config.get("default_query", "AI news")
        region = source_config.get("region", "wt-wt")

        log.debug("Searching query=%s region=%s timelimit=%s", query, region, TIMELIMIT_MAP.get(time_range, "w"))
        t0 = time.time()

        try:
            from duckduckgo_search import DDGS
        except ImportError:
            log.error("duckduckgo-search not installed: pip install duckduckgo-search")
            return []

        articles: list[RawArticleData] = []
        try:
            with DDGS() as ddgs:
                results = ddgs.news(
                    keywords=query,
                    region=region,
                    safesearch="moderate",
                    timelimit=TIMELIMIT_MAP.get(time_range, "w"),
                    max_results=min(max_items, 30),
                )
                for r in results:
                    articles.append(RawArticleData(
                        title=r.get("title", ""),
                        content=r.get("body", ""),
                        source_url=r.get("url", ""),
                        source_name=r.get("source", source_name),
                        category="general",
                    ))
        except Exception:
            log.exception("DuckDuckGo search failed")

        log.info("Collected %d articles from DuckDuckGo in %.1fs", len(articles), time.time() - t0)
        return articles
