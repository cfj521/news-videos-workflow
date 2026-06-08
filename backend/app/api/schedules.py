from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.api.dependencies import get_session_factory
from app.logging import get_logger
from app.pipeline import scheduler
from app.schemas.schedule import ScheduleCreate, ScheduleRead, ScheduleUpdate
from app.store import schedules_store

log = get_logger("api.schedules")
router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _to_read(s) -> ScheduleRead:
    return ScheduleRead(
        slug=s.slug, name=s.name, enabled=s.enabled, freq=s.freq, run_at=s.run_at,
        next_run_at=scheduler.next_run_for(s.slug),
        last_run_at=s.last_run_at, last_run_id=s.last_run_id, created_at=s.created_at or None,
        payload=s.payload,
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
