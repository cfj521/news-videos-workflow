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
    # 日报跳转 URL 指向当天日报前端页
    assert a.source_url == "https://aihot.virxact.com/daily/2026-05-28"
    assert a.aggregator_url == "https://aihot.virxact.com/daily/2026-05-28"


@pytest.mark.asyncio
async def test_aihot_daily_404_returns_empty():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_client(mock_cls, {}, status_code=404)
        articles = await collector.collect(source_config={"method": "daily"}, time_range="7d")
    assert articles == []


@pytest.mark.asyncio
async def test_aihot_daily_keeps_sections_in_metadata():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_client(mock_cls, DAILY_RESPONSE)
        articles = await collector.collect(source_config={"method": "daily"}, time_range="7d")
    secs = articles[0].metadata["daily_sections"]
    assert [s["label"] for s in secs] == ["模型发布/更新", "行业动态"]
    assert secs[0]["items"][0]["title"] == "模型A"


from datetime import date, timedelta


def _prev_week():
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7), this_monday - timedelta(days=1)


def _mock_router(mock_cls, routes):
    """routes: dict[url_suffix -> (json, status_code)]；未命中返回 404。"""
    async def _get(url, **kw):
        resp = MagicMock()
        for suffix, (j, sc) in routes.items():
            if url.endswith(suffix):
                resp.json.return_value = j
                resp.status_code = sc
                resp.raise_for_status = MagicMock(
                    side_effect=(None if sc < 400 else RuntimeError("http")))
                return resp
        resp.json.return_value = {}
        resp.status_code = 404
        resp.raise_for_status = MagicMock()
        return resp
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = AsyncMock(side_effect=_get)
    mock_cls.return_value = client
    return client


def _daily_for(d):
    return {"date": d, "lead": {"title": f"{d} 看点", "leadParagraph": f"{d} 导语"},
            "sections": [{"label": "模型", "items": [
                {"title": f"模型X-{d}", "summary": f"摘要-{d}"}]}],
            "flashes": [{"title": f"快讯-{d}", "sourceName": "S"}]}


@pytest.mark.asyncio
async def test_aihot_weekly_aggregates_prev_week():
    ws, we = _prev_week()
    in1, in2 = ws.isoformat(), (ws + timedelta(days=3)).isoformat()
    out = (we + timedelta(days=1)).isoformat()  # 本周一，超范围
    archive = {"items": [{"date": in1}, {"date": in2}, {"date": out}]}
    routes = {"/dailies": (archive, 200),
              f"/daily/{in1}": (_daily_for(in1), 200),
              f"/daily/{in2}": (_daily_for(in2), 200),
              f"/daily/{out}": (_daily_for(out), 200)}
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        client = _mock_router(mock_cls, routes)
        articles = await collector.collect(
            source_config={"method": "weekly", "name": "AI HOT", "week_start": ws.isoformat()}, time_range="7d")
    assert len(articles) == 1
    a = articles[0]
    assert a.metadata["aihot_method"] == "weekly"
    assert a.metadata["source_group"] == "aihot"
    assert a.metadata["week_start"] == ws.isoformat()
    assert a.metadata["week_end"] == we.isoformat()
    dates = {it["date"] for it in a.metadata["weekly_items"]}
    assert dates == {in1, in2}                       # 超范围日期未纳入
    titles = {it["title"] for it in a.metadata["weekly_items"]}
    assert f"模型X-{in1}" in titles and f"快讯-{in1}" in titles
    # 未对超范围日期发起 /daily 请求
    assert all(f"/daily/{out}" not in c.args[0] for c in client.get.call_args_list)


@pytest.mark.asyncio
async def test_aihot_weekly_skips_missing_day():
    ws, we = _prev_week()
    in1, in2 = ws.isoformat(), (ws + timedelta(days=2)).isoformat()
    archive = {"items": [{"date": in1}, {"date": in2}]}
    routes = {"/dailies": (archive, 200),
              f"/daily/{in1}": ({}, 404),            # 缺这天
              f"/daily/{in2}": (_daily_for(in2), 200)}
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_router(mock_cls, routes)
        articles = await collector.collect(source_config={"method": "weekly"}, time_range="7d")
    assert len(articles) == 1
    dates = {it["date"] for it in articles[0].metadata["weekly_items"]}
    assert dates == {in2}


@pytest.mark.asyncio
async def test_aihot_weekly_empty_when_no_dailies_in_range():
    ws, we = _prev_week()
    out = (we + timedelta(days=1)).isoformat()
    routes = {"/dailies": ({"items": [{"date": out}]}, 200)}
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_router(mock_cls, routes)
        articles = await collector.collect(source_config={"method": "weekly"}, time_range="7d")
    assert articles == []


@pytest.mark.asyncio
async def test_aihot_weekly_uses_configured_week_start():
    """source_config.week_start 指定的周应被采用，而非默认上周。"""
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    ws = this_monday - timedelta(days=14)  # 上上周
    d1 = ws.isoformat()
    routes = {"/dailies": ({"items": [{"date": d1}]}, 200), f"/daily/{d1}": (_daily_for(d1), 200)}
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_router(mock_cls, routes)
        articles = await collector.collect(
            source_config={"method": "weekly", "week_start": ws.isoformat()}, time_range="7d")
    assert len(articles) == 1
    assert articles[0].metadata["week_start"] == ws.isoformat()


@pytest.mark.asyncio
async def test_aihot_weekly_auto_picks_most_recent_complete_week():
    """自动（无 week_start）取上一个完整自然周；多周有数据时取最近的完整周（仍排除本周）。"""
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    prev = this_monday - timedelta(days=7)
    prev2 = this_monday - timedelta(days=14)
    archive = {"items": [{"date": prev2.isoformat()}, {"date": prev.isoformat()}]}
    routes = {"/dailies": (archive, 200),
              f"/daily/{prev.isoformat()}": (_daily_for(prev.isoformat()), 200),
              f"/daily/{prev2.isoformat()}": (_daily_for(prev2.isoformat()), 200)}
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_router(mock_cls, routes)
        articles = await collector.collect(source_config={"method": "weekly"}, time_range="7d")
    assert len(articles) == 1
    assert articles[0].metadata["week_start"] == prev.isoformat()  # 最近的完整周


@pytest.mark.asyncio
async def test_aihot_weekly_auto_excludes_current_week():
    """回归：本周已有日报时，自动仍取上一个完整自然周，绝不取未完成的本周。"""
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    prev = this_monday - timedelta(days=7)            # 上一个完整自然周（周一）
    in_current = this_monday                          # 本周一：本周已有数据
    archive = {"items": [{"date": prev.isoformat()}, {"date": in_current.isoformat()}]}
    routes = {"/dailies": (archive, 200),
              f"/daily/{prev.isoformat()}": (_daily_for(prev.isoformat()), 200),
              f"/daily/{in_current.isoformat()}": (_daily_for(in_current.isoformat()), 200)}
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_router(mock_cls, routes)
        articles = await collector.collect(source_config={"method": "weekly"}, time_range="7d")
    assert len(articles) == 1
    assert articles[0].metadata["week_start"] == prev.isoformat()              # 上一个完整周，非本周
    assert articles[0].metadata["week_end"] == (prev + timedelta(days=6)).isoformat()


@pytest.mark.asyncio
async def test_list_available_weeks_counts_days():
    from app.providers.collector.aihot import list_available_weeks
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    prev = this_monday - timedelta(days=7)
    prev2 = this_monday - timedelta(days=14)
    archive = {"items": [
        {"date": prev.isoformat()}, {"date": (prev + timedelta(days=1)).isoformat()},  # 上周 2 天
        {"date": prev2.isoformat()},                                                    # 上上周 1 天
    ]}
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_router(mock_cls, {"/dailies": (archive, 200)})
        weeks = await list_available_weeks()
    by_start = {w["week_start"]: w["days"] for w in weeks}
    assert by_start[prev.isoformat()] == 2
    assert by_start[prev2.isoformat()] == 1
