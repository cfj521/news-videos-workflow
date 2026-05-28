# AI HOT 信息源分组与方法 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AI HOT 拆成与普通源互斥的独立组，组内支持 items/daily 两种模式（daily 整份日报生成一条汇总视频），并撤掉去重/评分/摘要三个全局开关、改为按组自动分流。

**Architecture:** AI HOT 由单条源 + `config_json.method` 表示；collector 给产出文章打 `metadata.source_group="aihot"` 组标记；Stage1 按该标记分流（普通源始终去重+评分+摘要，AI HOT 走轻量旁路）；daily 渲染成单篇富文本 + Stage2 汇总提示词复用现有单文章管线；互斥由前端组开关 + runner 服务端兜底双保险。

**Tech Stack:** Python (FastAPI, httpx, SQLAlchemy, pytest), React (Vite + TypeScript), 设计文档见 `docs/superpowers/specs/2026-05-28-aihot-source-group-design.md`。

---

## File Structure

**后端：**
- `backend/app/providers/collector/aihot.py`（改写）— items/daily 双分支 + metadata 组标记 + 日报渲染
- `backend/app/pipeline/stage1_collect.py`（改写）— 移除 enable_* 入参；按组标记分流
- `backend/app/pipeline/stage2_script.py`（改）— 新增 daily 汇总提示词 + `style` 参数 + 放宽截断
- `backend/app/pipeline/runner.py`（改）— 移除 enable_* 引用；摘要仅普通源；daily 传 style；互斥兜底；daily 失败文案
- `backend/app/api/pipeline.py`（改）— reroll 路径同步上述采集/摘要改动
- `backend/app/config.py`（改）— `PipelineCfg` 删 3 个 enable_* 字段
- `backend/app/main.py`（改）— 启动时种子 AI HOT 源
- 测试：`backend/tests/test_collector_aihot.py`（新）、`test_stage1.py`/`test_stage2.py`/`test_config.py`（追加）

**前端：**
- `frontend/src/api/client.ts`（改）— `AppSettings.pipeline` 删 3 字段
- `frontend/src/pages/Settings.tsx`（改）— 删 3 个 toggle + EMPTY_SETTINGS
- `frontend/src/pages/Sources.tsx`（改）— 分组渲染 + AI HOT 组卡片（模式/分类/组开关）+ 普通源单条启用联动互斥

---

## Task 1: AIHotCollector — items 模式打组标记 + category 透传

**Files:**
- Modify: `backend/app/providers/collector/aihot.py`
- Test: `backend/tests/test_collector_aihot.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_collector_aihot.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_collector_aihot.py::test_aihot_items_returns_tagged_articles -v`
Expected: FAIL（`metadata["source_group"]` KeyError，因现有 collector 未打标记）

- [ ] **Step 3: 改写 collector 的 items 分支**

把 `backend/app/providers/collector/aihot.py` 整体改写为（本步先实现 items 分支与公共结构，daily 分支在 Task 2 补全）：

```python
import time as _time
from datetime import datetime, timedelta, timezone

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.aihot")

API = "https://aihot.virxact.com/api/public"

TIME_RANGE_HOURS = {"1d": 24, "3d": 72, "7d": 168, "15d": 360, "1m": 720}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsVid/1.0)", "Accept": "application/json"}


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


class AIHotCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        method = source_config.get("method", "items")
        if method == "daily":
            return await self._collect_daily(source_config)
        return await self._collect_items(source_config, time_range, max_items)

    async def _collect_items(self, source_config: dict, time_range: str, max_items: int) -> list[RawArticleData]:
        source_name = source_config.get("name", "AI Hot")
        category = source_config.get("category", "")
        hours = TIME_RANGE_HOURS.get(time_range, 168)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params: dict = {"mode": "selected", "since": since, "take": max_items}
        if category:
            params["category"] = category

        t0 = _time.time()
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/items", params=params)
            resp.raise_for_status()
        data = resp.json()

        articles: list[RawArticleData] = []
        for item in data.get("items", [])[:max_items]:
            articles.append(RawArticleData(
                title=item.get("title", ""),
                content=item.get("summary", ""),
                source_url=item.get("url", ""),
                source_name=item.get("source", source_name),
                published_at=_parse_dt(item.get("publishedAt")),
                category=item.get("category", "ai"),
                summary=item.get("summary", ""),
                aggregator_url="https://aihot.virxact.com",
                metadata={"source_group": "aihot", "aihot_method": "items"},
            ))
        log.info("Collected %d items from AI Hot in %.1fs", len(articles), _time.time() - t0)
        return articles

    async def _collect_daily(self, source_config: dict) -> list[RawArticleData]:
        # 在 Task 2 实现
        raise NotImplementedError
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_collector_aihot.py::test_aihot_items_returns_tagged_articles -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/collector/aihot.py backend/tests/test_collector_aihot.py
git commit -m "feat(aihot): items 模式打组标记并透传 category"
```

---

## Task 2: AIHotCollector — daily 模式渲染单篇 + 404 处理

**Files:**
- Modify: `backend/app/providers/collector/aihot.py`
- Test: `backend/tests/test_collector_aihot.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_collector_aihot.py` 末尾追加：

```python
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


@pytest.mark.asyncio
async def test_aihot_daily_404_returns_empty():
    collector = AIHotCollector()
    with patch("app.providers.collector.aihot.httpx.AsyncClient") as mock_cls:
        _mock_client(mock_cls, {}, status_code=404)
        articles = await collector.collect(source_config={"method": "daily"}, time_range="7d")
    assert articles == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_collector_aihot.py -k daily -v`
Expected: FAIL（`NotImplementedError`）

- [ ] **Step 3: 实现 `_collect_daily`**

把 `aihot.py` 中 `_collect_daily` 的占位替换为：

```python
    async def _collect_daily(self, source_config: dict) -> list[RawArticleData]:
        t0 = _time.time()
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/daily")
            if resp.status_code == 404:
                log.warning("AI Hot daily report not available (404)")
                return []
            resp.raise_for_status()
        report = resp.json()

        date = report.get("date", "")
        lead = report.get("lead") or {}
        lead_title = lead.get("title") or f"今日 AI 日报 {date}"
        lead_para = lead.get("leadParagraph", "")

        lines: list[str] = [lead_para, ""]
        for section in report.get("sections", []):
            lines.append(f"【{section.get('label', '')}】")
            for it in section.get("items", []):
                lines.append(f"「{it.get('title', '')}」{it.get('summary', '')}")
            lines.append("")
        flashes = report.get("flashes", [])
        if flashes:
            lines.append("【快讯】")
            for f in flashes:
                lines.append(f"· {f.get('title', '')}（{f.get('sourceName', '')}）")
        content = "\n".join(lines).strip()

        article = RawArticleData(
            title=lead_title,
            content=content,
            source_url="https://aihot.virxact.com",
            source_name="AI HOT 日报",
            category="ai",
            summary=lead_para,
            aggregator_url="https://aihot.virxact.com",
            metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": date},
        )
        log.info("Collected AI Hot daily (%s, %d chars) in %.1fs", date, len(content), _time.time() - t0)
        return [article]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_collector_aihot.py -v`
Expected: PASS（3 个用例全过）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/collector/aihot.py backend/tests/test_collector_aihot.py
git commit -m "feat(aihot): daily 模式渲染整份日报为单篇文章，404 返回空"
```

---

## Task 3: Stage2 — daily 汇总提示词 + style 参数 + 放宽截断

**Files:**
- Modify: `backend/app/pipeline/stage2_script.py`
- Test: `backend/tests/test_stage2.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_stage2.py` 顶部 import 行改为：

```python
from app.pipeline.stage2_script import DAILY_DIGEST_SYSTEM_PROMPT, SCRIPT_SYSTEM_PROMPT, run_stage2
```

并在文件末尾追加：

```python
@pytest.mark.asyncio
async def test_stage2_daily_uses_digest_prompt():
    mock_text = AsyncMock()
    mock_text.generate.return_value = SAMPLE_SCRIPT_JSON

    article = RawArticleData(
        title="今日 AI 日报",
        content="日报正文内容。" * 800,  # 远超 3000 字，验证放宽截断
        source_url="https://aihot.virxact.com",
        source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily"},
    )

    await run_stage2(article=article, text_provider=mock_text, style="daily")

    kwargs = mock_text.generate.call_args[1]
    assert kwargs["system_prompt"] == DAILY_DIGEST_SYSTEM_PROMPT
    assert len(kwargs["prompt"]) > 4000  # 截断上限放宽到 8000


def test_daily_digest_prompt_exists():
    assert "日报" in DAILY_DIGEST_SYSTEM_PROMPT
    assert "分镜" in DAILY_DIGEST_SYSTEM_PROMPT
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_stage2.py -k daily -v`
Expected: FAIL（`ImportError: DAILY_DIGEST_SYSTEM_PROMPT`）

- [ ] **Step 3: 实现 daily 提示词 + style 参数**

在 `stage2_script.py` 中 `SCRIPT_SYSTEM_PROMPT` 定义之后新增：

```python
DAILY_DIGEST_SYSTEM_PROMPT = """你是一个专业的 AI 资讯日报播报脚本编写者。根据下面整理好的「今日 AI 日报」生成一个汇总播报视频分镜脚本。

输出要求：
1. 纯 JSON 格式，不要包含 markdown 标记
2. 旁白文案用口语化中文，像新闻主播在播报当日 AI 资讯汇总
3. 第一个分镜根据日报开场语作总览引入，最后一个分镜作总结
4. 中间每条重要资讯一个分镜，按重要性挑选，**总分镜数不超过 10 个**
5. 每个分镜 4-8 秒
6. image_prompt 用英文，描述静态画面的构图、色调、风格
7. motion_prompt 用英文，描述镜头运动方向

输出 JSON 结构：
{
  "title": "视频标题（中文，吸引眼球）",
  "description": "视频简介（中文，1-2句话）",
  "tags": ["标签1", "标签2"],
  "scenes": [
    {
      "id": 1,
      "narration": "旁白文本（中文）",
      "image_prompt": "Scene description in English",
      "motion_prompt": "Camera slowly zooms in",
      "duration_hint": 5
    }
  ]
}"""
```

把 `run_stage2` 签名与前半段改为：

```python
async def run_stage2(
    article: RawArticleData,
    text_provider: TextProvider,
    language: str = "zh",
    style: str = "single",
) -> dict:
    log.info("Generating script (style=%s) for: '%s' (%d chars)", style, article.title, len(article.content))
    t0 = time.time()

    if style == "daily":
        system_prompt = DAILY_DIGEST_SYSTEM_PROMPT
        content_limit = 8000
    else:
        system_prompt = SCRIPT_SYSTEM_PROMPT
        content_limit = 3000

    prompt = f"""请为以下内容生成视频分镜脚本：

标题：{article.title}
来源：{article.source_name}
原文：
{article.content[:content_limit]}
"""

    response = await text_provider.generate(prompt=prompt, system_prompt=system_prompt)
```

（`response` 之后的解析逻辑保持不变。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_stage2.py -v`
Expected: PASS（含原有用例不回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2.py
git commit -m "feat(stage2): daily 汇总提示词 + style 参数 + 放宽截断"
```

---

## Task 4: Stage1 — 移除开关，按组标记分流

**Files:**
- Modify: `backend/app/pipeline/stage1_collect.py`
- Test: `backend/tests/test_stage1.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_stage1.py` 末尾追加：

```python
def _aihot_article(title: str, method: str = "items", content: str = "AI 资讯内容") -> RawArticleData:
    return RawArticleData(
        title=title, content=content,
        source_url=f"https://aihot.virxact.com/{title}", source_name="AI HOT",
        metadata={"source_group": "aihot", "aihot_method": method},
    )


@pytest.mark.asyncio
async def test_stage1_aihot_items_skips_dedup():
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = [
        _aihot_article("dup"), _aihot_article("dup"), _aihot_article("a2"),
    ]
    result = await run_stage1(
        sources=[{"name": "AI HOT", "type": "aihot", "url": "https://aihot.virxact.com/api/public"}],
        collectors={"aihot": mock_collector}, time_range="7d", max_articles=5,
    )
    # 跳过去重：重复标题保留
    assert len(result) == 3


@pytest.mark.asyncio
async def test_stage1_aihot_daily_single_passthrough():
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = [_aihot_article("日报", method="daily")]
    result = await run_stage1(
        sources=[{"name": "AI HOT", "type": "aihot", "url": "https://aihot.virxact.com/api/public"}],
        collectors={"aihot": mock_collector}, time_range="7d", max_articles=5,
    )
    assert len(result) == 1
    assert result[0].metadata["aihot_method"] == "daily"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_stage1.py -k aihot -v`
Expected: FAIL（当前 stage1 对 AI HOT 也跑去重，`test_stage1_aihot_items_skips_dedup` 会得到 2 而非 3）

- [ ] **Step 3: 改写 run_stage1**

把 `backend/app/pipeline/stage1_collect.py` 改写为（移除 `enable_dedup`/`enable_scoring` 入参；按组分流）：

```python
from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData
from app.services.compliance import ComplianceService
from app.services.dedup import DedupService
from app.services.scoring import ScoringService

log = get_logger("stage1")


def _filter_compliant(articles: list[RawArticleData]) -> list[RawArticleData]:
    compliance = ComplianceService()
    out: list[RawArticleData] = []
    blocked = 0
    for a in articles:
        if compliance.check(a.content, a.title).status != "blocked":
            out.append(a)
        else:
            blocked += 1
            log.info("Blocked: '%s'", a.title)
    if blocked:
        log.info("Compliance blocked %d articles", blocked)
    return out


async def run_stage1(
    sources: list[dict],
    collectors: dict[str, CollectorProvider],
    time_range: str = "7d",
    max_articles: int = 5,
    history_fingerprints: list[str] | None = None,
) -> list[RawArticleData]:
    all_articles: list[RawArticleData] = []
    for source in sources:
        source_type = source.get("type", "rss")
        source_name = source.get("name", source_type)
        collector = collectors.get(source_type)
        if not collector:
            log.warning("No collector for type '%s' (source: %s), skipping", source_type, source_name)
            continue
        try:
            articles = await collector.collect(source_config=source, time_range=time_range)
            log.info("Source '%s' (%s) → %d articles", source_name, source_type, len(articles))
            all_articles.extend(articles)
        except Exception:
            log.exception("Collector failed for source '%s' (%s)", source_name, source_type)

    log.info("Total raw articles: %d", len(all_articles))

    is_aihot = bool(all_articles) and all_articles[0].metadata.get("source_group") == "aihot"

    # AI HOT：聚合平台已精选/去重，跳过去重与评分，仅做合规与截断
    if is_aihot:
        method = all_articles[0].metadata.get("aihot_method", "items")
        compliant = _filter_compliant(all_articles)
        if method == "daily":
            log.info("AI HOT daily — single-doc passthrough")
            return compliant[:1]
        log.info("AI HOT items — taking top %d (no dedup/scoring)", max_articles)
        return compliant[:max_articles]

    # 普通源：始终去重 → 合规 → 评分挑 top N
    dedup = DedupService()
    deduplicated = dedup.deduplicate(all_articles, history_fingerprints)
    log.info("After dedup: %d (removed %d)", len(deduplicated), len(all_articles) - len(deduplicated))
    compliant = _filter_compliant(deduplicated)
    scoring = ScoringService()
    selected = scoring.select_top(compliant, n=max_articles)
    log.info("Selected top %d articles (from %d compliant)", len(selected), len(compliant))
    return selected
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_stage1.py -v`
Expected: PASS（含原有两个用例不回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage1_collect.py backend/tests/test_stage1.py
git commit -m "feat(stage1): 移除去重/评分开关，按组标记分流（AI HOT 走轻量旁路）"
```

---

## Task 5: runner — 移除开关引用、摘要仅普通源、daily 传 style、互斥兜底、daily 失败文案

**Files:**
- Modify: `backend/app/pipeline/runner.py`（`build_collectors_from_db` 约 107-133；`_run_inner` 约 233-294）

> 本任务改主流水线 runner，逻辑已被 Task 1-4 的单元测试覆盖；改动后用 `pytest` 全量回归 + 类型/导入检查验证。

- [ ] **Step 1: 在 `build_collectors_from_db` 顶部加互斥兜底**

把 `build_collectors_from_db` 开头改为（`_ensure_collector_registry()` 之后插入）：

```python
def build_collectors_from_db(db_sources: list) -> tuple[list[dict], dict]:
    _ensure_collector_registry()

    # 互斥兜底：AI HOT 源与普通源同时 enabled 时，只保留 AI HOT 组
    aihot_sources = [s for s in db_sources if _resolve_collector_type(s) == "aihot"]
    if aihot_sources and len(aihot_sources) != len(db_sources):
        get_logger("runner").warning(
            "Both AI HOT and regular sources enabled — using AI HOT only (mutual exclusion)")
        db_sources = aihot_sources

    source_configs: list[dict] = []
    collectors: dict = {}
    # ...（其余循环逻辑保持不变）
```

- [ ] **Step 2: `_run_inner` — 初始化 daily_mode 并移除 enable_* 引用**

在 `_run_inner` 中 `articles = []` 等初始化处（约 233 行）新增一行：

```python
    articles = []
    daily_mode = False
    script = None
```

把 Stage1 内构建源之后（约 247-248 行 `source_configs, collectors = ...` 之后）加：

```python
        daily_mode = any(sc.get("method") == "daily" for sc in source_configs)
```

把 `run_stage1(...)` 调用（约 253-257 行）改为去掉 enable 入参：

```python
        articles = await run_stage1(
            sources=source_configs, collectors=collectors,
            time_range=run.time_range, max_articles=run.max_articles,
        )
```

把摘要门控（约 262 行）改为仅普通源：

```python
        if articles and articles[0].metadata.get("source_group") != "aihot":
            _update(db, run, progress_detail=f"S1 生成摘要中 (0/{len(articles)})...")
            await _summarize_articles(articles, cfg, run, db, log)
```

- [ ] **Step 3: daily 无文章时给明确文案**

把 `if not articles:` 失败块（约 279-282 行）改为：

```python
    if not articles:
        msg = "今日 AI 日报尚未生成，请稍后再试或切换为动态(items)模式" if daily_mode else "No articles collected"
        _update(db, run, status="failed", error_message=msg, finished_at=datetime.now(timezone.utc))
        log.error(msg)
        return
```

- [ ] **Step 4: Stage2 按 daily 传 style**

把 Stage2 块里 `article = articles[0]`（约 287 行）之后加一行，并改 `run_stage2` 调用（约 294 行）：

```python
        article = articles[0]
        style = "daily" if article.metadata.get("aihot_method") == "daily" else "single"
```

```python
        script = await run_stage2(article=article, text_provider=text_provider,
                                  language=cfg.pipeline.default_language, style=style)
```

- [ ] **Step 5: 全量回归 + 导入检查**

Run: `cd backend && python -c "import app.pipeline.runner" && pytest tests/test_stage1.py tests/test_stage2.py tests/test_collector_aihot.py tests/test_engine.py -v`
Expected: 导入无报错；测试全 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/pipeline/runner.py
git commit -m "feat(runner): 摘要仅普通源、daily 传 style、互斥兜底、daily 失败文案"
```

---

## Task 6: reroll 路径同步采集/摘要改动

**Files:**
- Modify: `backend/app/api/pipeline.py:366-373`（`_reroll_articles_async`）

- [ ] **Step 1: 同步去掉 enable_* 并改摘要门控**

把 `_reroll_articles_async` 里的 run_stage1 调用与摘要门控（约 366-373 行）改为：

```python
        articles = await run_stage1(
            sources=source_configs, collectors=collectors,
            time_range=run.time_range, max_articles=run.max_articles,
        )
        if articles and articles[0].metadata.get("source_group") != "aihot":
            runner_update(db, run, progress_detail="S1 生成摘要中...")
            await _summarize_articles(articles, cfg, run, db, log)
```

- [ ] **Step 2: 导入检查**

Run: `cd backend && python -c "import app.api.pipeline"`
Expected: 无报错

- [ ] **Step 3: 提交**

```bash
git add backend/app/api/pipeline.py
git commit -m "fix(pipeline): reroll 路径同步去除开关、摘要仅普通源"
```

---

## Task 7: config — 移除三个 enable_* 字段

**Files:**
- Modify: `backend/app/config.py:68-70`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_config.py` 末尾追加：

```python
def test_pipeline_cfg_has_no_legacy_toggles():
    from app.config import PipelineCfg
    cfg = PipelineCfg()
    assert not hasattr(cfg, "enable_dedup")
    assert not hasattr(cfg, "enable_scoring")
    assert not hasattr(cfg, "enable_summary")
    assert hasattr(cfg, "dedup_lookback")  # 保留
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_config.py::test_pipeline_cfg_has_no_legacy_toggles -v`
Expected: FAIL

- [ ] **Step 3: 删除 PipelineCfg 中的 3 个字段**

把 `config.py` 的 `PipelineCfg`（约 62-70 行）改为：

```python
class PipelineCfg(BaseModel):
    default_time_range: str = "7d"
    default_max_articles: int = 5
    default_video_route: str = "hyperframes"
    default_language: str = "zh"
    dedup_lookback: str = "30d"
```

> `SummaryCfg.enabled`（行 54）为死字段（前端未暴露、runner 未用），本计划不动它以免牵连 client.ts summary 类型；如需清理另开任务。

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

Run: `cd backend && pytest tests/test_config.py -v && pytest -q`
Expected: PASS（确认无其他测试引用被删字段）

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "refactor(config): 移除 enable_summary/dedup/scoring 开关"
```

---

## Task 8: 启动时种子 AI HOT 源

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: 加种子函数并在 startup 调用**

在 `main.py` 顶部 import 区下方新增：

```python
def _seed_aihot_source(factory) -> None:
    import json

    from app.models.news_source import NewsSource

    db = factory()
    try:
        exists = db.query(NewsSource).filter(NewsSource.url.like("%aihot.virxact.com%")).first()
        if exists:
            return
        db.add(NewsSource(
            name="AI HOT", type="api", url="https://aihot.virxact.com/api/public",
            category="ai", language="zh", priority=1, enabled=False, tier="standard",
            config_json=json.dumps({"provider": "aihot", "method": "items"}),
        ))
        db.commit()
    finally:
        db.close()
```

把 `on_startup` 改为：

```python
    @app.on_event("startup")
    def on_startup():
        setup_global_logger()
        get_settings().ensure_data_dirs()
        factory = get_session_factory()
        Base.metadata.create_all(bind=factory.kw["bind"])
        _seed_aihot_source(factory)
```

- [ ] **Step 2: 导入检查**

Run: `cd backend && python -c "import app.main"`
Expected: 无报错

- [ ] **Step 3: 提交**

```bash
git add backend/app/main.py
git commit -m "feat: 启动时种子 AI HOT 源（默认禁用，items 模式）"
```

---

## Task 9: 前端 — 移除 Settings 三个开关

**Files:**
- Modify: `frontend/src/api/client.ts:23`
- Modify: `frontend/src/pages/Settings.tsx:245,413-427`

- [ ] **Step 1: client.ts 删类型字段**

把 `AppSettings.pipeline`（行 23）改为：

```ts
  pipeline: { default_time_range: string; default_max_articles: number; default_video_route: string; default_language: string; dedup_lookback: string };
```

- [ ] **Step 2: Settings.tsx 删 EMPTY_SETTINGS 字段**

把 `EMPTY_SETTINGS.pipeline`（行 245）改为：

```ts
  pipeline: { default_time_range: "7d", default_max_articles: 5, default_video_route: "hyperframes", default_language: "zh", dedup_lookback: "30d" },
```

- [ ] **Step 3: Settings.tsx 删 3 个 toggle Field**

删除"流水线默认值" Section 里的三块（约 413-427 行）：`文章去重`、`评分排序`、`摘要生成` 对应的三个 `<Field>...</Field>`。

- [ ] **Step 4: 类型检查**

Run: `cd frontend && pnpm build`
Expected: 构建成功，无 TS 报错（确认无其他文件引用被删字段）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Settings.tsx
git commit -m "refactor(settings): 移除去重/评分/摘要三个开关 UI 与类型"
```

---

## Task 10: 前端 Sources 页 — 分组渲染 + AI HOT 组卡片 + 互斥联动

**Files:**
- Modify: `frontend/src/pages/Sources.tsx`

- [ ] **Step 1: 加 import 与判定/解析 helper**

在 `Sources.tsx` 顶部 import 区加：

```tsx
import { Select } from "../components/Select";
```

在 `SortKey`/`SortDir` 类型定义之后加：

```tsx
function isAihotSource(s: NewsSource): boolean {
  if (s.config_json) {
    try { if (JSON.parse(s.config_json).provider === "aihot") return true; } catch { /* ignore */ }
  }
  return s.url.includes("aihot.virxact.com");
}

function parseConfig(json: string | null): Record<string, unknown> {
  if (!json) return {};
  try { return JSON.parse(json) as Record<string, unknown>; } catch { return {}; }
}

const AIHOT_CATEGORIES = [
  { value: "", label: "全部分类" },
  { value: "ai-models", label: "模型" },
  { value: "ai-products", label: "产品" },
  { value: "industry", label: "行业" },
  { value: "paper", label: "论文" },
  { value: "tip", label: "技巧" },
];
```

- [ ] **Step 2: 加 AIHotGroupCard 组件**

在 `SourcesPage` 函数定义之前加：

```tsx
function AIHotGroupCard({ source, customIds, onChange }: {
  source: NewsSource;
  customIds: number[];
  onChange: () => void;
}) {
  const cfg = parseConfig(source.config_json);
  const method = (cfg.method as string) ?? "items";
  const category = (cfg.category as string) ?? "";

  const setConfig = async (patch: Record<string, unknown>) => {
    await api.sources.update(source.id, { config_json: JSON.stringify({ ...cfg, ...patch }) });
    onChange();
  };

  const toggleGroup = async () => {
    if (source.enabled) {
      await api.sources.update(source.id, { enabled: false });
    } else {
      if (customIds.length) await api.sources.batch({ ids: customIds, enabled: false });
      await api.sources.update(source.id, { enabled: true });
    }
    onChange();
  };

  return (
    <div className={`${cardCls} p-5 mb-4`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold">AI HOT 聚合</h2>
          <p className="text-xs text-white/30 mt-0.5">聚合精选 AI 资讯 · 启用后与自定义源互斥</p>
        </div>
        <button onClick={toggleGroup} className={toggleCls(source.enabled)}>
          <span className={toggleThumbCls(source.enabled)} />
        </button>
      </div>
      <div className="flex items-center gap-2 mb-3">
        {(["items", "daily"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setConfig({ method: m })}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
              method === m
                ? "bg-blue-500/15 border-blue-500/30 text-blue-300"
                : "bg-white/[0.03] border-white/[0.06] text-white/40 hover:text-white/60"
            }`}
          >
            {m === "items" ? "动态" : "日报"}
          </button>
        ))}
      </div>
      {method === "items" && (
        <div className="w-48">
          <Select value={category} onChange={(v) => setConfig({ category: v })} options={AIHOT_CATEGORIES} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: SourcesPage 拆分组渲染 + 单条启用联动互斥**

在 `SourcesPage` 内，把 `const sorted = ...` 之后加分组：

```tsx
  const aihotSource = sources?.find(isAihotSource);
  const customSources = sorted.filter((s) => !isAihotSource(s));
  const customIds = (sources ?? []).filter((s) => !isAihotSource(s)).map((s) => s.id);
```

把 `toggleSource` 改为启用普通源时联动关掉 AI HOT：

```tsx
  const toggleSource = async (e: React.MouseEvent, source: NewsSource) => {
    e.stopPropagation();
    const enabling = !source.enabled;
    await api.sources.update(source.id, { enabled: enabling });
    if (enabling && aihotSource?.enabled) {
      await api.sources.update(aihotSource.id, { enabled: false });
    }
    mutate();
  };
```

把拖拽/表格里用到的列表数据从 `sorted` 换成 `customSources`：
- `useDragReorder(sorted, ...)` → `useDragReorder(customSources, ...)`
- `sorted.map((source, idx) => ...)` → `customSources.map((source, idx) => ...)`
- 空态判断 `sorted.length === 0` → `customSources.length === 0`

在表格容器（`<div className={`${cardCls} overflow-hidden`}>`）之前插入 AI HOT 卡片：

```tsx
      {aihotSource && (
        <AIHotGroupCard source={aihotSource} customIds={customIds} onChange={mutate} />
      )}
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && pnpm build`
Expected: 构建成功，无 TS 报错

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Sources.tsx
git commit -m "feat(sources): AI HOT 组卡片（模式/分类）+ 分组渲染 + 互斥联动"
```

---

## 验收

- [ ] 后端全量测试通过：`cd backend && pytest -q`
- [ ] 前端构建通过：`cd frontend && pnpm build`
- [ ] 手动核对（用户自行启动服务）：源管理页出现 AI HOT 组卡片；切到 daily 模式跑一次 run，产出一条日报汇总视频；启用 AI HOT 后普通源被禁用，反之亦然；Settings 页不再有去重/评分/摘要开关。
