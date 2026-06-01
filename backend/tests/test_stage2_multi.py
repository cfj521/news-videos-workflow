import json
from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage2_script import _batch_items, run_stage2_multi
from app.providers.base import RawArticleData


def test_batch_items():
    assert _batch_items(0) == []
    assert _batch_items(1) == [1]
    assert _batch_items(2) == [2]
    assert _batch_items(4) == [4]
    assert _batch_items(5) == [3, 2]
    assert _batch_items(7) == [3, 4]
    assert _batch_items(8) == [3, 3, 2]
    for n in range(2, 31):
        sizes = _batch_items(n)
        assert sum(sizes) == n
        assert all(2 <= s <= 4 for s in sizes)


def _scenes_json(*narrations):
    return json.dumps({"scenes": [{"narration": n, "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5} for n in narrations]})


@pytest.mark.asyncio
async def test_multi_normal_articles_group_per_article():
    tp = AsyncMock()
    tp.generate.side_effect = [
        _scenes_json("a1", "a2"),
        _scenes_json("b1"),
        json.dumps({"title": "汇总", "description": "d", "tags": ["t"]}),
    ]
    arts = [
        RawArticleData(title="文章1", content="c1", source_url="u1", source_name="s1"),
        RawArticleData(title="文章2", content="c2", source_url="u2", source_name="s2"),
    ]
    script = await run_stage2_multi(arts, tp)
    assert script["title"] == "汇总"
    assert [g["title"] for g in script["groups"]] == ["文章1", "文章2"]
    assert [g["source_index"] for g in script["groups"]] == [0, 1]
    assert [s["id"] for s in script["scenes"]] == [1, 2, 3]
    assert [s["group_id"] for s in script["scenes"]] == [1, 1, 2]


@pytest.mark.asyncio
async def test_multi_daily_groups_by_category():
    tp = AsyncMock()
    tp.generate.side_effect = [
        _scenes_json("m1", "m2", "m3"),
        _scenes_json("m4", "m5"),
        _scenes_json("i1", "i2"),
        json.dumps({"title": "日报汇总", "description": "d", "tags": []}),
    ]
    daily_sections = [
        {"label": "模型", "items": [{"title": f"模型{i}", "summary": "s"} for i in range(5)]},
        {"label": "行业", "items": [{"title": f"行业{i}", "summary": "s"} for i in range(2)]},
    ]
    art = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
                         metadata={"aihot_method": "daily", "daily_sections": daily_sections})
    script = await run_stage2_multi([art], tp)
    assert [g["title"] for g in script["groups"]] == ["模型 (1)", "模型 (2)", "行业"]
    assert all(g["source_index"] == 0 for g in script["groups"])
    assert len(script["scenes"]) == 7
    assert [s["id"] for s in script["scenes"]] == list(range(1, 8))


@pytest.mark.asyncio
async def test_multi_falls_back_on_bad_json():
    tp = AsyncMock()
    tp.generate.side_effect = [
        "这不是JSON",  # article scenes — malformed
        json.dumps({"title": "汇总", "description": "d", "tags": []}),  # summary
    ]
    arts = [RawArticleData(title="文章1", content="c1", source_url="u", source_name="s")]
    script = await run_stage2_multi(arts, tp)
    assert len(script["scenes"]) == 1
    assert script["scenes"][0]["narration"] == "文章1"  # fallback to title


from app.pipeline.stage2_script import distill_weekly_sections

_WEEKLY_ITEMS = [
    {"title": "GPT 新版", "summary": "s1", "category": "模型", "date": "2026-05-25"},
    {"title": "某产品发布", "summary": "s2", "category": "产品", "date": "2026-05-26"},
    {"title": "融资新闻", "summary": "s3", "category": "行业", "date": "2026-05-27"},
]


@pytest.mark.asyncio
async def test_distill_weekly_parses_sections():
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"sections": [
        {"label": "大模型进展", "items": [{"title": "GPT 新版", "summary": "s1"}]},
        {"label": "行业动态", "items": [{"title": "融资新闻", "summary": "s3"}]},
    ]})
    sections = await distill_weekly_sections(_WEEKLY_ITEMS, tp)
    assert [s["label"] for s in sections] == ["大模型进展", "行业动态"]
    assert sections[0]["items"][0]["title"] == "GPT 新版"


@pytest.mark.asyncio
async def test_distill_weekly_falls_back_on_bad_json():
    tp = AsyncMock()
    tp.generate.return_value = "这不是JSON"
    sections = await distill_weekly_sections(_WEEKLY_ITEMS, tp)
    # 兜底：按 category 分组，形状同 daily_sections
    assert {s["label"] for s in sections} == {"模型", "产品", "行业"}
    for s in sections:
        assert all("title" in it and "summary" in it for it in s["items"])


@pytest.mark.asyncio
async def test_multi_weekly_groups_like_daily():
    tp = AsyncMock()
    tp.generate.side_effect = [
        _scenes_json("w1"),                                  # 主题1 一条
        _scenes_json("w2", "w3"),                            # 主题2 两条
        json.dumps({"title": "周报汇总", "description": "d", "tags": []}),
    ]
    sections = [
        {"label": "大模型进展", "items": [{"title": "GPT", "summary": "s"}]},
        {"label": "行业动态", "items": [{"title": "融资", "summary": "s"}, {"title": "收购", "summary": "s"}]},
    ]
    art = RawArticleData(title="本周回顾", content="c", source_url="u", source_name="AI HOT 周报",
                         metadata={"aihot_method": "weekly", "daily_sections": sections})
    script = await run_stage2_multi([art], tp)
    assert [g["title"] for g in script["groups"]] == ["大模型进展", "行业动态"]
    assert all(g["source_index"] == 0 for g in script["groups"])
    assert len(script["scenes"]) == 3
    assert len(script["scenes"]) <= 10


from app import config
from app.pipeline.stage2_script import _gen_article_scenes


@pytest.mark.asyncio
async def test_gen_article_scenes_uses_prompt_override(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"roundup_article": "MY_OVERRIDE_PROMPT"}))
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"scenes": [{"narration": "x", "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5}]})
    art = RawArticleData(title="t", content="c", source_url="u", source_name="s")
    await _gen_article_scenes(art, tp)
    assert tp.generate.call_args.kwargs["system_prompt"] == "MY_OVERRIDE_PROMPT"
