from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.collector.tavily import TavilyCollector

SAMPLE_TAVILY_RESPONSE = {
    "results": [
        {
            "title": "Major AI Advancement",
            "url": "https://example.com/ai-news",
            "content": "A snippet of the article content...",
            "raw_content": "# Full Article\n\nThe full article content in markdown...",
            "score": 0.95,
            "published_date": "2026-05-26",
        },
        {
            "title": "LLM Update",
            "url": "https://example.com/llm",
            "content": "LLM news snippet",
            "raw_content": None,
            "score": 0.80,
            "published_date": "2026-05-25",
        },
    ],
    "response_time": 1.5,
}


@pytest.mark.asyncio
async def test_tavily_collect():
    collector = TavilyCollector(api_key="tvly-test")
    with patch("app.providers.collector.tavily.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_TAVILY_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        articles = await collector.collect(
            source_config={"name": "Tavily", "default_query": "AI breakthroughs", "topic": "news"},
            time_range="7d",
        )

    assert len(articles) == 2
    assert articles[0].title == "Major AI Advancement"
    assert "Full Article" in articles[0].content


@pytest.mark.asyncio
async def test_tavily_uses_raw_content_when_available():
    collector = TavilyCollector(api_key="tvly-test")
    with patch("app.providers.collector.tavily.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_TAVILY_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        articles = await collector.collect(
            source_config={"name": "Tavily", "default_query": "AI"},
            time_range="7d",
        )

    assert articles[0].content == "# Full Article\n\nThe full article content in markdown..."
    assert articles[1].content == "LLM news snippet"
