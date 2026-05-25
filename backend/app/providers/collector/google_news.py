from calendar import timegm
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser
import httpx

from app.providers.base import CollectorProvider, RawArticleData

TIME_RANGE_MAP = {
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
    "15d": timedelta(days=15),
    "1m": timedelta(days=30),
}

WHEN_MAP = {"1d": "1d", "3d": "3d", "7d": "7d", "15d": "15d", "1m": "30d"}


class GoogleNewsCollector(CollectorProvider):
    BASE = "https://news.google.com/rss"

    async def collect(
        self,
        source_config: dict,
        time_range: str,
        max_items: int = 30,
    ) -> list[RawArticleData]:
        source_name = source_config.get("name", "Google News")
        hl = source_config.get("hl", "en-US")
        gl = source_config.get("gl", "US")
        ceid = source_config.get("ceid", "US:en")
        search_query = source_config.get("search_query", "")
        topic = source_config.get("topic", "")

        url = self._build_url(
            search_query=search_query,
            topic=topic,
            hl=hl,
            gl=gl,
            ceid=ceid,
            time_range=time_range,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - TIME_RANGE_MAP.get(time_range, timedelta(days=7))

        articles: list[RawArticleData] = []
        for entry in feed.entries[:max_items]:
            published = None
            if entry.get("published_parsed"):
                published = datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc)
            if published and published < cutoff:
                continue

            articles.append(
                RawArticleData(
                    title=entry.get("title", ""),
                    content=entry.get("summary", ""),
                    source_url=entry.get("link", ""),
                    source_name=source_name,
                    published_at=published,
                    category="general",
                )
            )

        return articles

    def _build_url(
        self,
        search_query: str = "",
        topic: str = "",
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
        time_range: str = "7d",
    ) -> str:
        params = f"hl={hl}&gl={gl}&ceid={ceid}"
        if search_query:
            when = WHEN_MAP.get(time_range, "7d")
            encoded_q = quote(f"{search_query} when:{when}")
            return f"{self.BASE}/search?q={encoded_q}&{params}"
        if topic:
            return f"{self.BASE}/headlines/section/topic/{topic}?{params}"
        return f"{self.BASE}?{params}"
