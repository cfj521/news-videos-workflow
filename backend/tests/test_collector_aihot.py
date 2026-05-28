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
