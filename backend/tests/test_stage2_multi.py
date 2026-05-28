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
