import time
from calendar import timegm
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.rss")

TIME_RANGE_MAP = {"1d": timedelta(days=1), "3d": timedelta(days=3), "7d": timedelta(days=7), "15d": timedelta(days=15), "1m": timedelta(days=30)}


class RSSCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        url = source_config["url"]
        source_name = source_config.get("name", url)
        log.debug("Fetching RSS %s", url)
        t0 = time.time()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - TIME_RANGE_MAP.get(time_range, timedelta(days=7))

        articles: list[RawArticleData] = []
        for entry in feed.entries[: max_items * 2]:
            published = self._parse_date(entry)
            if published and published < cutoff:
                continue

            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            if not content:
                content = getattr(entry, "summary", "")

            articles.append(RawArticleData(
                title=entry.get("title", ""), content=content,
                source_url=entry.get("link", ""), source_name=source_name,
                published_at=published, author=entry.get("author"),
                category=self._extract_category(entry),
            ))
            if len(articles) >= max_items:
                break

        log.info("Collected %d articles from RSS %s in %.1fs", len(articles), source_name, time.time() - t0)
        return articles

    def _parse_date(self, entry) -> datetime | None:
        parsed = entry.get("published_parsed")
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
        return None

    def _extract_category(self, entry) -> str:
        tags = entry.get("tags", [])
        if tags:
            return tags[0].get("term", "general").lower()
        return "general"
