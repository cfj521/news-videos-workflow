from datetime import datetime, timezone

import httpx

from app.providers.base import CollectorProvider, RawArticleData

TIME_RANGE_TO_TAVILY = {
    "1d": "day",
    "3d": "week",
    "7d": "week",
    "15d": "month",
    "1m": "month",
}


class TavilyCollector(CollectorProvider):
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def collect(
        self,
        source_config: dict,
        time_range: str,
        max_items: int = 30,
    ) -> list[RawArticleData]:
        source_name = source_config.get("name", "Tavily")
        query = source_config.get("default_query", "AI news")
        topic = source_config.get("topic", "news")
        search_depth = source_config.get("search_depth", "basic")

        body = {
            "query": query,
            "topic": topic,
            "search_depth": search_depth,
            "time_range": TIME_RANGE_TO_TAVILY.get(time_range, "week"),
            "max_results": min(max_items, 20),
            "include_raw_content": "markdown",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()

        data = resp.json()
        articles: list[RawArticleData] = []

        for result in data.get("results", []):
            content = result.get("raw_content") or result.get("content", "")
            published_at = None
            if result.get("published_date"):
                try:
                    published_at = datetime.strptime(result["published_date"], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            articles.append(
                RawArticleData(
                    title=result.get("title", ""),
                    content=content,
                    source_url=result.get("url", ""),
                    source_name=source_name,
                    published_at=published_at,
                    category="ai",
                )
            )

        return articles
