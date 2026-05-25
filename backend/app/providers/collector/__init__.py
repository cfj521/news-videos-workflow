from app.providers.base import CollectorProvider

from .brave_search import BraveSearchCollector
from .google_news import GoogleNewsCollector
from .hackernews import HackerNewsCollector
from .rss import RSSCollector
from .tavily import TavilyCollector


def create_collector_registry(
    tavily_key: str = "",
    brave_key: str = "",
) -> dict[str, CollectorProvider]:
    return {
        "rss": RSSCollector(),
        "hackernews_algolia": HackerNewsCollector(),
        "tavily": TavilyCollector(api_key=tavily_key),
        "google_news_rss": GoogleNewsCollector(),
        "brave_search": BraveSearchCollector(api_key=brave_key),
    }
