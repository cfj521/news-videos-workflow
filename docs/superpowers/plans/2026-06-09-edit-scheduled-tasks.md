# 编辑计划任务（全场景）+ 列表行改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「计划任务」列表整行可点击打开复用的 `CreateRunDialog`，用该排期现有值预填全部字段并保存修改；同时改造列表行（移除立即执行、启停移到右侧）。

**Architecture:** 后端 `PATCH /api/schedules/{slug}` 放开 name/freq/run_at/enabled/payload 并按 enabled 重排 job（兼容现有 toggle）；前端把 payload→弹窗 state 的反填抽成纯函数 `payloadToDialogState`/`backendStagesToVisual`（可单测），`CreateRunDialog` 加 `edit` prop 惰性初始化，提交走 PATCH。

**Tech Stack:** FastAPI + pydantic + APScheduler；React/TS + SWR；pytest + vitest（均用 `conda run -n env_news_videos_wf` 跑后端、`pnpm` 跑前端）。

**依据 spec：** `docs/superpowers/specs/2026-06-09-edit-scheduled-tasks-design.md`

---

## File Structure

- `backend/app/schemas/schedule.py` — 新增 `ScheduleUpdate`
- `backend/app/api/schedules.py` — `PATCH` 改用 `ScheduleUpdate`，放开全字段 + once 过期校验 + 重排
- `backend/tests/test_api_schedules.py` — 追加全量编辑 / 编辑成 once 过期测试
- `frontend/src/api/client.ts` — `api.schedules.update`
- `frontend/src/lib/runConfig.ts` — `backendStagesToVisual` + `payloadToDialogState`（新建）
- `frontend/src/lib/runConfig.test.ts` — vitest（新建）
- `frontend/src/components/CreateRunDialog.tsx` — `edit` prop + 惰性预填 + 三态提交/标题/按钮
- `frontend/src/pages/Schedules.tsx` — 行可点编辑 / 移除立即执行 / 启停移右 / 冒泡拦截 / 渲染编辑弹窗

环境约定（每个后端命令都加前缀）：`cd backend && conda run -n env_news_videos_wf python -m pytest ...`；前端 `cd frontend && pnpm ...`。分支 `feat/scheduled-tasks` 已检出。**不要启动后端服务**。

---

## Task 1: 后端 PATCH 放开字段

**Files:**
- Modify: `backend/app/schemas/schedule.py`
- Modify: `backend/app/api/schedules.py`
- Test: `backend/tests/test_api_schedules.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_api_schedules.py` 末尾追加（文件顶部已有 `PAYLOAD` 常量与 `client` fixture，复用）：

```python
def test_patch_full_edit_changes_fields(client):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    r = client.patch("/api/schedules/daily_ai", json={
        "name": "周更", "freq": "weekly", "run_at": "2026-06-20T09:30:00",
        "payload": {"video_route": "comfyui", "time_range": "3d", "selected_stages": [1, 2, 3]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "周更" and body["freq"] == "weekly"
    assert body["payload"]["video_route"] == "comfyui"   # payload 随 read 返回，供前端编辑预填
    lst = client.get("/api/schedules/").json()
    assert lst[0]["freq"] == "weekly" and lst[0]["name"] == "周更"
    assert lst[0]["payload"]["video_route"] == "comfyui"


def test_patch_edit_to_once_past_rejected(client):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    r = client.patch("/api/schedules/daily_ai", json={"freq": "once", "run_at": "2000-01-01T08:00:00"})
    assert r.status_code == 400
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && conda run -n env_news_videos_wf python -m pytest tests/test_api_schedules.py -v`
Expected: 两个新测试 FAIL（`test_patch_full_edit_changes_fields` 因当前 `_SchedulePatch` 丢弃 name/freq/... 而 freq 不变；`test_patch_edit_to_once_past_rejected` 因无过期校验返回 200）。

- [ ] **Step 3: schemas 新增 ScheduleUpdate + ScheduleRead 暴露 payload**

在 `backend/app/schemas/schedule.py`：

(a) 在 `ScheduleRead` 里新增一个字段（供前端编辑预填读取整份建任务参数）。把 `ScheduleRead` 的最后一个字段 `created_at: str | None = None` 之后加一行：
```python
    payload: dict = {}
```

(b) 文件末尾追加 `ScheduleUpdate`（文件已 `from typing import Literal`、`from datetime import datetime`、`from app.schemas.pipeline import PipelineRunCreate`）：
```python
class ScheduleUpdate(BaseModel):
    name: str | None = None
    freq: Literal["once", "daily", "weekly", "monthly"] | None = None
    run_at: datetime | None = None
    enabled: bool | None = None
    payload: PipelineRunCreate | None = None
```

- [ ] **Step 4: 路由改用 ScheduleUpdate**

在 `backend/app/api/schedules.py`：

把 import 行 `from app.schemas.schedule import ScheduleCreate, ScheduleRead` 改为：
```python
from app.schemas.schedule import ScheduleCreate, ScheduleRead, ScheduleUpdate
```

在 `_to_read(s)` 里补 payload 字段（让 list/post/patch 响应都带上 payload）。把：
```python
        last_run_at=s.last_run_at, last_run_id=s.last_run_id, created_at=s.created_at or None,
```
改为：
```python
        last_run_at=s.last_run_at, last_run_id=s.last_run_id, created_at=s.created_at or None,
        payload=s.payload,
```

删除现有这两段（`_SchedulePatch` 类定义 + 旧 `update_schedule`）：
```python
class _SchedulePatch(BaseModel):
    enabled: bool | None = None


@router.patch("/{slug}", response_model=ScheduleRead)
def update_schedule(slug: str, body: _SchedulePatch):
    patch = body.model_dump(exclude_unset=True)
    s = schedules_store.update_schedule(slug, patch)
    if s is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if s.enabled:
        scheduler.register(s, get_session_factory())
    else:
        scheduler.unregister(slug)
    log.info("Updated schedule '%s' enabled=%s", slug, s.enabled)
    return _to_read(s)
```
替换为：
```python
@router.patch("/{slug}", response_model=ScheduleRead)
def update_schedule(slug: str, body: ScheduleUpdate):
    existing = schedules_store.get_schedule(slug)
    if existing is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    patch = body.model_dump(exclude_unset=True)
    if body.run_at is not None:
        patch["run_at"] = body.run_at.isoformat()
    if body.payload is not None:
        patch["payload"] = body.payload.model_dump()
    # 用合并后的有效值做 once 过期校验（对齐 POST）
    eff_freq = patch.get("freq", existing.freq)
    eff_run_at = patch.get("run_at", existing.run_at)
    if eff_freq == "once" and datetime.fromisoformat(eff_run_at) <= datetime.now():
        raise HTTPException(status_code=400, detail="执行时间已过去")
    s = schedules_store.update_schedule(slug, patch)
    if s.enabled:
        scheduler.register(s, get_session_factory())
    else:
        scheduler.unregister(slug)
    log.info("Updated schedule '%s'", slug)
    return _to_read(s)
```

删除现在已无用的 import（`_SchedulePatch` 是该文件里 `BaseModel` 的唯一使用处）：把 `from pydantic import BaseModel` 这一行删掉。

- [ ] **Step 5: 运行测试确认通过（含兼容性回归）**

Run: `cd backend && conda run -n env_news_videos_wf python -m pytest tests/test_api_schedules.py -v`
Expected: 全部 PASS —— 两个新测试通过，且原 `test_list_patch_toggle_delete`（发 `{enabled: false}`）仍 PASS（ScheduleUpdate 接受 enabled，eff_freq=daily 不触发过期校验）。

- [ ] **Step 6: ruff 检查无未用 import**

Run: `cd backend && conda run -n env_news_videos_wf ruff check app/api/schedules.py app/schemas/schedule.py`
Expected: 无错误（确认删掉 BaseModel 后无 F401）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/schedule.py backend/app/api/schedules.py backend/tests/test_api_schedules.py
git commit -m "feat(api): PATCH /api/schedules 放开 name/freq/run_at/payload 全量编辑 + 重排"
```

---

## Task 2: 前端 api.schedules.update + Schedule.payload 类型

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Schedule 类型加 payload**

在 `frontend/src/types/index.ts` 的 `Schedule` 接口里，`created_at` 字段之后加一行（后端 `ScheduleRead` 现在返回 payload，编辑预填要用到）：

```ts
  payload: RunCreatePayload;
```
（`RunCreatePayload` 已在同文件定义，无需 import。）

- [ ] **Step 2: 加 update 方法**

在 `frontend/src/api/client.ts` 的 `schedules` 块里，`toggle` 之后、`remove` 之前插入（`RunCreatePayload` 已在本文件 import）：

```ts
    update: (slug: string, body: { name?: string; freq?: string; run_at?: string; payload?: RunCreatePayload }) =>
      fetchJSON<Schedule>(`/schedules/${slug}`, { method: "PATCH", body: JSON.stringify(body) }),
```

> `toggle` 保留不动（只发 `{ enabled }`）；两者共用同一 `PATCH /{slug}`，后端 `exclude_unset` 各取所需。

- [ ] **Step 3: 类型检查**

Run: `cd frontend && pnpm exec tsc --noEmit`
Expected: 通过。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(api): 前端 api.schedules.update + Schedule.payload 类型（read 暴露 payload）"
```

---

## Task 3: 反填纯函数 runConfig.ts + vitest

**Files:**
- Create: `frontend/src/lib/runConfig.ts`
- Test: `frontend/src/lib/runConfig.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/lib/runConfig.test.ts`：

```ts
import { describe, it, expect } from "vitest";
import { backendStagesToVisual, payloadToDialogState } from "./runConfig";

describe("backendStagesToVisual", () => {
  it("全阶段 1-6 → 可视 {1,2,4,5,6}", () => {
    expect([...backendStagesToVisual([1, 2, 3, 4, 5, 6])]).toEqual([1, 2, 4, 5, 6]);
  });
  it("[1,2,3] → {1,2}", () => {
    expect([...backendStagesToVisual([1, 2, 3])]).toEqual([1, 2]);
  });
  it("audio 无 4：[1,2,3,5,6] → {1,2,5,6}", () => {
    expect([...backendStagesToVisual([1, 2, 3, 5, 6])]).toEqual([1, 2, 5, 6]);
  });
  it("空数组 → 空集", () => {
    expect([...backendStagesToVisual([])]).toEqual([]);
  });
});

describe("payloadToDialogState", () => {
  it("aihot payload：sourceMode=aihot、sourceIds=null、阶段反填", () => {
    const s = payloadToDialogState({
      video_route: "comfyui", time_range: "3d", selected_stages: [1, 2, 3],
      aihot_config: { method: "daily" }, publish_platforms: ["yt"],
    });
    expect(s.sourceMode).toBe("aihot");
    expect(s.sourceIds).toBeNull();
    expect(s.aihotCfg).toEqual({ method: "daily" });
    expect([...s.selectedVisual]).toEqual([1, 2]);
    expect(s.videoRoute).toBe("comfyui");
    expect([...(s.targetIds ?? [])]).toEqual(["yt"]);
  });
  it("custom payload：sourceMode=custom、sourceIds=Set、targetIds=null", () => {
    const s = payloadToDialogState({ source_ids: ["a", "b"] });
    expect(s.sourceMode).toBe("custom");
    expect([...(s.sourceIds ?? [])]).toEqual(["a", "b"]);
    expect(s.targetIds).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && pnpm exec vitest run src/lib/runConfig.test.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 runConfig.ts**

创建 `frontend/src/lib/runConfig.ts`：

```ts
import type { RunCreatePayload } from "../types";
import { VISIBLE_STAGES } from "../types";

/** toBackendStages 的逆映射：后端阶段 → 可视阶段集合。
 *  后端 2/3 折回可视 2；其余落在 VISIBLE_STAGES 的原样保留。 */
export function backendStagesToVisual(backend: number[]): Set<number> {
  const visible = new Set<number>(VISIBLE_STAGES);
  const out = new Set<number>();
  for (const s of backend) {
    const v = s === 2 || s === 3 ? 2 : s;
    if (visible.has(v)) out.add(v);
  }
  return out;
}

export interface DialogInit {
  videoRoute: string;
  timeRange: string;
  maxArticles: number;
  autoCollect: boolean;
  resolution: string;
  language: string;
  maxImages: number | null;
  selectedVisual: Set<number>;
  targetIds: Set<string> | null;
  sourceMode: "aihot" | "custom";
  aihotCfg: { method: string; category?: string; report_date?: string; week_start?: string };
  sourceIds: Set<string> | null;
}

/** 把存储的 payload 反填为弹窗初始 state；缺省字段回退到与新建一致的默认。 */
export function payloadToDialogState(p: RunCreatePayload): DialogInit {
  const aihot = !!p.aihot_config;
  return {
    videoRoute: p.video_route ?? "hyperframes",
    timeRange: p.time_range ?? "7d",
    maxArticles: p.max_articles ?? 5,
    autoCollect: p.auto_collect ?? true,
    resolution: p.resolution ?? "",
    language: p.language ?? "",
    maxImages: p.max_images ?? null,
    selectedVisual: p.selected_stages ? backendStagesToVisual(p.selected_stages) : new Set([1, 2, 4, 5, 6]),
    targetIds: p.publish_platforms ? new Set(p.publish_platforms) : null,
    sourceMode: aihot ? "aihot" : "custom",
    aihotCfg: aihot ? p.aihot_config! : { method: "items" },
    sourceIds: aihot ? null : new Set(p.source_ids ?? []),
  };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && pnpm exec vitest run src/lib/runConfig.test.ts`
Expected: PASS（6 项）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/runConfig.ts frontend/src/lib/runConfig.test.ts
git commit -m "feat(ui): payload→弹窗 state 反填纯函数 + 测试"
```

---

## Task 4: CreateRunDialog 加 edit 模式

**File:** Modify `frontend/src/components/CreateRunDialog.tsx`

> 关键：组件内现有判断用的是 `schedule`；本任务引入 `const isSchedule = schedule || !!edit;` 并把**这些处**的 `schedule` 改成 `isSchedule`（payload 的 mode/auto_collect、标题、排期区显隐、运行模式锁、按钮禁用）。提交分支与按钮文案再三态区分 edit。

- [ ] **Step 1: 加 import**

在第 7 行 `import { STAGE_LABELS, ... } from "../types";` 之后、第 8 行 `import { formatScheduleSummary } from "../lib/schedule";` 附近，追加两行：

```tsx
import type { Schedule } from "../types";
import { payloadToDialogState, type DialogInit } from "../lib/runConfig";
```

- [ ] **Step 2: Props + 签名**

把 `Props` 接口改为（加 `edit?`）：

```tsx
interface Props {
  onCreated: () => void;
  onClose: () => void;
  schedule?: boolean;          // true = 计划模式
  onScheduled?: () => void;    // 新建/编辑成功回调
  edit?: Schedule;             // 存在 = 编辑模式（隐含 schedule 行为）
}
```

把函数签名改为：

```tsx
export function CreateRunDialog({ onCreated, onClose, schedule = false, onScheduled, edit }: Props) {
```

- [ ] **Step 3: 用 init 惰性预填全部 state**

把现有这段（`const [mode, ...]` 到 `const [aihotCfg, ...]`，即所有顶层 useState）整体替换。

旧：
```tsx
  const [mode, setMode] = useState("auto");
  const [freq, setFreq] = useState<"once" | "daily" | "weekly" | "monthly">("once");
  const [runAt, setRunAt] = useState("");          // datetime-local 原始字符串
  const [scheduleName, setScheduleName] = useState("");
  const [timeRange, setTimeRange] = useState("7d");
  const [maxArticles, setMaxArticles] = useState(5);
  const [autoCollect, setAutoCollect] = useState(true);
  const [videoRoute, setVideoRoute] = useState("hyperframes");
  const [selectedVisual, setSelectedVisual] = useState<Set<number>>(new Set([1, 2, 4, 5, 6]));
  // null = 用户尚未手动改动 → 默认全选所有可用账号；非 null = 用户的具体选择
  const [targetIds, setTargetIds] = useState<Set<string> | null>(null);
  // null = 用默认规则；非 null = 用户显式选择
  const [sourceIds, setSourceIds] = useState<Set<string> | null>(null);
  const [loading, setLoading] = useState(false);
  const [resolution, setResolution] = useState("");
  const [language, setLanguage] = useState("");
  const [maxImages, setMaxImages] = useState<number | null>(null);  // null = 用流水线配置默认

  // 信息源模式：AI HOT 或 其他源
  const [sourceMode, setSourceMode] = useState<"aihot" | "custom">("aihot");
  const [aihotCfg, setAihotCfg] = useState<{ method: string; category?: string; report_date?: string; week_start?: string }>({ method: "items" });
```
新：
```tsx
  const isSchedule = schedule || !!edit;
  // 编辑模式：从存储 payload 反填弹窗 state（只在挂载时算一次）
  const [init] = useState<DialogInit | null>(() => (edit ? payloadToDialogState(edit.payload) : null));
  const [mode, setMode] = useState("auto");
  const [freq, setFreq] = useState<"once" | "daily" | "weekly" | "monthly">(edit?.freq ?? "once");
  const [runAt, setRunAt] = useState(edit ? edit.run_at.slice(0, 16) : "");  // ISO→datetime-local（截到分）
  const [scheduleName, setScheduleName] = useState(edit?.name ?? "");
  const [timeRange, setTimeRange] = useState(init?.timeRange ?? "7d");
  const [maxArticles, setMaxArticles] = useState(init?.maxArticles ?? 5);
  const [autoCollect, setAutoCollect] = useState(init?.autoCollect ?? true);
  const [videoRoute, setVideoRoute] = useState(init?.videoRoute ?? "hyperframes");
  const [selectedVisual, setSelectedVisual] = useState<Set<number>>(init?.selectedVisual ?? new Set([1, 2, 4, 5, 6]));
  // null = 用户尚未手动改动 → 默认全选所有可用账号；非 null = 用户的具体选择
  const [targetIds, setTargetIds] = useState<Set<string> | null>(init?.targetIds ?? null);
  // null = 用默认规则；非 null = 用户显式选择
  const [sourceIds, setSourceIds] = useState<Set<string> | null>(init?.sourceIds ?? null);
  const [loading, setLoading] = useState(false);
  const [resolution, setResolution] = useState(init?.resolution ?? "");
  const [language, setLanguage] = useState(init?.language ?? "");
  const [maxImages, setMaxImages] = useState<number | null>(init?.maxImages ?? null);  // null = 用流水线配置默认

  // 信息源模式：AI HOT 或 其他源
  const [sourceMode, setSourceMode] = useState<"aihot" | "custom">(init?.sourceMode ?? "aihot");
  const [aihotCfg, setAihotCfg] = useState<{ method: string; category?: string; report_date?: string; week_start?: string }>(init?.aihotCfg ?? { method: "items" });
```

- [ ] **Step 4: payload 的 mode/auto_collect 用 isSchedule**

在 `handleSubmit` 的 `payload` 对象里，把：
```tsx
        mode: schedule ? "auto" : mode,
```
改为：
```tsx
        mode: isSchedule ? "auto" : mode,
```
把：
```tsx
        auto_collect: schedule ? true : autoCollect,
```
改为：
```tsx
        auto_collect: isSchedule ? true : autoCollect,
```

- [ ] **Step 5: 提交分支三态**

把 `handleSubmit` 里现有的：
```tsx
      if (schedule) {
        await api.schedules.create({
          name: scheduleName.trim() || formatScheduleSummary(freq, runAt),
          freq,
          run_at: runAt,                 // 直接提交 datetime-local 原始串，勿 toISOString
          payload,
        });
        onScheduled?.();
      } else {
        await api.runs.create(payload);
        onCreated();
      }
```
替换为：
```tsx
      if (edit) {
        await api.schedules.update(edit.slug, {
          name: scheduleName.trim() || formatScheduleSummary(freq, runAt),
          freq,
          run_at: runAt,                 // 直接提交 datetime-local 原始串，勿 toISOString
          payload,
        });
        onScheduled?.();
      } else if (isSchedule) {
        await api.schedules.create({
          name: scheduleName.trim() || formatScheduleSummary(freq, runAt),
          freq,
          run_at: runAt,
          payload,
        });
        onScheduled?.();
      } else {
        await api.runs.create(payload);
        onCreated();
      }
```

- [ ] **Step 6: 标题三态**

把：
```tsx
        <h2 className="text-lg font-semibold mb-4">{schedule ? "新建计划任务" : "新建任务"}</h2>
```
改为：
```tsx
        <h2 className="text-lg font-semibold mb-4">{edit ? "编辑计划任务" : isSchedule ? "新建计划任务" : "新建任务"}</h2>
```

- [ ] **Step 7: 排期区显隐用 isSchedule**

把排期区的开头：
```tsx
        {schedule && (
          <div className="mb-5 rounded-lg border border-white/[0.06] p-3 grid grid-cols-2 gap-3">
```
改为：
```tsx
        {isSchedule && (
          <div className="mb-5 rounded-lg border border-white/[0.06] p-3 grid grid-cols-2 gap-3">
```

- [ ] **Step 8: 运行模式锁用 isSchedule**

把运行模式那块的：
```tsx
                {schedule ? (
                  <div className={`${selectCls} flex items-center opacity-50 cursor-not-allowed`}>
                    <span className="text-white/96">自动</span>
                  </div>
                ) : (
```
改为（仅首行 `schedule` → `isSchedule`）：
```tsx
                {isSchedule ? (
                  <div className={`${selectCls} flex items-center opacity-50 cursor-not-allowed`}>
                    <span className="text-white/96">自动</span>
                  </div>
                ) : (
```

- [ ] **Step 9: 按钮禁用与文案**

把：
```tsx
          <button onClick={handleSubmit} disabled={loading || effectiveVisual.size === 0 || (schedule && !runAt)} className={btnPrimary}>
            {loading ? "创建中..." : (schedule ? "创建计划" : "创建")}
          </button>
```
改为：
```tsx
          <button onClick={handleSubmit} disabled={loading || effectiveVisual.size === 0 || (isSchedule && !runAt)} className={btnPrimary}>
            {loading ? "创建中..." : edit ? "保存修改" : isSchedule ? "创建计划" : "创建"}
          </button>
```

- [ ] **Step 10: 类型检查与构建**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`
Expected: 通过（无类型/构建错误）。

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(ui): CreateRunDialog 加 edit 模式（全字段预填 + 保存修改）"
```

---

## Task 5: Schedules.tsx 行改造 + 编辑入口

**File:** Modify `frontend/src/pages/Schedules.tsx`

- [ ] **Step 1: 去掉 toast/run-now，加 editing 状态**

把顶部 import：
```tsx
import { useToast } from "../components/Toast";
```
删除（run-now 移除后 toast 不再使用）。

把组件内状态/回调段：
```tsx
  const { data: schedules, mutate } = useSWR<Schedule[]>("schedules", api.schedules.list);
  const [showCreate, setShowCreate] = useState(false);
  const { showToast } = useToast();

  const onToggle = async (s: Schedule) => {
    await api.schedules.toggle(s.slug, !s.enabled);
    mutate();
  };
  const onDelete = async (s: Schedule) => {
    if (!window.confirm(`删除计划「${s.name}」？`)) return;
    await api.schedules.remove(s.slug);
    mutate();
  };
  const onRunNow = async (s: Schedule) => {
    try {
      await api.schedules.runNow(s.slug);
      showToast("已触发一次执行，前往工作台查看", "success");
      mutate();
    } catch {
      showToast("触发失败", "error");
    }
  };
```
替换为：
```tsx
  const { data: schedules, mutate } = useSWR<Schedule[]>("schedules", api.schedules.list);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);

  const onToggle = async (s: Schedule) => {
    await api.schedules.toggle(s.slug, !s.enabled);
    mutate();
  };
  const onDelete = async (s: Schedule) => {
    if (!window.confirm(`删除计划「${s.name}」？`)) return;
    await api.schedules.remove(s.slug);
    mutate();
  };
```

- [ ] **Step 2: 改行结构（整行可点编辑 / 启停移右 / 去掉立即执行 / 冒泡拦截）**

把现有的 `{schedules?.map((s) => ( ... ))}` 整块（从 `<div key={s.slug}` 到对应 `))}`）替换为：

```tsx
        {schedules?.map((s) => (
          <div
            key={s.slug}
            onClick={() => setEditing(s)}
            className={`${cardCls} px-4 py-3 flex items-center gap-4 cursor-pointer hover:bg-white/[0.02] transition`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white/92 truncate">{s.name}</span>
                <span className={`${chipCls} bg-white/[0.06] text-white/66 text-[10px]`}>{formatScheduleSummary(s.freq, s.run_at)}</span>
                {!s.enabled && <span className={`${chipCls} bg-white/[0.06] text-white/46 text-[10px]`}>已停用</span>}
              </div>
              <div className="text-xs text-white/46 mt-0.5">
                下次：{fmt(s.next_run_at)} · 上次：{s.last_run_id
                  ? <Link to="/" onClick={(e) => e.stopPropagation()} className="text-blue-300 hover:underline">{fmt(s.last_run_at)} #{s.last_run_id}</Link>
                  : "—"}
              </div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); onToggle(s); }}
              className={toggleCls(s.enabled)}
              title={s.enabled ? "点击停用" : "点击启用"}
            >
              <span className={toggleThumbCls(s.enabled)} />
            </button>
            <DeleteIconButton onClick={(e) => { e.stopPropagation(); onDelete(s); }} title="删除此计划" />
          </div>
        ))}
```

- [ ] **Step 3: 渲染编辑弹窗**

在现有 `{showCreate && ( ... )}` 块之后追加：

```tsx
      {editing && (
        <CreateRunDialog
          edit={editing}
          onCreated={() => setEditing(null)}
          onScheduled={() => { setEditing(null); mutate(); }}
          onClose={() => setEditing(null)}
        />
      )}
```

- [ ] **Step 4: 类型检查与构建**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`
Expected: 通过（确认 `useToast`/`onRunNow`/`runNow` 移除后无未用变量/导入告警导致的失败）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Schedules.tsx
git commit -m "feat(ui): 计划列表整行可点编辑 + 启停移右 + 移除立即执行"
```

---

## Task 6: 端到端校验

- [ ] **Step 1: 后端全量**

Run: `cd backend && conda run -n env_news_videos_wf python -m pytest -q`
Expected: 全绿（含 Task 1 新测试）。

- [ ] **Step 2: 前端 lint（仅本次文件）+ vitest + build**

Run:
```
cd frontend && pnpm exec eslint src/pages/Schedules.tsx src/components/CreateRunDialog.tsx src/lib/runConfig.ts src/api/client.ts
pnpm exec vitest run
pnpm build
```
Expected: 本次改动文件 eslint exit 0；vitest 全过（含 runConfig 新测试 + 既有 schedule 测试）；build 成功。

> 说明：仓库 `pnpm lint`（全量）有 12 条**既有** `set-state-in-effect` 报错（App/Toast/Dashboard/Settings），与本次无关，不在本任务范围内修。只验证本次改动文件干净。

- [ ] **Step 3: 无新增提交则结束**

本任务仅校验，无代码改动；若前述命令全绿即完成。如发现问题，回到对应 Task 修复。

---

## 自查与手动验收

- **手动验证**（后端由用户自管）：进「计划任务」页 → 点某一行 → 弹窗标题「编辑计划任务」、名称/间隔/时间/各建任务参数均为该排期当前值 → 改名称+间隔+某参数 → 「保存修改」→ 列表该行摘要随之更新、slug 不变、`上次 #id` 历史仍在；点启停开关/删除图标/「上次 #id」链接均不触发编辑弹窗。
- **YAGNI**：未做批量编辑、改 slug、编辑清历史；立即执行按钮移除但后端端点保留。
