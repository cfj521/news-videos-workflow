# 计划任务执行时间：按 freq 专用控件 + 每月「月末」 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建/编辑计划弹窗的「执行时间」按间隔类型分化控件（单次=datetime、每日=time、每周=周几+time、每月=1~28+月末+time），每月 29/30/31 统一在当月最后一天执行。

**Architecture:** 保持后端 run_at 锐点模型；前端纯函数 `composeRunAt`/`decomposeRunAt` 在控件值与 run_at 间互转。后端唯一改动：`_trigger_spec` 每月分支 `day>=29 → "last"`（APScheduler 月末）。

**Tech Stack:** APScheduler CronTrigger(day="last")；React/TS + 既有 `Select` 组件；pytest（`conda run -n env_news_videos_wf`）+ vitest（pnpm）。

**依据 spec：** `docs/superpowers/specs/2026-06-09-schedule-time-controls-design.md`

---

## File Structure
- `backend/app/pipeline/scheduler.py` — `_trigger_spec` 每月分支支持「月末」
- `backend/tests/test_scheduler.py` — 月末/普通号数 trigger 测试
- `frontend/src/lib/schedule.ts` — 新增 `composeRunAt`/`decomposeRunAt`/`ScheduleTimeParts`，更新 `formatScheduleSummary` 每月分支
- `frontend/src/lib/schedule.test.ts` — compose/decompose/往返/月末摘要 测试
- `frontend/src/components/CreateRunDialog.tsx` — 执行时间按 freq 渲染控件 + 分件 state + compose 提交 + decompose 预填

环境：后端命令加前缀 `conda run -n env_news_videos_wf`；前端 `pnpm`。分支 `feat/scheduled-tasks` 已检出。**不要启动后端服务。**

---

## Task 1: 后端 `_trigger_spec` 每月「月末」

**Files:**
- Modify: `backend/app/pipeline/scheduler.py`
- Test: `backend/tests/test_scheduler.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_scheduler.py` 末尾追加（文件已有 `_sched(freq, run_at)` 工厂与 `scheduler` import）：

```python
def test_monthly_day_under_29_uses_exact_day():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2024-12-15T08:30:00"))
    assert kind == "cron"
    assert kw == {"day": 15, "hour": 8, "minute": 30}


def test_monthly_day_31_maps_to_last():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2024-12-31T08:30:00"))
    assert kind == "cron"
    assert kw == {"day": "last", "hour": 8, "minute": 30}


def test_monthly_day_29_maps_to_last():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2024-12-29T09:00:00"))
    assert kw["day"] == "last"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && conda run -n env_news_videos_wf python -m pytest tests/test_scheduler.py -v`
Expected: `test_monthly_day_31_maps_to_last` / `test_monthly_day_29_maps_to_last` FAIL（当前返回 `day=31`/`day=29`）。

- [ ] **Step 3: 改 _trigger_spec 每月分支**

在 `backend/app/pipeline/scheduler.py`，把：
```python
    if sched.freq == "monthly":
        return "cron", {"day": dt.day, "hour": dt.hour, "minute": dt.minute}
```
改为：
```python
    if sched.freq == "monthly":
        # 29/30/31 统一 → 每月最后一天（APScheduler day="last"，短月自动顺延）
        day = "last" if dt.day >= 29 else dt.day
        return "cron", {"day": day, "hour": dt.hour, "minute": dt.minute}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && conda run -n env_news_videos_wf python -m pytest tests/test_scheduler.py -v`
Expected: 全 PASS（原有 + 3 新测试）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): 每月 29/30/31 统一在当月最后一天执行（day=last）"
```

---

## Task 2: 前端 compose/decompose 纯函数 + formatScheduleSummary

**Files:**
- Modify: `frontend/src/lib/schedule.ts`
- Test: `frontend/src/lib/schedule.test.ts`

- [ ] **Step 1: 追加失败测试**

在 `frontend/src/lib/schedule.test.ts` 顶部 import 行改为：
```ts
import { describe, it, expect } from "vitest";
import { formatScheduleSummary, composeRunAt, decomposeRunAt } from "./schedule";
```
在文件末尾追加：
```ts
describe("composeRunAt", () => {
  const base = { onceAt: "", tod: "", weekday: 0, monthDay: 1 as number | "last" };
  it("once 原样返回 onceAt", () => {
    expect(composeRunAt("once", { ...base, onceAt: "2026-06-15T08:30" })).toBe("2026-06-15T08:30");
  });
  it("daily → 2000-01-01T<时间>", () => {
    expect(composeRunAt("daily", { ...base, tod: "08:05" })).toBe("2000-01-01T08:05");
  });
  it("weekly 周一(0)→01-01、周日(6)→01-07", () => {
    expect(composeRunAt("weekly", { ...base, tod: "09:00", weekday: 0 })).toBe("2024-01-01T09:00");
    expect(composeRunAt("weekly", { ...base, tod: "09:00", weekday: 6 })).toBe("2024-01-07T09:00");
  });
  it("monthly 15 号 / 月末", () => {
    expect(composeRunAt("monthly", { ...base, tod: "08:00", monthDay: 15 })).toBe("2024-12-15T08:00");
    expect(composeRunAt("monthly", { ...base, tod: "08:00", monthDay: "last" })).toBe("2024-12-31T08:00");
  });
});

describe("decomposeRunAt", () => {
  it("once → onceAt", () => {
    expect(decomposeRunAt("once", "2026-06-15T08:30:00").onceAt).toBe("2026-06-15T08:30");
  });
  it("daily → tod", () => {
    expect(decomposeRunAt("daily", "2000-01-01T08:05:00").tod).toBe("08:05");
  });
  it("weekly 周日 → weekday 6", () => {
    const p = decomposeRunAt("weekly", "2024-01-07T09:00:00");  // 周日
    expect(p.weekday).toBe(6);
    expect(p.tod).toBe("09:00");
  });
  it("monthly day31 → last、day28 → 28", () => {
    expect(decomposeRunAt("monthly", "2024-12-31T08:00:00").monthDay).toBe("last");
    expect(decomposeRunAt("monthly", "2024-12-28T08:00:00").monthDay).toBe(28);
  });
});

describe("compose/decompose 往返", () => {
  it("daily", () => {
    const p = { onceAt: "", tod: "07:30", weekday: 0, monthDay: 1 as number | "last" };
    const back = decomposeRunAt("daily", composeRunAt("daily", p));
    expect(back.tod).toBe("07:30");
  });
  it("weekly", () => {
    const p = { onceAt: "", tod: "07:30", weekday: 3, monthDay: 1 as number | "last" };
    const back = decomposeRunAt("weekly", composeRunAt("weekly", p));
    expect(back.weekday).toBe(3);
    expect(back.tod).toBe("07:30");
  });
  it("monthly last", () => {
    const p = { onceAt: "", tod: "07:30", weekday: 0, monthDay: "last" as number | "last" };
    const back = decomposeRunAt("monthly", composeRunAt("monthly", p));
    expect(back.monthDay).toBe("last");
  });
});

describe("formatScheduleSummary monthly 月末", () => {
  it("day31 → 每月月末", () => {
    expect(formatScheduleSummary("monthly", "2024-12-31T08:00:00")).toBe("每月月末 08:00");
  });
  it("day15 → 每月 15 号（保留）", () => {
    expect(formatScheduleSummary("monthly", "2026-06-15T08:00:00")).toBe("每月 15 号 08:00");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && pnpm exec vitest run src/lib/schedule.test.ts`
Expected: FAIL（`composeRunAt`/`decomposeRunAt` 不存在；月末摘要用例失败）。

- [ ] **Step 3: 实现 compose/decompose + 改 formatScheduleSummary**

把 `frontend/src/lib/schedule.ts` 整体替换为：
```ts
import type { ScheduleFreq } from "../types";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** 把「freq + 锚点 run_at」格式化为人类可读的规则摘要。run_at 为本地 naive ISO 串。 */
export function formatScheduleSummary(freq: ScheduleFreq, runAt: string): string {
  const d = new Date(runAt);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const time = `${hh}:${mm}`;
  if (freq === "daily") return `每天 ${time}`;
  if (freq === "weekly") return `每${WEEKDAYS[d.getDay()]} ${time}`;
  if (freq === "monthly") return d.getDate() >= 29 ? `每月月末 ${time}` : `每月 ${d.getDate()} 号 ${time}`;
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return `${date} ${time}（单次）`;
}

export type ScheduleTimeParts = {
  onceAt: string;            // datetime-local 串 "YYYY-MM-DDTHH:mm"（仅 once 用）
  tod: string;              // "HH:mm"（daily/weekly/monthly 用）
  weekday: number;          // 0=周一..6=周日（weekly 用）
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
  const day = d.getDate();
  return { ...base, tod, monthDay: day >= 29 ? "last" : day };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && pnpm exec vitest run src/lib/schedule.test.ts`
Expected: PASS（原有 + 新增全过）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/schedule.ts frontend/src/lib/schedule.test.ts
git commit -m "feat(ui): composeRunAt/decomposeRunAt + formatScheduleSummary 月末显示"
```

---

## Task 3: 弹窗执行时间按 freq 渲染控件

**File:** Modify `frontend/src/components/CreateRunDialog.tsx`

> 关键：删除单一 `runAt` state，改为 `onceAt/tod/weekday/monthDay` 四件；提交时 `composeRunAt`，编辑时 `decomposeRunAt` 预填。`handleSubmit` 里引入局部 `const runAt = composeRunAt(...)`，使现有 4 处 `runAt` 引用（name 摘要 / run_at 字段）无需逐个改。

- [ ] **Step 1: import 增加 compose/decompose**

把第 8 行 `import { formatScheduleSummary } from "../lib/schedule";` 改为：
```tsx
import { formatScheduleSummary, composeRunAt, decomposeRunAt } from "../lib/schedule";
```

- [ ] **Step 2: 替换 runAt state 为四件 + timeReady**

把第 54 行：
```tsx
  const [runAt, setRunAt] = useState(edit ? edit.run_at.slice(0, 16) : "");  // ISO→datetime-local（截到分）
```
替换为：
```tsx
  // 执行时间分件：once 用 onceAt；其余用 tod(HH:mm)；weekly 用 weekday；monthly 用 monthDay
  const [tparts] = useState(() => (edit ? decomposeRunAt(edit.freq, edit.run_at) : null));
  const [onceAt, setOnceAt] = useState(tparts?.onceAt ?? "");
  const [tod, setTod] = useState(tparts?.tod ?? "");
  const [weekday, setWeekday] = useState<number>(tparts?.weekday ?? 0);
  const [monthDay, setMonthDay] = useState<number | "last">(tparts?.monthDay ?? 1);
```
然后在 `const [scheduleName, ...]` 那一行之后，新增一行派生 const：
```tsx
  const timeReady = freq === "once" ? !!onceAt : !!tod;
```

- [ ] **Step 3: handleSubmit 顶部计算 runAt**

在 `handleSubmit` 的 `setLoading(true);` 与 `try {` 之后、`const payload = {` 之前，插入一行：
```tsx
      const runAt = composeRunAt(freq, { onceAt, tod, weekday, monthDay });
```
（其余 `name: scheduleName.trim() || formatScheduleSummary(freq, runAt)` 与 `run_at: runAt` 各 2 处保持不变 —— 现在它们引用这个局部 `runAt`。）

- [ ] **Step 4: 替换「执行时间」控件块**

把第 220-223 行：
```tsx
            <div>
              <label className={labelCls}>执行时间</label>
              <input type="datetime-local" value={runAt} onChange={(e) => setRunAt(e.target.value)} className={inputCls} />
            </div>
```
替换为：
```tsx
            <div>
              <label className={labelCls}>执行时间</label>
              {freq === "once" && (
                <input type="datetime-local" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} className={inputCls} />
              )}
              {freq === "daily" && (
                <input type="time" value={tod} onChange={(e) => setTod(e.target.value)} className={inputCls} />
              )}
              {freq === "weekly" && (
                <div className="flex gap-2">
                  <Select value={String(weekday)} onChange={(v) => setWeekday(Number(v))} options={[
                    { value: "0", label: "周一" }, { value: "1", label: "周二" }, { value: "2", label: "周三" },
                    { value: "3", label: "周四" }, { value: "4", label: "周五" }, { value: "5", label: "周六" }, { value: "6", label: "周日" },
                  ]} />
                  <input type="time" value={tod} onChange={(e) => setTod(e.target.value)} className={inputCls} />
                </div>
              )}
              {freq === "monthly" && (
                <div className="flex gap-2">
                  <Select value={typeof monthDay === "number" ? String(monthDay) : "last"}
                    onChange={(v) => setMonthDay(v === "last" ? "last" : Number(v))}
                    options={[...Array.from({ length: 28 }, (_, i) => ({ value: String(i + 1), label: `${i + 1} 号` })), { value: "last", label: "月末（最后一天）" }]} />
                  <input type="time" value={tod} onChange={(e) => setTod(e.target.value)} className={inputCls} />
                </div>
              )}
            </div>
```

- [ ] **Step 5: 名称占位符改用 composeRunAt**

把第 227 行：
```tsx
                placeholder={runAt ? formatScheduleSummary(freq, runAt) : "如：每日AI日报"} className={inputCls} />
```
替换为：
```tsx
                placeholder={timeReady ? formatScheduleSummary(freq, composeRunAt(freq, { onceAt, tod, weekday, monthDay })) : "如：每日AI日报"} className={inputCls} />
```

- [ ] **Step 6: 提示文案改写（去掉旧 29~31 跳过，加月末提示）**

把第 229-234 行：
```tsx
            <p className="col-span-2 text-[11px] text-white/40 leading-snug">
              {freq === "once"
                ? "在所选时刻执行一次。"
                : "所选日期为锚点，之后按间隔在该时分重复。"}
              {freq === "monthly" && new Date(runAt || 0).getDate() >= 29 && " 注意：部分月份无 29~31 号，当月将跳过。"}
            </p>
```
替换为：
```tsx
            <p className="col-span-2 text-[11px] text-white/40 leading-snug">
              {freq === "once"
                ? "在所选时刻执行一次。"
                : "按所选间隔在该时间重复执行。"}
              {freq === "monthly" && monthDay === "last" && " 每月最后一天执行（短月自动顺延，如 2 月跑 28/29 号）。"}
            </p>
```

- [ ] **Step 7: 提交按钮就绪条件改 timeReady**

把第 411 行 `(isSchedule && !runAt)` 改为 `(isSchedule && !timeReady)`：
```tsx
          <button onClick={handleSubmit} disabled={loading || effectiveVisual.size === 0 || (isSchedule && !timeReady)} className={btnPrimary}>
```

- [ ] **Step 8: 类型检查与构建**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`
Expected: 通过（确认旧 `runAt`/`setRunAt` 已无残留引用 → 无 TS 未定义错误）。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(ui): 执行时间按 freq 专用控件（每日 time/每周 周几/每月 1-28+月末）"
```

---

## Task 4: 端到端校验

- [ ] **Step 1: 后端全量**

Run: `cd backend && conda run -n env_news_videos_wf python -m pytest -q`
Expected: 全绿。

- [ ] **Step 2: 前端本次文件 eslint + vitest + build**

Run:
```
cd frontend && pnpm exec eslint src/components/CreateRunDialog.tsx src/lib/schedule.ts
pnpm exec vitest run
pnpm build
```
Expected: 本次文件 eslint exit 0；vitest 全过；build 成功。
> 仓库全量 `pnpm lint` 有 12 条既有 set-state-in-effect 报错（App/Toast/Dashboard/Settings），与本次无关，不修。

- [ ] **Step 3: 无新增改动则结束**

仅校验。如有问题回到对应 Task 修复。

---

## 自查与手动验收

- 新建计划：间隔切到「每周」→ 出现「周几 + 时间」；切「每月」→ 出现「1~28 + 月末 + 时间」；选「月末」显示顺延提示；时间未选时「创建计划」置灰。
- 选「每月 / 月末 / 09:00」创建 → 列表显示「每月月末 09:00」；点该行编辑 → 间隔=每月、几日=月末、时间=09:00 正确回填。
- 选「每周 / 周三 / 08:00」→ 列表「每周三 08:00」；编辑回填周三。
- 单次仍用 datetime；编辑单次回填年月日时分。
- **YAGNI**：未做「精确 N 号仅缺失月退月末」；29/30/31 统一月末。
