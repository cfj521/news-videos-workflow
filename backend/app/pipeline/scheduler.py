"""计划任务调度：进程内 APScheduler（显式时区），schedule.yaml 为唯一真相源。

job `_fire` 复用与 POST /api/pipeline/runs 相同的 create_run + serial_submit 链路。
本模块不 import app.api.*（防循环依赖）。
"""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.base import JobLookupError
from tzlocal import get_localzone

from app.logging import get_logger
from app.pipeline.engine import PipelineEngine
from app.pipeline.runner import run_pipeline_bg
from app.pipeline.serial_executor import submit as serial_submit
from app.store.schedules_store import (
    ScheduleData, ensure_file, get_schedule, list_schedules, update_schedule,
)

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


# ── 调度器单例 ───────────────────────────────────────────
_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()

# 进程重启后最多补跑 _MISFIRE_GRACE_S 秒内错过的触发（coalesce=True 保证最多补一次）
_MISFIRE_GRACE_S = 300

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
        with _scheduler_lock:
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
        id=sched.slug, replace_existing=True, coalesce=True, misfire_grace_time=_MISFIRE_GRACE_S,
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


def next_run_for(slug: str) -> "datetime | None":
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
