# Plan 2 — publish_targets.yaml 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把发布账号（`PublishTarget` 表）+ YouTube OAuth client（config.yaml 顶层 `youtube`）迁到 `publish_targets.yaml`，slug 作主键；CRUD 文件化；run 的发布账号选择由 int id 改 slug。

**Architecture:** 复用 Plan 1 的 `store/_io.py`。新增 `store/_slug.py`（slug 生成，Plan 3 复用）、`store/targets_store.py`（读写 publish_targets.yaml：targets[slug] + youtube_oauth_client）。`api/publishers.py` 改调 store；`build_publishers` 改吃 store 的 `TargetData`；runner S6 与 api/pipeline 的发布按 slug 取数。config.py 把 `youtube` 字段透明路由到 targets_store（设置页零改动）。启动迁移：DB publish_targets + config.yaml.youtube → publish_targets.yaml，并把历史 run.publish_platforms 的 int id 改写为 slug。删 `PublishTarget` 模型。

**Tech Stack:** Python 3.12 / FastAPI / pydantic / PyYAML / pytest；前端 React/TS（少量 id 类型改动）。

**整体规则:** 仓库根 `publish_targets.yaml`（与 config.yaml 同级，gitignore）。后端命令 `cd backend`。完成后 `pytest` 全绿、新增/改动文件 `ruff check` 干净。Plan 1 已完成（providers/oauth 已在 model_providers.yaml）。

**前置事实（已核实）:**
- `run.publish_platforms`（`pipeline_run.py:24`，`Text default "[]"`）存发布账号 id 的 JSON 列表。
- 两处按 id 查 `PublishTarget`：`runner.py:863-865`（S6 发布）、`api/pipeline.py:940-942`（`_publish_async` 重发）。`_parse_target_ids`（`api/pipeline.py:890`）返回 `set[int]`。
- `build_publishers`（`providers/publisher/__init__.py:8`）吃 ORM targets，读 `.enabled/.platform/.config_json/.name`。
- 前端 target 侧已用 `Set<string>` + `String(t.id)`（`CreateRunDialog.tsx:50,107,160`），改 slug 后基本不动。
- `config.youtube`（`config.py:102` YouTubeCfg）**无运行时消费者**（youtube publisher 只读 target 的 config）——迁移仅搬家。

---

## 文件结构

- **新增** `backend/app/store/_slug.py` — `slugify(name)` + `unique_slug(base, existing, fallback)`。
- **新增** `backend/app/store/targets_store.py` — `TargetData` 模型 + `TARGETS_PATH` + `list_targets/get_target/create_target/update_target/delete_target` + `load_youtube_client/save_youtube_client`。
- **修改** `backend/app/schemas/publish_target.py` — `id: str`（slug）；Create 增 `slug: str | None`。
- **修改** `backend/app/api/publishers.py` — CRUD 改 targets_store。
- **修改** `backend/app/providers/publisher/__init__.py` — `build_publishers` 吃 `TargetData`。
- **修改** `backend/app/pipeline/runner.py` — S6 取 targets 改 store（slug）。
- **修改** `backend/app/api/pipeline.py` — `_parse_target_ids`→`set[str]`；`_publish_async` 取 targets 改 store。
- **修改** `backend/app/config.py` — `youtube` 字段透明路由到 targets_store。
- **修改** `backend/app/store/migrate.py` — 增 publish_targets + youtube 迁移 + 改写历史 run.publish_platforms。
- **修改** `backend/app/main.py` — 迁移调用串起 targets（已有 `_run_storage_migrations`，扩展之）。
- **删除** `backend/app/models/publish_target.py` + `models/__init__.py` 的 import。
- **前端** `types/index.ts`（PublishTarget.id→string）、`api/client.ts`（publishers id:string）、`pages/Publishers.tsx`（id 类型）、`components/CreateRunDialog.tsx`（核对，预期无改）。
- **测试** `test_slug.py`、`test_targets_store.py`、`test_migrate_targets.py`、改 `test_l1_contract.py`（publishers CRUD 用 slug）、`test_api_pipeline.py`（publish_platforms slug）。

---

## Task 1: slug 工具

**Files:**
- Create: `backend/app/store/_slug.py`
- Test: `backend/tests/test_slug.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_slug.py`:

```python
from app.store._slug import slugify, unique_slug


def test_slugify_basic():
    assert slugify("Hacker News") == "hacker_news"
    assert slugify("YouTube  Main!") == "youtube_main"
    assert slugify("  a--b  ") == "a_b"


def test_slugify_chinese_returns_empty():
    assert slugify("抖音官方") == ""


def test_unique_slug_no_collision():
    assert unique_slug("youtube", set(), "target") == "youtube"


def test_unique_slug_collision_appends_number():
    assert unique_slug("youtube", {"youtube"}, "target") == "youtube_1"
    assert unique_slug("youtube", {"youtube", "youtube_1"}, "target") == "youtube_2"


def test_unique_slug_empty_base_uses_fallback():
    assert unique_slug("", set(), "douyin") == "douyin"
    assert unique_slug("", {"douyin"}, "douyin") == "douyin_1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_slug.py -v`
Expected: FAIL (ModuleNotFoundError: app.store._slug)

- [ ] **Step 3: 实现 `_slug.py`**

Create `backend/app/store/_slug.py`:

```python
"""slug 生成：实体（信息源/发布账号）的 YAML 主键。

英文名转小写下划线；中文/全特殊字符名 slugify 得空串，由调用方用 fallback（platform/type）兜底。
"""
from __future__ import annotations

import re


def slugify(name: str) -> str:
    """转 [a-z0-9_]；非字母数字折叠为单个下划线，去首尾下划线。中文等无 ASCII 字母数字 → 空串。"""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")


def unique_slug(base: str, existing: set[str], fallback: str) -> str:
    """在 existing 内取唯一 slug。base 为空用 fallback；冲突则 base_1、base_2… 递增。"""
    base = base or fallback
    if base not in existing:
        return base
    i = 1
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_slug.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/store/_slug.py backend/tests/test_slug.py
git commit -m "feat(store): slug 生成工具（slugify + unique_slug）"
```

---

## Task 2: targets_store

**Files:**
- Create: `backend/app/store/targets_store.py`
- Test: `backend/tests/test_targets_store.py`

publish_targets.yaml 结构：
```yaml
youtube_oauth_client: {client_id: '', client_secret: ''}
targets:
  youtube_main:
    name: YouTube
    platform: youtube
    enabled: true
    created_at: '2026-06-07T...'
    config: {client_id: '', client_secret: '', refresh_token: ''}
```

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_targets_store.py`:

```python
from pathlib import Path

import pytest

import app.store.targets_store as ts


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")


def test_list_empty():
    assert ts.list_targets() == []


def test_create_generates_slug_from_name():
    t = ts.create_target(name="YouTube", platform="youtube", config={"client_id": "x"})
    assert t.slug == "youtube"
    assert t.name == "YouTube" and t.platform == "youtube" and t.enabled is True
    assert t.config == {"client_id": "x"}
    assert t.created_at  # ISO 字符串


def test_create_chinese_name_falls_back_to_platform():
    t = ts.create_target(name="抖音官方", platform="douyin", config={})
    assert t.slug == "douyin"


def test_create_collision_appends_number():
    ts.create_target(name="YouTube", platform="youtube", config={})
    t2 = ts.create_target(name="YouTube", platform="youtube", config={})
    assert t2.slug == "youtube_1"


def test_get_update_delete():
    ts.create_target(name="YouTube", platform="youtube", config={"client_id": "a"})
    assert ts.get_target("youtube").config["client_id"] == "a"
    ts.update_target("youtube", {"enabled": False, "config": {"client_id": "b"}})
    got = ts.get_target("youtube")
    assert got.enabled is False and got.config["client_id"] == "b"
    ts.delete_target("youtube")
    assert ts.get_target("youtube") is None


def test_update_missing_returns_none():
    assert ts.update_target("nope", {"enabled": False}) is None


def test_youtube_client_roundtrip():
    assert ts.load_youtube_client() == {"client_id": "", "client_secret": ""}
    ts.save_youtube_client({"client_id": "cid", "client_secret": "sec"})
    assert ts.load_youtube_client() == {"client_id": "cid", "client_secret": "sec"}


def test_create_explicit_slug():
    t = ts.create_target(name="My YT", platform="youtube", config={}, slug="custom_yt")
    assert t.slug == "custom_yt"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_targets_store.py -v`
Expected: FAIL (AttributeError: TARGETS_PATH)

- [ ] **Step 3: 实现 `targets_store.py`**

Create `backend/app/store/targets_store.py`:

```python
"""publish_targets.yaml 读写：发布账号（slug 主键）+ YouTube OAuth client。

结构：
    youtube_oauth_client: {client_id, client_secret}
    targets:
      <slug>: {name, platform, enabled, created_at, config: {...}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.store import _io
from app.store._slug import slugify, unique_slug

TARGETS_PATH = Path(__file__).resolve().parents[3] / "publish_targets.yaml"

_DEFAULT_YT_CLIENT = {"client_id": "", "client_secret": ""}


class TargetData(BaseModel):
    """单个发布账号。slug 为主键（YAML key），config 为平台凭证内联 dict。"""
    slug: str
    name: str
    platform: str
    enabled: bool = True
    created_at: str = ""
    config: dict = {}


def _read() -> dict:
    return _io.load_yaml(TARGETS_PATH)


def list_targets() -> list[TargetData]:
    raw = _read().get("targets", {}) or {}
    return [TargetData(slug=slug, **(slot or {})) for slug, slot in raw.items()]


def get_target(slug: str) -> TargetData | None:
    slot = (_read().get("targets", {}) or {}).get(slug)
    return TargetData(slug=slug, **slot) if slot else None


def create_target(*, name: str, platform: str, config: dict,
                  enabled: bool = True, slug: str | None = None) -> TargetData:
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        targets = data.setdefault("targets", {})
        existing = set(targets.keys())
        new_slug = slug or unique_slug(slugify(name), existing, platform)
        if new_slug in existing:
            new_slug = unique_slug(new_slug, existing, platform)
        rec = {
            "name": name, "platform": platform, "enabled": enabled,
            "created_at": datetime.now(timezone.utc).isoformat(), "config": config or {},
        }
        targets[new_slug] = rec
        _io.save_yaml(TARGETS_PATH, data)
        return TargetData(slug=new_slug, **rec)


def update_target(slug: str, patch: dict) -> TargetData | None:
    """部分更新；patch 可含 name/platform/enabled/config。返回更新后的 TargetData，slug 不存在返回 None。"""
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        targets = data.get("targets", {}) or {}
        if slug not in targets:
            return None
        slot = targets[slug]
        for k in ("name", "platform", "enabled", "config"):
            if k in patch and patch[k] is not None:
                slot[k] = patch[k]
        targets[slug] = slot
        data["targets"] = targets
        _io.save_yaml(TARGETS_PATH, data)
        return TargetData(slug=slug, **slot)


def delete_target(slug: str) -> bool:
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        targets = data.get("targets", {}) or {}
        if slug not in targets:
            return False
        del targets[slug]
        data["targets"] = targets
        _io.save_yaml(TARGETS_PATH, data)
        return True


def load_youtube_client() -> dict:
    yc = _read().get("youtube_oauth_client") or {}
    return {**_DEFAULT_YT_CLIENT, **yc}


def save_youtube_client(client: dict) -> None:
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        data["youtube_oauth_client"] = {**_DEFAULT_YT_CLIENT, **(client or {})}
        _io.save_yaml(TARGETS_PATH, data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_targets_store.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: ruff + 提交**

```bash
cd backend && ruff check app/store/targets_store.py tests/test_targets_store.py
git add backend/app/store/targets_store.py backend/tests/test_targets_store.py
git commit -m "feat(store): targets_store 读写 publish_targets.yaml（slug 主键 + youtube client）"
```

---

## Task 3: schemas + api/publishers.py 改用 targets_store

现状 `schemas/publish_target.py`：`PublishTargetCreate{name,platform,enabled,config_json}`、`PublishTargetRead{id:int,name,platform,enabled,config_json,created_at}`、`PublishTargetUpdate{...}`。
现状 `api/publishers.py`：list/create/patch/delete 走 DB。
改为：id→slug 字符串；API 内部把 store 的 `config`(dict)↔`config_json`(str) 互转，保持前端契约不变（前端仍收发 config_json 字符串）。

**Files:**
- Modify: `backend/app/schemas/publish_target.py`
- Modify: `backend/app/api/publishers.py`
- Test: `backend/tests/test_api_publishers.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_api_publishers.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

import app.store.targets_store as ts
from app.auth import get_current_user
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_create_returns_slug_id(client):
    r = client.post("/api/publishers/", json={"name": "YouTube", "platform": "youtube",
                                              "config_json": json.dumps({"client_id": "x"})})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "youtube"
    assert json.loads(body["config_json"])["client_id"] == "x"


def test_list_and_patch_and_delete(client):
    client.post("/api/publishers/", json={"name": "YouTube", "platform": "youtube", "config_json": "{}"})
    assert len(client.get("/api/publishers/").json()) == 1
    r = client.patch("/api/publishers/youtube", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete("/api/publishers/youtube").status_code == 200
    assert client.get("/api/publishers/").json() == []


def test_patch_missing_404(client):
    assert client.patch("/api/publishers/nope", json={"enabled": False}).status_code == 404


def test_delete_missing_404(client):
    assert client.delete("/api/publishers/nope").status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_api_publishers.py -v`
Expected: FAIL (id 仍为 int / 走 DB)

- [ ] **Step 3: 改 schemas**

Replace `backend/app/schemas/publish_target.py` with:

```python
from pydantic import BaseModel


class PublishTargetCreate(BaseModel):
    name: str
    platform: str
    enabled: bool = True
    config_json: str | None = None
    slug: str | None = None  # 可显式指定 slug；缺省按 name 生成


class PublishTargetRead(BaseModel):
    id: str            # slug
    name: str
    platform: str
    enabled: bool
    config_json: str | None
    created_at: str | None


class PublishTargetUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    enabled: bool | None = None
    config_json: str | None = None
```

- [ ] **Step 4: 改 api/publishers.py**

Replace `backend/app/api/publishers.py` with:

```python
import json

from fastapi import APIRouter, HTTPException

from app.logging import get_logger
from app.schemas.publish_target import PublishTargetCreate, PublishTargetRead, PublishTargetUpdate
from app.store import targets_store

log = get_logger("api.publishers")
router = APIRouter(prefix="/api/publishers", tags=["publishers"])


def _to_read(t) -> PublishTargetRead:
    return PublishTargetRead(
        id=t.slug, name=t.name, platform=t.platform, enabled=t.enabled,
        config_json=json.dumps(t.config, ensure_ascii=False) if t.config else None,
        created_at=t.created_at or None,
    )


def _parse_config(config_json: str | None) -> dict:
    if not config_json:
        return {}
    try:
        return json.loads(config_json)
    except (ValueError, TypeError):
        return {}


@router.get("/", response_model=list[PublishTargetRead])
def list_targets():
    return [_to_read(t) for t in targets_store.list_targets()]


@router.post("/", response_model=PublishTargetRead, status_code=201)
def create_target(body: PublishTargetCreate):
    t = targets_store.create_target(
        name=body.name, platform=body.platform, enabled=body.enabled,
        config=_parse_config(body.config_json), slug=body.slug,
    )
    log.info("Created publish target '%s' (%s)", t.slug, t.platform)
    return _to_read(t)


@router.patch("/{slug}", response_model=PublishTargetRead)
def update_target(slug: str, body: PublishTargetUpdate):
    patch: dict = body.model_dump(exclude_unset=True)
    if "config_json" in patch:
        patch["config"] = _parse_config(patch.pop("config_json"))
    t = targets_store.update_target(slug, patch)
    if t is None:
        raise HTTPException(status_code=404, detail="Target not found")
    log.info("Updated publish target '%s'", slug)
    return _to_read(t)


@router.delete("/{slug}")
def delete_target(slug: str):
    if not targets_store.delete_target(slug):
        raise HTTPException(status_code=404, detail="Target not found")
    log.info("Deleted publish target '%s'", slug)
    return {"status": "ok"}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_api_publishers.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: ruff + 提交**

```bash
cd backend && ruff check app/schemas/publish_target.py app/api/publishers.py tests/test_api_publishers.py
git add backend/app/schemas/publish_target.py backend/app/api/publishers.py backend/tests/test_api_publishers.py
git commit -m "feat(publishers): CRUD 改 targets_store（id→slug，config dict↔json 适配）"
```

---

## Task 4: build_publishers + 发布取数改 store（slug）

`build_publishers` 现吃 ORM targets（`.enabled/.platform/.config_json/.name`）。改为吃 `TargetData`（`.enabled/.platform/.config(dict)/.name/.slug`）。S6（runner）与重发（api/pipeline）改从 `targets_store` 按 slug 取数；`_parse_target_ids`→`set[str]`。

**Files:**
- Modify: `backend/app/providers/publisher/__init__.py`
- Modify: `backend/app/pipeline/runner.py`
- Modify: `backend/app/api/pipeline.py`
- Test: `backend/tests/test_build_publishers.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_build_publishers.py`:

```python
from app.providers.publisher import build_publishers
from app.store.targets_store import TargetData


def test_build_publishers_from_targetdata_bilibili():
    t = TargetData(slug="bili_main", name="B站", platform="bilibili", enabled=True,
                   config={"sessdata": "s", "bili_jct": "j", "tid": "17"})
    pubs = build_publishers([t])
    assert len(pubs) == 1
    target, adapter = pubs[0]
    assert target.slug == "bili_main"
    assert adapter is not None


def test_build_publishers_skips_disabled():
    t = TargetData(slug="x", name="x", platform="bilibili", enabled=False, config={})
    assert build_publishers([t]) == []


def test_build_publishers_skips_unsupported_platform():
    t = TargetData(slug="x", name="x", platform="nonexistent", enabled=True, config={})
    assert build_publishers([t]) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_build_publishers.py -v`
Expected: FAIL (build_publishers 读 .config_json 而非 .config)

- [ ] **Step 3: 改 build_publishers**

In `backend/app/providers/publisher/__init__.py` replace the `build_publishers` function body so it reads `t.config` (dict) instead of parsing `t.config_json`:

```python
def build_publishers(targets) -> list:
    """从 TargetData 列表构造发布 adapter，返回 [(target, adapter)]。

    以「账号」为单位（不按 platform 去重）；禁用、暂不支持的平台跳过。
    targets: list[TargetData]（.enabled/.platform/.config(dict)/.name/.slug）
    """
    pubs: list = []
    for t in targets:
        if not t.enabled:
            continue
        adapter = _build_one(t.platform, t.config or {})
        if adapter is not None:
            pubs.append((t, adapter))
        else:
            log.warning("暂不支持构造 '%s' publisher（账号 %s），跳过", t.platform, t.name)
    return pubs
```

Leave `_build_one(platform, cfg)` unchanged (it already takes a dict) and remove the now-unused `import json` at top of the file if nothing else uses it (run `ruff check`).

- [ ] **Step 4: 改 api/pipeline.py 的 _parse_target_ids + _publish_async**

In `backend/app/api/pipeline.py`:

(a) Replace `_parse_target_ids` (lines ~890-898) with slug version:

```python
def _parse_target_slugs(publish_platforms: str | None) -> set[str]:
    """从 run.publish_platforms（账号 slug 列表，JSON）解析 slug 集合；容错非字符串项跳过。"""
    out: set[str] = set()
    for x in json.loads(publish_platforms or "[]"):
        if isinstance(x, str) and x:
            out.add(x)
    return out
```

(b) Update its two call sites: `trigger_publish` (line ~908) `if not _parse_target_ids(...)` → `if not _parse_target_slugs(...)`.

(c) In `_publish_async` (lines ~926-942) replace the PublishTarget import + query block:

```python
async def _publish_async(run_id: int, session_factory):
    from dataclasses import asdict

    from app.pipeline.stage6_publish import run_stage6
    from app.providers.publisher import build_publishers
    from app.store import targets_store

    reload_settings()
    db = session_factory()
    try:
        run = db.get(PipelineRun, run_id)
        if not run:
            return
        rd = _run_dir(run_id)
        slugs = _parse_target_slugs(run.publish_platforms)
        targets = [t for t in targets_store.list_targets() if t.enabled and t.slug in slugs]
        if not targets:
            _update(db, run, status="failed", error_message="无可用发布账号（可能已被禁用）",
                    finished_at=datetime.now(timezone.utc))
```

(Keep the rest of `_publish_async` after this block unchanged; it already uses `build_publishers(targets)` and `t.name`.)

- [ ] **Step 5: 改 runner.py S6**

In `backend/app/pipeline/runner.py` S6 block (lines ~849-865) replace the target_ids parsing + PublishTarget query:

```python
        _check_cancel(run.id)
        # publish_platforms 现存「发布账号 slug」列表；容错非字符串项跳过
        target_slugs: set[str] = set()
        for x in json.loads(run.publish_platforms):
            if isinstance(x, str) and x:
                target_slugs.add(x)
        if target_slugs:
            from dataclasses import asdict

            from app.pipeline.stage6_publish import run_stage6
            from app.providers.publisher import build_publishers
            from app.store import targets_store

            targets = [t for t in targets_store.list_targets() if t.enabled and t.slug in target_slugs]
            names = [t.name for t in targets]
```

(Keep the rest of the S6 block — `_update`, `build_publishers(targets)`, `result` handling — unchanged; `t.name` still valid on TargetData.)

- [ ] **Step 6: 跑测试 + 回归**

Run: `cd backend && pytest tests/test_build_publishers.py -v` → PASS (3 passed)
Run: `cd backend && pytest -q` → 无新失败（注意 test_api_pipeline.py 里若有 publish 相关 int id 断言，Task 6 修；本步若它们失败先记录）

- [ ] **Step 7: ruff + 提交**

```bash
cd backend && ruff check app/providers/publisher/__init__.py app/pipeline/runner.py app/api/pipeline.py tests/test_build_publishers.py
git add backend/app/providers/publisher/__init__.py backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_build_publishers.py
git commit -m "feat(publish): 发布取数改 targets_store（slug），build_publishers 吃 TargetData"
```

---

## Task 5: config.py 把 youtube 路由到 targets_store

现状 `config.py`：`Settings.youtube: YouTubeCfg`（从 config.yaml 读）。`/api/settings` GET/PUT 带 `youtube`。
改为：youtube 不进出 config.yaml，`get_settings()` 从 `targets_store.load_youtube_client()` 注入，`save_settings()` 写回 `targets_store.save_youtube_client()` 并从 config.yaml dump 排除。前端设置页零改动（与 Plan 1 providers 同模式）。

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config_youtube.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_config_youtube.py`:

```python
from pathlib import Path

import app.config as cfgmod
import app.store.targets_store as ts
from app.config import Settings, YouTubeCfg


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    import app.store.providers_store as ps
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    cfgmod._settings = None


def test_save_settings_writes_youtube_to_targets_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Settings()
    s.youtube = YouTubeCfg(client_id="cid", client_secret="sec")
    cfgmod.save_settings(s)
    import yaml
    raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "youtube" not in raw
    assert ts.load_youtube_client() == {"client_id": "cid", "client_secret": "sec"}


def test_get_settings_injects_youtube_from_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ts.save_youtube_client({"client_id": "from_store", "client_secret": "s2"})
    cfgmod._settings = None
    s = cfgmod.get_settings()
    assert s.youtube.client_id == "from_store" and s.youtube.client_secret == "s2"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_config_youtube.py -v`
Expected: FAIL

- [ ] **Step 3: 改 get_settings()**

In `backend/app/config.py` `get_settings()`, alongside the existing providers injection, add youtube injection. After the providers block, before `_ensure_default_models`:

```python
        raw.pop("youtube", None)  # youtube 不再从 config.yaml 取
        ...
        from app.store import providers_store
        stored = providers_store.load_providers()
        if stored:
            _settings.providers = stored
        from app.store import targets_store
        _settings.youtube = YouTubeCfg(**targets_store.load_youtube_client())
```

(Place `raw.pop("youtube", None)` next to the existing `raw.pop("providers", None)`. The final `get_settings()` should pop both providers and youtube from raw, then inject both from their stores.)

- [ ] **Step 4: 改 save_settings()**

In `backend/app/config.py` `save_settings()`, alongside the providers routing:

```python
def save_settings(settings: Settings) -> None:
    global _settings
    _settings = settings
    from app.store import providers_store, targets_store
    providers_store.save_providers(settings.providers)
    targets_store.save_youtube_client(settings.youtube.model_dump())
    data = settings.model_dump()
    data.pop("providers", None)
    data.pop("youtube", None)
    _save_yaml(CONFIG_PATH, data)
    import logging
    logging.getLogger("nv.config").info("Saved config to %s", CONFIG_PATH)
```

- [ ] **Step 4.5: 扩展 conftest autouse 隔离 TARGETS_PATH（防泄漏真实文件）**

Task 5 后 `save_settings` 也会写 `targets_store`（youtube），经 `/api/settings` 的 API 测试会写到真实 `publish_targets.yaml`。在 `backend/tests/conftest.py` 的 `_isolate_store_paths` autouse fixture 里追加一行（与已有的 MODEL_PROVIDERS_PATH 并列）：

```python
@pytest.fixture(autouse=True)
def _isolate_store_paths(tmp_path, monkeypatch):
    """全局隔离：把 model_providers.yaml / publish_targets.yaml 重定向到每测试临时目录，
    防止任何测试（尤其经 /api/settings → save_settings）写到仓库根真实文件。"""
    monkeypatch.setattr(
        "app.store.providers_store.MODEL_PROVIDERS_PATH",
        tmp_path / "model_providers.yaml",
    )
    monkeypatch.setattr(
        "app.store.targets_store.TARGETS_PATH",
        tmp_path / "publish_targets.yaml",
    )
```

- [ ] **Step 5: 跑测试 + 回归**

Run: `cd backend && pytest tests/test_config_youtube.py -v` → PASS (2 passed)
Run: `cd backend && pytest -q` → 无新失败
Run: 验证隔离生效：`cd backend && pytest -q && test -f ../publish_targets.yaml && echo "泄漏!" || echo "未泄漏 ✓"`

- [ ] **Step 6: ruff + 提交**

```bash
cd backend && ruff check app/config.py tests/test_config_youtube.py
git add backend/app/config.py backend/tests/test_config_youtube.py
git commit -m "feat(config): youtube client 透明路由到 targets_store"
```

---

## Task 6: 迁移 publish_targets + youtube + 改写历史 run.publish_platforms

扩展 `migrate.py`：新增 `migrate_targets_to_yaml(*, config_path, sqlite_path)`：
- 幂等：`targets_store.TARGETS_PATH` 已存在则跳过。
- 从 sqlite `publish_targets` 表（raw sqlite3）读各行 → slug（slugify(name) 缺省回退 platform，按旧 id 升序分配保证稳定）→ create 到 publish_targets.yaml；同时建 `旧 int_id → slug` 映射。
- 从 config.yaml 的 `youtube` 块写入 youtube_oauth_client。
- 用映射改写 sqlite `pipeline_runs.publish_platforms`（int id → slug；映射不到的项保留原值）。
- `main.py` 的 `_run_storage_migrations` 增调该函数。

**Files:**
- Modify: `backend/app/store/migrate.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_migrate_targets.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_migrate_targets.py`:

```python
import json
import sqlite3
from pathlib import Path

import yaml

import app.store.targets_store as ts
from app.store.migrate import migrate_targets_to_yaml


def _make_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE publish_targets (id INTEGER PRIMARY KEY, name TEXT, platform TEXT,"
                 " enabled BOOLEAN, config_json TEXT)")
    conn.execute("INSERT INTO publish_targets VALUES (1,'YouTube','youtube',1,?)",
                 (json.dumps({"client_id": "x"}),))
    conn.execute("INSERT INTO publish_targets VALUES (2,'抖音','douyin',1,'{}')")
    conn.execute("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, publish_platforms TEXT)")
    conn.execute("INSERT INTO pipeline_runs VALUES (10, ?)", (json.dumps([1, 2]),))
    conn.execute("INSERT INTO pipeline_runs VALUES (11, ?)", (json.dumps([1]),))
    conn.commit()
    conn.close()


def test_migrate_targets_seeds_slugs_and_youtube(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"youtube": {"client_id": "ytid", "client_secret": "yts"}}), encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_targets_to_yaml(config_path=cfg, sqlite_path=db)

    slugs = {t.slug for t in ts.list_targets()}
    assert slugs == {"youtube", "douyin"}
    assert ts.get_target("youtube").config["client_id"] == "x"
    assert ts.load_youtube_client()["client_id"] == "ytid"


def test_migrate_targets_rewrites_run_publish_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_targets_to_yaml(config_path=cfg, sqlite_path=db)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, publish_platforms FROM pipeline_runs").fetchall())
    conn.close()
    assert json.loads(rows[10]) == ["youtube", "douyin"]
    assert json.loads(rows[11]) == ["youtube"]


def test_migrate_targets_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    ts.save_youtube_client({"client_id": "keep", "client_secret": ""})  # 文件已存在
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"youtube": {"client_id": "should_not_load"}}), encoding="utf-8")
    migrate_targets_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert ts.load_youtube_client()["client_id"] == "keep"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_migrate_targets.py -v`
Expected: FAIL (no migrate_targets_to_yaml)

- [ ] **Step 3: 实现 migrate_targets_to_yaml**

在 `backend/app/store/migrate.py` 顶部 import 区加：

```python
from app.store import targets_store as ts
from app.store._slug import slugify, unique_slug
```

并在文件末尾追加：

```python
def _rewrite_publish_platforms(conn, id_to_slug: dict[int, str]) -> None:
    """把 pipeline_runs.publish_platforms 里的旧 int id 改写为 slug；映射不到的项原样保留。"""
    try:
        rows = conn.execute("SELECT id, publish_platforms FROM pipeline_runs").fetchall()
    except sqlite3.Error:
        return
    for run_id, pp in rows:
        if not pp:
            continue
        try:
            items = json.loads(pp)
        except (ValueError, TypeError):
            continue
        new = []
        for x in items:
            try:
                new.append(id_to_slug.get(int(x), x))
            except (ValueError, TypeError):
                new.append(x)
        conn.execute("UPDATE pipeline_runs SET publish_platforms = ? WHERE id = ?",
                     (json.dumps(new), run_id))
    conn.commit()


def migrate_targets_to_yaml(*, config_path: Path, sqlite_path: Path) -> None:
    if ts.TARGETS_PATH.exists():
        return  # 幂等
    # youtube client（来自 config.yaml 顶层 youtube）
    raw_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    yt = (raw_cfg or {}).get("youtube") or {}
    # 发布账号（来自 DB publish_targets，raw sqlite3）
    id_to_slug: dict[int, str] = {}
    if sqlite_path.exists():
        try:
            with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute("SELECT * FROM publish_targets ORDER BY id").fetchall()
                except sqlite3.Error:
                    rows = []
                existing: set[str] = set()
                for row in rows:
                    name = row["name"] or ""
                    platform = row["platform"] or ""
                    slug = unique_slug(slugify(name), existing, platform or "target")
                    existing.add(slug)
                    id_to_slug[int(row["id"])] = slug
                    try:
                        config = json.loads(row["config_json"]) if row["config_json"] else {}
                    except (ValueError, TypeError):
                        config = {}
                    ts.create_target(name=name, platform=platform, config=config,
                                     enabled=bool(row["enabled"]), slug=slug)
                if id_to_slug:
                    _rewrite_publish_platforms(conn, id_to_slug)
        except sqlite3.Error:
            pass
    ts.save_youtube_client({"client_id": yt.get("client_id", ""), "client_secret": yt.get("client_secret", "")})
    log.info("Migrated %d publish targets + youtube → %s", len(id_to_slug), ts.TARGETS_PATH)
```

> 注：`contextlib`、`sqlite3`、`json`、`yaml`、`Path`、`log` 已在 migrate.py 顶部（Plan 1）。若 `contextlib` 未 import 则补 `import contextlib`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_migrate_targets.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 在 lifespan 串入**

In `backend/app/main.py` `_run_storage_migrations()`, add the targets migration after the providers one:

```python
def _run_storage_migrations() -> None:
    from app.config import CONFIG_PATH, get_settings, reload_settings
    from app.store.migrate import migrate_providers_to_yaml, migrate_targets_to_yaml
    sqlite_path = _sqlite_path_from_url(get_settings().infra.database_url)
    migrate_providers_to_yaml(config_path=CONFIG_PATH, sqlite_path=sqlite_path)
    migrate_targets_to_yaml(config_path=CONFIG_PATH, sqlite_path=sqlite_path)
    reload_settings()
```

- [ ] **Step 6: 回归 + 提交**

Run: `cd backend && pytest -q` → 无新失败；`python -c "import app.main"` OK。
Run: `cd backend && ruff check app/store/migrate.py app/main.py tests/test_migrate_targets.py`

```bash
git add backend/app/store/migrate.py backend/app/main.py backend/tests/test_migrate_targets.py
git commit -m "feat(migrate): publish_targets + youtube 迁入 yaml + 改写历史 run.publish_platforms 为 slug"
```

---

## Task 7: 删除 PublishTarget 模型

**Files:**
- Delete: `backend/app/models/publish_target.py`
- Modify: `backend/app/models/__init__.py`
- Test: 确认无残留引用

- [ ] **Step 1: 查残余引用**

Run: `cd backend && grep -rn "PublishTarget\b\|publish_target import\|models.publish_target" app/ tests/`
Expected: 仅 `models/publish_target.py`、`models/__init__.py`。若 app 其它文件仍 import（runner/api/pipeline 应在 Task 4 已移除），STOP 报 NEEDS_CONTEXT。

- [ ] **Step 2: 删文件 + import**

```bash
git rm backend/app/models/publish_target.py
```
In `backend/app/models/__init__.py` delete the line `from .publish_target import PublishTarget as PublishTarget`.

- [ ] **Step 3: 启动 + 回归**

Run: `cd backend && python -c "import app.main" && pytest -q`
Expected: import OK；PASS 无新失败。

- [ ] **Step 4: 提交**

```bash
git add backend/app/models/__init__.py
git commit -m "refactor(models): 删除 PublishTarget（已迁 publish_targets.yaml）"
```

---

## Task 8: 前端 id → slug（string）

现状前端 `PublishTarget.id: number`。改 string（slug）。target 侧 CreateRunDialog 已用 `Set<string>`/`String(t.id)`，预期无逻辑改动。

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Publishers.tsx`
- Verify: `frontend/src/components/CreateRunDialog.tsx`

- [ ] **Step 1: 改 types**

In `frontend/src/types/index.ts` `PublishTarget` interface, change `id: number;` → `id: string;`. Also change `created_at: string;` to `created_at: string | null;` (store may omit). Keep the rest.

- [ ] **Step 2: 改 client.ts**

In `frontend/src/api/client.ts` publishers block: `update: (id: number, ...)` → `update: (id: string, ...)`; `remove: (id: number)` → `remove: (id: string)`. URLs `/publishers/${id}` unchanged.

- [ ] **Step 3: 改 Publishers.tsx**

In `frontend/src/pages/Publishers.tsx`: `handleDelete = async (id: number)` → `(id: string)`. No other change (t.id flows through as key/url). Verify no `Number(t.id)` usage exists.

- [ ] **Step 4: 核对 CreateRunDialog.tsx**

Run: `cd frontend && grep -n "Number(.*\.id\|targetIds\|String(t.id)" src/components/CreateRunDialog.tsx`
Confirm target side uses `String(t.id)` / `Set<string>` and has NO `Number()` on target ids. If clean, no change.

- [ ] **Step 5: 类型检查 + 构建**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: EXIT 0
Run: `cd frontend && pnpm build` (或 `npx vite build`)
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/pages/Publishers.tsx
git commit -m "feat(frontend): PublishTarget.id 改 slug（string）"
```

---

## Self-Review（写完计划的自检结果）

- **Spec 覆盖**：覆盖 spec 的 publish_targets.yaml（slug 主键 + youtube client 归位）、CRUD 文件化、build_publishers/发布取数改 store、run.publish_platforms int→slug（含历史改写）、删 PublishTarget、config youtube facade（设置页零改动，与 Plan 1 providers 同模式）。news_sources / search_keys 属 Plan 3。
- **slug 稳定性**：迁移按旧 id 升序分配 slug（`ORDER BY id`），回退序号确定 → 可重复迁移结果稳定（spec I3）。
- **历史 run 改写**：`_rewrite_publish_platforms` 映射 int→slug，映射不到原样保留（spec）。降级语义（发布账号全失效）：`_publish_async`/`trigger_publish` 已有「无可用发布账号」报错路径，slug 化后保持。
- **前端最小化**：因 target 侧早已 `Set<string>`/`String(t.id)`，仅 id 类型声明改动，无逻辑重写。
- **类型一致**：`TargetData`(slug/name/platform/enabled/created_at/config)、`_parse_target_slugs`、`targets_store.*`、`load/save_youtube_client` 跨任务一致；`build_publishers` 改吃 `.config`(dict) 与 `_build_one(platform, cfg)` 签名匹配。
- **占位符扫描**：无 TBD/TODO；每步含完整代码。
- **测试隔离**：所有新测试 monkeypatch `TARGETS_PATH`（及涉及的 MODEL_PROVIDERS_PATH）；conftest autouse 已隔离 model_providers，本计划新测试再各自隔离 targets，避免写真实文件。
```
