# 计划任务执行时间：按 freq 专用控件 + 每月「月末」 设计

> 状态：待评审
> 日期：2026-06-09
> 关联：`2026-06-09-scheduled-tasks-design.md`（本体）、`2026-06-09-edit-scheduled-tasks-design.md`（编辑）

## 1. 目标

把创建/编辑计划弹窗里的「执行时间」从单一 `datetime-local` 改为按间隔类型分化的控件：

| freq | 控件 |
|---|---|
| 单次 once | `<input type="datetime-local">`（年月日时分） |
| 每日 daily | `<input type="time">`（时:分） |
| 每周 weekly | 周几下拉 + `<input type="time">` |
| 每月 monthly | 几日下拉（1—28 + 「月末」）+ `<input type="time">` |

并把「每月 29~31」的语义从"当月无此日就跳过"改为**在当月最后一天执行**（29/30/31 统一 = 月末）。

**保持 run_at 锐点模型**：后端仍只存一个 `run_at`，前端把控件值拼成合法 `run_at`、编辑时反推回控件值。后端唯一改动是 `_trigger_spec` 每月分支支持「月末」。

**非目标**：精确「N 号，仅缺失月份退月末」（APScheduler cron 无法单表达式表示 29/30 或月末，成本高，已与用户确认放弃）；改 store/schema/类型/列表页结构。

## 2. 后端（唯一改动：`_trigger_spec` 每月分支）

`backend/app/pipeline/scheduler.py` 的 `_trigger_spec`，把每月分支：
```python
    if sched.freq == "monthly":
        return "cron", {"day": dt.day, "hour": dt.hour, "minute": dt.minute}
```
改为：
```python
    if sched.freq == "monthly":
        day = "last" if dt.day >= 29 else dt.day   # 29/30/31 统一 → 每月最后一天
        return "cron", {"day": day, "hour": dt.hour, "minute": dt.minute}
```

- APScheduler `CronTrigger(day="last", ...)` = 每月最后一天（1月31 / 2月28或29 / 4月30…）。
- `dt.day >= 29` 覆盖 29/30/31，对历史上可能已存的 29/30 月度计划也统一按月末处理。
- once/daily/weekly 分支不变；`run_at` 仍是唯一真相源，本规则从 `run_at.day` 派生。

其余后端（store / schema / api / 一次性过期校验）全部不动。

## 3. 前端拼装 / 反推纯函数（`frontend/src/lib/schedule.ts`）

新增两个纯函数（与现有 `formatScheduleSummary` 同文件）：

```ts
export type ScheduleTimeParts = {
  onceAt: string;          // datetime-local 串 "YYYY-MM-DDTHH:mm"（仅 once 用）
  tod: string;             // "HH:mm"（daily/weekly/monthly 用）
  weekday: number;         // 0=周一..6=周日（weekly 用）
  monthDay: number | "last"; // 1..28 或 "last"=月末（monthly 用）
};

/** 控件值 → 合法 run_at（naive 本地串）。日期部分对周期任务只是载体（后端只读时/分/周几/号）。 */
export function composeRunAt(freq: ScheduleFreq, p: ScheduleTimeParts): string {
  if (freq === "once") return p.onceAt;
  if (freq === "daily") return `2000-01-01T${p.tod}`;
  if (freq === "weekly") return `2024-01-0${p.weekday + 1}T${p.tod}`;  // 2024-01-01 是周一
  // monthly：12 月有 31 天，可承载 1..31；"last" 用 31 承载，后端据 day>=29 映射为 last
  const dd = p.monthDay === "last" ? "31" : String(p.monthDay).padStart(2, "0");
  return `2024-12-${dd}T${p.tod}`;
}

/** run_at → 控件值（编辑预填）。不相关字段给默认。 */
export function decomposeRunAt(freq: ScheduleFreq, runAt: string): ScheduleTimeParts {
  const base: ScheduleTimeParts = { onceAt: "", tod: "", weekday: 0, monthDay: 1 };
  if (freq === "once") return { ...base, onceAt: runAt.slice(0, 16) };
  const tod = runAt.slice(11, 16);
  if (freq === "daily") return { ...base, tod };
  const d = new Date(runAt);
  if (freq === "weekly") return { ...base, tod, weekday: (d.getDay() + 6) % 7 };
  // monthly
  const day = d.getDate();
  return { ...base, tod, monthDay: day >= 29 ? "last" : day };
}
```

**周几约定钉死**：UI 周一=0…周日=6，与后端 Python `weekday()` 一致。`composeRunAt` weekly 用真实周一基准（2024-01-01），`decomposeRunAt` 用 `(getDay()+6)%7`（JS 周日=0 → 周一=0）。

**`2024-01-0${weekday+1}`**：weekday 0..6 → 日 1..7，均个位，`0${n}` 安全得 `01`..`07`（2024-01-01 周一 … 2024-01-07 周日）。

## 4. 列表显示（`formatScheduleSummary` 每月分支）

现有每月：`每月 ${d.getDate()} 号 ${time}`。改为：
```ts
if (freq === "monthly") {
  return d.getDate() >= 29 ? `每月月末 ${time}` : `每月 ${d.getDate()} 号 ${time}`;
}
```
（其余 once/daily/weekly 分支不变。原「每月 15 号」用例保留，新增「月末」用例。）

## 5. 弹窗控件（`frontend/src/components/CreateRunDialog.tsx`）

把现有单一 `runAt` 状态替换为分件状态：
```tsx
const [onceAt, setOnceAt] = useState("");                              // datetime-local
const [tod, setTod] = useState("");                                    // time，默认空强制选
const [weekday, setWeekday] = useState(0);                             // 0=周一..6=周日
const [monthDay, setMonthDay] = useState<number | "last">(1);
```
编辑预填：在 `init` 旁，`const tparts = edit ? decomposeRunAt(edit.freq, edit.run_at) : null;` 用其初始化以上四个 state（`tparts?.onceAt ?? ""` 等；monthDay 用 `tparts?.monthDay ?? 1`）。

排期区「执行时间」按 `freq` 渲染：
- once：`<input type="datetime-local" value={onceAt} onChange=... />`
- daily：`<input type="time" value={tod} onChange=... />`
- weekly：周几 `<Select>`（选项 周一..周日，value 0..6）+ time
- monthly：几日 `<Select>`（选项 1..28 各一项 + `{ value: "last", label: "月末（最后一天）" }`）+ time；选 "last" 时下方提示「每月最后一天执行（短月自动顺延）」

> Select 的 value 是字符串：weekday/monthDay 在 onChange 里做 Number/"last" 解析；monthDay Select 的 value 用 `String(monthDay)`，"last" 原样。

**就绪判定**：`const timeReady = freq === "once" ? !!onceAt : !!tod;` 提交按钮 `disabled` 用 `(isSchedule && !timeReady)` 取代原来的 `(isSchedule && !runAt)`。

**提交**：`handleSubmit` 里先 `const runAt = composeRunAt(freq, { onceAt, tod, weekday, monthDay });`，再在三态提交里用这个 `runAt`（替代原先直接用的 `runAt` state）。`name` 默认仍 `scheduleName.trim() || formatScheduleSummary(freq, runAt)`。

**名称占位符**：现有 `placeholder={runAt ? formatScheduleSummary(freq, runAt) : "如：每日AI日报"}` 改为基于 `timeReady ? formatScheduleSummary(freq, composeRunAt(...)) : "如：每日AI日报"`。

> 移除原排期区里那段基于 `new Date(runAt||0).getDate()>=29` 的旧「29~31 当月跳过」提示（语义已变）；改为 monthly 选「月末」时的新提示文案。

## 6. 数据流

```
控件（onceAt/tod/weekday/monthDay）
  → composeRunAt(freq) → run_at（once 真实；daily/weekly/monthly 为载体）
  → POST/PATCH /api/schedules → store run_at
触发：_trigger_spec(run_at) → once=DateTrigger；daily/weekly=Cron(时/分[/周几])；
       monthly=Cron(day = day>=29 ? "last" : day, 时/分)
编辑：decomposeRunAt(freq, run_at) → 回填控件
列表：formatScheduleSummary(freq, run_at)（月末显示「每月月末」）
```

## 7. 测试

**后端**（`backend/tests/test_scheduler.py` 追加）：
- monthly day=15 → `("cron", {"day": 15, "hour":.., "minute":..})`
- monthly day=31 → `day == "last"`；day=29 → `day == "last"`（≥29 边界）

**前端**（`frontend/src/lib/schedule.test.ts` 追加）：
- `composeRunAt`：once 原样；daily→`2000-01-01THH:mm`；weekly weekday=0→01-01(周一)、=6→01-07(周日)；monthly 15→`2024-12-15`、"last"→`2024-12-31`。
- `decomposeRunAt`：各 freq 反推；weekly 周日 run_at→weekday=6；monthly day31→"last"、day28→28。
- **往返**：对每个 freq，`decomposeRunAt(freq, composeRunAt(freq, parts))` 等于原 parts（取该 freq 相关字段）。
- `formatScheduleSummary`：monthly day31/29 → 「每月月末 HH:mm」；day15 → 「每月 15 号」（原用例保留）。

弹窗本身走 tsc + build 验证（不强求组件测试）。

## 8. 边界与约束

- daily/weekly/monthly 的 `run_at` 日期是合成载体（2000-01-01 / 2024-01-0X / 2024-12-DD），仅其时/分/周几/号被后端读取；DateTrigger 仅 once 用，故合成日期无副作用。
- 历史已存的 monthly 计划：day 1–28 行为不变；day 29/30/31（若旧 UI 建过）现在统一按月末触发。
- 周几/月末经由真实 run_at 编码，`formatScheduleSummary` 与 `_trigger_spec` 各自从 run_at 派生，保持一致。
- 时区沿用既有（后端进程本地时区，naive run_at）。
