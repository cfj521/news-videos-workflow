import json
from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage2_script import replan_scenes_to_limit, run_stage2_multi
from app.providers.base import RawArticleData


def _mk_script(n: int) -> dict:
    scenes = [{"id": i, "group_id": i, "group_title": f"g{i}", "narration": f"n{i}",
               "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5} for i in range(1, n + 1)]
    return {"title": "t", "description": "d", "tags": [], "groups": [], "scenes": scenes}


@pytest.mark.asyncio
async def test_replan_noop_when_within_limit():
    tp = AsyncMock()
    script = _mk_script(3)
    out = await replan_scenes_to_limit(script, limit=5, text_provider=tp)
    assert out is script  # 未超限：原样返回，不调用 AI
    tp.generate.assert_not_called()


@pytest.mark.asyncio
async def test_replan_merges_over_limit():
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"scenes": [
        {"narration": "合并A", "image_prompt": "p1", "motion_prompt": "m", "duration_hint": 5, "group_title": "甲"},
        {"narration": "合并B", "image_prompt": "p2", "motion_prompt": "m", "duration_hint": 5, "group_title": "乙"},
    ]})
    out = await replan_scenes_to_limit(_mk_script(6), limit=2, text_provider=tp)
    assert len(out["scenes"]) == 2
    assert [s["id"] for s in out["scenes"]] == [1, 2]  # id 重建连续
    assert out["scenes"][0]["group_id"] == 1 and out["scenes"][0]["group_title"] == "甲"
    assert len(out["groups"]) == 2


@pytest.mark.asyncio
async def test_replan_truncates_if_ai_returns_too_many():
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"scenes": [
        {"narration": f"m{i}", "image_prompt": "p", "motion_prompt": "", "duration_hint": 5} for i in range(5)
    ]})
    out = await replan_scenes_to_limit(_mk_script(10), limit=3, text_provider=tp)
    assert len(out["scenes"]) == 3  # 严格不超过上限


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
    assert all(s["title"] == s["group_title"] for s in script["scenes"])


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


from app import config
from app.pipeline.stage2_script import _gen_article_scenes


@pytest.mark.asyncio
async def test_gen_article_scenes_uses_prompt_override(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"roundup_article": "MY_OVERRIDE_PROMPT"}))
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"scenes": [{"narration": "x", "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5}]})
    art = RawArticleData(title="t", content="c", source_url="u", source_name="s")
    await _gen_article_scenes(art, tp)
    # system_prompt = 覆盖的提示词 + 语言/画面风格指令
    assert tp.generate.call_args.kwargs["system_prompt"].startswith("MY_OVERRIDE_PROMPT")


@pytest.mark.asyncio
async def test_gen_article_scenes_english_directive(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"roundup_article": "BASE"}))
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"scenes": [{"narration": "x", "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5}]})
    art = RawArticleData(title="t", content="c", source_url="u", source_name="s")
    await _gen_article_scenes(art, tp, language="en")
    sp = tp.generate.call_args.kwargs["system_prompt"]
    assert "English" in sp and "Western" in sp  # 英文模式注入英文 + 西方场景指令


from unittest.mock import patch


def _aihot_daily_article():
    daily_sections = [
        {"label": "模型", "items": [{"title": f"模型{i}", "summary": f"摘要{i}"} for i in range(5)]},
        {"label": "行业", "items": [{"title": f"行业{i}", "summary": f"摘要{i}"} for i in range(2)]},
    ]
    return RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
                          metadata={"source_group": "aihot", "aihot_method": "daily",
                                    "daily_sections": daily_sections})


@pytest.mark.asyncio
async def test_aihot_daily_direct_use(monkeypatch):
    # aihot_top_n=3 → 7 条 item 选 3 条，1 item→1 scene；narration=summary 原样，不调 AI 生成旁白
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=3)))
    tp = AsyncMock()
    # 出图 prompt（每条1次）+ summary_meta（1次）会调 AI；旁白不调
    tp.generate.side_effect = ["画面A", "画面B", "画面C",
                               json.dumps({"title": "日报汇总", "description": "d", "tags": []})]
    script = await run_stage2_multi([_aihot_daily_article()], tp)

    assert len(script["scenes"]) == 3
    assert [s["id"] for s in script["scenes"]] == [1, 2, 3]
    assert [s["group_id"] for s in script["scenes"]] == [1, 2, 3]   # 每条 item 自成一组
    for s in script["scenes"]:
        assert s["title"] == s["group_title"]                       # 烧录文字 = item.title
        assert s["narration"].startswith("摘要")                    # 旁白 = summary 原样
        assert s["title"].startswith(("模型", "行业"))
    assert tp.generate.call_count == 4                              # 3 出图 prompt + 1 meta，无旁白生成


@pytest.mark.asyncio
async def test_aihot_items_direct_use(monkeypatch):
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=10)))
    tp = AsyncMock()
    tp.generate.side_effect = ["画面1", "画面2",
                               json.dumps({"title": "动态", "description": "d", "tags": []})]
    arts = [RawArticleData(title=f"动态{i}", content=f"内容{i}", summary=f"摘要{i}",
                           source_url="u", source_name="AI HOT",
                           metadata={"source_group": "aihot", "aihot_method": "items"}) for i in range(2)]
    script = await run_stage2_multi(arts, tp)
    assert len(script["scenes"]) == 2
    assert {s["title"] for s in script["scenes"]} == {"动态0", "动态1"}
    assert all(s["narration"].startswith("摘要") for s in script["scenes"])


@pytest.mark.asyncio
async def test_aihot_image_prompt_fallback_to_title(monkeypatch):
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=1)))
    tp = AsyncMock()
    tp.generate.side_effect = [Exception("出图prompt失败"),
                               json.dumps({"title": "t", "description": "d", "tags": []})]
    script = await run_stage2_multi([_aihot_daily_article()], tp)
    assert script["scenes"][0]["image_prompt"] == script["scenes"][0]["title"]  # 退化为 title
