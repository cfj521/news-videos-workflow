from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.collector.aihot import AIHotCollector

ITEMS_RESPONSE = {
    "count": 2, "hasNext": False, "nextCursor": None,
    "items": [
        {"id": "a1", "title": "OpenAI 发布新模型", "title_en": "OpenAI ships",
         "url": "https://x.com/1", "source": "TechCrunch",
         "publishedAt": "2026-05-28T10:00:00.000Z", "summary": "摘要1", "category": "ai-models"},
        {"id": "a2", "title": "某公司融资", "title_en": "Co raises",
         "url": "https://x.com/2", "source": "RSS",
         "publishedAt": "2026-05-28T09:00:00.000Z", "summary": "摘要2", "category": "industry"},
    ],
}


def _mock_client(mock_cls, json_value, status_code=200):
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_value
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_cls.return_value = mock_client
    return mock_client


@pytest.mark.asyncio
async def test_aihot_items_returns_tagged_articles():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        client = _mock_client(mock_cls, ITEMS_RESPONSE)
        articles = await collector.collect(
            source_config={"method": "items", "category": "ai-models", "name": "AI HOT"},
            time_range="7d", max_items=30,
        )
    assert len(articles) == 2
    assert articles[0].title == "OpenAI 发布新模型"
    assert articles[0].metadata["source_group"] == "aihot"
    assert articles[0].metadata["aihot_method"] == "items"
    params = client.get.call_args[1]["params"]
    assert params["category"] == "ai-models"
    assert params["mode"] == "selected"


DAILY_RESPONSE = {
    "date": "2026-05-28", "generatedAt": "2026-05-28T12:00:00.000Z",
    "windowStart": "2026-05-27T12:00:00.000Z", "windowEnd": "2026-05-28T12:00:00.000Z",
    "lead": {"title": "今日 AI 看点", "leadParagraph": "今天有几条重磅消息。"},
    "sections": [
        {"label": "模型发布/更新", "items": [
            {"title": "模型A", "summary": "模型A摘要", "sourceUrl": "https://x.com/m1", "sourceName": "S1"}]},
        {"label": "行业动态", "items": [
            {"title": "行业B", "summary": "行业B摘要", "sourceUrl": "https://x.com/i1", "sourceName": "S2"}]},
    ],
    "flashes": [{"title": "快讯C", "sourceName": "S3", "sourceUrl": "https://x.com/f1",
                 "publishedAt": "2026-05-28T11:00:00.000Z"}],
}


@pytest.mark.asyncio
async def test_aihot_daily_renders_single_article():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_client(mock_cls, DAILY_RESPONSE)
        articles = await collector.collect(
            source_config={"method": "daily", "name": "AI HOT"}, time_range="7d",
        )
    assert len(articles) == 1
    a = articles[0]
    assert a.title == "今日 AI 看点"
    assert a.metadata["source_group"] == "aihot"
    assert a.metadata["aihot_method"] == "daily"
    assert a.metadata["report_date"] == "2026-05-28"
    assert "模型A摘要" in a.content
    assert "行业B摘要" in a.content
    assert "快讯C" in a.content


@pytest.mark.asyncio
async def test_aihot_daily_404_returns_empty():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_client(mock_cls, {}, status_code=404)
        articles = await collector.collect(source_config={"method": "daily"}, time_range="7d")
    assert articles == []
