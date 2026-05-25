from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.collector.rss import RSSCollector

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Test Feed</title>
    <item>
        <title>AI Breakthrough</title>
        <link>https://example.com/article-1</link>
        <description>A major AI breakthrough was announced today.</description>
        <pubDate>Mon, 26 May 2026 08:00:00 +0000</pubDate>
        <category>AI</category>
    </item>
    <item>
        <title>Old Article</title>
        <link>https://example.com/article-old</link>
        <description>This is an old article.</description>
        <pubDate>Mon, 01 Jan 2024 08:00:00 +0000</pubDate>
    </item>
</channel>
</rss>"""


@pytest.mark.asyncio
async def test_rss_collect_parses_feed():
    collector = RSSCollector()
    with patch("app.providers.collector.rss.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS_XML
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        articles = await collector.collect(
            source_config={"url": "https://example.com/feed", "name": "Test"},
            time_range="7d",
            max_items=10,
        )

    assert len(articles) >= 1
    assert articles[0].title == "AI Breakthrough"
    assert articles[0].source_url == "https://example.com/article-1"


@pytest.mark.asyncio
async def test_rss_collect_filters_by_time():
    collector = RSSCollector()
    with patch("app.providers.collector.rss.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS_XML
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        articles = await collector.collect(
            source_config={"url": "https://example.com/feed", "name": "Test"},
            time_range="7d",
            max_items=10,
        )

    titles = [a.title for a in articles]
    assert "Old Article" not in titles
