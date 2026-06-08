# Plan 3 — news_sources.yaml 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把信息源（`NewsSource` 表）+ 搜索 key（config.yaml `collectors`）迁到 `news_sources.yaml`，slug 作主键；CRUD 文件化；run.source_ids int→slug（含历史改写）；历史源全失效时报错而非静默回退 HN。

**Architecture:** 复用 `store/_io.py` + `store/_slug.py`。新增 `store/sources_store.py`（SourceData + CRUD + batch + search_keys）。`api/sources.py` 改调 store；runner 的 `_resolve_collector_type`/`build_collectors_from_db`/`_sources_for_run`/`_collectors_for_run` 改吃 SourceData（`.config` dict）并加降级语义。config.py 把 `collectors` 透明路由到 sources_store.search_keys（设置页零改动）。迁移 news_sources + collectors → yaml，并改写历史 run.source_ids。删 NewsSource 模型。前端 NewsSource.id→string。

**Tech Stack:** Python 3.12 / FastAPI / pydantic / PyYAML / pytest；前端 React/TS。

**整体规则:** 仓库根 `news_sources.yaml`（gitignore）。后端 `cd backend`。完成后 `pytest` 全绿、touched 文件 ruff 干净。Plan 1/2 已完成。

**前置事实（已核实）:**
- `_sources_for_run(db, run)`（runner.py:109）按 `run.source_ids`(JSON int) 查 `NewsSource`；空回退 enabled。
- `_resolve_collector_type(src)`（runner.py:84）读 `src.config_json`(string) 取 provider；`build_collectors_from_db`（runner.py:124）读 `src.name/.type/.url/.config_json`。两者兼容 ORM(hasattr) 与 dict(.get)。
- `_collectors_for_run`（runner.py:183）：aihot_config 非空→AI HOT 单源；否则 `_sources_for_run` 过滤掉 aihot；空→`build_collectors`(默认 HN)。
- reroll（api/pipeline.py:607）调 `_collectors_for_run`。
- `NewsSource` 字段：id/name/type/url/category/language/priority/enabled/tier/pinned/config_json。
- `collectors`（config.py `CollectorsCfg`：tavily_key/brave_key/serper_key）**运行时未接通**（搬家不改行为）。
- `isAihotSource`（前端 types）判 config_json.provider=="aihot" 或 url 含 aihot.virxact.com。
- 前端源侧：`sourceIds: Set<number>|null`、`toggleSource(id:number)`、`toggleSource(Number(v))`、SourceSummary `ids:number[]`+`ids.includes(s.id)`。**`CreateRunDialog.tsx:118` 的 `Number(dep)` 是 stage 依赖，勿动。**

---

## 文件结构

- **新增** `backend/app/store/sources_store.py` — `SourceData` + `NEWS_SOURCES_PATH` + `list_sources/get_source/create_source/update_source/delete_source/batch_update` + `load_search_keys/save_search_keys`。
- **修改** `backend/app/schemas/source.py` — id→slug；Create 增 slug。
- **修改** `backend/app/api/sources.py` — CRUD/batch 改 store + search_keys 子路由。
- **修改** `backend/app/pipeline/runner.py` — `_resolve_collector_type`/`build_collectors_from_db`/`_sources_for_run`/`_collectors_for_run` 改吃 SourceData + 降级语义。
- **修改** `backend/app/config.py` — `collectors` 透明路由到 sources_store.search_keys。
- **修改** `backend/app/store/migrate.py` — 增 news_sources + collectors 迁移 + 改写 run.source_ids。
- **修改** `backend/app/main.py` — 串入 sources 迁移。
- **修改** `backend/tests/conftest.py` — autouse 隔离 NEWS_SOURCES_PATH。
- **删除** `backend/app/models/news_source.py` + `models/__init__.py` import。
- **前端** `types/index.ts`（NewsSource.id→string，isAihotSource 不变）、`api/client.ts`（sources id/batch string）、`components/SourceSummary.tsx`、`components/CreateRunDialog.tsx`（源侧 string）、`pages/Sources.tsx`。
- **测试** `test_sources_store.py`、`test_api_sources.py`、`test_migrate_sources.py`、改 `test_collectors_for_run.py`/`test_sources_for_run.py`/`test_api_pipeline.py`。

---

## Task 1: sources_store

**Files:**
- Create: `backend/app/store/sources_store.py`
- Test: `backend/tests/test_sources_store.py`

news_sources.yaml 结构：
```yaml
search_keys: {tavily_key: '', brave_key: '', serper_key: ''}
sources:
  hacker_news:
    name: Hacker News
    type: api
    url: https://hn.algolia.com/api/v1/
    category: general
    language: en
    priority: 5
    enabled: true
    tier: free
    pinned: false
    config: {}
```

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_sources_store.py`:

```python
import pytest

import app.store.sources_store as ss


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")


def test_list_empty():
    assert ss.list_sources() == []


def test_create_generates_slug():
    s = ss.create_source(name="Hacker News", type="api", url="https://hn.algolia.com/api/v1/")
    assert s.slug == "hacker_news"
    assert s.name == "Hacker News" and s.type == "api"
    assert s.enabled is True and s.priority == 5 and s.category == "general"
    assert s.config == {}


def test_create_chinese_name_falls_back_to_type():
    s = ss.create_source(name="机器之心", type="rss", url="https://x.com/feed")
    assert s.slug == "rss"


def test_create_collision():
    ss.create_source(name="News", type="rss", url="u1")
    s2 = ss.create_source(name="News", type="rss", url="u2")
    assert s2.slug == "news_1"


def test_get_update_delete():
    ss.create_source(name="HN", type="api", url="u", config={"provider": "aihot"})
    assert ss.get_source("hn").config["provider"] == "aihot"
    ss.update_source("hn", {"enabled": False, "priority": 9})
    got = ss.get_source("hn")
    assert got.enabled is False and got.priority == 9
    assert ss.delete_source("hn") is True
    assert ss.get_source("hn") is None


def test_update_missing_returns_none():
    assert ss.update_source("nope", {"enabled": False}) is None


def test_batch_update_enabled_and_priority():
    ss.create_source(name="A", type="rss", url="a", slug="a")
    ss.create_source(name="B", type="rss", url="b", slug="b")
    updated = ss.batch_update(["a", "b"], enabled=False, priority_map={"a": 3})
    assert len(updated) == 2
    assert ss.get_source("a").enabled is False and ss.get_source("a").priority == 3
    assert ss.get_source("b").enabled is False


def test_search_keys_roundtrip():
    assert ss.load_search_keys() == {"tavily_key": "", "brave_key": "", "serper_key": ""}
    ss.save_search_keys({"tavily_key": "tk", "brave_key": "", "serper_key": ""})
    assert ss.load_search_keys()["tavily_key"] == "tk"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_sources_store.py -v`
Expected: FAIL (AttributeError NEWS_SOURCES_PATH)

- [ ] **Step 3: 实现 `sources_store.py`**

Create `backend/app/store/sources_store.py`:

```python
"""news_sources.yaml 读写：信息源（slug 主键）+ 搜索 key。

结构：
    search_keys: {tavily_key, brave_key, serper_key}
    sources:
      <slug>: {name, type, url, category, language, priority, enabled, tier, pinned, config: {...}}
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.store import _io
from app.store._slug import slugify, unique_slug

NEWS_SOURCES_PATH = Path(__file__).resolve().parents[3] / "news_sources.yaml"

_DEFAULT_SEARCH_KEYS = {"tavily_key": "", "brave_key": "", "serper_key": ""}

_UPDATABLE = ("name", "type", "url", "category", "language", "priority", "enabled", "tier", "pinned", "config")


class SourceData(BaseModel):
    """单个信息源。slug 为主键（YAML key），config 为内联 dict（原 config_json）。"""
    slug: str
    name: str
    type: str
    url: str = ""
    category: str = "general"
    language: str = "en"
    priority: int = 5
    enabled: bool = True
    tier: str = "free"
    pinned: bool = False
    config: dict = {}


def _read() -> dict:
    return _io.load_yaml(NEWS_SOURCES_PATH)


def list_sources() -> list[SourceData]:
    raw = _read().get("sources", {}) or {}
    out = [SourceData(slug=slug, **(slot or {})) for slug, slot in raw.items()]
    out.sort(key=lambda s: s.priority)
    return out


def get_source(slug: str) -> SourceData | None:
    slot = (_read().get("sources", {}) or {}).get(slug)
    return SourceData(slug=slug, **slot) if slot else None


def create_source(*, name: str, type: str, url: str = "", category: str = "general",
                  language: str = "en", priority: int = 5, enabled: bool = True,
                  tier: str = "free", pinned: bool = False, config: dict | None = None,
                  slug: str | None = None) -> SourceData:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.setdefault("sources", {})
        existing = set(sources.keys())
        new_slug = slug or unique_slug(slugify(name), existing, type or "source")
        if new_slug in existing:
            new_slug = unique_slug(new_slug, existing, type or "source")
        rec = {"name": name, "type": type, "url": url, "category": category,
               "language": language, "priority": priority, "enabled": enabled,
               "tier": tier, "pinned": pinned, "config": config or {}}
        sources[new_slug] = rec
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return SourceData(slug=new_slug, **rec)


def update_source(slug: str, patch: dict) -> SourceData | None:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.get("sources", {}) or {}
        if slug not in sources:
            return None
        slot = sources[slug]
        for k in _UPDATABLE:
            if k in patch and patch[k] is not None:
                slot[k] = patch[k]
        sources[slug] = slot
        data["sources"] = sources
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return SourceData(slug=slug, **slot)


def delete_source(slug: str) -> bool:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.get("sources", {}) or {}
        if slug not in sources:
            return False
        del sources[slug]
        data["sources"] = sources
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return True


def batch_update(slugs: list[str], *, enabled: bool | None = None,
                 pinned: bool | None = None, priority_map: dict[str, int] | None = None) -> list[SourceData]:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.get("sources", {}) or {}
        changed: list[SourceData] = []
        for slug in slugs:
            if slug not in sources:
                continue
            slot = sources[slug]
            if enabled is not None:
                slot["enabled"] = enabled
            if pinned is not None:
                slot["pinned"] = pinned
            if priority_map and slug in priority_map:
                slot["priority"] = priority_map[slug]
            sources[slug] = slot
            changed.append(SourceData(slug=slug, **slot))
        data["sources"] = sources
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return changed


def load_search_keys() -> dict:
    sk = _read().get("search_keys") or {}
    return {**_DEFAULT_SEARCH_KEYS, **sk}


def save_search_keys(keys: dict) -> None:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        data["search_keys"] = {**_DEFAULT_SEARCH_KEYS, **(keys or {})}
        _io.save_yaml(NEWS_SOURCES_PATH, data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_sources_store.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: ruff + 提交**

```bash
cd backend && ruff check app/store/sources_store.py tests/test_sources_store.py
git add backend/app/store/sources_store.py backend/tests/test_sources_store.py
git commit -m "feat(store): sources_store 读写 news_sources.yaml（slug 主键 + search_keys）"
```

---

## Task 2: schemas + api/sources.py 改用 sources_store

现状 `api/sources.py`：list/create/patch/delete/batch 走 DB；另有 `aihot/weeks`、`aihot/days` 两个只读端点（不动）。
改为：id→slug；config↔config_json 转换；batch 用 slug；新增 search_keys 子路由（供设置页/未来用，本任务即建）。

**Files:**
- Modify: `backend/app/schemas/source.py`
- Modify: `backend/app/api/sources.py`
- Test: `backend/tests/test_api_sources.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_api_sources.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

import app.store.sources_store as ss
from app.auth import get_current_user
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_create_returns_slug_id(client):
    r = client.post("/api/sources/", json={"name": "Hacker News", "type": "api",
                                           "url": "https://hn.algolia.com/api/v1/"})
    assert r.status_code == 201
    assert r.json()["id"] == "hacker_news"


def test_list_patch_delete(client):
    client.post("/api/sources/", json={"name": "HN", "type": "api", "url": "u"})
    assert len(client.get("/api/sources/").json()) == 1
    assert client.patch("/api/sources/hn", json={"enabled": False}).json()["enabled"] is False
    assert client.delete("/api/sources/hn").status_code == 204
    assert client.get("/api/sources/").json() == []


def test_patch_missing_404(client):
    assert client.patch("/api/sources/nope", json={"enabled": False}).status_code == 404


def test_config_json_roundtrip(client):
    r = client.post("/api/sources/", json={"name": "AIHot", "type": "api", "url": "u",
                                           "config_json": json.dumps({"provider": "aihot"})})
    assert json.loads(r.json()["config_json"])["provider"] == "aihot"


def test_batch_update(client):
    a = client.post("/api/sources/", json={"name": "A", "type": "rss", "url": "a"}).json()["id"]
    b = client.post("/api/sources/", json={"name": "B", "type": "rss", "url": "b"}).json()["id"]
    r = client.post("/api/sources/batch", json={"ids": [a, b], "enabled": False})
    assert r.status_code == 200
    assert all(s["enabled"] is False for s in r.json())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_api_sources.py -v`
Expected: FAIL.

- [ ] **Step 3: 改 schemas** — Replace `backend/app/schemas/source.py` with:

```python
from pydantic import BaseModel


class NewsSourceCreate(BaseModel):
    name: str
    type: str
    url: str = ""
    category: str = "general"
    language: str = "en"
    priority: int = 5
    enabled: bool = True
    pinned: bool = False
    tier: str = "free"
    config_json: str | None = None
    slug: str | None = None


class NewsSourceRead(BaseModel):
    id: str            # slug
    name: str
    type: str
    url: str
    category: str
    language: str
    priority: int
    enabled: bool
    pinned: bool
    tier: str
    config_json: str | None


class NewsSourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    url: str | None = None
    category: str | None = None
    language: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    pinned: bool | None = None
    config_json: str | None = None
```

- [ ] **Step 4: 改 api/sources.py** — Replace `backend/app/api/sources.py` with (保留 aihot/weeks、aihot/days 只读端点不变):

```python
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.logging import get_logger
from app.schemas.source import NewsSourceCreate, NewsSourceRead, NewsSourceUpdate
from app.store import sources_store

log = get_logger("api.sources")
router = APIRouter(prefix="/api/sources", tags=["sources"])


def _to_read(s) -> NewsSourceRead:
    return NewsSourceRead(
        id=s.slug, name=s.name, type=s.type, url=s.url, category=s.category,
        language=s.language, priority=s.priority, enabled=s.enabled, pinned=s.pinned,
        tier=s.tier, config_json=json.dumps(s.config, ensure_ascii=False) if s.config else None,
    )


def _parse_config(config_json: str | None) -> dict:
    if not config_json:
        return {}
    try:
        return json.loads(config_json)
    except (ValueError, TypeError):
        return {}


@router.get("/", response_model=list[NewsSourceRead])
def list_sources():
    return [_to_read(s) for s in sources_store.list_sources()]


@router.get("/aihot/weeks")
async def aihot_weeks():
    from app.providers.collector.aihot import list_available_weeks
    try:
        return await list_available_weeks()
    except Exception as e:
        log.warning("Failed to list AI HOT weeks: %s", e)
        return []


@router.get("/aihot/days")
async def aihot_days():
    from app.providers.collector.aihot import list_available_days
    try:
        return await list_available_days()
    except Exception as e:
        log.warning("Failed to list AI HOT days: %s", e)
        return []


@router.post("/", response_model=NewsSourceRead, status_code=201)
def create_source(body: NewsSourceCreate):
    s = sources_store.create_source(
        name=body.name, type=body.type, url=body.url, category=body.category,
        language=body.language, priority=body.priority, enabled=body.enabled,
        pinned=body.pinned, tier=body.tier, config=_parse_config(body.config_json), slug=body.slug,
    )
    log.info("Created source '%s' (%s)", s.slug, s.type)
    return _to_read(s)


@router.patch("/{slug}", response_model=NewsSourceRead)
def update_source(slug: str, body: NewsSourceUpdate):
    patch: dict = body.model_dump(exclude_unset=True)
    if "config_json" in patch:
        patch["config"] = _parse_config(patch.pop("config_json"))
    s = sources_store.update_source(slug, patch)
    if s is None:
        raise HTTPException(status_code=404, detail="Source not found")
    log.info("Updated source '%s'", slug)
    return _to_read(s)


@router.delete("/{slug}", status_code=204)
def delete_source(slug: str):
    if not sources_store.delete_source(slug):
        raise HTTPException(status_code=404, detail="Source not found")
    log.info("Deleted source '%s'", slug)


class BatchUpdateBody(BaseModel):
    ids: list[str]
    enabled: bool | None = None
    pinned: bool | None = None
    priority_map: dict[str, int] | None = None


@router.post("/batch", response_model=list[NewsSourceRead])
def batch_update(body: BatchUpdateBody):
    changed = sources_store.batch_update(
        body.ids, enabled=body.enabled, pinned=body.pinned, priority_map=body.priority_map)
    log.info("Batch updated %d sources", len(changed))
    return [_to_read(s) for s in changed]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_api_sources.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: ruff + 提交**

```bash
cd backend && ruff check app/schemas/source.py app/api/sources.py tests/test_api_sources.py
git add backend/app/schemas/source.py backend/app/api/sources.py backend/tests/test_api_sources.py
git commit -m "feat(sources): CRUD/batch 改 sources_store（id→slug，config dict↔json）"
```

---

## Task 3: runner 取数改 sources_store（slug）+ 降级语义

`_resolve_collector_type` 与 `build_collectors_from_db` 改吃 SourceData（用 `.config` dict，不再 `.config_json`）。`_sources_for_run` 改读 sources_store（slug）。`_collectors_for_run` 加降级：run 有 source_ids 但全部解析不到非 aihot 源 → 抛 `ValueError`（"所选信息源已不存在，请重新选择"），不再静默回退 HN（仅"从未选源"才回退 HN）。

**Files:**
- Modify: `backend/app/pipeline/runner.py`
- Test: `backend/tests/test_collectors_for_run.py`（改写）、`backend/tests/test_sources_for_run.py`（改写，若存在）

- [ ] **Step 1: 改写测试**

Replace `backend/tests/test_collectors_for_run.py` with:

```python
import json

import pytest

import app.pipeline.runner as runner
import app.store.sources_store as ss


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")


class _Run:
    def __init__(self, source_ids=None, aihot_config=None):
        self.source_ids = json.dumps(source_ids) if source_ids is not None else None
        self.aihot_config = json.dumps(aihot_config) if aihot_config is not None else None


def test_aihot_config_uses_aihot_source():
    run = _Run(aihot_config={"method": "daily"})
    cfgs, collectors = runner._collectors_for_run(None, run, None)
    assert cfgs[0]["type"] == "aihot" and "aihot" in collectors


def test_selected_slugs_build_those_sources():
    ss.create_source(name="HN", type="api", url="https://hn.algolia.com/api/v1/", slug="hn")
    ss.create_source(name="RSS One", type="rss", url="https://x.com/feed", slug="rss_one")
    run = _Run(source_ids=["rss_one"])
    cfgs, collectors = runner._collectors_for_run(None, run, None)
    names = [c["name"] for c in cfgs]
    assert "RSS One" in names and "HN" not in names


def test_no_source_ids_falls_back_to_hn():
    run = _Run()
    cfgs, collectors = runner._collectors_for_run(None, run, None)
    assert any(c["type"] == "hackernews_algolia" for c in cfgs)


def test_all_selected_sources_missing_raises():
    # run 选了 source_ids，但 store 里没有对应 slug → 报错而非回退 HN
    run = _Run(source_ids=["ghost_slug"])
    with pytest.raises(ValueError):
        runner._collectors_for_run(None, run, None)


def test_aihot_source_excluded_from_custom():
    ss.create_source(name="AIHot", type="api", url="u", slug="aihot_src", config={"provider": "aihot"})
    ss.create_source(name="RSS", type="rss", url="https://x.com/feed", slug="rss_one")
    run = _Run(source_ids=["aihot_src", "rss_one"])
    cfgs, _ = runner._collectors_for_run(None, run, None)
    names = [c["name"] for c in cfgs]
    assert "RSS" in names and "AIHot" not in names
```

If `backend/tests/test_sources_for_run.py` exists, delete it (`git rm`) — its behavior is now covered by test_collectors_for_run.py + test_sources_store.py.

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_collectors_for_run.py -v`
Expected: FAIL (still uses db.query(NewsSource) / no degrade).

- [ ] **Step 3: 改 `_resolve_collector_type`**

In `backend/app/pipeline/runner.py` replace `_resolve_collector_type` so it reads `.config` dict (SourceData) OR config_json (legacy dict). Final:

```python
def _resolve_collector_type(src) -> str:
    """Determine collector key: config.provider > URL hint > type field."""
    config = getattr(src, "config", None)
    if config is None and isinstance(src, dict):
        config = src.get("config")
    provider = (config or {}).get("provider", "") if isinstance(config, dict) else ""
    if provider and provider in TYPE_TO_COLLECTOR:
        return provider

    url = (getattr(src, "url", None) or (src.get("url", "") if isinstance(src, dict) else "")).lower()
    for pattern, collector_key in _URL_HINTS:
        if pattern in url:
            return collector_key

    src_type = getattr(src, "type", None) or (src.get("type", "") if isinstance(src, dict) else "")
    if src_type in TYPE_TO_COLLECTOR:
        return src_type
    type_map = {"api": "hackernews_algolia", "search": "duckduckgo", "scrape": "scraping"}
    return type_map.get(src_type, "")
```

- [ ] **Step 4: 改 `build_collectors_from_db`**

In `backend/app/pipeline/runner.py` replace the per-source cfg building so it reads `.config` dict (SourceData) instead of `.config_json`. The loop body becomes:

```python
    for src in db_sources:
        collector_key = _resolve_collector_type(src)
        if not collector_key or collector_key not in TYPE_TO_COLLECTOR:
            get_logger("runner").warning("Skipping source '%s': no collector for type '%s'",
                                        getattr(src, "name", "?"), getattr(src, "type", "?"))
            continue
        if collector_key not in collectors:
            collectors[collector_key] = TYPE_TO_COLLECTOR[collector_key]()
        cfg: dict = {"name": getattr(src, "name", ""), "type": collector_key,
                     "url": getattr(src, "url", "")}
        src_config = getattr(src, "config", None)
        if isinstance(src_config, dict):
            cfg.update(src_config)
        source_configs.append(cfg)
```

(Keep the aihot mutual-exclusion block at the top of `build_collectors_from_db` unchanged — it uses `_resolve_collector_type` which now handles SourceData.)

- [ ] **Step 5: 改 `_sources_for_run` + `_collectors_for_run`**

Replace both functions in `backend/app/pipeline/runner.py`:

```python
def _sources_for_run(db, run) -> list:
    """按 run.source_ids（slug 列表）取 SourceData；为空/无则回退所有 enabled。"""
    from app.store import sources_store
    slugs: list = []
    raw = getattr(run, "source_ids", None)
    if raw:
        try:
            slugs = [s for s in (json.loads(raw) or []) if isinstance(s, str)]
        except Exception:
            slugs = []
    all_sources = sources_store.list_sources()
    if slugs:
        by_slug = {s.slug: s for s in all_sources}
        return [by_slug[s] for s in slugs if s in by_slug]
    return [s for s in all_sources if s.enabled]


def _collectors_for_run(db, run, settings) -> tuple[list[dict], dict]:
    """按 run 选模式返回 (source_configs, collectors)。
    - aihot_config 非空 → AI HOT 单源（硬编码）。
    - 否则 → run.source_ids 选中的非 aihot 源；空 source_ids → 默认 HN；
      有 source_ids 但全部失效 → 抛 ValueError（不静默回退）。
    """
    _ensure_collector_registry()
    raw = getattr(run, "aihot_config", None)
    if raw:
        try:
            aihot = json.loads(raw) or {}
        except Exception:
            aihot = {}
        if aihot:
            return [_aihot_source_config(aihot)], {"aihot": TYPE_TO_COLLECTOR["aihot"]()}

    raw_ids = getattr(run, "source_ids", None)
    requested: list = []
    if raw_ids:
        try:
            requested = [s for s in (json.loads(raw_ids) or []) if isinstance(s, str)]
        except Exception:
            requested = []

    db_sources = [s for s in _sources_for_run(db, run) if _resolve_collector_type(s) != "aihot"]
    if db_sources:
        return build_collectors_from_db(db_sources)
    if requested:
        raise ValueError("所选信息源已不存在，请在「新建任务窗口」重新选择信息源")
    return build_collectors(settings)
```

- [ ] **Step 6: 跑测试 + 回归**

Run: `cd backend && pytest tests/test_collectors_for_run.py -v` → 5 passed.
Run: `cd backend && pytest -q` → 报告 count；test_api_pipeline.py 若有 source_ids 整数断言会失败（Task 后续/本步若失败记录，整数→slug 由 Task 5 迁移 + 该测试本身需改：若失败，把 test_api_pipeline.py 里 reroll/source 相关用例的整数 id 改为 slug 字符串并让其用 sources_store 建源——在本任务内修，因为它直接因 slug 化失败）。

- [ ] **Step 7: ruff + 提交**

```bash
cd backend && ruff check app/pipeline/runner.py tests/test_collectors_for_run.py
git add -A backend/app/pipeline/runner.py backend/tests/
git commit -m "feat(runner): 信息源取数改 sources_store（slug）+ 源全失效报错降级"
```

---

## Task 4: config.py 把 collectors 路由到 sources_store + conftest 隔离

与 providers/youtube 同模式：`collectors`（搜索 key）从 config.yaml 迁出，由 sources_store.search_keys 注入/持久化。同时给 conftest autouse 加 NEWS_SOURCES_PATH 隔离（防 API 测试写真实文件）。

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_config_collectors.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_config_collectors.py`:

```python
import app.config as cfgmod
import app.store.sources_store as ss
from app.config import CollectorsCfg, Settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    import app.store.providers_store as ps
    import app.store.targets_store as ts
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    cfgmod._settings = None


def test_save_settings_writes_collectors_to_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Settings()
    s.collectors = CollectorsCfg(tavily_key="tk", brave_key="", serper_key="")
    cfgmod.save_settings(s)
    import yaml
    raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "collectors" not in raw
    assert ss.load_search_keys()["tavily_key"] == "tk"


def test_get_settings_injects_collectors_from_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ss.save_search_keys({"tavily_key": "from_store", "brave_key": "", "serper_key": ""})
    cfgmod._settings = None
    s = cfgmod.get_settings()
    assert s.collectors.tavily_key == "from_store"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_config_collectors.py -v` → FAIL.

- [ ] **Step 3: 改 get_settings()** — 在 config.py `get_settings()` 中，与 providers/youtube 并列加 collectors：

```python
        raw.pop("collectors", None)  # 搜索 key 改由 sources_store 注入
        ...
        from app.store import providers_store, sources_store, targets_store
        stored = providers_store.load_providers()
        if stored:
            _settings.providers = stored
        _settings.youtube = YouTubeCfg(**targets_store.load_youtube_client())
        _settings.collectors = CollectorsCfg(**sources_store.load_search_keys())
```

（把 `raw.pop("collectors", None)` 放在已有的 providers/youtube pop 旁；import 合并 sources_store。）

- [ ] **Step 4: 改 save_settings()** — 加 collectors 写回 + 排除：

```python
    from app.store import providers_store, sources_store, targets_store
    providers_store.save_providers(settings.providers)
    targets_store.save_youtube_client(settings.youtube.model_dump())
    sources_store.save_search_keys(settings.collectors.model_dump())
    data = settings.model_dump()
    data.pop("providers", None)
    data.pop("youtube", None)
    data.pop("collectors", None)
    _save_yaml(CONFIG_PATH, data)
```

- [ ] **Step 5: conftest 加 NEWS_SOURCES_PATH 隔离** — 在 `backend/tests/conftest.py` 的 `_isolate_store_paths` autouse fixture 追加：

```python
    monkeypatch.setattr(
        "app.store.sources_store.NEWS_SOURCES_PATH",
        tmp_path / "news_sources.yaml",
    )
```

- [ ] **Step 6: 跑测试 + 回归 + 隔离验证**

Run: `cd backend && pytest tests/test_config_collectors.py -v` → 2 passed.
Run: `cd backend && pytest -q` → 无新失败。
Run: `cd backend && pytest -q && test -f ../news_sources.yaml && echo LEAK || echo OK` → OK.

- [ ] **Step 7: ruff + 提交**

```bash
cd backend && ruff check app/config.py tests/conftest.py tests/test_config_collectors.py
git add backend/app/config.py backend/tests/conftest.py backend/tests/test_config_collectors.py
git commit -m "feat(config): collectors(搜索 key) 路由到 sources_store + conftest 隔离 NEWS_SOURCES_PATH"
```

---

## Task 5: 迁移 news_sources + collectors + 改写 run.source_ids

`migrate.py` 增 `migrate_sources_to_yaml(*, config_path, sqlite_path)`：
- 幂等：`sources_store.NEWS_SOURCES_PATH` 已存在则跳过。
- 从 sqlite `news_sources` 表（raw sqlite3，ORDER BY id）→ slug（slugify(name) 回退 type）→ create_source；建 int_id→slug 映射。
- 从 config.yaml `collectors` 写 search_keys。
- 改写 sqlite `pipeline_runs.source_ids`（int→slug；映射不到原样保留）。
- `main.py` 串入。

**Files:**
- Modify: `backend/app/store/migrate.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_migrate_sources.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_migrate_sources.py`:

```python
import json
import sqlite3
from pathlib import Path

import yaml

import app.store.sources_store as ss
from app.store.migrate import migrate_sources_to_yaml


def _make_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE news_sources (id INTEGER PRIMARY KEY, name TEXT, type TEXT, url TEXT,"
                 " category TEXT, language TEXT, priority INTEGER, enabled BOOLEAN, tier TEXT,"
                 " pinned BOOLEAN, config_json TEXT)")
    conn.execute("INSERT INTO news_sources VALUES (1,'Hacker News','api','https://hn.algolia.com/api/v1/',"
                 "'general','en',5,1,'free',0,NULL)")
    conn.execute("INSERT INTO news_sources VALUES (2,'机器之心','rss','https://x.com/feed',"
                 "'general','zh',5,1,'free',0,?)", (json.dumps({"provider": "rss"}),))
    conn.execute("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, source_ids TEXT)")
    conn.execute("INSERT INTO pipeline_runs VALUES (10, ?)", (json.dumps([1, 2]),))
    conn.execute("INSERT INTO pipeline_runs VALUES (11, ?)", (json.dumps([2]),))
    conn.commit()
    conn.close()


def test_migrate_sources_seeds_slugs_and_search_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"collectors": {"tavily_key": "tk", "brave_key": "", "serper_key": ""}}),
                   encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_sources_to_yaml(config_path=cfg, sqlite_path=db)

    slugs = {s.slug for s in ss.list_sources()}
    assert "hacker_news" in slugs and "rss" in slugs
    assert ss.get_source("hacker_news").type == "api"
    assert ss.load_search_keys()["tavily_key"] == "tk"


def test_migrate_sources_rewrites_run_source_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_sources_to_yaml(config_path=cfg, sqlite_path=db)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, source_ids FROM pipeline_runs").fetchall())
    conn.close()
    assert json.loads(rows[10]) == ["hacker_news", "rss"]
    assert json.loads(rows[11]) == ["rss"]


def test_migrate_sources_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    ss.save_search_keys({"tavily_key": "keep", "brave_key": "", "serper_key": ""})
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"collectors": {"tavily_key": "no"}}), encoding="utf-8")
    migrate_sources_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert ss.load_search_keys()["tavily_key"] == "keep"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_migrate_sources.py -v` → FAIL.

- [ ] **Step 3: 实现 migrate_sources_to_yaml** — 在 `backend/app/store/migrate.py` 顶部 import 区加：

```python
from app.store import sources_store as ss
```

文件末尾追加：

```python
def _rewrite_source_ids(conn, id_to_slug: dict[int, str]) -> None:
    """把 pipeline_runs.source_ids 里的旧 int id 改写为 slug；映射不到原样保留。"""
    try:
        rows = conn.execute("SELECT id, source_ids FROM pipeline_runs").fetchall()
    except sqlite3.Error:
        return
    for run_id, sids in rows:
        if not sids:
            continue
        try:
            items = json.loads(sids)
        except (ValueError, TypeError):
            continue
        new = []
        for x in items:
            try:
                new.append(id_to_slug.get(int(x), x))
            except (ValueError, TypeError):
                new.append(x)
        conn.execute("UPDATE pipeline_runs SET source_ids = ? WHERE id = ?",
                     (json.dumps(new), run_id))
    conn.commit()


_SRC_COLS = ("name", "type", "url", "category", "language", "priority", "enabled", "tier", "pinned")


def migrate_sources_to_yaml(*, config_path: Path, sqlite_path: Path) -> None:
    if ss.NEWS_SOURCES_PATH.exists():
        return  # 幂等
    raw_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    collectors = (raw_cfg or {}).get("collectors") or {}
    id_to_slug: dict[int, str] = {}
    if sqlite_path.exists():
        try:
            with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute("SELECT * FROM news_sources ORDER BY id").fetchall()
                except sqlite3.Error:
                    rows = []
                existing: set[str] = set()
                for row in rows:
                    keys = row.keys()
                    name = row["name"] or ""
                    stype = row["type"] or ""
                    slug = unique_slug(slugify(name), existing, stype or "source")
                    existing.add(slug)
                    id_to_slug[int(row["id"])] = slug
                    try:
                        config = json.loads(row["config_json"]) if ("config_json" in keys and row["config_json"]) else {}
                    except (ValueError, TypeError):
                        config = {}
                    kw = {c: row[c] for c in _SRC_COLS if c in keys}
                    kw["enabled"] = bool(kw.get("enabled", True))
                    kw["pinned"] = bool(kw.get("pinned", False))
                    ss.create_source(config=config, slug=slug, **kw)
                if id_to_slug:
                    _rewrite_source_ids(conn, id_to_slug)
        except sqlite3.Error:
            pass
    ss.save_search_keys({
        "tavily_key": collectors.get("tavily_key", ""),
        "brave_key": collectors.get("brave_key", ""),
        "serper_key": collectors.get("serper_key", ""),
    })
    log.info("Migrated %d news sources + search_keys → %s", len(id_to_slug), ss.NEWS_SOURCES_PATH)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_migrate_sources.py -v` → 3 passed.

- [ ] **Step 5: main.py 串入** — `_run_storage_migrations()` 加 sources 迁移：

```python
def _run_storage_migrations() -> None:
    from app.config import CONFIG_PATH, get_settings, reload_settings
    from app.store.migrate import (
        migrate_providers_to_yaml, migrate_sources_to_yaml, migrate_targets_to_yaml,
    )
    sqlite_path = _sqlite_path_from_url(get_settings().infra.database_url)
    migrate_providers_to_yaml(config_path=CONFIG_PATH, sqlite_path=sqlite_path)
    migrate_targets_to_yaml(config_path=CONFIG_PATH, sqlite_path=sqlite_path)
    migrate_sources_to_yaml(config_path=CONFIG_PATH, sqlite_path=sqlite_path)
    reload_settings()
```

- [ ] **Step 6: 回归 + import + ruff + 提交**

Run: `cd backend && pytest -q` → 无新失败；`python -c "import app.main"` OK；`ruff check app/store/migrate.py app/main.py tests/test_migrate_sources.py`.

```bash
git add backend/app/store/migrate.py backend/app/main.py backend/tests/test_migrate_sources.py
git commit -m "feat(migrate): news_sources + collectors 迁入 yaml + 改写历史 run.source_ids 为 slug"
```

---

## Task 6: 删除 NewsSource 模型

**Files:**
- Delete: `backend/app/models/news_source.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: 查残余引用**

Run: `cd backend && grep -rn "NewsSource\|news_source import\|models.news_source\|db.query(NewsSource)" app/ tests/`
Expected: 仅 `models/news_source.py`、`models/__init__.py`。若 app 其它文件仍 live 引用（runner/api 应在 Task 2/3 已移除），STOP 报 NEEDS_CONTEXT。注意 schemas 的 `NewsSourceCreate/Read/Update` 保留。

- [ ] **Step 2: 删文件 + import**

```bash
git rm backend/app/models/news_source.py
```
In `backend/app/models/__init__.py` delete `from .news_source import NewsSource as NewsSource`.

- [ ] **Step 3: 启动 + 回归**

Run: `cd backend && python -c "import app.main" && pytest -q` → import OK；PASS 无新失败。

- [ ] **Step 4: 提交**

```bash
git add backend/app/models/__init__.py
git commit -m "refactor(models): 删除 NewsSource（已迁 news_sources.yaml）"
```

---

## Task 7: 前端 NewsSource.id → slug + SourceSummary/Sources/CreateRunDialog

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/SourceSummary.tsx`
- Modify: `frontend/src/components/CreateRunDialog.tsx`
- Modify: `frontend/src/pages/Sources.tsx`

- [ ] **Step 1: 改 types** — In `frontend/src/types/index.ts` `NewsSource`: `id: number` → `id: string`; `created_at: string` 若存在改 `string | null`（或删除该字段若 Read 不再返回 created_at —— 后端 NewsSourceRead 已无 created_at，故删除 `created_at` 字段）。`isAihotSource(s)` 逻辑不变（仍读 config_json）。

- [ ] **Step 2: 改 client.ts** — sources: `update: (id: number, ...)` → `(id: string, ...)`; `batch: (body: { ids: number[]; ...; priority_map?: Record<number, number> })` → `ids: string[]` + `priority_map?: Record<string, number>`.

- [ ] **Step 3: 改 SourceSummary.tsx** — `const ids: number[]` → `const ids: string[]`；解析 `as number[]` → `as string[]`；`ids.includes(s.id)` 现 s.id 为 string，类型自洽。

- [ ] **Step 4: 改 CreateRunDialog.tsx 源侧** — `sourceIds: Set<number>|null` → `Set<string>|null`；`availableSourceIdSet = new Set(availableSources.map(s=>s.id))`（s.id 现 string，自然）；`effectiveSourceIds` Set<string>；`toggleSource(id: number)` → `(id: string)`；`onToggle={(v) => toggleSource(Number(v))}` → `toggleSource(v)`；`values={[...effectiveSourceIds].map(String)}` 可保留（对 string 幂等）或简化为 `[...effectiveSourceIds]`；`source_ids: Array.from(effectiveSourceIds)` 现为 string[]。**不要动第 118 行 `Number(dep)`（stage 依赖）。**

- [ ] **Step 5: 改 Sources.tsx** — 把对 source id 的 number 假设改 string：`toggleSource`/`toggleAllCustom`/批量 priority_map 等用到 id 的地方改 string；`Number(s.id)` 若有则改。运行 tsc 按报错定位逐个修。保留 `isAihotSource` 过滤逻辑。

- [ ] **Step 6: 类型检查 + 构建**

Run: `cd D:/sanyan/projects/news-videos-workflow/frontend && npx tsc --noEmit -p tsconfig.app.json` → EXIT 0（按报错修到 0）。
Run: `cd D:/sanyan/projects/news-videos-workflow/frontend && npx vite build` → 成功。

- [ ] **Step 7: 提交**

```bash
cd D:/sanyan/projects/news-videos-workflow
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/components/SourceSummary.tsx frontend/src/components/CreateRunDialog.tsx frontend/src/pages/Sources.tsx
git commit -m "feat(frontend): NewsSource.id 改 slug（string）+ SourceSummary/源选择适配"
```

---

## Self-Review（写完计划的自检结果）

- **Spec 覆盖**：news_sources.yaml（slug + search_keys 归位）、CRUD/batch 文件化、runner 取数改 store、run.source_ids int→slug（含历史改写）、**降级语义（源全失效报错不回退 HN）**、config collectors facade、删 NewsSource、前端 SourceSummary（spec 原漏，已含）+ 源侧 string。
- **降级语义**：`_collectors_for_run` 区分「从未选源（requested 空）→ HN 回退」与「选了但全失效（requested 非空、db_sources 空）→ ValueError」。execute_pipeline / reroll 调用处异常会冒泡标记 run 失败并带提示。
- **SourceData 适配**：`_resolve_collector_type`/`build_collectors_from_db` 改吃 `.config` dict（SourceData）兼容 dict 输入；`_aihot_source_config`/`build_collectors` 不变（返回 dict cfg）。
- **测试隔离**：Task 4 给 conftest 加 NEWS_SOURCES_PATH（在源 API 测试写文件前）；各新测试另自隔离。
- **类型一致**：`SourceData`、`sources_store.*`、`_to_read`、`batch_update(slugs, ...)`、前端 `Set<string>` 跨任务一致。`config_json`↔`config` 转换只在 API 层。
- **占位符扫描**：无 TBD/TODO；每步含完整代码。
```
