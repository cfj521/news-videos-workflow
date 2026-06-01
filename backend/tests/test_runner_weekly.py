from unittest.mock import AsyncMock

import pytest

from app.pipeline.runner import _no_article_message, _distill_weekly_if_needed
from app.providers.base import RawArticleData


def test_no_article_message_weekly():
    assert "周报" in _no_article_message("weekly")


def test_no_article_message_daily():
    assert "日报" in _no_article_message("daily")


def test_no_article_message_default():
    assert _no_article_message(None) == "No articles collected"


@pytest.mark.asyncio
async def test_distill_weekly_writes_daily_sections(monkeypatch):
    art = RawArticleData(
        title="本周回顾", content="c", source_url="u", source_name="AI HOT 周报",
        metadata={"source_group": "aihot", "aihot_method": "weekly",
                  "weekly_items": [{"title": "t", "summary": "s", "category": "模型", "date": "2026-05-25"}]})

    async def _fake_distill(items, tp):
        return [{"label": "主题A", "items": [{"title": "t", "summary": "s"}]}]

    monkeypatch.setattr("app.pipeline.stage2_script.distill_weekly_sections", _fake_distill)
    monkeypatch.setattr("app.pipeline.runner._build_text_provider", lambda: AsyncMock())

    import logging
    await _distill_weekly_if_needed([art], logging.getLogger("test"))
    assert art.metadata["daily_sections"] == [{"label": "主题A", "items": [{"title": "t", "summary": "s"}]}]


@pytest.mark.asyncio
async def test_distill_weekly_noop_for_non_weekly(monkeypatch):
    art = RawArticleData(title="x", content="c", source_url="u", source_name="s",
                         metadata={"aihot_method": "daily"})
    import logging
    await _distill_weekly_if_needed([art], logging.getLogger("test"))
    assert "daily_sections" not in art.metadata
