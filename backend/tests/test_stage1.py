from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage1_collect import run_stage1
from app.providers.base import RawArticleData


def _make_article(title: str, content: str = "content about AI") -> RawArticleData:
    return RawArticleData(
        title=title,
        content=content,
        source_url=f"https://example.com/{title}",
        source_name="Test",
    )


@pytest.mark.asyncio
async def test_stage1_collects_dedup_score_select():
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = [
        _make_article("AI Article 1", "content about AI and machine learning"),
        _make_article("AI Article 1"),
        _make_article("AI Article 2", "another AI article about deep learning"),
        _make_article("Unrelated Article", "cooking recipe"),
    ]

    result = await run_stage1(
        sources=[{"name": "Test", "type": "rss", "url": "https://example.com/feed"}],
        collectors={"rss": mock_collector},
        time_range="7d",
        max_articles=2,
    )

    assert len(result) <= 2
    titles = [a.title for a in result]
    assert "AI Article 1" in titles


@pytest.mark.asyncio
async def test_stage1_filters_blocked_content():
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = [
        _make_article("Normal AI Article", "safe content about AI"),
        _make_article("Bad Article", "这篇包含暴力内容"),
    ]

    result = await run_stage1(
        sources=[{"name": "T", "type": "rss", "url": "https://x.com/feed"}],
        collectors={"rss": mock_collector},
        time_range="7d",
        max_articles=5,
    )

    titles = [a.title for a in result]
    assert "Bad Article" not in titles
