from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.logging import get_logger
from app.models.news_source import NewsSource
from app.schemas.source import NewsSourceCreate, NewsSourceRead, NewsSourceUpdate

log = get_logger("api.sources")
router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/", response_model=list[NewsSourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.query(NewsSource).order_by(NewsSource.priority).all()


@router.get("/aihot/weeks")
async def aihot_weeks():
    """AI HOT 周报可选的「自然周」及其可用日报天数（供前端周选择框）。"""
    from app.providers.collector.aihot import list_available_weeks
    try:
        return await list_available_weeks()
    except Exception as e:
        log.warning("Failed to list AI HOT weeks: %s", e)
        return []


@router.post("/", response_model=NewsSourceRead, status_code=201)
def create_source(body: NewsSourceCreate, db: Session = Depends(get_db)):
    source = NewsSource(**body.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    log.info("Created source #%d: '%s' (%s)", source.id, source.name, source.type)
    return source


@router.patch("/{source_id}", response_model=NewsSourceRead)
def update_source(source_id: int, body: NewsSourceUpdate, db: Session = Depends(get_db)):
    source = db.get(NewsSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    log.info("Updated source #%d: %s", source_id, list(changes.keys()))
    return source


from pydantic import BaseModel as _PydanticBase


class BatchUpdateBody(_PydanticBase):
    ids: list[int]
    enabled: bool | None = None
    pinned: bool | None = None
    priority_map: dict[int, int] | None = None


@router.post("/batch", response_model=list[NewsSourceRead])
def batch_update(body: BatchUpdateBody, db: Session = Depends(get_db)):
    sources = db.query(NewsSource).filter(NewsSource.id.in_(body.ids)).all()
    for s in sources:
        if body.enabled is not None:
            s.enabled = body.enabled
        if body.pinned is not None:
            s.pinned = body.pinned
        if body.priority_map and s.id in body.priority_map:
            s.priority = body.priority_map[s.id]
    db.commit()
    for s in sources:
        db.refresh(s)
    log.info("Batch updated %d sources", len(sources))
    return sources
