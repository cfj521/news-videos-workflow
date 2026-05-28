import time

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.serper")

TBS_MAP = {"1d": "qdr:d", "3d": "qdr:d", "7d": "qdr:w", "15d": "qdr:m", "1m": "qdr:m"}


class SerperCollector(CollectorProvider):
    def __init__(self, api_key: str = ""):
        self._default_key = api_key

    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        api_key = source_config.get("api_key") or self._default_key
        if not api_key:
            log.warning("No API key for Serper, skipping")
            return []
        source_name = source_config.get("name", "Serper")
        query = source_config.get("default_query", "AI news")
        gl = source_config.get("gl", "us")
        hl = source_config.get("hl", "en")

        body = {
            "q": query,
            "gl": gl,
            "hl": hl,
            "num": min(max_items, 100),
            "tbs": TBS_MAP.get(time_range, "qdr:w"),
        }

        log.debug("Searching query=%s gl=%s tbs=%s", query, gl, body["tbs"])
        t0 = time.time()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://google.serper.dev/news",
                json=body,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()

        data = resp.json()
        articles: list[RawArticleData] = []
        for item in data.get("news", []):
            articles.append(RawArticleData(
                title=item.get("title", ""),
                content=item.get("snippet", ""),
                source_url=item.get("link", ""),
                source_name=item.get("source", source_name),
                category="general",
            ))

        log.info("Collected %d articles from Serper in %.1fs", len(articles), time.time() - t0)
        return articles
