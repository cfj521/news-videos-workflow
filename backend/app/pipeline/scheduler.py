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
