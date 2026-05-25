from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.collector.hackernews import HackerNewsCollector

SAMPLE_ALGOLIA_RESPONSE = {
    "hits": [
        {
            "objectID": "12345",
            "title": "Show HN: A new AI tool",
            "url": "https://example.com/ai-tool",
            "author": "testuser",
            "points": 150,
            "num_comments": 42,
            "created_at": "2026-05-26T08:00:00.000Z",
            "created_at_i": 1779926400,
            "story_text": None,
            "_tags": ["story", "front_page"],
        },
        {
            "objectID": "12346",
            "title": "Ask HN: Best LLM framework?",
            "url": None,
            "author": "another",
            "points": 80,
            "num_comments": 55,
            "created_at": "2026-05-25T10:00:00.000Z",
            "created_at_i": 1779847200,
            "story_text": "What are the best frameworks for building with LLMs?",
            "_tags": ["story", "ask_hn"],
        },
    ],
    "nbHits": 2,
    "page": 0,
    "nbPages": 1,
    "hitsPerPage": 20,
}


@pytest.mark.asyncio
async def test_hn_collect_returns_articles():
    collector = HackerNewsCollector()
    with patch("app.providers.collector.hackernews.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_ALGOLIA_RESPONSE
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        articles = await collector.collect(
            source_config={
                "url": "https://hn.algolia.com/api/v1/",
                "name": "Hacker News",
                "default_query": "AI",
                "tags": "story",
                "min_points": 10,
            },
            time_range="7d",
        )

    assert len(articles) == 2
    assert articles[0].title == "Show HN: A new AI tool"
    assert articles[0].source_url == "https://example.com/ai-tool"
    assert articles[1].content == "What are the best frameworks for building with LLMs?"


@pytest.mark.asyncio
async def test_hn_collect_builds_correct_url():
    collector = HackerNewsCollector()
    with patch("app.providers.collector.hackernews.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "nbHits": 0}
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        await collector.collect(
            source_config={
                "url": "https://hn.algolia.com/api/v1/",
                "name": "HN",
                "default_query": "LLM",
                "tags": "story",
            },
            time_range="3d",
        )

        call_args = mock_client.get.call_args
        url = call_args[0][0]
        assert "search_by_date" in url
        params = call_args[1].get("params", {})
        assert params["query"] == "LLM"
        assert params["tags"] == "story"
        assert "created_at_i>" in params["numericFilters"]
