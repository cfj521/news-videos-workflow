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
