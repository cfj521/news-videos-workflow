from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.collector.brave_search import BraveSearchCollector

SAMPLE_BRAVE_RESPONSE = {
    "results": [
        {
            "title": "AI News Article",
            "url": "https://example.com/ai",
            "description": "Description of AI article",
            "age": "2 hours ago",
        },
    ],
}


@pytest.mark.asyncio
async def test_brave_collect():
    collector = BraveSearchCollector(api_key="BSA-test")
    with patch("app.providers.collector.brave_search.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_BRAVE_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        articles = await collector.collect(
            source_config={"name": "Brave", "default_query": "AI"},
            time_range="7d",
        )

    assert len(articles) == 1
    assert articles[0].title == "AI News Article"


def test_freshness_mapping():
    collector = BraveSearchCollector(api_key="test")
    assert collector._time_range_to_freshness("1d") == "pd"
    assert collector._time_range_to_freshness("7d") == "pw"
    assert collector._time_range_to_freshness("1m") == "pm"
