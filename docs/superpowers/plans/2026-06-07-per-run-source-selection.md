# 按任务选择信息源 + 任务窗口双列布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「用哪些信息源」从信息源管理页（全局 enabled）移到新建任务窗口（按任务选择并存到 run），并把任务窗口改为双列布局。

**Architecture:** 后端 `PipelineRun` 增 `source_ids`（JSON），采集按该 run 的所选源（空则回退 enabled）；前端任务窗口加可勾选信息源列表（默认按 AI HOT 规则、AI HOT 与常规组互斥），双列 flex 布局；信息源页 CRUD 不变、tab 改名。

**Tech Stack:** FastAPI / SQLAlchemy / pytest · React + TS + SWR

**Spec:** `docs/superpowers/specs/2026-06-07-per-run-source-selection-design.md`

> 命令在 `backend/` 下、conda 环境执行：`D:\miniconda\envs\env_news_videos_wf\python.exe -m pytest ...`；前端在 `frontend/`：`pnpm build`。已在分支 `feat/per-run-sources`。

## 文件结构
- Modify `backend/app/models/pipeline_run.py` — 加 `source_ids` 列
- Modify `backend/app/main.py` — `_ensure_pipeline_run_columns` 加列
- Modify `backend/app/schemas/pipeline.py` — Create/Read 加 `source_ids`
- Modify `backend/app/pipeline/engine.py` — `create_run` 接收并存 `source_ids`
- Modify `backend/app/api/pipeline.py` — `create_run` 透传；`_reroll_articles_async` 改用 `_sources_for_run`
- Modify `backend/app/pipeline/runner.py` — 新增 `_sources_for_run`，采集点改用它
- Modify `frontend/src/api/client.ts` — `runs.create` body 加 `source_ids`
- Modify `frontend/src/App.tsx` — 「信息源」→「信息源管理」
- Modify `frontend/src/components/CreateRunDialog.tsx` — 信息源选择 + 互斥 + 双列布局
- Modify `frontend/src/pages/Sources.tsx` — enabled 文案微调
- Tests: `backend/tests/test_models_pipeline.py`(扩展)、`backend/tests/test_sources_for_run.py`(新)、`backend/tests/test_api_pipeline.py`(扩展)

---

### Task 1: PipelineRun.source_ids 列 + 迁移 + schema

**Files:**
- Modify: `backend/app/models/pipeline_run.py`（约 line 37 后）
- Modify: `backend/app/main.py`（`_ensure_pipeline_run_columns`）
- Modify: `backend/app/schemas/pipeline.py`
- Test: `backend/tests/test_models_pipeline.py`

- [ ] **Step 1: 写失败测试** — 在 `backend/tests/test_models_pipeline.py` 末尾追加（若文件无则参考其它 test_models_* 的 in-memory engine 写法）：

```python
def test_pipeline_run_source_ids_roundtrip():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.base import Base
    from app.models.pipeline_run import PipelineRun

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    run = PipelineRun(mode="auto", video_route="hyperframes", source_ids="[1, 3]")
    s.add(run); s.commit(); s.refresh(run)
    assert run.source_ids == "[1, 3]"
    # 默认可空
    run2 = PipelineRun(mode="auto", video_route="hyperframes")
    s.add(run2); s.commit(); s.refresh(run2)
    assert run2.source_ids is None
```

- [ ] **Step 2: 运行确认失败** — `... -m pytest tests/test_models_pipeline.py::test_pipeline_run_source_ids_roundtrip -v` → FAIL（无 source_ids 属性）

- [ ] **Step 3: 加模型列** — `backend/app/models/pipeline_run.py`，在 `max_images` 行后加：
```python
    # 该任务选用的信息源 id 列表（JSON 数组）；None/空 = 未指定（采集回退到 enabled 源）
    source_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
```
（`Text` 已在该文件 import。）

- [ ] **Step 4: 启动迁移补列** — `backend/app/main.py` 的 `_ensure_pipeline_run_columns` 的 `needed` 字典加一项：
```python
        "source_ids": "TEXT",
```

- [ ] **Step 5: schema 加字段** — `backend/app/schemas/pipeline.py`：
  - `PipelineRunCreate` 加：`source_ids: list[int] | None = None`
  - `PipelineRunRead` 加：`source_ids: str | None`

- [ ] **Step 6: 运行确认通过** — `... -m pytest tests/test_models_pipeline.py -v` → PASS

- [ ] **Step 7: 提交**
```bash
git add backend/app/models/pipeline_run.py backend/app/main.py backend/app/schemas/pipeline.py backend/tests/test_models_pipeline.py
git commit -m "feat(run): PipelineRun.source_ids 列 + 迁移 + schema"
```

---

### Task 2: engine.create_run + api 透传

**Files:**
- Modify: `backend/app/pipeline/engine.py`（`create_run`）
- Modify: `backend/app/api/pipeline.py`（`create_run` 路由）
- Test: `backend/tests/test_api_pipeline.py`（扩展）

- [ ] **Step 1: 写失败测试** — 在 `backend/tests/test_api_pipeline.py` 追加（沿用其 `client` fixture，已 patch `_run_pipeline_bg`、override get_db、注入 admin）：

```python
def test_create_run_stores_source_ids(client):
    r = client.post("/api/pipeline/runs", json={"time_range": "7d", "source_ids": [2, 5]})
    assert r.status_code == 201
    assert r.json()["source_ids"] == "[2, 5]"
```

- [ ] **Step 2: 运行确认失败** — `... -m pytest tests/test_api_pipeline.py::test_create_run_stores_source_ids -v` → FAIL（source_ids 未存/未返回）

- [ ] **Step 3: engine.create_run 接收并存** — `backend/app/pipeline/engine.py`：
  - 函数签名加参数：`source_ids: list[int] | None = None,`
  - 在 `PipelineRun(...)` 构造里加：`source_ids=json.dumps(source_ids) if source_ids else None,`
  （`json` 已在该文件 import。）

- [ ] **Step 4: api create_run 透传** — `backend/app/api/pipeline.py` 的 `create_run` 里，`engine.create_run(...)` 调用补一个参数：`source_ids=body.source_ids,`

- [ ] **Step 5: 运行确认通过** — `... -m pytest tests/test_api_pipeline.py -v` → PASS（含原有用例）

- [ ] **Step 6: 提交**
```bash
git add backend/app/pipeline/engine.py backend/app/api/pipeline.py backend/tests/test_api_pipeline.py
git commit -m "feat(run): create_run 接收并存 source_ids"
```

---

### Task 3: 采集按任务所选源（_sources_for_run）

**Files:**
- Modify: `backend/app/pipeline/runner.py`（新增 `_sources_for_run`；采集点约 line 481）
- Modify: `backend/app/api/pipeline.py`（`_reroll_articles_async` 约 line 606-608）
- Test: `backend/tests/test_sources_for_run.py`（新）

- [ ] **Step 1: 写失败测试** — Create `backend/tests/test_sources_for_run.py`:

```python
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.news_source import NewsSource
from app.pipeline.runner import _sources_for_run


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _seed(db):
    db.add_all([
        NewsSource(id=1, name="A", type="rss", url="https://a/feed", enabled=True),
        NewsSource(id=2, name="B", type="rss", url="https://b/feed", enabled=False),
        NewsSource(id=3, name="C", type="rss", url="https://c/feed", enabled=True),
    ])
    db.commit()


class _Run:
    def __init__(self, source_ids):
        self.source_ids = source_ids


def test_uses_run_source_ids():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run(json.dumps([1, 3])))
    assert sorted(s.id for s in rows) == [1, 3]  # 含 disabled 也按 id 选


def test_falls_back_to_enabled_when_empty():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run(None))
    assert sorted(s.id for s in rows) == [1, 3]  # 回退到 enabled


def test_falls_back_when_blank_json():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run("[]"))
    assert sorted(s.id for s in rows) == [1, 3]
```

- [ ] **Step 2: 运行确认失败** — `... -m pytest tests/test_sources_for_run.py -v` → FAIL（`_sources_for_run` 不存在）

- [ ] **Step 3: 实现 `_sources_for_run`** — `backend/app/pipeline/runner.py`，在 `build_collectors_from_db` 附近（模块级，`json` 已 import）加：

```python
def _sources_for_run(db, run) -> list:
    """按 run.source_ids 取 NewsSource；为空/无则回退所有 enabled。"""
    from app.models.news_source import NewsSource
    ids: list = []
    raw = getattr(run, "source_ids", None)
    if raw:
        try:
            ids = json.loads(raw) or []
        except Exception:
            ids = []
    if ids:
        return db.query(NewsSource).filter(NewsSource.id.in_(ids)).all()
    return db.query(NewsSource).filter(NewsSource.enabled.is_(True)).all()
```

- [ ] **Step 4: 采集点改用它** — `backend/app/pipeline/runner.py` 约 line 481，把：
```python
            db_sources = db.query(NewsSource).filter(NewsSource.enabled.is_(True)).all()
```
改为：
```python
            db_sources = _sources_for_run(db, run)
```
（`from app.models.news_source import NewsSource` 那行若仅此处用可保留，不影响。）

- [ ] **Step 5: 重采集也改用它** — `backend/app/api/pipeline.py` 的 `_reroll_articles_async`（约 line 606-610），把：
```python
        from app.models.news_source import NewsSource
        db_sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()
```
改为：
```python
        from app.pipeline.runner import _sources_for_run
        db_sources = _sources_for_run(db, run)
```
（顺带消除该处 ruff E712。`run` 在该函数内已取到；若变量名不同按实际。）

- [ ] **Step 6: 运行确认通过 + 回归** — `... -m pytest tests/test_sources_for_run.py -v && ... -m pytest -q` → PASS / 全绿

- [ ] **Step 7: 提交**
```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_sources_for_run.py
git commit -m "feat(pipeline): 采集与重采集按 run.source_ids 选源（空回退 enabled）"
```

---

### Task 4: 前端 API 字段 + tab 改名

**Files:**
- Modify: `frontend/src/api/client.ts`（`runs.create` body，约 line 112-122）
- Modify: `frontend/src/App.tsx`（line 13）

- [ ] **Step 1: client 加 source_ids** — `frontend/src/api/client.ts`，在 `runs.create` 的 body 类型里（`max_images?: number;` 后）加：
```ts
      source_ids?: number[];
```

- [ ] **Step 2: tab 改名** — `frontend/src/App.tsx` line 13：
```ts
  { to: "/sources", label: "信息源管理" },
```

- [ ] **Step 3: 构建验证** — 在 `frontend/`：`pnpm build` → 通过

- [ ] **Step 4: 提交**
```bash
git add frontend/src/api/client.ts frontend/src/App.tsx
git commit -m "feat(frontend): runs.create 加 source_ids；tab 改名信息源管理"
```

---

### Task 5: 任务窗口信息源选择 + 互斥 + 双列布局

**Files:**
- Modify: `frontend/src/components/CreateRunDialog.tsx`

> 前端无强 TDD；以 `pnpm build` + 手动验收为主。先通读该文件（已在 spec/上下文中给出）。

- [ ] **Step 1: 信息源选择状态与解析** — 在组件内（`targetIds` 相关代码附近）加：
```tsx
  // null = 用默认规则；非 null = 用户显式选择
  const [sourceIds, setSourceIds] = useState<Set<number> | null>(null);
```
并把现有 `const enabledSources = (sources ?? []).filter((s) => s.enabled);` 之后改为：
```tsx
  const availableSources = (sources ?? []).filter((s) => s.enabled);
  const aihotAvail = availableSources.filter(isAihotSource);
  // 默认：有 AI HOT 则默认仅选 AI HOT；否则全选可用
  const defaultSourceIds = (aihotAvail.length ? aihotAvail : availableSources).map((s) => s.id);
  const availableSourceIdSet = new Set(availableSources.map((s) => s.id));
  const effectiveSourceIds = sourceIds === null
    ? new Set(defaultSourceIds)
    : new Set([...sourceIds].filter((id) => availableSourceIdSet.has(id)));
```

- [ ] **Step 2: AI HOT 推导改基于所选源** — 把原 `const aihotSource = enabledSources.find(isAihotSource);` 改为：
```tsx
  const aihotSource = availableSources.find((s) => isAihotSource(s) && effectiveSourceIds.has(s.id));
```
（其下 `aihotMethod` / `isAihotDigest` 不变，自动跟随。）

- [ ] **Step 3: toggleSource（含 AI HOT ↔ 常规互斥）** — 加：
```tsx
  const toggleSource = (id: number) => {
    setSourceIds((prev) => {
      const base = prev ?? new Set(defaultSourceIds);
      const next = new Set(base);
      const turningOn = !next.has(id);
      if (next.has(id)) next.delete(id); else next.add(id);
      if (turningOn) {
        const src = availableSources.find((s) => s.id === id);
        const onIsAihot = src ? isAihotSource(src) : false;
        // 选中 AI HOT → 只留 AI HOT；选中常规 → 去掉所有 AI HOT
        for (const x of [...next]) {
          const s = availableSources.find((a) => a.id === x);
          if (!s) continue;
          if (onIsAihot ? !isAihotSource(s) : isAihotSource(s)) next.delete(x);
        }
      }
      return next;
    });
  };
```

- [ ] **Step 4: 提交带 source_ids** — `handleSubmit` 的 `api.runs.create({...})` 里加：
```tsx
        source_ids: Array.from(effectiveSourceIds),
```

- [ ] **Step 5: 信息源选择 UI（替换 SourceSummary）** — 移除 `import { SourceSummary } from "./SourceSummary";` 与 `<div className="mb-5"><SourceSummary /></div>`。新增一段信息源勾选列表（放入左列，见 Step 6），JSX：
```tsx
        <label className={labelCls}>信息源</label>
        {availableSources.length === 0 ? (
          <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2.5 text-xs text-amber-300/80 mb-4">
            暂无可用信息源，请先到「信息源管理」启用（将回退默认 Hacker News）
          </div>
        ) : (
          <div className="rounded-lg border border-white/[0.06] mb-4 overflow-hidden">
            {availableSources.map((s) => (
              <label key={s.id} className="flex items-center gap-3 px-3 py-2.5 hover:bg-white/[0.03] cursor-pointer border-b border-white/[0.04] last:border-0 transition">
                <input type="checkbox" checked={effectiveSourceIds.has(s.id)} onChange={() => toggleSource(s.id)} className="w-3.5 h-3.5 rounded accent-blue-500" />
                <span className="text-sm text-white/92 flex-1">{s.name}</span>
                {isAihotSource(s) && <span className="text-[10px] text-blue-300/80">AI HOT</span>}
              </label>
            ))}
          </div>
        )}
```

- [ ] **Step 6: 双列 flex 布局** — 弹窗面板宽度由 `w-[500px]` 改为 `w-[720px]`。把标题下、按钮上的所有表单内容包进双列容器：
```tsx
        <div className="flex gap-5">
          <div className="flex-1 min-w-0">
            {/* 左列：信息源（Step 5）→ 执行阶段 → 发布账号(stage6 时) */}
          </div>
          <div className="flex-1 min-w-0">
            {/* 右列：运行模式·路线(grid-2) → 分辨率·语言(grid-2) → 最多图片数 → 采集方式 → 时间·文章数(grid-2) */}
          </div>
        </div>
```
把现有各区块按 spec 决策 4 分别移入左/右列；「取消/创建」按钮区保留在双列容器**之外**（底部整宽）。注意保留各区块原有的条件渲染（如 `effectiveVisual.has(6)` 才显示发布账号、`autoCollect && !isAihotDigest` 才显示时间/文章数、audio 路线约束等）。

- [ ] **Step 7: 构建验证** — `pnpm build` → 通过

- [ ] **Step 8: 提交**
```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(frontend): 任务窗口按任务选信息源(AI HOT 互斥) + 双列布局"
```

---

### Task 6: 信息源页 enabled 文案微调

**Files:**
- Modify: `frontend/src/pages/Sources.tsx`

- [ ] **Step 1: 调整说明文案** — 通读 `Sources.tsx`，找到页面顶部/enabled 开关附近的说明文字，改为体现新语义（「启用 = 作为新建任务的可选信息源；具体某次任务用哪些在『新建任务』里选」）。若当前无此说明，在页面标题区加一行小字提示即可。CRUD（增删改）逻辑与 UI 保持不变。

- [ ] **Step 2: 构建验证** — `pnpm build` → 通过

- [ ] **Step 3: 提交**
```bash
git add frontend/src/pages/Sources.tsx
git commit -m "docs(frontend): 信息源页 enabled 文案对齐新语义"
```

---

## 验收
- [ ] 后端 `... -m pytest -q` 全绿；新表列、_sources_for_run、create_run 存 source_ids 均覆盖。
- [ ] 前端 `pnpm build` 通过。
- [ ] 手动：新建任务窗口为双列；信息源可勾选、默认按规则、AI HOT 与常规互斥；创建后该 run 的 source_ids 落库；采集/重采集只用所选源；信息源页只切 enable、CRUD 正常、tab 名为「信息源管理」。

## 收尾
- [ ] 合并/PR（用户决定）。
