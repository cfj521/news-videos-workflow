# 计划任务（定时自动建流水线任务）设计

> 状态：待评审
> 日期：2026-06-09
> 说明：本版按 2026-06-09 会话的明确决策重写。与初版的差异：调度引擎改用 **APScheduler**（初版为自建轮询线程）；执行时间改为**单个 datetime-local 锚点**（初版为按 freq 拆分的时/分/周几/号字段）；**复用「新建任务」弹窗**而非独立 ScheduleDialog。存储沿用初版的 `schedule.yaml`（YAML store）。

## 1. 目标

在「工作台」后新增「计划任务」tab，「+ 计划任务」按钮放在该 tab 页面内（不在工作台）。用户保存一份「建任务参数 + 排期规则」；到点后系统用这份参数（强制 `mode=auto` 全自动）自动创建并运行一条 pipeline run。创建出的 run 出现在「工作台」任务列表，与手动建的无区别，监控/结果复用现有 UI。

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
- **发版硬门槛**：`schedule.yaml` 必须加入 `.gitignore`（当前 `.gitignore:28-31` 列了 config/model_providers/publish_targets/news_sources 但**漏了它**；payload 内含发布账号 slug 等本地运行态数据，绝不能入库），并提供 `schedule.yaml.example` 模板（对齐 `news_sources.yaml.example` / `publish_targets.yaml.example`）。实现 PR 必须同时改这两处。

### Store 模块 `app/store/schedules_store.py`

仿 `targets_store.py`：

- `ScheduleData(BaseModel)`：`slug / name / enabled / freq / run_at / created_at / last_run_at / last_run_id / payload`。
- `list_schedules() / get_schedule(slug) / create_schedule(...) / update_schedule(slug, patch) / delete_schedule(slug)`。
- 写操作用 `_io.file_lock(SCHEDULE_PATH)` 包「读-改-写」，`_io.save_yaml` 原子落盘。
- `ensure_file()` 在不存在时写 `{"schedules": {}}` 占位。

## 4. 调度 —— APScheduler

依赖：`requirements.txt` 增加 `APScheduler>=3.10` 和 `tzlocal`（见下「时区」，不靠传递依赖）。

引擎：用 `apscheduler.schedulers.background.BackgroundScheduler`（同步线程模型，与现有 `serial_executor` 常驻 daemon 线程风格一致；job 内部只是把作业 `serial_submit` 进现有串行队列，不与异步事件循环耦合）。**调度器内存运行，`schedule.yaml` 是唯一真相源**，启动时从 YAML 重新注册（不使用 APScheduler 的 SQLAlchemyJobStore —— 那会 pickle job、难以做干净的列表/管理）。

**时区（关键，必须显式处理）**：APScheduler 默认用 `tzlocal.get_localzone()`，会给 naive 的 `run_at` 附加该时区。本项目 Docker 跑在 WSL 容器（见部署约定），容器默认常为 UTC，会让用户预期的「本地 08:00」变成「UTC 08:00」偏 8 小时。因此：
- 构造调度器时**显式传 `timezone=`**（从 `tzlocal.get_localzone()` 显式取，或读 config 指定），不依赖隐式默认。
- `requirements.txt` 显式加 `APScheduler>=3.10` **和 `tzlocal`**（不靠传递依赖）。
- 部署文档提醒 Docker/WSL 需设 `TZ` 环境变量与宿主一致。

模块 `app/pipeline/scheduler.py`：

- 单例 `_scheduler`（模块级），`get_scheduler()` 懒构造。
- `freq → trigger` 映射（`run_at` 解析为 `datetime`）：
  - `once` → `DateTrigger(run_date=run_at)`
  - `daily` → `CronTrigger(hour=run_at.hour, minute=run_at.minute)`
  - `weekly` → `CronTrigger(day_of_week=run_at.weekday(), hour=run_at.hour, minute=run_at.minute)`
  - `monthly` → `CronTrigger(day=run_at.day, hour=run_at.hour, minute=run_at.minute)`
  - 所有 trigger 统一 `coalesce=True`、`misfire_grace_time=300`。准确语义：错过的触发**只有落在 5 分钟宽限窗内**才会（被 coalesce 合并为一次）补跑；宕机超过 5 分钟才重启则**直接丢弃、不补跑**。对 daily/weekly/monthly（间隔远大于 5min）即「重启不在到点后 5 分钟内就不补」。若产品要「宕机后补当天遗漏」，需单独调大 `misfire_grace_time`（如 daily 设 3600+）——当前取舍为**不回灌**。
- `register(sched: ScheduleData)`：按 `id=slug` 加/替换 job（`replace_existing=True`）；`enabled=false` 的不注册。
- `unregister(slug)`：`remove_job(slug)`（忽略不存在）。
- `reload_all(session_factory)`：清空后从 `list_schedules()` 重新注册所有启用项；启动时调用。
- `start_scheduler(session_factory)` / `shutdown_scheduler()`：供 lifespan 拉起/停止。
- **job 函数 `_fire(slug, session_factory)`**（与「立即执行」API 共用）：
  1. **取该 slug 的执行锁**（模块级 `dict[slug] -> threading.Lock`，`non-blocking acquire`）——拿不到说明同一 slug 正在 `_fire`（到点触发与 run-now 撞车），直接跳过，避免重复建任务。`try/finally` 释放。
  2. 开 DB session，`get_schedule(slug)`，禁用则跳过。
  3. `run = PipelineEngine(db).create_run(**{**payload, "mode": "auto"})`。
  4. `serial_submit(_run_pipeline_bg, run.id, session_factory, label=f"sched:{slug}#{run.id}")` —— **与 `POST /api/pipeline/runs` 完全相同的执行路径**。
  5. 回写 store：`update_schedule(slug, {"last_run_at": now, "last_run_id": run.id})`；`freq=="once"` 额外 `{"enabled": False}` 并 `unregister(slug)`。
  6. 异常隔离：单条失败写日志，不影响调度器其余 job。

**`_run_pipeline_bg` 必须先下沉到 `app/pipeline/runner.py`**（当前它在 `app/api/pipeline.py:94`，body 仅 `asyncio.run(execute_pipeline(...))`）。调度层由 `main.py` lifespan 拉起，若 import `app.api.pipeline` 会把调度层反向耦合到 API 层、引入循环 import。`runner.py` 顶层不 import 任何 `app.api.*`，是干净下层。下沉后 `app/api/pipeline.py` 从 runner re-export 该函数（保持原路由不变），`scheduler.py` 只 import runner。**这是实现前置步骤，非可选。**

## 5. 启动接线 —— `main.py` lifespan

在现有 `lifespan` 的 `yield` 之前、`seed_default_admin` 之后调用 `start_scheduler(factory)`（DB / store 已就绪）；`yield` 之后 `shutdown_scheduler()`。`schedule.yaml` 无 DB 来源、无需迁移，故 `schedules_store.ensure_file()` **不进** `_run_storage_migrations`，直接在 `start_scheduler` 开头调用以保证文件存在，再 `reload_all`。

## 6. API `app/api/schedules.py`（前缀 `/api/schedules`，登录守卫）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/schedules` | 列表（含计算出的 `next_run_at`，取自 `scheduler.get_job(slug).next_run_time`） |
| POST | `/api/schedules` | 创建（写 store + `register`） |
| PATCH | `/api/schedules/{slug}` | 启停（`enabled` 改写 + `register`/`unregister`） |
| DELETE | `/api/schedules/{slug}` | 删除（`delete_schedule` + `unregister`） |
| POST | `/api/schedules/{slug}/run-now` | 立即手动触发一次：复用 `_fire(slug)`，**计入** `last_run_at`/`last_run_id`（与到点触发一致，便于看「上次跑」）；不改变后续排期节奏；与到点触发若并发，由 `_fire` 的 slug 锁去重（见 §4），不会重复建任务 |

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
- **`run_at` 序列化（关键）**：直接提交 datetime-local 的原始字符串（形如 `"2026-06-15T08:00"`，无秒无时区），后端 `ScheduleCreate.run_at` 按 **naive datetime** 接收。**严禁** `new Date(value).toISOString()`——那会转成 UTC，叠加后端时区处理后产生 8h 偏移（与 §4 时区联动）。
- 间隔为 daily/weekly/monthly 时，datetime-local 仍要求选完整日期（作为锚点）；UI 加一行小字说明「日期作为首次/锚点，之后按间隔重复」。`monthly` 锚点选 29~31 号时提示「部分月份无此日，当月跳过」（不拦截）。

> `name`：默认用规则摘要自动填（如「每日 08:00」），允许用户改；存 store 时 slugify 作主键。

### 7.2 计划任务 tab

- `App.tsx` 的 `navItems` 在「工作台」后插入 `{ to: "/schedules", label: "计划任务" }`，并加 `<Route path="/schedules" element={<SchedulesPage />} />`。
- 新增 `pages/Schedules.tsx`：
  - 页面标题行右侧放 **`+ 计划任务`** 按钮（`btnPrimary`），点击打开 `CreateRunDialog schedule`。**工作台（Dashboard）不加此按钮**。
  - 列表卡片显示 **名称**、**规则摘要**（「每天 08:00」/「每周一 09:00」/「每月 15 号 08:00」/「2026-06-15 08:00（单次）」）、**下次执行**（`next_run_at`）、**上次执行**（`last_run_at` + run 链接跳工作台）、**启用/停用开关**、**删除**、**立即执行**。
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

- **trigger 映射**（`app/pipeline/scheduler.py` 纯函数 `_trigger_for(sched)`）：once/daily/weekly/monthly 各产出正确的 trigger 类型与字段（hour/minute/day_of_week/day = run_at 派生值）。**显式断言周日锚点**（`run_at.weekday()==6`）映射到 `CronTrigger(day_of_week=6)`，防「0=周日」习惯误改。
- **store** `schedules_store`：临时 yaml 上 create/list/update(启停)/delete 往返。
- **API**：创建（once 过期 → 400）、列表（带 next_run_at）、启停、删除、run-now（mock `serial_submit` / `_fire`）。
- **_fire**：到期触发能调 `create_run`（mode 被强制 auto）+ `serial_submit`，并回写 last_run_*；once 触发后 enabled=false（mock store / serial_submit）。
- **前端**（vitest，最小）：计划模式弹窗提交 body 形状（freq/run_at/payload.mode==="auto"）。

## 10. 边界与约束

- 后端必须运行才会触发（本地单用户应用，符合现有部署）。
- 进程重启不丢计划（存 yaml，启动 `reload_all` 重注册）；正在排队/正在跑的触发若重启会丢，与现有 BackgroundTasks/serial 队列行为一致。
- 按「调度器显式配置的时区」排期（见 §4，须与用户预期的本地时区一致；Docker/WSL 注意 `TZ`），不处理夏令时切换日的歧义。
- 宕机错过的触发只在 5 分钟宽限内补跑一次，超时丢弃、不回灌（见 §2 misfire 说明）。
- monthly 锚点日 29~31 在缺失该日的月份当月不触发（APScheduler 行为），前端给提示不拦截。
