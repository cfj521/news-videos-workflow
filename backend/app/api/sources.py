import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.logging import get_logger
from app.schemas.source import NewsSourceCreate, NewsSourceRead, NewsSourceUpdate
from app.store import sources_store

log = get_logger("api.sources")
router = APIRouter(prefix="/api/sources", tags=["sources"])


def _to_read(s) -> NewsSourceRead:
    """将 SourceData 转换为 API 响应格式（config dict → config_json 字符串）。"""
    return NewsSourceRead(
        id=s.slug, name=s.name, type=s.type, url=s.url, category=s.category,
        language=s.language, priority=s.priority, enabled=s.enabled, pinned=s.pinned,
        tier=s.tier, config_json=json.dumps(s.config, ensure_ascii=False) if s.config else None,
    )


def _parse_config(config_json: str | None) -> dict:
    """将前端传来的 config_json 字符串解析为 dict；无效时返回空 dict。"""
    if not config_json:
        return {}
    try:
        return json.loads(config_json)
    except (ValueError, TypeError):
        return {}


@router.get("/", response_model=list[NewsSourceRead])
def list_sources():
    return [_to_read(s) for s in sources_store.list_sources()]


@router.get("/aihot/weeks")
async def aihot_weeks():
    """AI HOT 周报可选的「自然周」及其可用日报天数（供前端周选择框）。"""
    from app.providers.collector.aihot import list_available_weeks
    try:
        return await list_available_weeks()
    except Exception as e:
        log.warning("Failed to list AI HOT weeks: %s", e)
        return []


@router.get("/aihot/days")
async def aihot_days():
    """AI HOT 日报可选的日期（供前端日选择框）。"""
    from app.providers.collector.aihot import list_available_days
    try:
        return await list_available_days()
    except Exception as e:
        log.warning("Failed to list AI HOT days: %s", e)
        return []


@router.post("/", response_model=NewsSourceRead, status_code=201)
def create_source(body: NewsSourceCreate):
    s = sources_store.create_source(
        name=body.name, type=body.type, url=body.url, category=body.category,
        language=body.language, priority=body.priority, enabled=body.enabled,
        pinned=body.pinned, tier=body.tier, config=_parse_config(body.config_json), slug=body.slug,
    )
    log.info("Created source '%s' (%s)", s.slug, s.type)
    return _to_read(s)


@router.patch("/{slug}", response_model=NewsSourceRead)
def update_source(slug: str, body: NewsSourceUpdate):
    patch: dict = body.model_dump(exclude_unset=True)
    if "config_json" in patch:
        patch["config"] = _parse_config(patch.pop("config_json"))
    s = sources_store.update_source(slug, patch)
    if s is None:
        raise HTTPException(status_code=404, detail="Source not found")
    log.info("Updated source '%s'", slug)
    return _to_read(s)


@router.delete("/{slug}", status_code=204)
def delete_source(slug: str):
    if not sources_store.delete_source(slug):
        raise HTTPException(status_code=404, detail="Source not found")
    log.info("Deleted source '%s'", slug)


class BatchUpdateBody(BaseModel):
    ids: list[str]
    enabled: bool | None = None
    pinned: bool | None = None
    priority_map: dict[str, int] | None = None


@router.post("/batch", response_model=list[NewsSourceRead])
def batch_update(body: BatchUpdateBody):
    changed = sources_store.batch_update(
        body.ids, enabled=body.enabled, pinned=body.pinned, priority_map=body.priority_map)
    log.info("Batch updated %d sources", len(changed))
    return [_to_read(s) for s in changed]
