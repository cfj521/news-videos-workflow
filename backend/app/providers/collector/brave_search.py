import time

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.brave")

FRESHNESS_MAP = {"1d": "pd", "3d": "pd", "7d": "pw", "15d": "pm", "1m": "pm"}


class BraveSearchCollector(CollectorProvider):
    def __init__(self, api_key: str = ""):
        self._default_key = api_key

    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        api_key = source_config.get("api_key") or self._default_key
        if not api_key:
            log.warning("No API key for Brave Search, skipping")
            return []
        source_name = source_config.get("name", "Brave Search")
        query = source_config.get("default_query", "AI news")

        params: dict = {"q": query, "count": min(max_items, 20), "freshness": FRESHNESS_MAP.get(time_range, "pw")}
        if source_config.get("search_lang"):
            params["search_lang"] = source_config["search_lang"]

        log.debug("Searching query=%s freshness=%s", query, params["freshness"])
        t0 = time.time()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/news/search",
                params=params, headers={"X-Subscription-Token": api_key},
            )
            resp.raise_for_status()

        data = resp.json()
        articles: list[RawArticleData] = []
        for result in data.get("results", []):
            articles.append(RawArticleData(
                title=result.get("title", ""), content=result.get("description", ""),
                source_url=result.get("url", ""), source_name=source_name, category="ai",
            ))

        log.info("Collected %d articles from Brave in %.1fs", len(articles), time.time() - t0)
        return articles

    def _time_range_to_freshness(self, time_range: str) -> str:
        return FRESHNESS_MAP.get(time_range, "pw")
