# 编辑计划任务（全场景）+ 列表行改造 设计

> 状态：待评审
> 日期：2026-06-09
> 关联：`docs/superpowers/specs/2026-06-09-scheduled-tasks-design.md`（计划任务本体，已实现于分支 `feat/scheduled-tasks`）

## 1. 目标

给「计划任务」列表加上**编辑能力**：点击任意一行打开复用的 `CreateRunDialog`，用该排期的现有值预填**全部字段**（间隔 / 执行时间 / 名称 + 全部建任务参数），改完原地保存。顺带按用户要求改造列表行布局。

初版（计划任务本体）按 YAGNI 砍掉了「编辑已有排期」，本设计补上。

**非目标**：批量编辑、改 slug、编辑时清空运行历史。

## 2. 列表行改造（`frontend/src/pages/Schedules.tsx`）

新行布局（左 → 右）：

```
[名称 + 规则摘要chip + 已停用chip]   [下次/上次执行]   ……（弹性留白）……   [启停开关] [删除图标]
```

- **整行可点 → 打开编辑弹窗**：卡片 `onClick={() => setEditing(s)}`。
- **移除「立即执行」按钮**：从 UI 删除该按钮及 `onRunNow`。后端 `POST /api/schedules/{slug}/run-now` 端点**保留不动**（已实现+测试，只是前端不再暴露）。
- **启停开关移到行右侧**，紧挨删除图标左边（原先在行左首）。
- **阻止冒泡**（否则误触发整行编辑）：启停开关、删除图标、以及「上次 #id」那个 `Link to="/"`，各自 `onClick` 里 `e.stopPropagation()`。

列表交互状态：新增 `const [editing, setEditing] = useState<Schedule | null>(null)`；`showCreate` 仍管新建。同时渲染：`showCreate` → `<CreateRunDialog schedule .../>`；`editing` → `<CreateRunDialog edit={editing} .../>`。

> 删除按 §3 说明仍走 `window.confirm`；启停 `onToggle` 不变。原 "fix(ui): 仅对启用的计划显示立即执行" 因按钮被移除而自然失效（可保留代码无害，但本次会随按钮一并删掉）。

## 3. 编辑弹窗（复用 `CreateRunDialog`，加 `edit?: Schedule` prop）

### Props

```tsx
interface Props {
  onCreated: () => void;
  onClose: () => void;
  schedule?: boolean;
  onScheduled?: () => void;      // 新建/编辑成功后都回调它做列表刷新
  edit?: Schedule;              // 存在 = 编辑模式（隐含 schedule 行为）
}
```

`edit` 存在时：

- **隐含 schedule 行为**：组件内统一用 `const isSchedule = schedule || !!edit;`，把现有所有 `schedule` 判断替换为 `isSchedule`（排期区显示、运行模式锁自动、采集方式锁、提交分支、按钮禁用/文案）。
- **标题**：`{edit ? "编辑计划任务" : isSchedule ? "新建计划任务" : "新建任务"}`。
- **确认按钮文案**：`edit ? "保存修改" : isSchedule ? "创建计划" : "创建"`。

### 字段预填（核心，纯函数 + 惰性初始化）

新建纯函数模块 `frontend/src/lib/runConfig.ts`：

```ts
import type { RunCreatePayload } from "../types";
import { VISIBLE_STAGES } from "../types";

/** toBackendStages 的逆映射：后端阶段 → 可视阶段集合。
 *  后端 2/3 折回可视 2；其余落在 VISIBLE_STAGES 的原样保留。 */
export function backendStagesToVisual(backend: number[]): Set<number> {
  const visible = new Set<number>(VISIBLE_STAGES);
  const out = new Set<number>();
  for (const s of backend) {
    const v = (s === 2 || s === 3) ? 2 : s;
    if (visible.has(v)) out.add(v);
  }
  return out;
}

export interface DialogInit {
  videoRoute: string; timeRange: string; maxArticles: number; autoCollect: boolean;
  resolution: string; language: string; maxImages: number | null;
  selectedVisual: Set<number>;
  targetIds: Set<string> | null;
  sourceMode: "aihot" | "custom";
  aihotCfg: { method: string; category?: string; report_date?: string; week_start?: string };
  sourceIds: Set<string> | null;
}

/** 把存储的 payload 反填为弹窗初始 state。缺省字段回退到与新建一致的默认。 */
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

在 `CreateRunDialog` 内，用一次性惰性初始化把这些喂给现有的 `useState`：

```tsx
const [init] = useState<DialogInit | null>(() => edit ? payloadToDialogState(edit.payload) : null);
const [videoRoute, setVideoRoute] = useState(init?.videoRoute ?? "hyperframes");
const [timeRange, setTimeRange] = useState(init?.timeRange ?? "7d");
const [maxArticles, setMaxArticles] = useState(init?.maxArticles ?? 5);
const [autoCollect, setAutoCollect] = useState(init?.autoCollect ?? true);
const [resolution, setResolution] = useState(init?.resolution ?? "");
const [language, setLanguage] = useState(init?.language ?? "");
const [maxImages, setMaxImages] = useState<number | null>(init?.maxImages ?? null);
const [selectedVisual, setSelectedVisual] = useState<Set<number>>(init?.selectedVisual ?? new Set([1, 2, 4, 5, 6]));
const [targetIds, setTargetIds] = useState<Set<string> | null>(init?.targetIds ?? null);
const [sourceIds, setSourceIds] = useState<Set<string> | null>(init?.sourceIds ?? null);
const [sourceMode, setSourceMode] = useState<"aihot" | "custom">(init?.sourceMode ?? "aihot");
const [aihotCfg, setAihotCfg] = useState(init?.aihotCfg ?? { method: "items" });
```

排期字段（名称/间隔/执行时间）预填：

```tsx
const [freq, setFreq] = useState<...>(edit?.freq ?? "once");
const [scheduleName, setScheduleName] = useState(edit?.name ?? "");
const [runAt, setRunAt] = useState(edit ? edit.run_at.slice(0, 16) : "");  // ISO 截到 "YYYY-MM-DDTHH:mm" 喂 datetime-local
```

> `edit.run_at` 是后端 naive ISO（`2026-06-15T08:00:00`），datetime-local 需 `"YYYY-MM-DDTHH:mm"`，取前 16 字符即可。**「名称」输入框**因此在编辑模式下预填当前名称（这就是用户说的"弹窗里加名称输入框"——复用现有 schedule 模式的名称输入框，编辑时带值）。

### 提交分支

`handleSubmit` 在现有 schedule 分支基础上再分编辑/新建：

```tsx
if (edit) {
  await api.schedules.update(edit.slug, {
    name: scheduleName.trim() || formatScheduleSummary(freq, runAt),
    freq, run_at: runAt, payload,
  });
  onScheduled?.();
} else if (isSchedule) {
  await api.schedules.create({ name: ..., freq, run_at: runAt, payload });
  onScheduled?.();
} else {
  await api.runs.create(payload); onCreated();
}
```

`payload` 构造不变（编辑时 `mode:"auto"`、`auto_collect:true` 同新建计划）。**不提交 `enabled`**（启停只由列表开关管）。`run_at` 仍直接提交 datetime-local 原始串，禁止 `toISOString`。

## 4. 前端 API 客户端

`frontend/src/api/client.ts` 的 `schedules` 块新增 `update`（保留现有 `toggle` 不动）：

```ts
update: (slug: string, body: { name?: string; freq?: string; run_at?: string; payload?: RunCreatePayload }) =>
  fetchJSON<Schedule>(`/schedules/${slug}`, { method: "PATCH", body: JSON.stringify(body) }),
```

> `toggle` 仍只发 `{ enabled }`，与 `update` 共用同一个 `PATCH /{slug}`，后端按 `exclude_unset` 各取所需，互不影响。

## 5. 后端：放开 `PATCH /api/schedules/{slug}`

### Schema（`backend/app/schemas/schedule.py` 新增）

```python
class ScheduleUpdate(BaseModel):
    name: str | None = None
    freq: Literal["once", "daily", "weekly", "monthly"] | None = None
    run_at: datetime | None = None
    enabled: bool | None = None
    payload: PipelineRunCreate | None = None
```

### 路由（`backend/app/api/schedules.py` 改 `update_schedule`）

把现有只收 `enabled` 的 `_SchedulePatch` 换成 `ScheduleUpdate`，逻辑：

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
        scheduler.register(s, get_session_factory())   # replace_existing=True → 用新 freq/run_at 重排
    else:
        scheduler.unregister(slug)
    log.info("Updated schedule '%s'", slug)
    return _to_read(s)
```

要点：
- **向后兼容 toggle**：只发 `{enabled}` 时 `patch` 仅含 enabled，`eff_freq/eff_run_at` 取 existing，daily/weekly/monthly 不触发过期校验；register/unregister 行为与现状一致。
- **改 freq/run_at → 重排**：`register` 内 `add_job(..., replace_existing=True, id=slug)` 会用新触发器替换旧 job。
- **slug / 运行历史不变**：`update_schedule` 不动 slug、不动 `last_run_at/last_run_id`。
- `datetime.now()` 与 `datetime.fromisoformat(eff_run_at)` 均 naive 本地，比较一致（同 POST）。

`schedules_store.update_schedule` 已支持 `name/freq/run_at/payload/enabled` 键，**无需改动 store**。

## 6. 数据流

```
列表点击某行 → setEditing(s) → CreateRunDialog(edit=s)
  └ payloadToDialogState(s.payload) + s.freq/run_at/name 预填全部字段
提交 → PATCH /api/schedules/{slug} { name, freq, run_at, payload }
  → get_schedule 校验(once 过期?) → update_schedule 写回
  → enabled ? scheduler.register(replace_existing 重排) : unregister
  → 列表 mutate 刷新；last_run_* 不变
```

## 7. 测试

**后端**（`backend/tests/test_api_schedules.py` 追加）：
- PATCH 全量改：建一条 daily，PATCH `{name, freq:"weekly", run_at, payload:{...}}` → 200，list 里值已变（freq=weekly、name 新值、payload 字段变）。
- 编辑成 once 过去 → 400。
- 兼容性：PATCH `{enabled:false}`（旧 toggle 路径）仍 200 且 enabled=false（已有测试，确认不破）。

**前端**（`frontend/src/lib/runConfig.test.ts` 新增，vitest）：
- `backendStagesToVisual`：`[1,2,3,4,5,6]→{1,2,4,5,6}`、`[1,2,3]→{1,2}`、`[1,2,3,5,6]`(audio 无 4)`→{1,2,5,6}`、空数组→空集。
- `payloadToDialogState`：aihot payload → `sourceMode==="aihot"` 且 `sourceIds===null`；custom payload(`source_ids`) → `sourceMode==="custom"` 且 `targetIds` 为对应 Set；阶段经 `backendStagesToVisual` 反填。

> 弹窗本身（预填 UI、编辑提交体）走 tsc + build 验证，不强求 jsdom 组件测试（与初版一致）。

## 8. 边界与约束

- 编辑不改 slug：列表 key、scheduler job id 都稳定。
- 编辑不清运行历史（`last_run_*` 保留）。
- 编辑时若某些 `publish_platforms`/`source_ids` 已不可用，弹窗现有的 `effectiveTargetIds`/`effectiveSourceIds` 过滤逻辑会自动剔除不可用项（与新建同款行为）。
- 移除「立即执行」后，手动即时触发不再有 UI 入口（后端端点仍在，可日后需要时再恢复按钮）。
