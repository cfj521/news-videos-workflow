import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from app.providers.base import RawArticleData
from app.services.scoring import ScoringService


def _art(title="t", content="c", url="", source="", published_at=None):
    return RawArticleData(title=title, content=content, source_url=url,
                          source_name=source, published_at=published_at)


def test_source_score_tiers():
    s = ScoringService()
    assert s._source_score(_art(url="https://www.anthropic.com/news/x")) == 1.0
    assert s._source_score(_art(source="Hacker News")) == 0.88
    assert s._source_score(_art(source="TechCrunch")) == 0.7
    assert s._source_score(_art(source="Tavily")) == 0.5
    assert s._source_score(_art(source="某不知名站")) == 0.5


def test_recency_score_piecewise():
    s = ScoringService()
    now = datetime.now(timezone.utc)
    assert s._recency_score(now) == 1.0
    assert abs(s._recency_score(now - timedelta(days=7)) - 0.9) < 1e-6
    assert abs(s._recency_score(now - timedelta(days=30)) - 0.3) < 1e-6
    assert s._recency_score(now - timedelta(days=60)) == 0.3
    assert s._recency_score(None) == 0.3
    assert s._recency_score(now - timedelta(days=3)) > s._recency_score(now - timedelta(days=15))


def test_keyword_score_language_lens():
    s = ScoringService()
    zh = s._keyword_score("DeepSeek 发布新模型", "国产大模型突破", "zh")
    en = s._keyword_score("DeepSeek 发布新模型", "国产大模型突破", "en")
    assert zh > en
    assert s._keyword_score("crypto casino 招聘", "赌博", "zh") >= 0.0
    assert s._keyword_score("OpenAI agent", "", "en") > 0.4


def test_rule_score_normalized():
    s = ScoringService()
    r = s._rule_score(_art(source="Hacker News", title="OpenAI agent",
                           published_at=datetime.now(timezone.utc)), "en")
    assert 0.0 <= r <= 1.0


@pytest.mark.asyncio
async def test_llm_score_parses_and_passes_language(monkeypatch):
    import app.services.scoring as scoring
    from app import config
    # 强制走内置默认 prompt（绕过本地 config.yaml 可能的覆盖值）
    monkeypatch.setattr(config, "_settings", config.Settings())
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 8, "reason": "重要", "tags": ["模型"]}'
    s = ScoringService()
    out = await s._llm_score(_art(title="GPT-5", content="发布"), tp, "zh")
    assert out["score"] == 8 and out["tags"] == ["模型"]
    assert "中国" in tp.generate.call_args.kwargs["system_prompt"]  # zh rubric


@pytest.mark.asyncio
async def test_llm_score_cache_hits():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 5, "reason": "", "tags": []}'
    s = ScoringService()
    a = _art(title="same", content="same")
    await s._llm_score(a, tp, "zh")
    await s._llm_score(a, tp, "zh")
    assert tp.generate.call_count == 1


@pytest.mark.asyncio
async def test_llm_score_bad_json_fallback():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = "评分：7 分，不错"
    s = ScoringService()
    out = await s._llm_score(_art(), tp, "zh")
    assert out["score"] == 7


# ── S6: select_top 编排测试 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_select_top_small_pool_all_llm():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 7, "reason": "r", "tags": []}'
    arts = [_art(title=f"t{i}", content="OpenAI agent", source="Hacker News") for i in range(6)]
    s = ScoringService()
    res = await s.select_top(arts, tp, "en", n=3)
    assert len(res.selected) == 3
    assert tp.generate.call_count == 6
    assert len(res.report["candidates"]) == 6
    assert sum(c["selected"] for c in res.report["candidates"]) == 3
    assert res.report["candidates"][0]["final"] >= res.report["candidates"][-1]["final"]


@pytest.mark.asyncio
async def test_select_top_large_pool_preshortlist():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 6, "reason": "", "tags": []}'
    arts = [_art(title=f"t{i}", content="x", source="Tavily") for i in range(12)]
    s = ScoringService()
    s.cfg.llm_candidate_cap = 5     # 2K=10；12>10 触发预筛
    res = await s.select_top(arts, tp, "en", n=3)
    assert tp.generate.call_count == 5
    assert len(res.report["candidates"]) == 12
    assert any(not c["llm_ran"] for c in res.report["candidates"])


@pytest.mark.asyncio
async def test_select_top_min_score_floor():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 0, "reason": "", "tags": []}'
    s = ScoringService()
    s.cfg.min_score = 0.9
    res = await s.select_top([_art(source="Tavily") for _ in range(4)], tp, "en", n=3)
    assert len(res.selected) == 1


@pytest.mark.asyncio
async def test_select_top_rule_only_when_no_provider():
    s = ScoringService()
    s.cfg.min_score = 0.0   # 不受其他测试 min_score 修改影响
    res = await s.select_top([_art(title="OpenAI", source="Hacker News") for _ in range(3)], None, "en", n=2)
    assert len(res.selected) == 2
    assert all(not c["llm_ran"] for c in res.report["candidates"])


@pytest.mark.asyncio
async def test_select_top_llm_all_fail_degrades():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.side_effect = Exception("provider down")
    s = ScoringService()
    s.cfg.min_score = 0.0   # LLM 全失败 → 退回规则分，不受地板影响
    res = await s.select_top([_art(source="Hacker News") for _ in range(3)], tp, "en", n=2)
    assert len(res.selected) == 2
