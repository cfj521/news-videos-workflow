# AI HOT 周报模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AI HOT 聚合源新增 `weekly` 采集模式——聚合上一自然周的每日日报，经文本 AI 跨天提炼成主题热点，复用 daily 的分组分镜，生成一条"本周 AI 热点回顾"视频。

**Architecture:** Collector 纯抓取（算周范围 + 逐天拉日报 + 扁平汇总 `weekly_items`）→ Stage1 整理层调文本 AI 把 `weekly_items` 提炼成 `daily_sections` 形状的主题（提炼=整理层，非脚本层）→ Stage2 仅放宽一处分支判断即复用 daily 的分组→分镜路径。提炼 helper 由 runner 主流程与 reroll 共享，避免分叉。

**Tech Stack:** Python 3.10+（FastAPI / httpx / pytest-asyncio），React + TypeScript（Vite）。

参考设计文档：`docs/superpowers/specs/2026-06-01-aihot-weekly-digest-design.md`

---

## File Structure

后端：
- `backend/app/providers/collector/aihot.py` — 新增 `_collect_weekly`（纯抓取 + 周范围 + 扁平汇总）。
- `backend/app/pipeline/stage2_script.py` — 新增 `WEEKLY_DIGEST_SYSTEM_PROMPT`、`_sample_weekly_items`、`_fallback_weekly_sections`、`distill_weekly_sections`；放宽 `run_stage2_multi` 分支判断。
- `backend/app/pipeline/stage1_collect.py` — AI HOT 分流：weekly 走单篇直通。
- `backend/app/pipeline/runner.py` — 新增 `_distill_weekly_if_needed`、`_no_article_message`；Stage1 段调提炼、失败文案改 `digest_method`。
- `backend/app/api/pipeline.py` — `_reroll_articles_async` 调同一提炼 helper。

前端：
- `frontend/src/pages/Sources.tsx` — 模式切换加 `weekly`。
- `frontend/src/components/CreateRunDialog.tsx` — `isAihotDaily` → `isAihotDigest`。
- `frontend/src/components/SourceSummary.tsx` — weekly 标签。

测试：
- `backend/tests/test_collector_aihot.py` — weekly collector 用例。
- `backend/tests/test_stage2_multi.py` — weekly 提炼 + 分组分镜用例。
- `backend/tests/test_runner_weekly.py`（新建）— `_no_article_message` 与 `_distill_weekly_if_needed` 用例。

---

## Task 1: Collector `_collect_weekly` — 抓取上一自然周日报并扁平汇总

**Files:**
- Modify: `backend/app/providers/collector/aihot.py:1-2`（import `date`）、`:28-32`（`collect` 分支）、文件末尾追加 `_collect_weekly`
- Test: `backend/tests/test_collector_aihot.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_collector_aihot.py` 末尾追加（顶部已有 `from unittest.mock import AsyncMock, MagicMock, patch` 与 `import pytest`）：

```python
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
            source_config={"method": "weekly", "name": "AI HOT"}, time_range="7d")
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_collector_aihot.py -k weekly -v`
Expected: FAIL（`collect` 走不到 weekly 分支，返回 items 流程或报错）

- [ ] **Step 3: 实现 `_collect_weekly`**

改 `backend/app/providers/collector/aihot.py` 第 2 行 import，加入 `date`：

```python
from datetime import date, datetime, timedelta, timezone
```

在 `collect` 方法（约 28-32 行）的分支里，`daily` 判断之后加 weekly：

```python
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        method = source_config.get("method", "items")
        if method == "daily":
            return await self._collect_daily(source_config)
        if method == "weekly":
            return await self._collect_weekly(source_config)
        return await self._collect_items(source_config, time_range, max_items)
```

在文件末尾追加方法：

```python
    async def _collect_weekly(self, source_config: dict) -> list[RawArticleData]:
        """聚合上一个完整自然周（周一~周日）的每日日报，扁平汇总条目供 Stage1 提炼。"""
        t0 = _time.time()
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        week_start = this_monday - timedelta(days=7)
        week_end = this_monday - timedelta(days=1)

        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/dailies")
            if resp.status_code == 404:
                log.warning("AI Hot dailies archive not available (404)")
                return []
            resp.raise_for_status()
            archive = resp.json()

            dates: list[str] = []
            for it in archive.get("items", []):
                raw = it.get("date", "")
                try:
                    d = date.fromisoformat(raw)
                except ValueError:
                    continue
                if week_start <= d <= week_end:
                    dates.append(raw)
            dates.sort()

            weekly_items: list[dict] = []
            content_lines: list[str] = []
            first_lead = ""
            for d in dates:
                r = await client.get(f"{API}/daily/{d}")
                if r.status_code == 404:
                    log.warning("AI Hot daily %s missing (404), skip", d)
                    continue
                try:
                    r.raise_for_status()
                except Exception:
                    log.warning("AI Hot daily %s failed, skip", d)
                    continue
                report = r.json()
                lead = report.get("lead") or {}
                lead_para = lead.get("leadParagraph", "")
                if lead_para and not first_lead:
                    first_lead = lead_para
                content_lines.append(f"# {d} {lead.get('title', '')}")
                content_lines.append(lead_para)
                for section in report.get("sections", []):
                    label = section.get("label", "")
                    content_lines.append(f"【{label}】")
                    for sit in section.get("items", []):
                        title = sit.get("title", "")
                        summary = sit.get("summary", "")
                        content_lines.append(f"「{title}」{summary}")
                        weekly_items.append({"title": title, "summary": summary,
                                             "category": label, "date": d})
                for f in report.get("flashes", []):
                    weekly_items.append({"title": f.get("title", ""), "summary": "",
                                         "category": "快讯", "date": d})
                content_lines.append("")

        if not weekly_items:
            log.warning("AI Hot weekly: no dailies in %s~%s", week_start, week_end)
            return []

        content = "\n".join(content_lines).strip()
        article = RawArticleData(
            title=f"本周 AI 热点回顾 {week_start}~{week_end}",
            content=content,
            source_url="https://aihot.virxact.com",
            source_name="AI HOT 周报",
            category="ai",
            summary=first_lead,
            aggregator_url="https://aihot.virxact.com",
            metadata={"source_group": "aihot", "aihot_method": "weekly",
                      "week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
                      "weekly_items": weekly_items},
        )
        log.info("Collected AI Hot weekly (%s~%s, %d items) in %.1fs",
                 week_start, week_end, len(weekly_items), _time.time() - t0)
        return [article]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_collector_aihot.py -v`
Expected: PASS（含原有 items/daily 用例不回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/collector/aihot.py backend/tests/test_collector_aihot.py
git commit -m "feat(aihot): weekly collector 聚合上一自然周日报"
```

---

## Task 2: Stage1 分流 — weekly 单篇直通

**Files:**
- Modify: `backend/app/pipeline/stage1_collect.py:66`
- Test: `backend/tests/test_stage1.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_stage1.py` 末尾追加：

```python
import pytest

from app.pipeline.stage1_collect import run_stage1
from app.providers.base import CollectorProvider, RawArticleData


class _FakeWeeklyCollector(CollectorProvider):
    async def collect(self, source_config, time_range, max_items=30):
        return [RawArticleData(
            title="本周回顾", content="c", source_url="u", source_name="AI HOT 周报",
            metadata={"source_group": "aihot", "aihot_method": "weekly",
                      "weekly_items": [{"title": "t", "summary": "s", "category": "x", "date": "2026-05-25"}]})]


@pytest.mark.asyncio
async def test_stage1_weekly_single_passthrough_ignores_max():
    sources = [{"type": "api", "name": "AI HOT"}]
    collectors = {"api": _FakeWeeklyCollector()}
    # max_articles=0 不应把唯一一篇周报截断成空
    out = await run_stage1(sources=sources, collectors=collectors, time_range="7d", max_articles=0)
    assert len(out) == 1
    assert out[0].metadata["aihot_method"] == "weekly"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage1.py::test_stage1_weekly_single_passthrough_ignores_max -v`
Expected: FAIL（weekly 落入 `compliant[:max_articles]` = `[:0]` → 空，断言 `len==1` 失败）

- [ ] **Step 3: 改分流判断**

`backend/app/pipeline/stage1_collect.py` 第 66 行：

```python
        if method == "daily":
```

改为：

```python
        if method in ("daily", "weekly"):
```

并把其上一行日志（67 行）改为对两种模式都成立的措辞：

```python
            log.info("AI HOT %s — single-doc passthrough", method)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_stage1.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage1_collect.py backend/tests/test_stage1.py
git commit -m "feat(aihot): weekly 走单篇直通分流"
```

---

## Task 3: Stage2 — 周报提炼函数 `distill_weekly_sections`

**Files:**
- Modify: `backend/app/pipeline/stage2_script.py`（新增提示词 + 三个函数，放在 `run_stage2_multi` 之前、`SUMMARY_META_SYSTEM_PROMPT` 附近）
- Test: `backend/tests/test_stage2_multi.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_stage2_multi.py` 末尾追加（顶部已有 `import json` / `from unittest.mock import AsyncMock` / `import pytest`）：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage2_multi.py -k distill -v`
Expected: FAIL（`ImportError: cannot import name 'distill_weekly_sections'`）

- [ ] **Step 3: 实现提示词 + 三个函数**

在 `backend/app/pipeline/stage2_script.py` 中 `SUMMARY_META_SYSTEM_PROMPT`（约 116-117 行）之后、`def _parse_json` 之前插入：

```python
WEEKLY_DIGEST_SYSTEM_PROMPT = """你是 AI 资讯周报编辑。下面给你过去一整周的全部资讯条目（含日期/分类线索）。
请跨天归纳出**本周 3-5 个最重要的热点主题**，每个主题挑 1-3 条最有代表性的资讯，**全部主题的资讯总条数不超过 9 条**。
要求：体现"本周"视角（趋势、归纳），合并跨天对同一事件的重复报道。
输出纯 JSON（无 markdown 标记）：
{"sections":[{"label":"主题名(中文)","items":[{"title":"资讯标题","summary":"一句话摘要"}]}]}"""
```

在 `def _parse_json` 与 `def _batch_items` 之间（或 `SUMMARY_META` 函数附近）插入三个函数：

```python
def _sample_weekly_items(weekly_items: list[dict], per_day: int = 8, char_cap: int = 12000) -> str:
    """按天采样渲染，避免简单截断偏向前半周。"""
    from collections import OrderedDict
    by_day: "OrderedDict[str, list]" = OrderedDict()
    for it in weekly_items:
        by_day.setdefault(it.get("date", ""), []).append(it)
    lines: list[str] = []
    total = 0
    for day, day_items in by_day.items():
        for it in day_items[:per_day]:
            line = f"[{day}/{it.get('category', '')}] 「{it.get('title', '')}」{it.get('summary', '')}"
            if total + len(line) > char_cap:
                return "\n".join(lines)
            lines.append(line)
            total += len(line)
    return "\n".join(lines)


def _fallback_weekly_sections(weekly_items: list[dict], max_sections: int = 5, per_section: int = 3) -> list[dict]:
    """提炼失败兜底：按 category 分组，形状同 daily_sections。"""
    from collections import OrderedDict
    groups: "OrderedDict[str, list]" = OrderedDict()
    for it in weekly_items:
        groups.setdefault(it.get("category", "其它"), []).append(
            {"title": it.get("title", ""), "summary": it.get("summary", "")})
    sections: list[dict] = []
    for label, items in groups.items():
        sections.append({"label": label, "items": items[:per_section]})
        if len(sections) >= max_sections:
            break
    return sections


async def distill_weekly_sections(weekly_items: list[dict], text_provider) -> list[dict]:
    """把一周扁平条目跨天提炼成主题 sections（形状同 daily_sections）。失败/空则兜底分组。"""
    text = _sample_weekly_items(weekly_items)
    try:
        resp = await text_provider.generate(
            prompt="本周资讯条目：\n" + text, system_prompt=WEEKLY_DIGEST_SYSTEM_PROMPT)
        sections = _parse_json(resp).get("sections", [])
    except Exception:
        log.warning("[S1] weekly distill parse failed")
        sections = []
    sections = [s for s in sections if s.get("items")]
    if not sections:
        log.warning("[S1] weekly distill empty — fallback group by category")
        sections = _fallback_weekly_sections(weekly_items)
    log.info("[S1] weekly distilled into %d themes", len(sections))
    return sections
```

> 注：`_parse_json` 已定义于本文件（约 120 行），`distill_weekly_sections` 必须放在其之后。`log` 已在文件顶部定义。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_stage2_multi.py -k distill -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "feat(aihot): 周报跨天提炼 distill_weekly_sections + 兜底分组"
```

---

## Task 4: Stage2 — 放宽分组分支让 weekly 复用 daily 分镜

**Files:**
- Modify: `backend/app/pipeline/stage2_script.py:185`
- Test: `backend/tests/test_stage2_multi.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_stage2_multi.py` 末尾追加：

```python
from app.providers.base import RawArticleData


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage2_multi.py::test_multi_weekly_groups_like_daily -v`
Expected: FAIL（weekly 未命中分组分支，走单篇 `_gen_article_scenes`，groups 为 `["本周回顾"]`）

- [ ] **Step 3: 放宽分支判断**

`backend/app/pipeline/stage2_script.py` 第 185 行：

```python
        if article.metadata.get("aihot_method") == "daily" and sections:
```

改为：

```python
        if article.metadata.get("aihot_method") in ("daily", "weekly") and sections:
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_stage2_multi.py -v`
Expected: PASS（含原有 daily 用例不回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "feat(aihot): weekly 复用 daily 分组分镜路径"
```

---

## Task 5: Runner — 提炼 helper + 失败文案 + Stage1 调用

**Files:**
- Modify: `backend/app/pipeline/runner.py`（新增 `_distill_weekly_if_needed`、`_no_article_message`；改 Stage1 段、失败文案）
- Test: `backend/tests/test_runner_weekly.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_runner_weekly.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_runner_weekly.py -v`
Expected: FAIL（`ImportError`：`_no_article_message` / `_distill_weekly_if_needed` 未定义）

- [ ] **Step 3: 新增两个 helper**

在 `backend/app/pipeline/runner.py` 的 `_summarize_articles` 函数（约 168-180 行）之后插入：

```python
async def _distill_weekly_if_needed(articles, log):
    """weekly article：调文本 AI 把 weekly_items 跨天提炼成 daily_sections（写回 metadata）。
    必须在 _save_articles 之前调用——weekly_items 不会被序列化，只有 daily_sections 会存盘。"""
    if not articles or articles[0].metadata.get("aihot_method") != "weekly":
        return
    from app.pipeline.stage2_script import distill_weekly_sections
    art = articles[0]
    items = art.metadata.get("weekly_items", [])
    log.info("[S1] weekly distill — %d items", len(items))
    tp = _build_text_provider()
    art.metadata["daily_sections"] = await distill_weekly_sections(items, tp)


def _no_article_message(digest_method) -> str:
    if digest_method == "weekly":
        return "上周 AI 日报数据不足，无法生成周报，请改用日报(daily)或动态(items)模式"
    if digest_method == "daily":
        return "今日 AI 日报尚未生成，请稍后再试或切换为动态(items)模式"
    return "No articles collected"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_runner_weekly.py -v`
Expected: PASS

- [ ] **Step 5: 接入 Stage1 段（提炼调用 + 失败文案变量）**

`backend/app/pipeline/runner.py` 第 350 行：

```python
    daily_mode = False
```

改为：

```python
    digest_method = None
```

第 376 行：

```python
            daily_mode = any(sc.get("method") == "daily" for sc in source_configs)
```

改为：

```python
            digest_method = next((sc.get("method") for sc in source_configs
                                  if sc.get("method") in ("daily", "weekly")), None)
```

第 383-385 行（摘要门控块）：

```python
            if articles and articles[0].metadata.get("source_group") != "aihot":
                _update(db, run, progress_detail=f"S1 生成摘要中 (0/{len(articles)})...")
                await _summarize_articles(articles, cfg, run, db, log)
```

改为（追加 weekly 提炼分支）：

```python
            if articles and articles[0].metadata.get("source_group") != "aihot":
                _update(db, run, progress_detail=f"S1 生成摘要中 (0/{len(articles)})...")
                await _summarize_articles(articles, cfg, run, db, log)
            elif articles and articles[0].metadata.get("aihot_method") == "weekly":
                _update(db, run, progress_detail="S1 提炼本周热点中...")
                await _distill_weekly_if_needed(articles, log)
```

第 406 行：

```python
        msg = "今日 AI 日报尚未生成，请稍后再试或切换为动态(items)模式" if daily_mode else "No articles collected"
```

改为：

```python
        msg = _no_article_message(digest_method)
```

- [ ] **Step 6: 跑相关测试确认无回归**

Run: `cd backend && pytest tests/test_runner_weekly.py tests/test_runner_articles.py tests/test_runner_mutual_exclusion.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/pipeline/runner.py backend/tests/test_runner_weekly.py
git commit -m "feat(aihot): runner 接入周报提炼 + digest 失败文案"
```

---

## Task 6: reroll 复用提炼 helper

**Files:**
- Modify: `backend/app/api/pipeline.py:450`（import）、`:468-470`（提炼分支）

> 该改动复用 Task 5 已测试的 `_distill_weekly_if_needed`，无新增单测；由 Step 4 的 import 健全性检查 + 既有 reroll 测试覆盖。

- [ ] **Step 1: 加 import**

`backend/app/api/pipeline.py` 第 450 行：

```python
    from app.pipeline.runner import _summarize_articles, _save_articles, _update as runner_update
```

改为：

```python
    from app.pipeline.runner import _summarize_articles, _save_articles, _update as runner_update, _distill_weekly_if_needed
```

- [ ] **Step 2: 接入提炼分支**

第 468-470 行：

```python
        if articles and articles[0].metadata.get("source_group") != "aihot":
            runner_update(db, run, progress_detail="S1 生成摘要中...")
            await _summarize_articles(articles, cfg, run, db, log)
```

改为：

```python
        if articles and articles[0].metadata.get("source_group") != "aihot":
            runner_update(db, run, progress_detail="S1 生成摘要中...")
            await _summarize_articles(articles, cfg, run, db, log)
        elif articles and articles[0].metadata.get("aihot_method") == "weekly":
            runner_update(db, run, progress_detail="S1 提炼本周热点中...")
            await _distill_weekly_if_needed(articles, log)
```

- [ ] **Step 3: import 健全性 + 全后端测试**

Run: `cd backend && python -c "import app.api.pipeline" && pytest -q`
Expected: 模块导入无 ImportError；全部测试 PASS

- [ ] **Step 4: 提交**

```bash
git add backend/app/api/pipeline.py
git commit -m "feat(aihot): reroll 复用周报提炼 helper"
```

---

## Task 7: 前端 — weekly 模式三处接线

**Files:**
- Modify: `frontend/src/pages/Sources.tsx:167-175`
- Modify: `frontend/src/components/CreateRunDialog.tsx:70-71,214`
- Modify: `frontend/src/components/SourceSummary.tsx:26`

- [ ] **Step 1: Sources 页加 weekly 分段**

`frontend/src/pages/Sources.tsx` 第 167-175 行：

```tsx
        {(["items", "daily"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setConfig({ method: m })}
            className={segItem(method === m)}
          >
            {m === "items" ? "动态" : "日报"}
          </button>
        ))}
```

改为：

```tsx
        {(["items", "daily", "weekly"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setConfig({ method: m })}
            className={segItem(method === m)}
          >
            {m === "items" ? "动态" : m === "daily" ? "日报" : "周报"}
          </button>
        ))}
```

- [ ] **Step 2: CreateRunDialog 泛化 digest 判断**

`frontend/src/components/CreateRunDialog.tsx` 第 70-71 行：

```tsx
  // 仅日报模式忽略时间范围与文章数；动态(items)模式两者仍生效
  const isAihotDaily = aihotMethod === "daily";
```

改为：

```tsx
  // 日报/周报模式忽略时间范围与文章数；动态(items)模式两者仍生效
  const isAihotDigest = aihotMethod === "daily" || aihotMethod === "weekly";
```

第 214 行：

```tsx
        {autoCollect && !isAihotDaily && (
```

改为：

```tsx
        {autoCollect && !isAihotDigest && (
```

- [ ] **Step 3: SourceSummary 加 weekly 标签**

`frontend/src/components/SourceSummary.tsx` 第 26 行：

```tsx
        <span className="text-blue-300">{aihot.name} · {method === "daily" ? "每日日报" : "动态聚合"}</span>
```

改为：

```tsx
        <span className="text-blue-300">{aihot.name} · {method === "daily" ? "每日日报" : method === "weekly" ? "每周周报" : "动态聚合"}</span>
```

- [ ] **Step 4: 构建 + lint 校验**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 无 TS / ESLint 错误，构建成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Sources.tsx frontend/src/components/CreateRunDialog.tsx frontend/src/components/SourceSummary.tsx
git commit -m "feat(aihot): 前端周报模式切换与摘要标签"
```

---

## 收尾验证

- [ ] **全量后端测试**：`cd backend && pytest -q` → 全 PASS
- [ ] **前端构建**：`cd frontend && pnpm build` → 成功
- [ ] **手动冒烟（用户自行执行，勿代启后端）**：前端 Sources 页把 AI HOT 切到「周报」→ 新建任务 → 确认 S1 显示「提炼本周热点中」→ S2 生成主题分组脚本（≤10 分镜）。上周无日报时确认错误文案为「上周 AI 日报数据不足…」。
