# S2 多文章分组脚本 + 自由增删分镜（Phase B）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage2 改为给一次运行的全部文章各自生成分镜组（普通每篇 LLM 1~3 分镜、AI HOT daily 按类目 2~4 条/组每条 1 分镜，结构化持久化），扁平 scenes 带 group 元数据；S2 面板按组展示并支持自由增删分镜（每组 ≥1）；汇总标题 LLM 综合生成。

**Architecture:** script.json 保持扁平 `scenes`（Stage3/4/5 不改），每个 scene 加 `group_id`/`group_title`、全局唯一 `id`，顶层加 `groups[{id,title,source_index}]` 与汇总 `title/description/tags`。新增 `run_stage2_multi` 编排多文章/日报分组生成；daily 结构化数据经 aihot collector→articles.json→reload 持久化；新增分镜增删端点；S2Panel 分组渲染 + 增删对话框。

**Tech Stack:** Python (FastAPI, pytest), React + TS。设计见 `docs/superpowers/specs/2026-05-28-multi-article-grouped-scripts-design.md`。本分支 `feat/multi-article-grouped-scripts` 叠在 Phase A 分支上。

---

## File Structure

- `backend/app/providers/collector/aihot.py` — daily collector 存 `metadata["daily_sections"]`
- `backend/app/pipeline/runner.py` — `_save_articles`/`_article_from_dict` 携带 `daily_sections`；Stage2 块改调 `run_stage2_multi`
- `backend/app/pipeline/stage2_script.py` — `_batch_items` + roundup/daily/summary 提示词 + `run_stage2_multi`（保留 `run_stage2`）
- `backend/app/api/pipeline.py` — `regen_script` 改调 multi；新增 `POST/DELETE /runs/{id}/scenes`
- `frontend/src/api/client.ts` — `ScriptData` 加 groups/scene group 字段；`addScene`/`deleteScene`
- `frontend/src/pages/Dashboard.tsx` — `S2Panel` 分组渲染 + 增删 + `AddSceneDialog`
- 测试：`backend/tests/` 追加 collector/runner/stage2_multi/scenes 用例

---

## Task 1: daily 结构化持久化（collector + articles.json 往返）

**Files:**
- Modify: `backend/app/providers/collector/aihot.py`、`backend/app/pipeline/runner.py`
- Test: `backend/tests/test_collector_aihot.py`、`backend/tests/test_runner_articles.py`

- [ ] **Step 1: 追加失败测试**

`backend/tests/test_collector_aihot.py`（已有 `DAILY_RESPONSE`、`_mock_client`、`AIHotCollector`）末尾追加：
```python
@pytest.mark.asyncio
async def test_aihot_daily_keeps_sections_in_metadata():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_client(mock_cls, DAILY_RESPONSE)
        articles = await collector.collect(source_config={"method": "daily"}, time_range="7d")
    secs = articles[0].metadata["daily_sections"]
    assert [s["label"] for s in secs] == ["模型发布/更新", "行业动态"]
    assert secs[0]["items"][0]["title"] == "模型A"
```
`backend/tests/test_runner_articles.py` 末尾追加：
```python
def test_save_and_reload_preserves_daily_sections(tmp_path):
    import json
    from app.providers.base import RawArticleData
    from app.pipeline.runner import _save_articles, _load_articles
    secs = [{"label": "模型", "items": [{"title": "A", "summary": "sa", "sourceUrl": "u", "sourceName": "s"}]}]
    art = RawArticleData(title="日报", content="c", source_url="https://aihot.virxact.com", source_name="AI HOT 日报",
                         metadata={"source_group": "aihot", "aihot_method": "daily", "daily_sections": secs})
    _save_articles([art], tmp_path)
    raw = json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))
    assert raw[0]["daily_sections"] == secs
    reloaded = _load_articles(tmp_path)
    assert reloaded[0].metadata["daily_sections"] == secs
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_collector_aihot.py::test_aihot_daily_keeps_sections_in_metadata tests/test_runner_articles.py::test_save_and_reload_preserves_daily_sections -v`
Expected: FAIL

- [ ] **Step 3a: collector 存 sections** — `backend/app/providers/collector/aihot.py` `_collect_daily` 里，构造 `article` 的 `metadata` 改为包含 `daily_sections`：
找到 `metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": date},` 改为：
```python
            metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": date,
                      "daily_sections": report.get("sections", [])},
```

- [ ] **Step 3b: _save_articles 持久化** — `backend/app/pipeline/runner.py` `_save_articles` 里每篇追加的 dict（已含 `aihot_method`）加一行：
```python
            "daily_sections": a.metadata.get("daily_sections"),
```

- [ ] **Step 3c: _article_from_dict 还原** — `backend/app/pipeline/runner.py` `_article_from_dict` 里，把 metadata 构造改为同时还原 daily_sections：
```python
def _article_from_dict(d: dict):
    from app.providers.base import RawArticleData
    metadata = {}
    if d.get("aihot_method"):
        metadata["aihot_method"] = d["aihot_method"]
    if d.get("daily_sections"):
        metadata["daily_sections"] = d["daily_sections"]
    return RawArticleData(
        title=d.get("title", ""),
        content=d.get("content", ""),
        source_url=d.get("url", ""),
        source_name=d.get("source", ""),
        summary=d.get("summary", ""),
        aggregator_url=d.get("aggregator_url", ""),
        metadata=metadata,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_collector_aihot.py tests/test_runner_articles.py -v`
Expected: PASS（含原有用例不回归）

- [ ] **Step 5: 提交**
```bash
git add backend/app/providers/collector/aihot.py backend/app/pipeline/runner.py backend/tests/test_collector_aihot.py backend/tests/test_runner_articles.py
git commit -m "feat(daily): 结构化 daily_sections 持久化（collector + articles.json 往返）"
```

---

## Task 2: stage2 — _batch_items + 提示词 + run_stage2_multi

**Files:**
- Modify: `backend/app/pipeline/stage2_script.py`
- Test: `backend/tests/test_stage2_multi.py`（新）

- [ ] **Step 1: 写失败测试** — 创建 `backend/tests/test_stage2_multi.py`:
```python
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
        assert all(2 <= s <= 4 for s in sizes)  # n>=2 → 每批 2~4，无尾批 1


def _scenes_json(*narrations):
    return json.dumps({"scenes": [{"narration": n, "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5} for n in narrations]})


@pytest.mark.asyncio
async def test_multi_normal_articles_group_per_article():
    tp = AsyncMock()
    tp.generate.side_effect = [
        _scenes_json("a1", "a2"),          # article 1 → 2 scenes
        _scenes_json("b1"),                # article 2 → 1 scene
        json.dumps({"title": "汇总", "description": "d", "tags": ["t"]}),  # summary
    ]
    arts = [
        RawArticleData(title="文章1", content="c1", source_url="u1", source_name="s1"),
        RawArticleData(title="文章2", content="c2", source_url="u2", source_name="s2"),
    ]
    script = await run_stage2_multi(arts, tp)
    assert script["title"] == "汇总"
    assert [g["title"] for g in script["groups"]] == ["文章1", "文章2"]
    assert [g["source_index"] for g in script["groups"]] == [0, 1]
    ids = [s["id"] for s in script["scenes"]]
    assert ids == [1, 2, 3]                # 全局唯一连续
    assert [s["group_id"] for s in script["scenes"]] == [1, 1, 2]


@pytest.mark.asyncio
async def test_multi_daily_groups_by_category():
    tp = AsyncMock()
    # 模型类目 5 条 → _batch_items(5)=[3,2] → 2 组；行业 2 条 → [2] → 1 组；+1 summary = 4 calls
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_stage2_multi.py -v`
Expected: FAIL（`_batch_items`/`run_stage2_multi` 不存在）

- [ ] **Step 3: 实现** — 在 `backend/app/pipeline/stage2_script.py` 末尾追加（保留现有 `run_stage2`/`SCRIPT_SYSTEM_PROMPT`/`DAILY_DIGEST_SYSTEM_PROMPT` 不动）：
```python
ROUNDUP_ARTICLE_SYSTEM_PROMPT = """你是新闻汇总短视频的分镜脚本编写者。下面给你一条资讯，为它生成 1~3 个分镜（内容多/重要则多，简短则 1 个）。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English static scene description","motion_prompt":"English camera motion","duration_hint":5}]}
要求：旁白像新闻主播口播；image_prompt 用英文描述构图/色调/风格；分镜数不超过 3。"""

DAILY_BATCH_SYSTEM_PROMPT = """你是 AI 资讯日报短视频的分镜脚本编写者。下面给你同一类目下的若干条资讯，请**每条资讯生成 1 个分镜**，顺序与给定一致。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"...","image_prompt":"...","motion_prompt":"...","duration_hint":5}]}
分镜数量须等于给定资讯条数。"""

SUMMARY_META_SYSTEM_PROMPT = """你是短视频运营。下面给你一条汇总视频包含的各条资讯标题，生成整条视频的吸睛标题与简介。
输出纯 JSON（无 markdown 标记）：{"title":"中文标题","description":"1-2句中文简介","tags":["标签1","标签2"]}"""


def _parse_json(response: str) -> dict:
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned)


def _batch_items(n: int) -> list[int]:
    """把 n 条 items 切成每批 2~4（以 3 为主，无尾批 1）；n==1→[1]。"""
    if n <= 0:
        return []
    sizes: list[int] = []
    remaining = n
    while remaining > 4:
        sizes.append(3)
        remaining -= 3
    sizes.append(remaining)
    return sizes


async def _gen_article_scenes(article, tp) -> list[dict]:
    prompt = f"标题：{article.title}\n来源：{article.source_name}\n内容：\n{(article.content or article.title)[:2000]}"
    resp = await tp.generate(prompt=prompt, system_prompt=ROUNDUP_ARTICLE_SYSTEM_PROMPT)
    scenes = _parse_json(resp).get("scenes", [])
    if not scenes:
        scenes = [{"narration": article.title, "image_prompt": article.title, "motion_prompt": "", "duration_hint": 5}]
    return scenes[:3]


async def _gen_daily_batch_scenes(items: list[dict], tp) -> list[dict]:
    lines = [f"{i + 1}. 「{it.get('title', '')}」{it.get('summary', '')}" for i, it in enumerate(items)]
    resp = await tp.generate(prompt="本组资讯：\n" + "\n".join(lines), system_prompt=DAILY_BATCH_SYSTEM_PROMPT)
    return _parse_json(resp).get("scenes", [])


async def _gen_summary_meta(titles: list[str], tp) -> dict:
    resp = await tp.generate(prompt="各条资讯标题：\n" + "\n".join(f"- {t}" for t in titles), system_prompt=SUMMARY_META_SYSTEM_PROMPT)
    try:
        m = _parse_json(resp)
    except Exception:
        m = {}
    return {"title": m.get("title", "资讯汇总"), "description": m.get("description", ""), "tags": m.get("tags", [])}


async def run_stage2_multi(articles: list, text_provider, language: str = "zh") -> dict:
    scenes: list[dict] = []
    groups: list[dict] = []
    next_id = 1
    next_gid = 1
    titles: list[str] = []

    for idx, article in enumerate(articles):
        sections = article.metadata.get("daily_sections")
        if article.metadata.get("aihot_method") == "daily" and sections:
            for section in sections:
                label = section.get("label", "")
                items = section.get("items", [])
                sizes = _batch_items(len(items))
                multi = len(sizes) > 1
                start = 0
                for bi, size in enumerate(sizes):
                    batch = items[start:start + size]
                    start += size
                    gid = next_gid
                    next_gid += 1
                    gtitle = label if not multi else f"{label} ({bi + 1})"
                    batch_scenes = await _gen_daily_batch_scenes(batch, text_provider)
                    if len(batch_scenes) != len(batch):
                        log.warning("[S2] daily batch returned %d scenes for %d items", len(batch_scenes), len(batch))
                    for sc in batch_scenes:
                        sc["id"] = next_id
                        next_id += 1
                        sc["group_id"] = gid
                        sc["group_title"] = gtitle
                        scenes.append(sc)
                    groups.append({"id": gid, "title": gtitle, "source_index": idx})
                    titles.extend(it.get("title", "") for it in batch)
        else:
            gid = next_gid
            next_gid += 1
            art_scenes = await _gen_article_scenes(article, text_provider)
            for sc in art_scenes:
                sc["id"] = next_id
                next_id += 1
                sc["group_id"] = gid
                sc["group_title"] = article.title
                scenes.append(sc)
            groups.append({"id": gid, "title": article.title, "source_index": idx})
            titles.append(article.title)

    meta = await _gen_summary_meta(titles, text_provider)
    log.info("[S2] multi script: %d groups, %d scenes", len(groups), len(scenes))
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"], "groups": groups, "scenes": scenes}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_stage2_multi.py tests/test_stage2.py -v`
Expected: PASS（含 stage2 单篇旧测试不回归）

- [ ] **Step 5: 提交**
```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "feat(stage2): run_stage2_multi 多文章分组 + daily 批分 + 汇总标题"
```

---

## Task 3: runner Stage2 + regen-script 改调 multi

**Files:**
- Modify: `backend/app/pipeline/runner.py`、`backend/app/api/pipeline.py`

- [ ] **Step 1: runner Stage2 块** — `backend/app/pipeline/runner.py` 把 `if 2 in selected:` 块开头到 `run_stage2(...)` 调用替换（去掉单篇 `article`/`style`，改调 multi）：
找到：
```python
    if 2 in selected:
        t0 = time.time()
        article = articles[0]
        style = "daily" if article.metadata.get("aihot_method") == "daily" else "single"
        _update(db, run, current_stage=2, progress_detail=f"S2 生成脚本 — {article.title[:30]}...")
        log.info("[S2] Generating script for: %s", article.title)

        text_provider = _build_text_provider()
        log.info("[S2] Provider: %s / %s", cfg.text.provider, cfg.text.model)

        script = await run_stage2(article=article, text_provider=text_provider,
                                  language=cfg.pipeline.default_language, style=style)
```
替换为：
```python
    if 2 in selected:
        t0 = time.time()
        _update(db, run, current_stage=2, progress_detail=f"S2 生成脚本 — {len(articles)} 篇文章...")
        log.info("[S2] Generating multi-article script for %d articles", len(articles))

        text_provider = _build_text_provider()
        log.info("[S2] Provider: %s / %s", cfg.text.provider, cfg.text.model)

        from app.pipeline.stage2_script import run_stage2_multi
        script = await run_stage2_multi(articles, text_provider, language=cfg.pipeline.default_language)
```
（其后 `script.json` 写入、`scene_count`、review 暂停等保持不变。）

- [ ] **Step 2: regen-script 改 multi** — `backend/app/api/pipeline.py` `regen_script` 中，把读单篇 + `run_stage2(article,…)` 改为全部文章 + multi。替换：
```python
    from app.providers.base import RawArticleData
    articles_raw = json.loads(articles_path.read_text(encoding="utf-8"))
    article = _article_from_dict(articles_raw[0])
    style = "daily" if article.metadata.get("aihot_method") == "daily" else "single"
```
为：
```python
    articles_raw = json.loads(articles_path.read_text(encoding="utf-8"))
    arts = [_article_from_dict(d) for d in articles_raw]
```
并把：
```python
    from app.pipeline.stage2_script import run_stage2
    log.info("Regenerating script for run #%d", run_id)
    script = await run_stage2(article=article, text_provider=tp, language=cfg.pipeline.default_language, style=style)
```
改为：
```python
    from app.pipeline.stage2_script import run_stage2_multi
    log.info("Regenerating multi-article script for run #%d (%d articles)", run_id, len(arts))
    script = await run_stage2_multi(arts, tp, language=cfg.pipeline.default_language)
```

- [ ] **Step 3: 验证**

Run: `cd backend && python -c "import app.pipeline.runner; import app.api.pipeline" && python -m pytest tests/test_stage2_multi.py tests/test_api_pipeline.py tests/test_stage1.py -q`
Expected: 导入无错；测试 PASS

- [ ] **Step 4: 提交**
```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py
git commit -m "feat(runner): Stage2 与 regen-script 改用 run_stage2_multi（全部文章）"
```

---

## Task 4: 分镜增删端点

**Files:**
- Modify: `backend/app/api/pipeline.py`
- Test: `backend/tests/test_api_scenes.py`（新）

- [ ] **Step 1: 写失败测试** — 创建 `backend/tests/test_api_scenes.py`:
```python
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import create_app
from app.models import Base  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.pipeline._run_dir", lambda run_id: tmp_path / str(run_id))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    app = create_app()
    Base.metadata.create_all(engine)

    def override_get_db():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.api.pipeline._run_pipeline_bg"):
        yield TestClient(app)


def _seed(tmp_path, run_id, script, articles):
    d = tmp_path / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    (d / "articles.json").write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")


SCRIPT = {
    "title": "T", "description": "d", "tags": [],
    "groups": [{"id": 1, "title": "文章1", "source_index": 0}, {"id": 2, "title": "文章2", "source_index": 1}],
    "scenes": [
        {"id": 1, "group_id": 1, "group_title": "文章1", "narration": "n1", "image_prompt": "p1", "motion_prompt": "", "duration_hint": 5},
        {"id": 2, "group_id": 2, "group_title": "文章2", "narration": "n2", "image_prompt": "p2", "motion_prompt": "", "duration_hint": 5},
    ],
}
ARTICLES = [{"title": "文章1", "content": "c1"}, {"title": "文章2", "content": "c2"}]


def test_add_scene_appends_to_group(client, tmp_path):
    _seed(tmp_path, 1, SCRIPT, ARTICLES)
    fake = '{"scenes":[{"narration":"new","image_prompt":"np","motion_prompt":"nm","duration_hint":4}]}'
    with patch("app.api.pipeline._build_text_provider") as mk:
        tp = mk.return_value
        tp.generate = AsyncMock(return_value=fake)
        r = client.post("/api/pipeline/runs/1/scenes", json={"group_id": 1, "requirement": "讲讲X"})
    assert r.status_code == 200
    new = r.json()
    assert new["group_id"] == 1 and new["id"] == 3 and new["narration"] == "new"
    saved = json.loads((tmp_path / "1" / "script.json").read_text(encoding="utf-8"))
    g1 = [s for s in saved["scenes"] if s["group_id"] == 1]
    assert len(g1) == 2  # 原 1 + 新 1


def test_delete_scene_ok(client, tmp_path):
    s = json.loads(json.dumps(SCRIPT))
    s["scenes"].append({"id": 3, "group_id": 1, "group_title": "文章1", "narration": "n3", "image_prompt": "p3", "motion_prompt": "", "duration_hint": 5})
    _seed(tmp_path, 1, s, ARTICLES)
    r = client.delete("/api/pipeline/runs/1/scenes/3")
    assert r.status_code == 200
    saved = json.loads((tmp_path / "1" / "script.json").read_text(encoding="utf-8"))
    assert 3 not in [sc["id"] for sc in saved["scenes"]]


def test_delete_last_scene_in_group_blocked(client, tmp_path):
    _seed(tmp_path, 1, SCRIPT, ARTICLES)  # group 2 只有 scene id=2
    r = client.delete("/api/pipeline/runs/1/scenes/2")
    assert r.status_code == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_api_scenes.py -v`
Expected: FAIL（端点不存在）

- [ ] **Step 3: 实现** — 在 `backend/app/api/pipeline.py` 新增（放在 regen-script 端点附近；复用已有 `_run_dir`、`get_settings`、`json`、`HTTPException`、`_PydBase`、`_build_text_provider` 来自 runner）。先在顶部 import 区确保有 `from app.pipeline.runner import _build_text_provider`（若已 import runner 其他符号，合并进去）。然后：
```python
class _AddSceneBody(_PydBase):
    group_id: int
    requirement: str = ""


@router.post("/runs/{run_id}/scenes")
async def add_scene(run_id: int, body: _AddSceneBody):
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    group = next((g for g in script.get("groups", []) if g["id"] == body.group_id), None)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    articles = json.loads((rd / "articles.json").read_text(encoding="utf-8")) if (rd / "articles.json").exists() else []
    src = articles[group["source_index"]] if 0 <= group.get("source_index", -1) < len(articles) else {}
    src_text = f"标题：{src.get('title','')}\n内容：\n{(src.get('content') or '')[:2000]}"

    from app.pipeline.stage2_script import ROUNDUP_ARTICLE_SYSTEM_PROMPT, _parse_json
    tp = _build_text_provider()
    prompt = f"{src_text}\n\n额外要求：{body.requirement or '补充一个新分镜'}\n只输出 1 个分镜。"
    resp = await tp.generate(prompt=prompt, system_prompt=ROUNDUP_ARTICLE_SYSTEM_PROMPT)
    gen = _parse_json(resp).get("scenes") or [{"narration": "", "image_prompt": "", "motion_prompt": "", "duration_hint": 5}]
    sc = gen[0]
    new_id = max([s["id"] for s in script["scenes"]], default=0) + 1
    sc["id"] = new_id
    sc["group_id"] = body.group_id
    sc["group_title"] = group["title"]

    # 插入到该组最后一个分镜之后
    last = max((i for i, s in enumerate(script["scenes"]) if s["group_id"] == body.group_id), default=len(script["scenes"]) - 1)
    script["scenes"].insert(last + 1, sc)
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return sc


@router.delete("/runs/{run_id}/scenes/{scene_id}")
def delete_scene(run_id: int, scene_id: int):
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    target = next((s for s in script["scenes"] if s["id"] == scene_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Scene not found")
    same_group = [s for s in script["scenes"] if s["group_id"] == target["group_id"]]
    if len(same_group) <= 1:
        raise HTTPException(status_code=400, detail="每组至少保留 1 个分镜")
    script["scenes"] = [s for s in script["scenes"] if s["id"] != scene_id]
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_api_scenes.py -v` 与 `python -c "import app.api.pipeline"`
Expected: PASS；导入无错

- [ ] **Step 5: 提交**
```bash
git add backend/app/api/pipeline.py backend/tests/test_api_scenes.py
git commit -m "feat(api): 分镜增删端点（新增基于该组文章 AI 生成；删除守卫每组≥1）"
```

---

## Task 5: 前端 client — ScriptData 分组类型 + addScene/deleteScene

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: ScriptData 类型** — 把 `interface ScriptData` 改为带分组字段：
```ts
export interface ScriptData {
  title: string;
  description: string;
  tags: string[];
  groups?: { id: number; title: string; source_index: number }[];
  scenes: { id: number; group_id?: number; group_title?: string; narration: string; image_prompt: string; motion_prompt?: string; duration_hint?: number }[];
}
```

- [ ] **Step 2: API 方法** — 在 `api.runs` 里（regenScript 附近）加：
```ts
    addScene: (runId: number, groupId: number, requirement: string) =>
      fetchJSON(`/pipeline/runs/${runId}/scenes`, { method: "POST", body: JSON.stringify({ group_id: groupId, requirement }) }),
    deleteScene: (runId: number, sceneId: number) =>
      fetchJSON(`/pipeline/runs/${runId}/scenes/${sceneId}`, { method: "DELETE" }),
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 错误

- [ ] **Step 4: 提交**
```bash
git add frontend/src/api/client.ts
git commit -m "feat(client): ScriptData 分组类型 + addScene/deleteScene API"
```

---

## Task 6: 前端 S2Panel — 分组渲染 + 增删

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: 加 AddSceneDialog 组件** — 在 `S2Panel` 之前加：
```tsx
function AddSceneDialog({ runId, groupId, onDone, onClose }: { runId: number; groupId: number; onDone: () => void; onClose: () => void; }) {
  const [requirement, setRequirement] = useState("");
  const [loading, setLoading] = useState(false);
  const { showToast } = useToast();
  const submit = async () => {
    setLoading(true);
    try { await api.runs.addScene(runId, groupId, requirement); showToast("已新增分镜", "success"); onDone(); }
    catch (e) { showToast(e instanceof Error ? e.message : "新增失败", "error"); }
    finally { setLoading(false); }
  };
  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[480px]`}>
        <h2 className="text-lg font-semibold mb-3">新增分镜</h2>
        <label className={labelCls}>这个分镜想讲什么（选填）</label>
        <textarea value={requirement} onChange={(e) => setRequirement(e.target.value)} rows={3} className={`${inputCls} mb-4 text-[13px]`} placeholder="例如：强调它对开发者的影响" />
        <div className="flex justify-end gap-3">
          <button onClick={onClose} className={btnCompact}>取消</button>
          <button onClick={submit} disabled={loading} className={btnPrimary}>{loading ? "生成中..." : "生成"}</button>
        </div>
      </div>
    </div>
  );
}
```
（确保 Dashboard.tsx 顶部已从 `../styles` 导入 `dialogOverlayCls, dialogPanelCls`——Phase A 的 Task 10 已加；若没有则补上。）

- [ ] **Step 2: SceneEditor 加删除按钮** — 给 `SceneEditor` 组件 props 增加 `onDelete?: () => void; canDelete: boolean`，并在其按钮区（"重新配音"附近）加一个删除按钮：
在 `SceneEditor` 函数签名加 `onDelete, canDelete`，在场景头部 `<span>场景 {sid}</span>` 同行右侧加：
```tsx
            {onDelete && (
              <button onClick={onDelete} disabled={!canDelete} className={btnCompact} title={canDelete ? "删除分镜" : "每组至少保留 1 个"}>删除</button>
            )}
```

- [ ] **Step 3: 改写 S2Panel 为分组渲染** — 用下面替换现有 `S2Panel`（保留 imgSize 逻辑；按 group_id 分组、组头、组内 SceneEditor + 删除 + 组底新增）：
```tsx
function S2Panel({ runId }: { runId: number }) {
  const { data: script, mutate: mutateScript } = useSWR<ScriptData>(`script-${runId}`, () => api.runs.script(runId).catch(() => null as unknown as ScriptData));
  const { data: timeline } = useSWR<TimelineData>(`timeline-${runId}`, () => api.runs.timeline(runId).catch(() => null as unknown as TimelineData));
  const { data: settings } = useSWR<AppSettings>("settings", api.settings.get);
  const [imgSize, setImgSize] = useState("");
  const [addGroup, setAddGroup] = useState<number | null>(null);
  const { showToast } = useToast();
  useEffect(() => { if (settings && !imgSize) setImgSize(settings.video.resolution); }, [settings, imgSize]);

  if (!script) return <p className="text-white/30 text-sm">暂无脚本</p>;

  const scenes = script.scenes ?? [];
  // 按 group_id 首次出现顺序分组（旧脚本无 group_id → 落入默认组 0）
  const order: number[] = [];
  const byGroup = new Map<number, typeof scenes>();
  for (const sc of scenes) {
    const gid = sc.group_id ?? 0;
    if (!byGroup.has(gid)) { byGroup.set(gid, []); order.push(gid); }
    byGroup.get(gid)!.push(sc);
  }
  const groupTitle = (gid: number) => script.groups?.find((g) => g.id === gid)?.title ?? byGroup.get(gid)?.[0]?.group_title ?? "分镜";

  const onDelete = async (sceneId: number) => {
    try { await api.runs.deleteScene(runId, sceneId); mutateScript(); }
    catch (e) { showToast(e instanceof Error ? e.message : "删除失败", "error"); }
  };

  return (
    <div>
      <div className="flex justify-between items-start mb-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-medium truncate">{script.title}</h3>
          <p className="text-xs text-white/30 mt-0.5">{script.description}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-4">
          <label className="text-[11px] text-white/30 whitespace-nowrap">图片尺寸</label>
          <PresetInput value={imgSize} onChange={setImgSize} presets={RES_PRESETS} className="w-40" />
        </div>
      </div>

      {order.map((gid) => {
        const groupScenes = byGroup.get(gid)!;
        return (
          <div key={gid} className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <h4 className={sectionTitleCls}>{groupTitle(gid)}</h4>
              <button onClick={() => setAddGroup(gid)} className={btnCompact}>+ 新增分镜</button>
            </div>
            <div className="space-y-3">
              {groupScenes.map((scene) => {
                const entry = timeline?.entries?.find((e) => e.scene_id === scene.id);
                const durS = entry ? ((entry.end_ms - entry.start_ms) / 1000).toFixed(1) : null;
                return (
                  <SceneEditor key={scene.id} runId={runId} scene={scene} durationS={durS} mutateScript={mutateScript} imgSize={imgSize}
                    onDelete={() => onDelete(scene.id)} canDelete={groupScenes.length > 1} />
                );
              })}
            </div>
          </div>
        );
      })}

      {addGroup !== null && (
        <AddSceneDialog runId={runId} groupId={addGroup} onDone={() => { setAddGroup(null); mutateScript(); }} onClose={() => setAddGroup(null)} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: 类型检查 + 构建**

Run: `cd frontend && npx tsc --noEmit && pnpm build`
Expected: 0 错误，构建成功

- [ ] **Step 5: 提交**
```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(s2): 分镜按组展示 + 组内增删（新增填要求、删除守卫每组≥1）"
```

---

## 验收

- [ ] 后端全量：`cd backend && python -m pytest -q`（新增 stage2_multi / daily 持久化 / scenes 端点用例；其余维持通过）
- [ ] 前端：`cd frontend && npx tsc --noEmit && pnpm build` 通过
- [ ] 手动核对（用户启服务）：普通源跑一次 → S2 每篇一组、每组 1~3 分镜；AI HOT daily 跑一次 → 按类目分组、每条 1 分镜；组内「+新增分镜」填要求生成、删除（组内剩 1 个时被拦）；汇总标题合理。

## Self-Review 注记
- Stage3/4/5 不改：依赖扁平 `scenes` + `scene.id`，本计划保持。
- 旧 script.json 无 group_id：S2Panel 用 `group_id ?? 0` 兜底落入默认组。
- daily 批分确定性：`_batch_items` 纯函数 + n=2..30 性质测试（每批 2~4、无尾批 1）。
- `run_stage2`（单篇）保留不动，旧测试不破；多文章主流程走 `run_stage2_multi`。
