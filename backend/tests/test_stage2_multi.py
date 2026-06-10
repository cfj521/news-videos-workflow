import json
from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage2_script import run_stage2_multi
from app.providers.base import RawArticleData


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


def _aihot_daily_article():
    daily_sections = [
        {"label": "模型", "items": [{"title": f"模型{i}", "summary": f"摘要{i}"} for i in range(5)]},
        {"label": "行业", "items": [{"title": f"行业{i}", "summary": f"摘要{i}"} for i in range(2)]},
    ]
    return RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
                          metadata={"source_group": "aihot", "aihot_method": "daily",
                                    "daily_sections": daily_sections})


@pytest.mark.asyncio
async def test_aihot_daily_direct_use():
    # max_articles=3 → 7 条 item 选 3 条，1 item→1 scene；narration=summary 原样，不调 AI 生成旁白
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    # 新调用顺序：先 7 条 LLM 评分 JSON（并发，每候选1次）→ 再 3 条出图 prompt → 再 1 条 meta
    llm_scores = [json.dumps({"score": s, "reason": "r", "tags": []}) for s in [9, 8, 7, 6, 5, 4, 3]]
    tp.generate.side_effect = llm_scores + ["画面A", "画面B", "画面C",
                               json.dumps({"title": "日报汇总", "description": "d", "tags": []})]
    script = await run_stage2_multi([_aihot_daily_article()], tp, max_articles=3)

    assert len(script["scenes"]) == 3
    assert [s["id"] for s in script["scenes"]] == [1, 2, 3]
    assert [s["group_id"] for s in script["scenes"]] == [1, 2, 3]   # 每条 item 自成一组
    for s in script["scenes"]:
        assert s["title"] == s["group_title"]                       # 烧录文字 = item.title
        assert s["narration"].startswith("摘要")                    # 旁白 = summary 原样
        assert s["title"].startswith(("模型", "行业"))
    assert tp.generate.call_count == 11                             # 7 LLM 评分 + 3 出图 prompt + 1 meta，无旁白生成


@pytest.mark.asyncio
async def test_aihot_items_direct_use():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    # 新调用顺序：先 2 条 LLM 评分 JSON → 再 2 条出图 prompt → 再 1 条 meta
    llm_scores = [json.dumps({"score": s, "reason": "r", "tags": []}) for s in [8, 7]]
    tp.generate.side_effect = llm_scores + ["画面1", "画面2",
                               json.dumps({"title": "动态", "description": "d", "tags": []})]
    arts = [RawArticleData(title=f"动态{i}", content=f"内容{i}", summary=f"摘要{i}",
                           source_url="u", source_name="AI HOT",
                           metadata={"source_group": "aihot", "aihot_method": "items"}) for i in range(2)]
    script = await run_stage2_multi(arts, tp, max_articles=10)
    assert len(script["scenes"]) == 2
    assert {s["title"] for s in script["scenes"]} == {"动态0", "动态1"}
    assert all(s["narration"].startswith("摘要") for s in script["scenes"])


@pytest.mark.asyncio
async def test_aihot_image_prompt_fallback_to_title():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    # 新调用顺序：先 7 条 LLM 评分 JSON → 再 1 条出图 prompt（抛 Exception）→ 再 1 条 meta
    llm_scores = [json.dumps({"score": s, "reason": "r", "tags": []}) for s in [9, 8, 7, 6, 5, 4, 3]]
    tp.generate.side_effect = llm_scores + [Exception("出图prompt失败"),
                               json.dumps({"title": "t", "description": "d", "tags": []})]
    script = await run_stage2_multi([_aihot_daily_article()], tp, max_articles=1)
    assert script["scenes"][0]["image_prompt"] == script["scenes"][0]["title"]  # 退化为 title


def test_aihot_candidates_fill_published_at():
    from app.pipeline.stage2_script import _aihot_candidates
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01",
                  "daily_sections": [{"label": "模型", "items": [{"title": "x", "summary": "s"}]}]})
    cands = _aihot_candidates([daily])
    assert cands and cands[0].published_at is not None
    assert cands[0].published_at.year == 2026 and cands[0].published_at.month == 6


@pytest.mark.asyncio
async def test_aihot_direct_uses_scoring_and_reports():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.side_effect = ['{"score": 9, "reason": "a", "tags": []}',
                               '{"score": 5, "reason": "b", "tags": []}',
                               '{"score": 7, "reason": "c", "tags": []}',
                               "画面A", "画面B",
                               json.dumps({"title": "汇总", "description": "d", "tags": []})]
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01",
                  "daily_sections": [{"label": "模型", "items": [{"title": f"i{i}", "summary": f"s{i}"} for i in range(3)]}]})
    script = await run_stage2_multi([daily], tp, max_articles=2)
    assert len(script["scenes"]) == 2
    assert script.get("scoring_report") and len(script["scoring_report"]["candidates"]) == 3


# ── cap_scenes_by_score 测试 ─────────────────────────────────────────────────
from app.pipeline.stage2_script import cap_scenes_by_score


def _scene(i, gid, score, gtitle="g"):
    return {"id": i, "group_id": gid, "group_title": gtitle, "title": gtitle,
            "narration": f"n{i}", "image_prompt": "p", "motion_prompt": "", "duration_hint": 5, "score": score}


def test_cap_noop_when_within_limit():
    script = {"scenes": [_scene(1, 1, 0.9), _scene(2, 2, 0.8)], "groups": []}
    assert cap_scenes_by_score(script, 5) is script
    assert cap_scenes_by_score(script, 0) is script


def test_cap_aihot_takes_top_by_score():
    scenes = [_scene(i, i, score) for i, score in [(1, 0.3), (2, 0.9), (3, 0.5), (4, 0.7)]]
    out = cap_scenes_by_score({"scenes": scenes, "groups": []}, 2)
    assert len(out["scenes"]) == 2
    assert [s["score"] for s in out["scenes"]] == [0.9, 0.7]
    assert [s["id"] for s in out["scenes"]] == [1, 2]
    assert [s["group_id"] for s in out["scenes"]] == [1, 2]


def test_cap_normal_drops_whole_low_group():
    scenes = [_scene(1, 1, 0.9), _scene(2, 1, 0.9), _scene(3, 2, 0.5), _scene(4, 2, 0.5), _scene(5, 3, 0.8)]
    out = cap_scenes_by_score({"scenes": scenes, "groups": []}, 3)
    assert len(out["scenes"]) == 3
    kept = {s["narration"] for s in out["scenes"]}
    assert "n3" not in kept and "n4" not in kept
    assert [s["id"] for s in out["scenes"]] == [1, 2, 3]
    assert [s["narration"] for s in out["scenes"]] == ["n1", "n2", "n5"]


def test_cap_single_group_over_limit_truncates():
    scenes = [_scene(1, 1, 0.9), _scene(2, 1, 0.9), _scene(3, 1, 0.9), _scene(4, 2, 0.2)]
    out = cap_scenes_by_score({"scenes": scenes, "groups": []}, 2)
    assert len(out["scenes"]) == 2
    assert all(s["score"] == 0.9 for s in out["scenes"])


@pytest.mark.asyncio
async def test_run_stage2_max_articles_controls_aihot_topn():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.side_effect = ['{"score": 9, "reason": "", "tags": []}',
                               '{"score": 5, "reason": "", "tags": []}',
                               '{"score": 7, "reason": "", "tags": []}',
                               "画面A", "画面B",
                               json.dumps({"title": "汇总", "description": "d", "tags": []})]
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01",
                  "daily_sections": [{"label": "模型", "items": [{"title": f"i{i}", "summary": f"s{i}"} for i in range(3)]}]})
    script = await run_stage2_multi([daily], tp, max_articles=2)
    assert len(script["scenes"]) == 2
    assert all("score" in s for s in script["scenes"])


@pytest.mark.asyncio
async def test_run_stage2_normal_scene_carries_score():
    tp = AsyncMock()
    tp.generate.side_effect = [_scenes_json("a1"), json.dumps({"title": "t", "description": "d", "tags": []})]
    art = RawArticleData(title="文章1", content="c", source_url="u", source_name="s",
                         metadata={"score_final": 0.66})
    script = await run_stage2_multi([art], tp)
    assert script["scenes"][0]["score"] == 0.66
