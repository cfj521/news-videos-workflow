# 计划任务（APScheduler 定时建流水线）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户保存「建任务参数 + 排期规则」，由 APScheduler 到点自动以 `mode=auto` 创建并运行一条 pipeline run；新增「计划任务」tab 做列表/启停/删除/立即执行。

**Architecture:** 排期存仓库根 `schedule.yaml`（YAML store，仿 `targets_store`）为唯一真相源；进程内 `BackgroundScheduler`（显式时区）启动时从 YAML 重注册；job `_fire` 复用与 `POST /api/pipeline/runs` 完全相同的 `create_run` + `serial_submit` 链路。前端复用 `CreateRunDialog`（计划模式），列表在新 tab。

**Tech Stack:** Python/FastAPI + SQLAlchemy + APScheduler + tzlocal；React/Vite/TS + SWR + Tailwind；pytest + vitest。

**设计依据：** `docs/superpowers/specs/2026-06-09-scheduled-tasks-design.md`

---

## File Structure

**后端新增：**
- `backend/app/store/schedules_store.py` — `schedule.yaml` 读写（ScheduleData + CRUD）
- `backend/app/pipeline/scheduler.py` — APScheduler 单例、trigger 映射、register/unregister/reload、`_fire`、start/shutdown
- `backend/app/schemas/schedule.py` — `ScheduleCreate` / `ScheduleRead`
- `backend/app/api/schedules.py` — `/api/schedules` 路由
- `backend/tests/test_schedules_store.py` / `test_scheduler.py` / `test_api_schedules.py` / `test_runner_bg.py`

**后端修改：**
- `backend/app/pipeline/runner.py` — 新增 `run_pipeline_bg`（从 API 层下沉，断循环 import）
- `backend/app/api/pipeline.py` — 改为从 runner 引用 `run_pipeline_bg`
- `backend/app/api/router.py` — 注册 `schedules_router`（带登录守卫）
- `backend/app/main.py` — lifespan 启停调度器
- `backend/tests/conftest.py` — 隔离 `schedule.yaml` 路径
- `requirements.txt` / `.gitignore` / 新增 `schedule.yaml.example`

**前端新增：**
- `frontend/src/pages/Schedules.tsx` — 计划任务 tab 页
- `frontend/src/lib/schedule.ts` — `formatScheduleSummary` 纯函数
- `frontend/src/lib/schedule.test.ts` — vitest

**前端修改：**
- `frontend/src/types/index.ts` — `Schedule` 类型
- `frontend/src/api/client.ts` — `api.schedules.*`
- `frontend/src/components/CreateRunDialog.tsx` — 计划模式 props + 排期区 + 提交分支
- `frontend/src/App.tsx` — 导航项 + 路由

---

## Task 1: 依赖与防护（apscheduler / tzlocal / .gitignore / 示例文件）

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore:31`
- Create: `schedule.yaml.example`

- [ ] **Step 1: requirements.txt 增加依赖**

在 `requirements.txt` 末尾追加（与现有 `>=` 风格一致）：

```
APScheduler>=3.10
tzlocal>=5.0
```

- [ ] **Step 2: 安装依赖**

Run: `pip install "APScheduler>=3.10" "tzlocal>=5.0"`
Expected: 成功安装（apscheduler、tzlocal）。

- [ ] **Step 3: .gitignore 加入 schedule.yaml**

在 `.gitignore` 第 31 行 `news_sources.yaml` 之后新增一行：

```
schedule.yaml
```

- [ ] **Step 4: 创建 schedule.yaml.example 模板**

`schedule.yaml.example`：

```yaml
# 计划任务定义（由「计划任务」页写入；本文件为模板，实际文件 schedule.yaml 不入库）
schedules: {}
# 示例：
#   daily_ai:
#     name: "每日AI日报"
#     enabled: true
#     freq: daily               # once | daily | weekly | monthly
#     run_at: "2026-06-15T08:00:00"   # 锚点本地时刻（无时区）；daily/weekly/monthly 取其时分/星期/号
#     created_at: "2026-06-09T10:00:00+00:00"
#     last_run_at: null
#     last_run_id: null
#     payload:                  # 整份建任务参数；触发时 mode 强制 auto
#       video_route: hyperframes
#       time_range: "7d"
#       max_articles: 5
#       selected_stages: [1, 2, 3, 4, 5, 6]
#       publish_platforms: []
#       resolution: "1080x1920"
#       language: "zh"
#       max_images: 10
#       auto_collect: true
#       source_ids: null
#       aihot_config: { method: "items" }
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .gitignore schedule.yaml.example
git commit -m "chore(deps): 计划任务依赖 APScheduler/tzlocal + schedule.yaml 防护与示例"
```

---

## Task 2: `run_pipeline_bg` 下沉到 runner（断循环 import）

调度层不能 import `app.api.pipeline`（会反向耦合 API 层）。把仅一行的后台入口函数下沉到干净下层 `runner.py`。

**Files:**
- Modify: `backend/app/pipeline/runner.py`（新增 `run_pipeline_bg`）
- Modify: `backend/app/api/pipeline.py:19-21,94-95`
- Test: `backend/tests/test_runner_bg.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_runner_bg.py`：

```python
import app.pipeline.runner as runner


def test_run_pipeline_bg_invokes_execute_pipeline(monkeypatch):
    """run_pipeline_bg 应通过 asyncio.run 调用 execute_pipeline 一次。"""
    calls = []

    async def fake_execute(run_id, factory):
        calls.append((run_id, factory))

    monkeypatch.setattr(runner, "execute_pipeline", fake_execute)
    runner.run_pipeline_bg(7, "FACTORY")
    assert calls == [(7, "FACTORY")]


def test_runner_has_no_api_layer_import():
    """runner 不得 import app.api.*（防循环依赖回归）。"""
    import inspect
    src = inspect.getsource(runner)
    assert "app.api" not in src
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_runner_bg.py -v`
Expected: FAIL（`run_pipeline_bg` 不存在 → AttributeError）。

- [ ] **Step 3: 在 runner.py 新增函数**

确认 `backend/app/pipeline/runner.py` 顶部已 `import asyncio`（异步流水线必然已导入；若无则在文件顶部 import 区加 `import asyncio`）。在文件末尾追加：

```python
def run_pipeline_bg(run_id: int, session_factory) -> None:
    """串行执行器的同步入口：在独立线程内跑完整条异步流水线。

    原定义在 app.api.pipeline，为避免「调度层 → API 层」的循环 import 下沉到此（干净下层）。
    """
    asyncio.run(execute_pipeline(run_id, session_factory))
```

- [ ] **Step 4: 改 api/pipeline.py 引用下沉后的函数**

`backend/app/api/pipeline.py:19` 的 runner import 行末尾追加 `run_pipeline_bg`：

```python
from app.pipeline.runner import execute_pipeline, _collectors_for_run, _build_text_provider, _update, _article_from_dict, _humanize_error, export_final, run_pipeline_bg
```

删除 `pipeline.py:94-95` 的本地定义：

```python
def _run_pipeline_bg(run_id: int, session_factory):
    asyncio.run(execute_pipeline(run_id, session_factory))
```

在其原位置改为别名（保持文件内其余引用 `_run_pipeline_bg` 不变）：

```python
_run_pipeline_bg = run_pipeline_bg
```

- [ ] **Step 5: 运行测试确认通过 + 回归**

Run: `cd backend && pytest tests/test_runner_bg.py tests/test_api_pipeline.py -v`
Expected: PASS（新测试通过，pipeline API 回归不破）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_runner_bg.py
git commit -m "refactor(pipeline): run_pipeline_bg 下沉 runner 以便调度层复用且断循环 import"
```

---

## Task 3: `schedules_store`（schedule.yaml 读写）

**Files:**
- Create: `backend/app/store/schedules_store.py`
- Test: `backend/tests/test_schedules_store.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_schedules_store.py`：

```python
import pytest

import app.store.schedules_store as ss

PAYLOAD = {"video_route": "hyperframes", "time_range": "7d", "selected_stages": [1, 2]}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SCHEDULE_PATH", tmp_path / "schedule.yaml")


def test_list_empty():
    assert ss.list_schedules() == []


def test_create_generates_slug_and_defaults():
    s = ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload=PAYLOAD)
    assert s.slug == "daily_ai"
    assert s.name == "Daily AI" and s.freq == "daily" and s.enabled is True
    assert s.run_at == "2026-06-15T08:00:00"
    assert s.payload == PAYLOAD
    assert s.created_at and s.last_run_at is None and s.last_run_id is None


def test_create_chinese_name_falls_back_to_freq():
    s = ss.create_schedule(name="每日早八", freq="weekly", run_at="2026-06-15T08:00:00", payload={})
    assert s.slug == "weekly"


def test_create_collision_appends_number():
    ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload={})
    s2 = ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload={})
    assert s2.slug == "daily_ai_1"


def test_get_update_delete_roundtrip():
    ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload={})
    ss.update_schedule("daily_ai", {"enabled": False, "last_run_id": 42})
    got = ss.get_schedule("daily_ai")
    assert got.enabled is False and got.last_run_id == 42
    assert ss.delete_schedule("daily_ai") is True
    assert ss.get_schedule("daily_ai") is None


def test_update_missing_returns_none():
    assert ss.update_schedule("nope", {"enabled": False}) is None


def test_ensure_file_creates_placeholder(tmp_path, monkeypatch):
    p = tmp_path / "schedule.yaml"
    monkeypatch.setattr(ss, "SCHEDULE_PATH", p)
    ss.ensure_file()
    assert p.exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_schedules_store.py -v`
Expected: FAIL（模块不存在 → ImportError）。

- [ ] **Step 3: 实现 schedules_store.py**

`backend/app/store/schedules_store.py`：

```python
"""schedule.yaml 读写：计划任务（slug 主键）。

结构：
    schedules:
      <slug>: {name, enabled, freq, run_at, created_at, last_run_at, last_run_id, payload: {...}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.store import _io
from app.store._slug import slugify, unique_slug

SCHEDULE_PATH = Path(__file__).resolve().parents[3] / "schedule.yaml"


class ScheduleData(BaseModel):
    """单条计划任务。slug 为主键（YAML key）；payload 为整份建任务参数。"""

    slug: str
    name: str
    enabled: bool = True
    freq: str = "once"
    run_at: str = ""                 # 锚点本地时刻 ISO（无时区）
    created_at: str = ""
    last_run_at: str | None = None
    last_run_id: int | None = None
    payload: dict = {}


def _read() -> dict:
    return _io.load_yaml(SCHEDULE_PATH)


def ensure_file() -> None:
    """文件不存在时写入空 schedules 占位。"""
    if not SCHEDULE_PATH.exists():
        _io.save_yaml(SCHEDULE_PATH, {"schedules": {}})


def list_schedules() -> list[ScheduleData]:
    raw = _read().get("schedules", {}) or {}
    return [ScheduleData(slug=slug, **(slot or {})) for slug, slot in raw.items()]


def get_schedule(slug: str) -> ScheduleData | None:
    slot = (_read().get("schedules", {}) or {}).get(slug)
    return ScheduleData(slug=slug, **slot) if slot else None


def create_schedule(
    *,
    name: str,
    freq: str,
    run_at: str,
    payload: dict,
    enabled: bool = True,
    slug: str | None = None,
) -> ScheduleData:
    """新建计划。slug 未指定时从 name 生成，中文名空串回退用 freq，冲突追加数字后缀。"""
    with _io.file_lock(SCHEDULE_PATH):
        data = _read()
        schedules = data.setdefault("schedules", {})
        existing = set(schedules.keys())
        new_slug = slug or unique_slug(slugify(name), existing, freq)
        if new_slug in existing:
            new_slug = unique_slug(new_slug, existing, freq)
        rec = {
            "name": name,
            "enabled": enabled,
            "freq": freq,
            "run_at": run_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_run_at": None,
            "last_run_id": None,
            "payload": payload or {},
        }
        schedules[new_slug] = rec
        _io.save_yaml(SCHEDULE_PATH, data)
        return ScheduleData(slug=new_slug, **rec)


def update_schedule(slug: str, patch: dict) -> ScheduleData | None:
    """部分更新；patch 可含 name/enabled/freq/run_at/last_run_at/last_run_id/payload。"""
    with _io.file_lock(SCHEDULE_PATH):
        data = _read()
        schedules = data.get("schedules", {}) or {}
        if slug not in schedules:
            return None
        slot = schedules[slug]
        for k in ("name", "enabled", "freq", "run_at", "last_run_at", "last_run_id", "payload"):
            if k in patch:
                slot[k] = patch[k]
        schedules[slug] = slot
        data["schedules"] = schedules
        _io.save_yaml(SCHEDULE_PATH, data)
        return ScheduleData(slug=slug, **slot)


def delete_schedule(slug: str) -> bool:
    with _io.file_lock(SCHEDULE_PATH):
        data = _read()
        schedules = data.get("schedules", {}) or {}
        if slug not in schedules:
            return False
        del schedules[slug]
        data["schedules"] = schedules
        _io.save_yaml(SCHEDULE_PATH, data)
        return True
```

> 注意：`update_schedule` 用 `if k in patch`（不加 `is not None`），因为 `last_run_at`/`last_run_id` 合法值可为各种类型，且 `once` 触发后需把 `enabled` 置 False。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_schedules_store.py -v`
Expected: PASS（8 项）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/store/schedules_store.py backend/tests/test_schedules_store.py
git commit -m "feat(store): schedules_store 读写 schedule.yaml"
```

---

## Task 4: trigger 映射纯函数 `_trigger_spec`

只做「freq + run_at → 触发参数」的纯函数，先单测，APScheduler 触发对象在 Task 5 构建。

**Files:**
- Create: `backend/app/pipeline/scheduler.py`（本任务仅 `_trigger_spec`）
- Test: `backend/tests/test_scheduler.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_scheduler.py`：

```python
import pytest

from app.pipeline import scheduler
from app.store.schedules_store import ScheduleData


def _sched(freq, run_at):
    return ScheduleData(slug="s", name="s", freq=freq, run_at=run_at, payload={})


def test_once_spec_is_date_trigger():
    kind, kw = scheduler._trigger_spec(_sched("once", "2026-06-15T08:30:00"))
    assert kind == "date"
    assert kw["run_date"].hour == 8 and kw["run_date"].minute == 30


def test_daily_spec_takes_hour_minute():
    kind, kw = scheduler._trigger_spec(_sched("daily", "2026-06-15T08:30:00"))
    assert kind == "cron"
    assert kw == {"hour": 8, "minute": 30}


def test_weekly_sunday_maps_to_day_of_week_6():
    # 2026-06-14 是周日 → weekday()==6（钉死：不可被「0=周日」习惯改坏）
    kind, kw = scheduler._trigger_spec(_sched("weekly", "2026-06-14T09:00:00"))
    assert kind == "cron"
    assert kw == {"day_of_week": 6, "hour": 9, "minute": 0}


def test_monthly_spec_takes_day():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2026-06-15T08:30:00"))
    assert kind == "cron"
    assert kw == {"day": 15, "hour": 8, "minute": 30}


def test_unknown_freq_raises():
    with pytest.raises(ValueError):
        scheduler._trigger_spec(_sched("yearly", "2026-06-15T08:30:00"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_scheduler.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 创建 scheduler.py（仅 trigger 纯函数 + import）**

`backend/app/pipeline/scheduler.py`：

```python
"""计划任务调度：进程内 APScheduler（显式时区），schedule.yaml 为唯一真相源。

job `_fire` 复用与 POST /api/pipeline/runs 相同的 create_run + serial_submit 链路。
本模块不 import app.api.*（防循环依赖）。
"""
from __future__ import annotations

from datetime import datetime

from app.logging import get_logger
from app.store.schedules_store import ScheduleData

log = get_logger("pipeline.scheduler")


def _trigger_spec(sched: ScheduleData) -> tuple[str, dict]:
    """把一条计划映射为 ('date'|'cron', kwargs)。纯函数，便于单测。

    daily/weekly/monthly 的时分/星期/号全部从 run_at 锚点派生。
    weekday() 与 APScheduler CronTrigger(day_of_week) 同为 0=周一..6=周日。
    """
    dt = datetime.fromisoformat(sched.run_at)
    if sched.freq == "once":
        return "date", {"run_date": dt}
    if sched.freq == "daily":
        return "cron", {"hour": dt.hour, "minute": dt.minute}
    if sched.freq == "weekly":
        return "cron", {"day_of_week": dt.weekday(), "hour": dt.hour, "minute": dt.minute}
    if sched.freq == "monthly":
        return "cron", {"day": dt.day, "hour": dt.hour, "minute": dt.minute}
    raise ValueError(f"未知 freq: {sched.freq}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_scheduler.py -v`
Expected: PASS（5 项）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): trigger 映射纯函数（含周日=6 钉死）"
```

---

## Task 5: 调度器主体（singleton / register / `_fire` / start-stop）

**Files:**
- Modify: `backend/app/pipeline/scheduler.py`
- Test: `backend/tests/test_scheduler.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_scheduler.py` 末尾追加：

```python
import app.pipeline.scheduler as sched_mod


class _FakeRun:
    id = 99


class _FakeEngine:
    def __init__(self, db):
        pass

    def create_run(self, **kwargs):
        _FakeEngine.last_kwargs = kwargs
        return _FakeRun()


class _FakeSession:
    def close(self):
        pass


def _factory():
    return _FakeSession()


@pytest.fixture
def _patch_fire(monkeypatch):
    """隔离 _fire 的外部依赖：store 读/写、create_run、serial_submit。"""
    submitted = []
    updated = {}
    monkeypatch.setattr(sched_mod, "PipelineEngine", _FakeEngine)
    monkeypatch.setattr(sched_mod, "serial_submit", lambda fn, *a, **k: submitted.append((fn, a)))
    monkeypatch.setattr(sched_mod, "update_schedule", lambda slug, patch: updated.update({slug: patch}))
    monkeypatch.setattr(sched_mod, "unregister", lambda slug: updated.setdefault("_unregistered", []).append(slug))
    return submitted, updated


def test_fire_daily_creates_run_with_mode_auto(_patch_fire):
    submitted, updated = _patch_fire
    sched_mod.get_schedule = lambda slug: ScheduleData(
        slug="s", name="s", freq="daily", run_at="2026-06-15T08:00:00",
        enabled=True, payload={"video_route": "hyperframes", "mode": "manual"})
    sched_mod._fire("s", _factory)
    assert _FakeEngine.last_kwargs["mode"] == "auto"          # 强制 auto
    assert _FakeEngine.last_kwargs["video_route"] == "hyperframes"
    assert submitted and submitted[0][1][0] == 99             # serial_submit(run.id=99)
    assert updated["s"]["last_run_id"] == 99
    assert "enabled" not in updated["s"]                      # daily 不停用


def test_fire_once_disables_and_unregisters(_patch_fire, monkeypatch):
    submitted, updated = _patch_fire
    monkeypatch.setattr(sched_mod, "get_schedule", lambda slug: ScheduleData(
        slug="s", name="s", freq="once", run_at="2026-06-15T08:00:00",
        enabled=True, payload={}))
    sched_mod._fire("s", _factory)
    assert updated["s"]["enabled"] is False
    assert updated["_unregistered"] == ["s"]


def test_fire_skips_when_disabled(_patch_fire, monkeypatch):
    submitted, updated = _patch_fire
    monkeypatch.setattr(sched_mod, "get_schedule", lambda slug: ScheduleData(
        slug="s", name="s", freq="daily", run_at="2026-06-15T08:00:00",
        enabled=False, payload={}))
    sched_mod._fire("s", _factory)
    assert submitted == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_scheduler.py -v`
Expected: FAIL（`_fire` / `PipelineEngine` 等未定义）。

- [ ] **Step 3: 补全 scheduler.py**

在 `backend/app/pipeline/scheduler.py` 顶部 import 区补充：

```python
import threading
from collections import defaultdict
from datetime import datetime, timezone   # 替换原仅 `from datetime import datetime`

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.base import JobLookupError
from tzlocal import get_localzone

from app.pipeline.engine import PipelineEngine
from app.pipeline.runner import run_pipeline_bg
from app.pipeline.serial_executor import submit as serial_submit
from app.store.schedules_store import (
    ScheduleData, ensure_file, get_schedule, list_schedules, update_schedule,
)
```

> 删除文件顶部原有的 `from datetime import datetime` 与 `from app.store.schedules_store import ScheduleData` 单行 import，避免重复。

在 `_trigger_spec` 之后追加：

```python
# ── 调度器单例 ───────────────────────────────────────────
_scheduler: BackgroundScheduler | None = None

# 同一 slug 的执行锁：到点触发与 run-now 撞车时去重，避免重复建任务
_fire_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_fire_locks_guard = threading.Lock()


def _lock_for_slug(slug: str) -> threading.Lock:
    with _fire_locks_guard:
        return _fire_locks[slug]


def get_scheduler() -> BackgroundScheduler:
    """懒构造调度器，显式传本地时区（不依赖 APScheduler 隐式默认；Docker/WSL 见部署文档设 TZ）。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=get_localzone())
    return _scheduler


def _trigger_for(sched: ScheduleData):
    kind, kw = _trigger_spec(sched)
    return DateTrigger(**kw) if kind == "date" else CronTrigger(**kw)


def register(sched: ScheduleData, session_factory) -> None:
    """注册/替换一条计划的 job；禁用的不注册。"""
    if not sched.enabled:
        return
    get_scheduler().add_job(
        _fire, _trigger_for(sched), args=[sched.slug, session_factory],
        id=sched.slug, replace_existing=True, coalesce=True, misfire_grace_time=300,
    )


def unregister(slug: str) -> None:
    try:
        get_scheduler().remove_job(slug)
    except JobLookupError:
        pass


def reload_all(session_factory) -> None:
    """清空后从 schedule.yaml 重注册所有启用项（启动时调用）。"""
    get_scheduler().remove_all_jobs()
    for sched in list_schedules():
        register(sched, session_factory)


def next_run_for(slug: str):
    """供 API 展示「下次执行」。"""
    job = get_scheduler().get_job(slug)
    return job.next_run_time if job else None


def start_scheduler(session_factory) -> None:
    ensure_file()
    reload_all(session_factory)
    if not get_scheduler().running:
        get_scheduler().start()
    log.info("Scheduler started (timezone=%s)", get_scheduler().timezone)


def shutdown_scheduler() -> None:
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)


def _fire(slug: str, session_factory) -> None:
    """到点触发（也供 run-now 复用）：建 run + 入串行队列 + 回写 store。

    同 slug 并发由非阻塞锁去重；单条失败写日志不拖垮其余 job。
    """
    lock = _lock_for_slug(slug)
    if not lock.acquire(blocking=False):
        log.info("Schedule '%s' 正在触发中，跳过本次", slug)
        return
    try:
        db = session_factory()
        try:
            sched = get_schedule(slug)
            if sched is None or not sched.enabled:
                return
            payload = {**sched.payload, "mode": "auto"}
            run = PipelineEngine(db).create_run(**payload)
            serial_submit(run_pipeline_bg, run.id, session_factory, label=f"sched:{slug}#{run.id}")
            patch = {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_run_id": run.id,
            }
            if sched.freq == "once":
                patch["enabled"] = False
            update_schedule(slug, patch)
            if sched.freq == "once":
                unregister(slug)
            log.info("Schedule '%s' fired → run #%d", slug, run.id)
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        log.exception("Schedule '%s' 触发失败", slug)
    finally:
        lock.release()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/test_scheduler.py -v`
Expected: PASS（全部，含 Task 4 的 5 项 + 新 3 项）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): APScheduler 单例/注册/_fire（slug 锁去重、once 自停用）"
```

---

## Task 6: Schemas + API 路由 `/api/schedules`

**Files:**
- Create: `backend/app/schemas/schedule.py`
- Create: `backend/app/api/schedules.py`
- Modify: `backend/app/api/router.py:1-26`
- Modify: `backend/tests/conftest.py`（隔离 SCHEDULE_PATH）
- Test: `backend/tests/test_api_schedules.py`

- [ ] **Step 1: conftest 隔离 schedule.yaml 路径**

在 `backend/tests/conftest.py` 的 `_isolate_store_paths` fixture 内，追加一条 monkeypatch（与现有三条并列）：

```python
    monkeypatch.setattr(
        "app.store.schedules_store.SCHEDULE_PATH",
        tmp_path / "schedule.yaml",
    )
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_api_schedules.py`：

```python
import pytest
from fastapi.testclient import TestClient

import app.pipeline.scheduler as scheduler
import app.store.schedules_store as ss
from app.auth import get_current_user
from app.main import create_app

PAYLOAD = {"video_route": "hyperframes", "time_range": "7d", "selected_stages": [1, 2]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SCHEDULE_PATH", tmp_path / "schedule.yaml")
    # 隔离真实调度器：API 不真正注册/触发
    monkeypatch.setattr(scheduler, "register", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "unregister", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "next_run_for", lambda slug: None)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_create_daily_returns_slug(client):
    r = client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "daily_ai" and body["freq"] == "daily" and body["enabled"] is True


def test_create_once_in_past_rejected(client):
    r = client.post("/api/schedules/", json={
        "name": "Old", "freq": "once", "run_at": "2000-01-01T08:00:00", "payload": PAYLOAD})
    assert r.status_code == 400


def test_list_patch_toggle_delete(client):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    assert len(client.get("/api/schedules/").json()) == 1
    r = client.patch("/api/schedules/daily_ai", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete("/api/schedules/daily_ai").status_code == 200
    assert client.get("/api/schedules/").json() == []


def test_run_now_invokes_fire(client, monkeypatch):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    fired = []
    monkeypatch.setattr(scheduler, "_fire", lambda slug, factory: fired.append(slug))
    assert client.post("/api/schedules/daily_ai/run-now").status_code == 200
    assert fired == ["daily_ai"]


def test_patch_missing_404(client):
    assert client.patch("/api/schedules/nope", json={"enabled": False}).status_code == 404
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd backend && pytest tests/test_api_schedules.py -v`
Expected: FAIL（路由不存在 → 404/ImportError）。

- [ ] **Step 4: 实现 schemas/schedule.py**

`backend/app/schemas/schedule.py`：

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.pipeline import PipelineRunCreate


class ScheduleCreate(BaseModel):
    name: str
    freq: Literal["once", "daily", "weekly", "monthly"]
    run_at: datetime                 # 由前端 datetime-local 原始字符串解析为 naive 本地时刻
    enabled: bool = True
    payload: PipelineRunCreate


class ScheduleRead(BaseModel):
    slug: str
    name: str
    enabled: bool
    freq: str
    run_at: datetime
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_id: int | None = None
    created_at: str | None = None
```

- [ ] **Step 5: 实现 api/schedules.py**

`backend/app/api/schedules.py`：

```python
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_session_factory
from app.logging import get_logger
from app.pipeline import scheduler
from app.schemas.schedule import ScheduleCreate, ScheduleRead
from app.store import schedules_store

log = get_logger("api.schedules")
router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _to_read(s) -> ScheduleRead:
    return ScheduleRead(
        slug=s.slug, name=s.name, enabled=s.enabled, freq=s.freq, run_at=s.run_at,
        next_run_at=scheduler.next_run_for(s.slug),
        last_run_at=s.last_run_at, last_run_id=s.last_run_id, created_at=s.created_at or None,
    )


@router.get("/", response_model=list[ScheduleRead])
def list_schedules():
    return [_to_read(s) for s in schedules_store.list_schedules()]


@router.post("/", response_model=ScheduleRead, status_code=201)
def create_schedule(body: ScheduleCreate):
    if body.freq == "once" and body.run_at <= datetime.now():
        raise HTTPException(status_code=400, detail="执行时间已过去")
    s = schedules_store.create_schedule(
        name=body.name, freq=body.freq, run_at=body.run_at.isoformat(),
        payload=body.payload.model_dump(), enabled=body.enabled,
    )
    scheduler.register(s, get_session_factory())
    log.info("Created schedule '%s' (%s)", s.slug, s.freq)
    return _to_read(s)


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


@router.delete("/{slug}")
def delete_schedule(slug: str):
    if not schedules_store.delete_schedule(slug):
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler.unregister(slug)
    log.info("Deleted schedule '%s'", slug)
    return {"status": "ok"}


@router.post("/{slug}/run-now")
def run_now(slug: str):
    if schedules_store.get_schedule(slug) is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler._fire(slug, get_session_factory())
    return {"status": "ok"}
```

- [ ] **Step 6: 注册路由（带登录守卫）**

`backend/app/api/router.py`：第 9 行后加 import：

```python
from app.api.schedules import router as schedules_router
```

在第 25 行 `settings_router` 注册之后加：

```python
api_router.include_router(schedules_router, dependencies=_guard)
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && pytest tests/test_api_schedules.py -v`
Expected: PASS（6 项）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/schedule.py backend/app/api/schedules.py backend/app/api/router.py backend/tests/conftest.py backend/tests/test_api_schedules.py
git commit -m "feat(api): /api/schedules CRUD + 启停 + run-now（once 过期拦截）"
```

---

## Task 7: main.py lifespan 启停调度器

**Files:**
- Modify: `backend/app/main.py:10-14,65-74`
- Test: `backend/tests/test_main.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_main.py` 末尾追加：

```python
def test_lifespan_starts_and_stops_scheduler(monkeypatch):
    """create_app + TestClient 进入/退出时应调用 start/shutdown_scheduler。"""
    from fastapi.testclient import TestClient

    import app.main as main_mod

    calls = []
    monkeypatch.setattr(main_mod, "start_scheduler", lambda factory: calls.append("start"))
    monkeypatch.setattr(main_mod, "shutdown_scheduler", lambda: calls.append("stop"))

    app = main_mod.create_app()
    with TestClient(app):
        pass
    assert "start" in calls and "stop" in calls
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_main.py::test_lifespan_starts_and_stops_scheduler -v`
Expected: FAIL（`main` 无 `start_scheduler` 属性）。

- [ ] **Step 3: 接线 lifespan**

`backend/app/main.py`：在第 14 行 import 区后加：

```python
from app.pipeline.scheduler import shutdown_scheduler, start_scheduler
```

修改 `lifespan`（第 65-74 行）为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_global_logger()
    get_settings().ensure_data_dirs()
    factory = get_session_factory()
    _run_storage_migrations()
    Base.metadata.create_all(bind=factory.kw["bind"])
    _ensure_pipeline_run_columns(factory.kw["bind"])
    seed_default_admin(factory)
    start_scheduler(factory)
    yield
    shutdown_scheduler()
```

- [ ] **Step 4: 运行测试确认通过 + 全量后端回归**

Run: `cd backend && pytest tests/test_main.py -v && pytest -q`
Expected: PASS（新测试通过；全量 suite 不回归）。

> 说明：接线后，任何用 `with TestClient(app)` 的既有测试会触发 lifespan → 启动一个**空的**真实调度器（`schedule.yaml` 经 conftest 隔离到 tmp、reload_all 无 job、daemon 线程在退出时 `shutdown`）。这是预期行为，非回归。若某测试不希望真启调度器，可在该测试内 monkeypatch `app.main.start_scheduler` 为 no-op。

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py
git commit -m "feat(main): lifespan 启停 APScheduler 调度器"
```

---

## Task 8: 前端类型 + API 客户端

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts:1,107-218`

- [ ] **Step 1: 加 Schedule 类型与建任务 payload 类型**

`frontend/src/types/index.ts` 末尾追加：

```ts
export type ScheduleFreq = "once" | "daily" | "weekly" | "monthly";

/** 建任务参数（创建任务与计划任务共用的请求体）。 */
export interface RunCreatePayload {
  mode?: string;
  video_route?: string;
  time_range?: string;
  max_articles?: number;
  selected_stages?: number[];
  publish_platforms?: string[];
  auto_collect?: boolean;
  resolution?: string;
  language?: string;
  max_images?: number;
  source_ids?: string[];
  aihot_config?: { method: string; category?: string; report_date?: string; week_start?: string };
}

export interface Schedule {
  slug: string;
  name: string;
  enabled: boolean;
  freq: ScheduleFreq;
  run_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_id: number | null;
  created_at: string | null;
}
```

- [ ] **Step 2: client.ts 增加 api.schedules**

`frontend/src/api/client.ts` 第 1 行的 import 改为：

```ts
import type { NewsSource, PipelineRun, PublishTarget, Schedule, RunCreatePayload } from "../types";
```

在 `api` 对象内 `settings: {...}` 块之后（第 264 行 `},` 之后）插入：

```ts
  schedules: {
    list: () => fetchJSON<Schedule[]>("/schedules/"),
    create: (body: { name: string; freq: string; run_at: string; payload: RunCreatePayload }) =>
      fetchJSON<Schedule>("/schedules/", { method: "POST", body: JSON.stringify(body) }),
    toggle: (slug: string, enabled: boolean) =>
      fetchJSON<Schedule>(`/schedules/${slug}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    remove: (slug: string) =>
      fetchJSON<{ status: string }>(`/schedules/${slug}`, { method: "DELETE" }),
    runNow: (slug: string) =>
      fetchJSON<{ status: string }>(`/schedules/${slug}/run-now`, { method: "POST" }),
  },
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && pnpm exec tsc --noEmit`
Expected: 通过（无类型错误）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(api): 前端 Schedule 类型 + api.schedules 客户端"
```

---

## Task 9: 排期摘要纯函数 + vitest

**Files:**
- Create: `frontend/src/lib/schedule.ts`
- Test: `frontend/src/lib/schedule.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/lib/schedule.test.ts`：

```ts
import { describe, it, expect } from "vitest";
import { formatScheduleSummary } from "./schedule";

describe("formatScheduleSummary", () => {
  it("once 显示完整日期时刻", () => {
    expect(formatScheduleSummary("once", "2026-06-15T08:00:00")).toBe("2026-06-15 08:00（单次）");
  });
  it("daily 只显示时分", () => {
    expect(formatScheduleSummary("daily", "2026-06-15T08:05:00")).toBe("每天 08:05");
  });
  it("weekly 显示星期（周日锚点）", () => {
    // 2026-06-14 是周日
    expect(formatScheduleSummary("weekly", "2026-06-14T09:00:00")).toBe("每周日 09:00");
  });
  it("monthly 显示号数", () => {
    expect(formatScheduleSummary("monthly", "2026-06-15T08:00:00")).toBe("每月 15 号 08:00");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && pnpm exec vitest run src/lib/schedule.test.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 schedule.ts**

`frontend/src/lib/schedule.ts`：

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
  if (freq === "monthly") return `每月 ${d.getDate()} 号 ${time}`;
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return `${date} ${time}（单次）`;
}
```

> `new Date("2026-06-14T08:00:00")`（无时区）按本地时间解析，`getDay()`/`getHours()` 取本地值，与后端 naive 锚点语义一致。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && pnpm exec vitest run src/lib/schedule.test.ts`
Expected: PASS（4 项）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/schedule.ts frontend/src/lib/schedule.test.ts
git commit -m "feat(ui): 排期摘要纯函数 formatScheduleSummary + 测试"
```

---

## Task 10: CreateRunDialog 计划模式

复用建任务弹窗：加 `schedule` / `onScheduled` props；计划模式下顶部加排期区、锁运行模式为自动、提交改调 `api.schedules.create`。

**Files:**
- Modify: `frontend/src/components/CreateRunDialog.tsx`

- [ ] **Step 1: Props 与状态**

`CreateRunDialog.tsx` 第 9-12 行 `Props` 接口改为：

```tsx
interface Props {
  onCreated: () => void;
  onClose: () => void;
  schedule?: boolean;          // true = 计划模式
  onScheduled?: () => void;    // 计划创建成功回调
}
```

第 42 行函数签名改为：

```tsx
export function CreateRunDialog({ onCreated, onClose, schedule = false, onScheduled }: Props) {
```

在第 43 行 `const [mode, setMode] = useState("auto");` 之后追加排期状态：

```tsx
  const [freq, setFreq] = useState<"once" | "daily" | "weekly" | "monthly">("once");
  const [runAt, setRunAt] = useState("");          // datetime-local 原始字符串
  const [scheduleName, setScheduleName] = useState("");
```

- [ ] **Step 2: 提交分支**

把第 151-171 行的 `handleSubmit` 整体替换为（计划模式走 schedules.create，普通模式不变）：

```tsx
  const handleSubmit = async () => {
    setLoading(true);
    try {
      const payload = {
        mode: schedule ? "auto" : mode,
        video_route: effVideoRoute,
        time_range: timeRange,
        max_articles: maxArticles,
        selected_stages: toBackendStages(effectiveVisual),
        publish_platforms: Array.from(effectiveTargetIds),
        resolution: effRes,
        language: effLang,
        max_images: effMaxImages,
        auto_collect: schedule ? true : autoCollect,
        ...(sourceMode === "aihot"
          ? { aihot_config: aihotCfg }
          : { source_ids: Array.from(effectiveSourceIds) }),
      };
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
    } finally { setLoading(false); }
  };
```

在第 7 行 import 之后加：

```tsx
import { formatScheduleSummary } from "../lib/schedule";
```

- [ ] **Step 3: 标题与排期区 UI**

第 176 行 `<h2 ...>新建任务</h2>` 改为：

```tsx
        <h2 className="text-lg font-semibold mb-4">{schedule ? "新建计划任务" : "新建任务"}</h2>

        {schedule && (
          <div className="mb-5 rounded-lg border border-white/[0.06] p-3 grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>间隔</label>
              <Select value={freq} onChange={(v) => setFreq(v as typeof freq)} options={[
                { value: "once", label: "单次" },
                { value: "daily", label: "每日" },
                { value: "weekly", label: "每周" },
                { value: "monthly", label: "每月" },
              ]} />
            </div>
            <div>
              <label className={labelCls}>执行时间</label>
              <input type="datetime-local" value={runAt} onChange={(e) => setRunAt(e.target.value)} className={inputCls} />
            </div>
            <div className="col-span-2">
              <label className={labelCls}>名称（可空，默认用规则摘要）</label>
              <input type="text" value={scheduleName} onChange={(e) => setScheduleName(e.target.value)}
                placeholder={runAt ? formatScheduleSummary(freq, runAt) : "如：每日AI日报"} className={inputCls} />
            </div>
            <p className="col-span-2 text-[11px] text-white/40 leading-snug">
              {freq === "once"
                ? "在所选时刻执行一次。"
                : "所选日期为锚点，之后按间隔在该时分重复。"}
              {freq === "monthly" && new Date(runAt || 0).getDate() >= 29 && " 注意：部分月份无 29~31 号，当月将跳过。"}
            </p>
          </div>
        )}
```

- [ ] **Step 4: 锁定运行模式为自动**

第 267-273 行「运行模式」块改为：计划模式渲染只读「自动」，否则保持原 Select：

```tsx
              <div>
                <label className={labelCls}>运行模式</label>
                {schedule ? (
                  <div className={`${selectCls} flex items-center opacity-50 cursor-not-allowed`}>
                    <span className="text-white/96">自动</span>
                  </div>
                ) : (
                  <Select value={mode} onChange={(v) => { setMode(v); if (v === "auto") setAutoCollect(true); }} options={[
                    { value: "auto", label: "自动" },
                    { value: "manual", label: "手动（逐步审核）" },
                  ]} />
                )}
              </div>
```

- [ ] **Step 5: 提交按钮文案与禁用条件**

第 345-347 行确认按钮改为：

```tsx
          <button onClick={handleSubmit} disabled={loading || effectiveVisual.size === 0 || (schedule && !runAt)} className={btnPrimary}>
            {loading ? (schedule ? "创建中..." : "创建中...") : (schedule ? "创建计划" : "创建")}
          </button>
```

- [ ] **Step 6: 类型检查与构建**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`
Expected: 通过（无类型/构建错误）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(ui): CreateRunDialog 计划模式（排期区 + 锁自动 + 提交 schedules）"
```

---

## Task 11: 计划任务 tab 页 + 导航 + 路由

**Files:**
- Create: `frontend/src/pages/Schedules.tsx`
- Modify: `frontend/src/App.tsx:3-16,164-169`

- [ ] **Step 1: 实现 Schedules.tsx**

`frontend/src/pages/Schedules.tsx`：

```tsx
import { useState } from "react";
import useSWR from "swr";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Schedule } from "../types";
import { btnPrimary, cardCls, chipCls, toggleCls, toggleThumbCls } from "../styles";
import { CreateRunDialog } from "../components/CreateRunDialog";
import { DeleteIconButton } from "../components/DeleteIconButton";
import { formatScheduleSummary } from "../lib/schedule";
import { useToast } from "../components/Toast";

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function SchedulesPage() {
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

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">计划任务</h1>
        <button onClick={() => setShowCreate(true)} className={btnPrimary}>+ 计划任务</button>
      </div>

      <div className="flex flex-col gap-2">
        {schedules?.map((s) => (
          <div key={s.slug} className={`${cardCls} px-4 py-3 flex items-center gap-4`}>
            <button onClick={() => onToggle(s)} className={toggleCls(s.enabled)} title={s.enabled ? "点击停用" : "点击启用"}>
              <span className={toggleThumbCls(s.enabled)} />
            </button>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white/92 truncate">{s.name}</span>
                <span className={`${chipCls} bg-white/[0.06] text-white/66 text-[10px]`}>{formatScheduleSummary(s.freq, s.run_at)}</span>
                {!s.enabled && <span className={`${chipCls} bg-white/[0.06] text-white/46 text-[10px]`}>已停用</span>}
              </div>
              <div className="text-xs text-white/46 mt-0.5">
                下次：{fmt(s.next_run_at)} · 上次：{s.last_run_id
                  ? <Link to="/" className="text-blue-300 hover:underline">{fmt(s.last_run_at)} #{s.last_run_id}</Link>
                  : "—"}
              </div>
            </div>
            <button onClick={() => onRunNow(s)} className="px-3 py-1.5 rounded-lg text-xs text-white/66 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white/85 transition">立即执行</button>
            <DeleteIconButton onClick={() => onDelete(s)} title="删除此计划" />
          </div>
        ))}
        {(!schedules || schedules.length === 0) && (
          <p className="text-white/60 text-sm">暂无计划任务，点击上方按钮创建</p>
        )}
      </div>

      {showCreate && (
        <CreateRunDialog
          schedule
          onCreated={() => setShowCreate(false)}
          onScheduled={() => { setShowCreate(false); mutate(); }}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: 导航与路由**

`frontend/src/App.tsx` 第 3 行后加 import：

```tsx
import { SchedulesPage } from "./pages/Schedules";
```

`navItems`（第 11-16 行）在「工作台」后插入一项：

```tsx
const navItems = [
  { to: "/", label: "工作台", end: true },
  { to: "/schedules", label: "计划任务" },
  { to: "/sources", label: "信息源管理" },
  { to: "/publish", label: "发布管理" },
  { to: "/settings", label: "设置" },
];
```

`<Routes>`（第 164-169 行）在 Dashboard 路由后加：

```tsx
            <Route path="/schedules" element={<SchedulesPage />} />
```

- [ ] **Step 3: 类型检查与构建**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`
Expected: 通过。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Schedules.tsx frontend/src/App.tsx
git commit -m "feat(ui): 计划任务 tab 页（列表/启停/删除/立即执行）+ 导航路由"
```

---

## Task 12: 端到端校验与文档

**Files:**
- Modify: `CLAUDE.md`（依赖/配置段补一句）

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && pytest -q`
Expected: 全绿（含新增 4 个测试文件）。

- [ ] **Step 2: 前端 lint + 测试 + 构建**

Run: `cd frontend && pnpm lint && pnpm exec vitest run && pnpm build`
Expected: 全绿。

- [ ] **Step 3: CLAUDE.md 补依赖说明**

在 `CLAUDE.md` 的 `## Dependencies` 段末尾追加一条：

```markdown
- **APScheduler / tzlocal**（计划任务）: 「计划任务」页排期存仓库根 `schedule.yaml`，由进程内 `BackgroundScheduler` 到点自动建 run。调度按**后端进程所在时区**；Docker/WSL 部署须设 `TZ` 与宿主一致，否则「本地时刻」会偏移。
```

在 `## Configuration` 段「发布平台凭证不在此文件…」一句后补：

```markdown
- 计划任务排期不在 `config.yaml`，存仓库根 `schedule.yaml`（不入库，模板见 `schedule.yaml.example`）
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 补计划任务依赖/时区/schedule.yaml 说明"
```

---

## 自查与遗留

- **手动验证**（后端由用户自管，不自动启停）：建一条 `freq=daily`、时间设为「当前 +2 分钟」的计划，确认 2 分钟后工作台出现一条新 run；建一条 `once` 过去时刻应被拒 400；启停开关切换后 `next_run_at` 变化；「立即执行」即时产出一条 run。
- **时区**：本地直跑取 `tzlocal` 宿主时区即对；Docker/WSL 须设 `TZ`（已写入 CLAUDE.md），实测一条 daily 验证不偏移。
- **未做（YAGNI，已与用户确认）**：编辑已有排期、宕机回灌（仅 5 分钟宽限内 coalesce 补一次）、跨时区/夏令时。
