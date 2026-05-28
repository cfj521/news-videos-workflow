import time as _time
from datetime import datetime, timedelta, timezone

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.aihot")

API = "https://aihot.virxact.com/api/public"

TIME_RANGE_HOURS = {"1d": 24, "3d": 72, "7d": 168, "15d": 360, "1m": 720}


class AIHotCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        source_name = source_config.get("name", "AI Hot")
        mode = source_config.get("mode", "selected")
        category = source_config.get("category", "")
        query = source_config.get("default_query", "")

        hours = TIME_RANGE_HOURS.get(time_range, 168)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params: dict = {"mode": mode, "since": since}
        if category:
            params["category"] = category
        if query:
            params["q"] = query

        log.debug("Fetching %s/items mode=%s since=%s", API, mode, since)
        t0 = _time.time()

        headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsVid/1.0)", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(f"{API}/items", params=params)
            resp.raise_for_status()

        data = resp.json()
        articles: list[RawArticleData] = []
        for item in data.get("items", [])[:max_items]:
            published_at = None
            if item.get("publishedAt"):
                try:
                    published_at = datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00"))
                except Exception:
                    pass

            articles.append(RawArticleData(
                title=item.get("title", ""),
                content=item.get("summary", ""),
                source_url=item.get("url", ""),
                source_name=item.get("source", source_name),
                published_at=published_at,
                category=item.get("category", "ai"),
                summary=item.get("summary", ""),
                aggregator_url=f"https://aihot.virxact.com",
            ))

        log.info("Collected %d articles from AI Hot in %.1fs", len(articles), _time.time() - t0)
        return articles
