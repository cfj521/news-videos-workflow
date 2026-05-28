import time as _time
from datetime import datetime, timedelta, timezone

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.aihot")

API = "https://aihot.virxact.com/api/public"

TIME_RANGE_HOURS = {"1d": 24, "3d": 72, "7d": 168, "15d": 360, "1m": 720}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsVid/1.0)", "Accept": "application/json"}


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


class AIHotCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        method = source_config.get("method", "items")
        if method == "daily":
            return await self._collect_daily(source_config)
        return await self._collect_items(source_config, time_range, max_items)

    async def _collect_items(self, source_config: dict, time_range: str, max_items: int) -> list[RawArticleData]:
        source_name = source_config.get("name", "AI Hot")
        category = source_config.get("category", "")
        hours = TIME_RANGE_HOURS.get(time_range, 168)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params: dict = {"mode": "selected", "since": since, "take": max_items}
        if category:
            params["category"] = category

        t0 = _time.time()
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/items", params=params)
            resp.raise_for_status()
        data = resp.json()

        articles: list[RawArticleData] = []
        for item in data.get("items", [])[:max_items]:
            articles.append(RawArticleData(
                title=item.get("title", ""),
                content=item.get("summary", ""),
                source_url=item.get("url", ""),
                source_name=item.get("source", source_name),
                published_at=_parse_dt(item.get("publishedAt")),
                category=item.get("category", "ai"),
                summary=item.get("summary", ""),
                aggregator_url="https://aihot.virxact.com",
                metadata={"source_group": "aihot", "aihot_method": "items"},
            ))
        log.info("Collected %d items from AI Hot in %.1fs", len(articles), _time.time() - t0)
        return articles

    async def _collect_daily(self, source_config: dict) -> list[RawArticleData]:
        # 在 Task 2 实现
        raise NotImplementedError
