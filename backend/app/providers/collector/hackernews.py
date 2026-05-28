import time as _time
from datetime import datetime

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.hackernews")

TIME_RANGE_SECONDS = {"1d": 86400, "3d": 86400 * 3, "7d": 86400 * 7, "15d": 86400 * 15, "1m": 86400 * 30}


class HackerNewsCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        base_url = source_config.get("url", "https://hn.algolia.com/api/v1/")
        source_name = source_config.get("name", "Hacker News")
        query = source_config.get("default_query", "")
        tags = source_config.get("tags", "story")
        min_points = source_config.get("min_points", 0)

        seconds = TIME_RANGE_SECONDS.get(time_range, 86400 * 7)
        cutoff_ts = int(_time.time()) - seconds
        filters = f"created_at_i>{cutoff_ts}"
        if min_points > 0:
            filters += f",points>{min_points}"

        params = {"query": query, "tags": tags, "numericFilters": filters, "hitsPerPage": max_items}
        log.debug("Fetching %s query=%s tags=%s range=%s", base_url, query, tags, time_range)
        t0 = _time.time()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{base_url}search_by_date", params=params)
            resp.raise_for_status()

        data = resp.json()
        articles: list[RawArticleData] = []
        for hit in data.get("hits", []):
            original_url = hit.get("url") or ""
            hn_url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            content = hit.get("story_text") or ""
            published_at = None
            if hit.get("created_at"):
                published_at = datetime.fromisoformat(hit["created_at"].replace("Z", "+00:00"))
            articles.append(RawArticleData(
                title=hit.get("title", ""), content=content,
                source_url=original_url or hn_url,
                source_name=source_name, published_at=published_at, author=hit.get("author"), category="tech",
                aggregator_url=hn_url,
                metadata={"points": hit.get("points", 0), "num_comments": hit.get("num_comments", 0)},
            ))

        log.info("Collected %d articles from %s in %.1fs", len(articles), source_name, _time.time() - t0)
        return articles
