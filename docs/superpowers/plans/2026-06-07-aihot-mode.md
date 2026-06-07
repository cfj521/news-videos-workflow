# AI HOT 硬编码 + 任务窗口信息源 2 选 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI HOT 变为硬编码模式（不再是可配置 DB 源）；新建任务窗口信息源改为「AI HOT / 其他源」二选一（互斥落在窗口），AI HOT 配置项搬入窗口；信息源页移除 AI HOT 卡片与互斥；其他源用增强版折叠下拉（全选+搜索+chips）。

**Architecture:** run 加 `aihot_config`（JSON|None）；非空=AI HOT 模式（method/category/report_date/week_start），为空=其他源模式（`source_ids`）。后端 `_collectors_for_run` 据此二分；模式真值统一为 `run.aihot_config`（create/采集/reroll/展示一致）。

**Tech Stack:** FastAPI / SQLAlchemy / pytest · React + TS + SWR

**Spec:** `docs/superpowers/specs/2026-06-07-aihot-mode-design.md`（含「评审补充」必读）

> 后端命令在 `backend/` 下：`D:\miniconda\envs\env_news_videos_wf\python.exe -m pytest ...`；前端 `frontend/`：`pnpm build`。已在分支 `feat/aihot-mode`。

---

# 阶段一：后端

### Task B1: PipelineRun.aihot_config 列 + 迁移 + schema

**Files:** Modify `backend/app/models/pipeline_run.py`, `backend/app/main.py`, `backend/app/schemas/pipeline.py`; Test `backend/tests/test_models_pipeline.py`

- [ ] **Step 1: 写失败测试** — 追加：
```python
def test_pipeline_run_aihot_config_roundtrip():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.base import Base
    from app.models.pipeline_run import PipelineRun
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    run = PipelineRun(mode="auto", video_route="hyperframes", aihot_config='{"method": "items"}')
    s.add(run); s.commit(); s.refresh(run)
    assert run.aihot_config == '{"method": "items"}'
    run2 = PipelineRun(mode="auto", video_route="hyperframes")
    s.add(run2); s.commit(); s.refresh(run2)
    assert run2.aihot_config is None
```
- [ ] **Step 2: 确认失败** — `... -m pytest tests/test_models_pipeline.py::test_pipeline_run_aihot_config_roundtrip -v` → FAIL
- [ ] **Step 3: 模型列** — `pipeline_run.py` 在 `source_ids` 行后加：
```python
    # AI HOT 模式配置（JSON：method/category/report_date/week_start）；None = 其他源模式（用 source_ids）
    aihot_config: Mapped[str | None] = mapped_column(Text, nullable=True)
```
- [ ] **Step 4: 迁移** — `main.py::_ensure_pipeline_run_columns` 的 `needed` 加 `"aihot_config": "TEXT",`
- [ ] **Step 5: schema** — `schemas/pipeline.py`：`PipelineRunCreate` 加 `aihot_config: dict | None = None`；`PipelineRunRead` 加 `aihot_config: str | None`
- [ ] **Step 6: 确认通过** — `... -m pytest tests/test_models_pipeline.py -v` → PASS
- [ ] **Step 7: 提交**
```bash
git add backend/app/models/pipeline_run.py backend/app/main.py backend/app/schemas/pipeline.py backend/tests/test_models_pipeline.py
git commit -m "feat(run): PipelineRun.aihot_config 列 + 迁移 + schema"
```

---

### Task B2: engine.create_run + api 透传 aihot_config

**Files:** Modify `backend/app/pipeline/engine.py`, `backend/app/api/pipeline.py`; Test `backend/tests/test_api_pipeline.py`

- [ ] **Step 1: 写失败测试** — 追加（沿用 `client` fixture）：
```python
def test_create_run_stores_aihot_config(client):
    r = client.post("/api/pipeline/runs", json={"aihot_config": {"method": "weekly"}})
    assert r.status_code == 201
    assert r.json()["aihot_config"] == '{"method": "weekly"}'
```
- [ ] **Step 2: 确认失败** — `... -m pytest tests/test_api_pipeline.py::test_create_run_stores_aihot_config -v` → FAIL
- [ ] **Step 3: engine** — `engine.py::create_run` 加参数 `aihot_config: dict | None = None,`；`PipelineRun(...)` 加 `aihot_config=json.dumps(aihot_config) if aihot_config else None,`
- [ ] **Step 4: api** — `api/pipeline.py::create_run` 的 `engine.create_run(...)` 加实参 `aihot_config=body.aihot_config,`
- [ ] **Step 5: 确认通过 + 回归** — `... -m pytest tests/test_api_pipeline.py -v` → PASS；`... -m pytest -q` 全绿
- [ ] **Step 6: 提交**
```bash
git add backend/app/pipeline/engine.py backend/app/api/pipeline.py backend/tests/test_api_pipeline.py
git commit -m "feat(run): create_run 接收并存 aihot_config"
```

---

### Task B3: _collectors_for_run（AI HOT 硬编码 / 其他源过滤 aihot）

**Files:** Modify `backend/app/pipeline/runner.py`; Test `backend/tests/test_collectors_for_run.py`（新）

- [ ] **Step 1: 写失败测试** — Create `backend/tests/test_collectors_for_run.py`:
```python
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.news_source import NewsSource
from app.pipeline.runner import _aihot_source_config, _collectors_for_run
from app.config import get_settings


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


class _Run:
    def __init__(self, aihot_config=None, source_ids=None):
        self.aihot_config = aihot_config
        self.source_ids = source_ids


def test_aihot_source_config_passes_params():
    cfg = _aihot_source_config({"method": "weekly", "week_start": "2026-01-05"})
    assert cfg["type"] == "aihot" and cfg["method"] == "weekly" and cfg["week_start"] == "2026-01-05"


def test_aihot_source_config_defaults_items():
    assert _aihot_source_config({})["method"] == "items"


def test_collectors_for_run_aihot_mode():
    db = _db()
    scs, cols = _collectors_for_run(db, _Run(aihot_config=json.dumps({"method": "daily"})), get_settings())
    assert len(scs) == 1 and scs[0]["type"] == "aihot" and scs[0]["method"] == "daily"
    assert "aihot" in cols


def test_collectors_for_run_custom_filters_residual_aihot():
    db = _db()
    db.add_all([
        NewsSource(id=1, name="RSS", type="rss", url="https://a/feed", enabled=True),
        NewsSource(id=2, name="AI HOT", type="api", url="https://aihot.virxact.com/api/public",
                   enabled=True, config_json=json.dumps({"provider": "aihot"})),
    ])
    db.commit()
    scs, cols = _collectors_for_run(db, _Run(source_ids=json.dumps([1, 2])), get_settings())
    names = [s["name"] for s in scs]
    assert "RSS" in names and "AI HOT" not in names  # 残留 aihot 行被过滤


def test_collectors_for_run_empty_defaults_hn():
    db = _db()
    scs, cols = _collectors_for_run(db, _Run(), get_settings())
    assert len(scs) == 1 and scs[0]["type"] == "hackernews_algolia"
```
- [ ] **Step 2: 确认失败** — `... -m pytest tests/test_collectors_for_run.py -v` → FAIL
- [ ] **Step 3: 实现** — `runner.py`（`build_collectors_from_db` 附近，`json`/`_resolve_collector_type`/`TYPE_TO_COLLECTOR`/`_ensure_collector_registry`/`build_collectors`/`_sources_for_run` 均在本模块）加：
```python
def _aihot_source_config(aihot: dict) -> dict:
    """由 run.aihot_config 构造 AI HOT collector 的 source_config（URL 在 collector 内硬编码）。"""
    cfg = {"name": "AI HOT", "type": "aihot", "provider": "aihot"}
    for k in ("method", "category", "report_date", "week_start"):
        if aihot.get(k):
            cfg[k] = aihot[k]
    cfg.setdefault("method", "items")
    return cfg


def _collectors_for_run(db, run, settings) -> tuple[list[dict], dict]:
    """按 run 选模式返回 (source_configs, collectors)。
    - aihot_config 非空 → AI HOT 单源（硬编码）。
    - 否则 → run.source_ids 选中的非 aihot 源；空则 enabled 非 aihot；再空 → 默认 HN。
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
    db_sources = [s for s in _sources_for_run(db, run) if _resolve_collector_type(s) != "aihot"]
    if db_sources:
        return build_collectors_from_db(db_sources)
    return build_collectors(settings)
```
- [ ] **Step 4: 确认通过** — `... -m pytest tests/test_collectors_for_run.py -v` → PASS
- [ ] **Step 5: 提交**
```bash
git add backend/app/pipeline/runner.py backend/tests/test_collectors_for_run.py
git commit -m "feat(pipeline): _collectors_for_run（AI HOT 硬编码 / 其他源过滤 aihot）"
```

---

### Task B4: 接入采集点 + 重采集 + reroll 路由口径 + 文案

**Files:** Modify `backend/app/pipeline/runner.py`（execute_pipeline 采集块）、`backend/app/api/pipeline.py`（`_reroll_articles_async` + `reroll_articles` 路由）；Test `backend/tests/test_api_pipeline.py`

- [ ] **Step 1: 写失败测试**（reroll 路由按 aihot_config 判 daily 拒绝）— 追加：
```python
def test_reroll_rejects_daily_by_aihot_config(client):
    r = client.post("/api/pipeline/runs", json={"aihot_config": {"method": "daily"}})
    rid = r.json()["id"]
    rr = client.post(f"/api/pipeline/runs/{rid}/reroll-articles")
    assert rr.status_code == 400
```
- [ ] **Step 2: 确认失败** — `... -m pytest tests/test_api_pipeline.py::test_reroll_rejects_daily_by_aihot_config -v` → FAIL（现按 articles.json 判，新 run 无 articles → 不拒绝）
- [ ] **Step 3: execute_pipeline 采集块** — `runner.py` 约 line 481-501，把「`db_sources = ...` → if/else build_collectors」整段替换为：
```python
            source_configs, collectors = _collectors_for_run(db, run, cfg)
            log.info("[S1] Using %d sources: %s", len(source_configs), [s["name"] for s in source_configs])
```
  **保留**其后约 line 503-504 的 `digest_method = next((sc.get("method") ... in ("daily","weekly")), None)` 与 history_fps、run_stage1 调用不动。删除该块内现已无用的 `from app.models.news_source import NewsSource`（若该 import 仅服务于被替换的查询；先确认）。
- [ ] **Step 4: _reroll_articles_async 改用 _collectors_for_run** — `api/pipeline.py` 的 `_reroll_articles_async` 里把现有「`from app.pipeline.runner import _sources_for_run` + `db_sources = _sources_for_run(db, run)` + build_collectors_from_db/build_collectors」整理为：
```python
        from app.pipeline.runner import _collectors_for_run
        source_configs, collectors = _collectors_for_run(db, run, get_settings())
```
  （后续用 source_configs/collectors 跑 run_stage1 不变；`_no_article_message(method)` 的 method 仍从 source_configs 推。）
- [ ] **Step 5: reroll 路由口径改 aihot_config** — `api/pipeline.py::reroll_articles`（约 line 573-585）把读 articles.json 判 method 改为：
```python
    method = ""
    if run.aihot_config:
        try:
            method = (json.loads(run.aihot_config) or {}).get("method", "")
        except Exception:
            method = ""
    if method == "daily":
        raise HTTPException(status_code=400, detail="日报模式无需重新采集")
    is_weekly = method == "weekly"
```
  （删除原 `apath`/读 articles.json 那几行。）
- [ ] **Step 6: 文案** — `runner.py:219` 周报无数据文案里「信息源 → AI HOT」改「新建任务窗口」。
- [ ] **Step 7: 旧互斥测试改写** — `backend/tests/test_runner_mutual_exclusion.py` 三个用例围绕 `build_collectors_from_db` 的 aihot 互斥（现成死代码）。改写为覆盖「`_collectors_for_run` custom 分支过滤残留 aihot 行」（与 B3 的 `test_collectors_for_run_custom_filters_residual_aihot` 等价），或直接删除该文件（其语义已由 test_collectors_for_run.py 覆盖）。本步选择删除该文件。
- [ ] **Step 8: 确认通过 + 回归** — `... -m pytest tests/test_api_pipeline.py -v` → PASS；`... -m pytest -q` 全绿。
- [ ] **Step 9: 提交**
```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_api_pipeline.py
git rm backend/tests/test_runner_mutual_exclusion.py
git commit -m "feat(pipeline): 采集/重采集/reroll 统一按 run.aihot_config 选模式"
```

---

### Task B5: 移除 AI HOT seed

**Files:** Modify `backend/app/main.py`; Test: 回归

- [ ] **Step 1: 移除** — `main.py` 删除 `_seed_aihot_source` 函数定义，并删除 lifespan 里对它的调用（约 line 64 `_seed_aihot_source(factory)`）。其 import（`json` / NewsSource 若仅此函数用）一并清理。
- [ ] **Step 2: 回归** — `... -m pytest -q` 全绿；`... -m ruff check app/main.py` 无新增 F401。
- [ ] **Step 3: 提交**
```bash
git add backend/app/main.py
git commit -m "chore(seed): 移除 AI HOT 信息源 seed（AI HOT 改硬编码）"
```

---

## 阶段一验收
- [ ] `... -m pytest -q` 全绿；`_collectors_for_run` 两模式 + 过滤 + 回退、create 存 aihot_config、reroll daily 拒绝均覆盖。

---

# 阶段二：前端

### Task F1: api 类型 + PipelineRun 字段

**Files:** Modify `frontend/src/api/client.ts`, `frontend/src/types/index.ts`

- [ ] **Step 1: runs.create body** — `client.ts` 的 `runs.create` body 类型加：
```ts
      aihot_config?: { method: string; category?: string; report_date?: string; week_start?: string };
```
- [ ] **Step 2: PipelineRun 类型** — `types/index.ts` 的 `PipelineRun` 接口加：
```ts
  source_ids: string | null;
  aihot_config: string | null;
```
- [ ] **Step 3: 构建** — `pnpm build` 通过
- [ ] **Step 4: 提交**
```bash
git add frontend/src/api/client.ts frontend/src/types/index.ts
git commit -m "feat(frontend): runs.create 加 aihot_config；PipelineRun 加 source_ids/aihot_config"
```

---

### Task F2: 增强 MultiSelect（searchable / selectAll / chips 变体，opt-in）

**Files:** Modify `frontend/src/components/MultiSelect.tsx`

- [ ] **Step 1: 加可选 props 与渲染** — 读现有组件，按下述扩展（不传新 props 时行为完全不变）：
  - props 加：`searchable?: boolean`、`selectAll?: boolean`、`allSelected?: boolean`、`onSelectAll?: (next: boolean) => void`、`variant?: "list" | "chips"`、`totalCount?: number`（用于「已选 N/M」摘要，可由 options.length 替代）。
  - 展开面板内：`searchable` → 顶部一个搜索 input，按 label 过滤 options（本地 `useState` 搜索词）；`selectAll` → 搜索下方一行「全选/全不选 (已选/总数)」按钮，点击调 `onSelectAll(!allSelected)`。
  - `variant==="chips"`：选项区用 `<div className="flex flex-wrap gap-2 ...">`，每项渲染为可点 chip：选中 `bg-blue-500/15 text-blue-200 border-blue-400/30`，未选 `bg-white/[0.03] text-white/70 border-white/[0.06]`，统一 `px-2.5 py-1 text-xs rounded-md border transition`，点击 `onToggle(o.value)`。`variant` 缺省 `"list"` 时保持现有 checkbox 行渲染。
  - 收起摘要：`selectAll && allSelected` → 「全部 (N)」；否则沿用现有「已选 N 个 / labels」。
- [ ] **Step 2: 构建** — `pnpm build` 通过（确保不传新 props 的发布账号用法不报错、外观不变）
- [ ] **Step 3: 提交**
```bash
git add frontend/src/components/MultiSelect.tsx
git commit -m "feat(frontend): MultiSelect 增强（搜索/全选/chips 变体，opt-in）"
```

---

### Task F3: 任务窗口 2 选一 + AI HOT 配置搬入 + 其他源 chips

**Files:** Modify `frontend/src/components/CreateRunDialog.tsx`

> 先通读该组件（已含 sourceIds/effectiveSourceIds/toggleSource/aihotSource/isAihotDigest/提交）。

- [ ] **Step 1: 模式状态 + AI HOT 配置状态**
```tsx
  const [sourceMode, setSourceMode] = useState<"aihot" | "custom">("aihot");
  const [aihotCfg, setAihotCfg] = useState<{ method: string; category?: string; report_date?: string; week_start?: string }>({ method: "items" });
```
  迁入 `AIHOT_CATEGORIES`（从 Sources.tsx 复制）。`api.sources.aihotWeeks/aihotDays` 用 `useSWR`（method 为 weekly/daily 时拉）。
- [ ] **Step 2: AI HOT / custom 推导**
  - `isAihotDigest = sourceMode === "aihot" && (aihotCfg.method === "daily" || aihotCfg.method === "weekly")`（替换原基于源的推导）。
  - 其他源：`availableSources = (sources ?? []).filter(s => s.enabled && !isAihotSource(s))`；`sourceIds: Set<number>|null`，`effectiveSourceIds` = null→全 availableSources id，否则用户选择 ∩ 可用。
- [ ] **Step 3: toggleSource 去 AI HOT 互斥** — 把现有 `toggleSource` 里 AI HOT 互斥分支删除，仅留普通 toggle：
```tsx
  const toggleSource = (id: number) => {
    setSourceIds((prev) => {
      const base = prev ?? new Set(availableSources.map((s) => s.id));
      const next = new Set(base);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const allSourcesSelected = availableSources.length > 0 && availableSources.every((s) => effectiveSourceIds.has(s.id));
  const onSelectAllSources = (nextAll: boolean) => setSourceIds(nextAll ? null : new Set());
```
- [ ] **Step 4: UI（左列信息源区）** — 替换原信息源勾选块为：模式段 + 对应内容：
```tsx
        <label className={labelCls}>信息源</label>
        <div className="flex gap-1.5 mb-3">
          {(["aihot", "custom"] as const).map((m) => (
            <button key={m} type="button" onClick={() => setSourceMode(m)}
              className={`px-2.5 py-1 text-xs rounded-md border transition ${sourceMode === m ? "bg-blue-500/15 text-blue-300 border-blue-400/30" : "bg-white/[0.03] text-white/70 border-white/[0.06] hover:text-white/92"}`}>
              {m === "aihot" ? "AI HOT" : "其他源"}
            </button>
          ))}
        </div>
        {sourceMode === "aihot" ? (
          <div className="mb-4">
            <div className="flex gap-1.5 mb-2">
              {(["items", "daily", "weekly"] as const).map((m) => (
                <button key={m} type="button" onClick={() => setAihotCfg((c) => ({ ...c, method: m }))}
                  className={`px-2.5 py-1 text-xs rounded-md border transition ${aihotCfg.method === m ? "bg-blue-500/15 text-blue-300 border-blue-400/30" : "bg-white/[0.03] text-white/70 border-white/[0.06]"}`}>
                  {m === "items" ? "动态" : m === "daily" ? "日报" : "周报"}
                </button>
              ))}
            </div>
            {aihotCfg.method === "items" && (
              <Select value={aihotCfg.category ?? ""} onChange={(v) => setAihotCfg((c) => ({ ...c, category: v }))} options={AIHOT_CATEGORIES} />
            )}
            {aihotCfg.method === "daily" && (
              <Select value={aihotCfg.report_date ?? ""} onChange={(v) => setAihotCfg((c) => ({ ...c, report_date: v }))}
                options={[{ value: "", label: "自动（最新一期）" }, ...(days ?? []).map((d) => ({ value: d.date, label: d.date }))]} />
            )}
            {aihotCfg.method === "weekly" && (
              <Select value={aihotCfg.week_start ?? ""} onChange={(v) => setAihotCfg((c) => ({ ...c, week_start: v }))}
                options={[{ value: "", label: "自动（最近有数据的周）" }, ...(weeks ?? []).map((w) => ({ value: w.week_start, label: `${w.week_start.slice(5)}~${w.week_end.slice(5)}（${w.days}天）` }))]} />
            )}
          </div>
        ) : (
          <div className="mb-4">
            {availableSources.length === 0 ? (
              <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2.5 text-xs text-amber-300/80">暂无可用信息源，请到「信息源管理」启用（将回退默认 Hacker News）</div>
            ) : (
              <MultiSelect
                variant="chips" searchable selectAll
                allSelected={allSourcesSelected}
                onSelectAll={onSelectAllSources}
                values={[...effectiveSourceIds].map(String)}
                onToggle={(v) => toggleSource(Number(v))}
                options={availableSources.map((s) => ({ value: String(s.id), label: s.name }))}
                placeholder="选择信息源..."
              />
            )}
          </div>
        )}
```
- [ ] **Step 5: 提交逻辑** — `handleSubmit` 的 `api.runs.create({...})`：把原 `source_ids` 一行改为按模式带参：
```tsx
        ...(sourceMode === "aihot"
          ? { aihot_config: aihotCfg }
          : { source_ids: Array.from(effectiveSourceIds) }),
```
- [ ] **Step 6: 清理** — 移除原基于全部 enabled 的 `aihotSource`/`aihotMethod`/`enabledSources` 旧推导（被新逻辑替代）；确保 `isAihotSource` 仍 import。
- [ ] **Step 7: 构建** — `pnpm build` 通过
- [ ] **Step 8: 提交**
```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(frontend): 任务窗口 AI HOT/其他源 2 选一 + AI HOT 配置 + chips 多选"
```

---

### Task F4: 信息源页移除 AI HOT 卡片与互斥 + 清理

**Files:** Modify `frontend/src/pages/Sources.tsx`

- [ ] **Step 1: 移除卡片与互斥**
  - 删除 `AIHotGroupCard` 组件定义、其渲染 `{aihotSource && <AIHotGroupCard .../>}`、常量 `AIHOT_CATEGORIES`、helper `parseConfig`。
  - `toggleSource`：删除「启用自定义源时联动关 AI HOT」分支，仅翻转该行。
  - `toggleAllCustom`：删除 AI HOT 取反逻辑，仅批量开关自定义源；title 去掉「与 AI HOT 互斥」。
  - 删除/清理 `aihotSource`、`customIds`（若仅服务互斥）等变量。`customSources` 仍 `filter(s => !isAihotSource(s))` 保留（过滤残留行）。
- [ ] **Step 2: 清理未用 import** — 删除随之未用的 import（如 `KeyedMutator`、`useEffect`、`Select`——按实际编译报错清理），保证 `noUnusedLocals` 通过。
- [ ] **Step 3: 构建** — `pnpm build` 通过
- [ ] **Step 4: 提交**
```bash
git add frontend/src/pages/Sources.tsx
git commit -m "feat(frontend): 信息源页移除 AI HOT 卡片与互斥（AI HOT 改硬编码）"
```

---

### Task F5: SourceSummary 按 run 展示 + Dashboard reroll 口径

**Files:** Modify `frontend/src/components/SourceSummary.tsx`, `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: SourceSummary 改按 run** — 改签名 `SourceSummary({ run }: { run: PipelineRun })`：
```tsx
  const { data: sources } = useSWR("sources", api.sources.list);
  const aihot = run.aihot_config ? (() => { try { return JSON.parse(run.aihot_config) as { method?: string; category?: string }; } catch { return null; } })() : null;
  const ids: number[] = run.source_ids ? (() => { try { return JSON.parse(run.source_ids) as number[]; } catch { return []; } })() : [];
  const names = (sources ?? []).filter((s) => ids.includes(s.id)).map((s) => s.name);
  // 渲染：aihot → "AI HOT · 动态/日报/周报"；ids 非空 → names.join("、")；否则 "默认 Hacker News"
```
  按上述三分支渲染（method 映射 items→动态/daily→日报/weekly→周报）。
- [ ] **Step 2: Dashboard 调用处传 run** — `Dashboard.tsx:310` 改为 `<SourceSummary run={run} />`（`run` 为当前详情 run 对象；若该作用域只有 runId，则从已加载的 run 数据取——读组件确认 run 来源）。
- [ ] **Step 3: Dashboard reroll 模式由 run.aihot_config 推导** — `Dashboard.tsx:248-251` 把 `aihotMethod`/`isWeekly`/`isDaily` 改为解析 `run.aihot_config`：
```tsx
  const aihotMethod = (() => { try { return run.aihot_config ? (JSON.parse(run.aihot_config).method ?? "") : ""; } catch { return ""; } })();
  const isWeekly = aihotMethod === "weekly";
  const isDaily = aihotMethod === "daily";
```
  （若 `run` 在此作用域不可直接用，按实际取当前 run；保持 `isDaily` 控制按钮禁用、`isWeekly` 控制文案。）
- [ ] **Step 4: 构建** — `pnpm build` 通过
- [ ] **Step 5: 提交**
```bash
git add frontend/src/components/SourceSummary.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): SourceSummary/Dashboard reroll 改按 run.aihot_config 展示与分流"
```

---

## 阶段二验收
- [ ] `pnpm build` 通过。
- [ ] 手动：任务窗口 AI HOT/其他源 2 选一、AI HOT 配置（动态分类/日报日期/周报周）可选、其他源 chips 折叠下拉（全选/搜索）；信息源页无 AI HOT 卡片、无互斥；Dashboard 重采集框按该 run 显示信息源、日报禁用、周报为「重新总结」。
- [ ] 端到端：AI HOT 模式任务 → run.aihot_config 落库 → 采集走 AI HOT；其他源模式 → source_ids → 采集走所选源（不含 aihot）。

## 收尾
- [ ] 合并/push（用户决定）。
