# 计划任务（定时自动建流水线任务）设计

> 状态：待评审
> 日期：2026-06-09
> 说明：本版按 2026-06-09 会话的明确决策重写。与初版的差异：调度引擎改用 **APScheduler**（初版为自建轮询线程）；执行时间改为**单个 datetime-local 锚点**（初版为按 freq 拆分的时/分/周几/号字段）；**复用「新建任务」弹窗**而非独立 ScheduleDialog。存储沿用初版的 `schedule.yaml`（YAML store）。

## 1. 目标

在「工作台」后新增「计划任务」tab，并在工作台「+ 新建任务」左侧加「+ 计划任务」按钮。用户保存一份「建任务参数 + 排期规则」；到点后系统用这份参数（强制 `mode=auto` 全自动）自动创建并运行一条 pipeline run。创建出的 run 出现在「工作台」任务列表，与手动建的无区别，监控/结果复用现有 UI。

**非目标**：分布式调度、错过任务的批量回灌、跨时区/夏令时处理、编辑已有排期（YAGNI，先只做 增 / 删 / 启停 / 立即执行）。单用户本地应用，按服务器本地时间排期。

## 2. 排期模型

一条计划任务 = **间隔（freq）** + **锚点时刻（run_at）** + **建任务参数（payload）**。

| freq | 含义 | 触发规则（锚点 = run_at，本地时刻，精确到分） |
|---|---|---|
| `once` | 单次 | 在 run_at 跑一次；触发后自动 `enabled=false` |
| `daily` | 每日 | 每天的 `run_at 的时:分` |
| `weekly` | 每周 | 每周 `run_at 的星期几` 的 `时:分` |
| `monthly` | 每月 | 每月 `run_at 的号数` 的 `时:分` |

- **前端只采集一个 `datetime-local`（年月日时分）作为锚点**，外加一个 freq 下拉。daily/weekly/monthly 的时:分、星期几、号数全部从锚点 run_at **派生**，不单独出字段。
- **强制全自动**：触发时 payload 的 `mode` 一律覆写为 `auto`，避免无人值守时卡在手动审核（review）等人超时。弹窗在计划模式下把「运行模式」锁死为「自动」。
- **monthly 的号数边界**：APScheduler `CronTrigger(day=N)` 对没有 N 号的月份（如 2 月 30 号）当月不触发。锚点日 1~28 安全；若用户选了 29~31，前端给出提示「部分月份无此日期将跳过」（不强制拦截）。
- **星期约定**：用 Python `date.weekday()`（0=周一…6=周日），映射到 APScheduler `CronTrigger(day_of_week=...)`（APScheduler 接受 0-6 = 周一-周日，与之一致）。

## 3. 存储 —— `schedule.yaml`（仓库根目录）

与「信息源 / 发布账号」一致，走 `app/store` 的 YAML store 模式（不进 DB）。路径取 `Path(__file__).resolve().parents[3] / "schedule.yaml"`。

```yaml
schedules:
  <slug>:                          # 主键，由 name slugify 生成，冲突加数字后缀
    name: "每日AI日报"
    enabled: true
    freq: daily                    # once | daily | weekly | monthly
    run_at: "2026-06-15T08:00:00"  # 锚点本地时刻（ISO，无时区）；精确到分
    created_at: "2026-06-09T10:00:00+00:00"
    last_run_at: "2026-06-08T08:00:05+00:00"  # 上次触发时刻，无则 null
    last_run_id: 42                # 上次触发创建的 PipelineRun id，无则 null
    payload:                       # 整份建任务参数（触发时 mode 覆写为 auto）
      video_route: hyperframes
      time_range: "7d"
      max_articles: 5
      selected_stages: [1, 2, 3, 4, 5, 6]
      publish_platforms: ["youtube_main"]
      resolution: "1080x1920"
      language: "zh"
      max_images: 10
      auto_collect: true
      source_ids: null
      aihot_config: { method: "items" }
```

- `payload` 用单个嵌套 dict 存整份建任务参数 —— 将来「新建任务」加参数时计划任务自动跟上，不用改结构。
- `schedule.yaml` 加入 `.gitignore`，并提供 `schedule.yaml.example` 模板（对齐 `news_sources.yaml.example` / `publish_targets.yaml.example`）。

### Store 模块 `app/store/schedules_store.py`

仿 `targets_store.py`：

- `ScheduleData(BaseModel)`：`slug / name / enabled / freq / run_at / created_at / last_run_at / last_run_id / payload`。
- `list_schedules() / get_schedule(slug) / create_schedule(...) / update_schedule(slug, patch) / delete_schedule(slug)`。
- 写操作用 `_io.file_lock(SCHEDULE_PATH)` 包「读-改-写」，`_io.save_yaml` 原子落盘。
- `ensure_file()` 在不存在时写 `{"schedules": {}}` 占位。

## 4. 调度 —— APScheduler

依赖：`requirements.txt` 增加 `APScheduler`。

引擎：用 `apscheduler.schedulers.background.BackgroundScheduler`（同步线程模型，与现有 `serial_executor` 常驻 daemon 线程风格一致；job 内部只是把作业 `serial_submit` 进现有串行队列，不与异步事件循环耦合）。**调度器内存运行，`schedule.yaml` 是唯一真相源**，启动时从 YAML 重新注册（不使用 APScheduler 的 SQLAlchemyJobStore —— 那会 pickle job、难以做干净的列表/管理）。

模块 `app/pipeline/scheduler.py`：

- 单例 `_scheduler`（模块级），`get_scheduler()` 懒构造。
- `freq → trigger` 映射（`run_at` 解析为 `datetime`）：
  - `once` → `DateTrigger(run_date=run_at)`
  - `daily` → `CronTrigger(hour=run_at.hour, minute=run_at.minute)`
  - `weekly` → `CronTrigger(day_of_week=run_at.weekday(), hour=run_at.hour, minute=run_at.minute)`
  - `monthly` → `CronTrigger(day=run_at.day, hour=run_at.hour, minute=run_at.minute)`
  - 所有 trigger 统一 `misfire_grace_time=300`、`coalesce=True` —— 宕机期间错过的触发**至多补跑一次**，不回灌历史。
- `register(sched: ScheduleData)`：按 `id=slug` 加/替换 job（`replace_existing=True`）；`enabled=false` 的不注册。
- `unregister(slug)`：`remove_job(slug)`（忽略不存在）。
- `reload_all(session_factory)`：清空后从 `list_schedules()` 重新注册所有启用项；启动时调用。
- `start_scheduler(session_factory)` / `shutdown_scheduler()`：供 lifespan 拉起/停止。
- **job 函数 `_fire(slug, session_factory)`**（与「立即执行」API 共用）：
  1. 开 DB session，`get_schedule(slug)`，禁用则跳过。
  2. `run = PipelineEngine(db).create_run(**{**payload, "mode": "auto"})`。
  3. `serial_submit(_run_pipeline_bg, run.id, session_factory, label=f"sched:{slug}#{run.id}")` —— **与 `POST /api/pipeline/runs` 完全相同的执行路径**。
  4. 回写 store：`update_schedule(slug, {"last_run_at": now, "last_run_id": run.id})`；`freq=="once"` 额外 `{"enabled": False}` 并 `unregister(slug)`。
  5. 异常隔离：单条失败写日志，不影响调度器其余 job。

`_run_pipeline_bg` 复用 `app/api/pipeline.py` 中已有的同名函数（必要时下沉到 runner 以避免循环 import）。

## 5. 启动接线 —— `main.py` lifespan

在现有 `lifespan` 的 `yield` 之前、`seed_default_admin` 之后调用 `start_scheduler(factory)`（DB / store 已就绪）；`yield` 之后 `shutdown_scheduler()`。`schedules_store.ensure_file()` 一并在启动迁移阶段调用，保证文件存在。

## 6. API `app/api/schedules.py`（前缀 `/api/schedules`，登录守卫）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/schedules` | 列表（含计算出的 `next_run_at`，取自 `scheduler.get_job(slug).next_run_time`） |
| POST | `/api/schedules` | 创建（写 store + `register`） |
| PATCH | `/api/schedules/{slug}` | 启停（`enabled` 改写 + `register`/`unregister`） |
| DELETE | `/api/schedules/{slug}` | 删除（`delete_schedule` + `unregister`） |
| POST | `/api/schedules/{slug}/run-now` | 立即手动触发一次：复用 `_fire(slug)`，**计入** `last_run_at`/`last_run_id`（与到点触发一致，便于看「上次跑」）；不改变后续排期节奏 |

校验：

- `freq=="once"` 且 `run_at <= now` → 400「执行时间已过去」。
- 周期任务锚点在过去允许（APScheduler 自动算下一次）。
- `payload` 用 `PipelineRunCreate` 校验（复用现有 schema），但提交时 `mode` 由后端强制 `auto`。

Schemas `app/schemas/schedule.py`：

- `ScheduleCreate`：`name: str`、`freq: Literal["once","daily","weekly","monthly"]`、`run_at: datetime`、`enabled: bool = True`、`payload: PipelineRunCreate`。
- `ScheduleRead`：上述 + `slug / next_run_at / last_run_at / last_run_id / created_at`。

在 `app/api/router.py` 以 `dependencies=_guard` 注册 `schedules_router`。

## 7. 前端

### 7.1 复用「新建任务」弹窗

`CreateRunDialog` 加两个可选 prop：

```ts
interface Props {
  onCreated: () => void;
  onClose: () => void;
  schedule?: boolean;          // true = 计划模式
  onScheduled?: () => void;    // 计划创建成功回调（schedule 模式下用它替代 onCreated）
}
```

计划模式（`schedule===true`）下：

- 标题改「新建计划任务」。
- 顶部加「计划」区：**间隔**下拉（单次/每日/每周/每月）+ **执行时间** `<input type="datetime-local">`（年月日时分）。
- 「运行模式」锁死「自动」（隐藏 manual 选项或置灰），`autoCollect` 维持自动逻辑不变。
- 提交改调 `api.schedules.create({ name, freq, run_at, payload: {...现有建任务参数, mode:"auto"} })`，成功走 `onScheduled`。
- 间隔为 daily/weekly/monthly 时，datetime-local 仍要求选完整日期（作为锚点）；UI 加一行小字说明「日期作为首次/锚点，之后按间隔重复」。

> `name`：默认用规则摘要自动填（如「每日 08:00」），允许用户改；存 store 时 slugify 作主键。

### 7.2 工作台按钮

`Dashboard.tsx` 标题行：在 `+ 新建任务` 左侧加 `+ 计划任务` 按钮（`btnSecondary` 风格），点击打开 `CreateRunDialog schedule`。

### 7.3 计划任务 tab

- `App.tsx` 的 `navItems` 在「工作台」后插入 `{ to: "/schedules", label: "计划任务" }`，并加 `<Route path="/schedules" element={<SchedulesPage />} />`。
- 新增 `pages/Schedules.tsx`：列表卡片显示 **名称**、**规则摘要**（「每天 08:00」/「每周一 09:00」/「每月 15 号 08:00」/「2026-06-15 08:00（单次）」）、**下次执行**（`next_run_at`）、**上次执行**（`last_run_at` + run 链接跳工作台）、**启用/停用开关**、**删除**、**立即执行**。页内也放一个 `+ 计划任务` 按钮。
- `api/client.ts` 加 `api.schedules.{ list, create, toggle, remove, runNow }`；`types` 加 `Schedule` 类型。

## 8. 数据流

```
用户 → CreateRunDialog(schedule) → POST /api/schedules
     → schedule.yaml 写入一条（payload + freq + run_at）+ scheduler.register
APScheduler 到点 → _fire(slug)
     → PipelineEngine.create_run(**payload, mode=auto) + serial_submit
     → PipelineRun（出现在工作台任务列表，与手动建的一致）
     → 回写 last_run_at / last_run_id（once: enabled=false + unregister）
```

## 9. 测试

- **trigger 映射**（`app/pipeline/scheduler.py` 纯函数 `_trigger_for(sched)`）：once/daily/weekly/monthly 各产出正确的 trigger 类型与字段（hour/minute/day_of_week/day = run_at 派生值）。
- **store** `schedules_store`：临时 yaml 上 create/list/update(启停)/delete 往返。
- **API**：创建（once 过期 → 400）、列表（带 next_run_at）、启停、删除、run-now（mock `serial_submit` / `_fire`）。
- **_fire**：到期触发能调 `create_run`（mode 被强制 auto）+ `serial_submit`，并回写 last_run_*；once 触发后 enabled=false（mock store / serial_submit）。
- **前端**（vitest，最小）：计划模式弹窗提交 body 形状（freq/run_at/payload.mode==="auto"）。

## 10. 边界与约束

- 后端必须运行才会触发（本地单用户应用，符合现有部署）。
- 进程重启不丢计划（存 yaml，启动 `reload_all` 重注册）；正在排队/正在跑的触发若重启会丢，与现有 BackgroundTasks/serial 队列行为一致。
- 按服务器本地时间排期，不处理时区/夏令时。
- monthly 锚点日 29~31 在缺失该日的月份当月不触发（APScheduler 行为），前端给提示不拦截。
