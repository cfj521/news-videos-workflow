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


def _aihot_article(title: str, method: str = "items", content: str = "AI 资讯内容") -> RawArticleData:
    return RawArticleData(
        title=title, content=content,
        source_url=f"https://aihot.virxact.com/{title}", source_name="AI HOT",
        metadata={"source_group": "aihot", "aihot_method": method},
    )


@pytest.mark.asyncio
async def test_stage1_aihot_items_skips_dedup():
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = [
        _aihot_article("dup"), _aihot_article("dup"), _aihot_article("a2"),
    ]
    result = await run_stage1(
        sources=[{"name": "AI HOT", "type": "aihot", "url": "https://aihot.virxact.com/api/public"}],
        collectors={"aihot": mock_collector}, time_range="7d", max_articles=5,
    )
    # 跳过去重：重复标题保留
    assert len(result) == 3


@pytest.mark.asyncio
async def test_stage1_aihot_daily_single_passthrough():
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = [_aihot_article("日报", method="daily")]
    result = await run_stage1(
        sources=[{"name": "AI HOT", "type": "aihot", "url": "https://aihot.virxact.com/api/public"}],
        collectors={"aihot": mock_collector}, time_range="7d", max_articles=5,
    )
    assert len(result) == 1
    assert result[0].metadata["aihot_method"] == "daily"
