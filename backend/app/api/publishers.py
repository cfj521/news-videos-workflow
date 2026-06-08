import json

from fastapi import APIRouter, HTTPException

from app.logging import get_logger
from app.schemas.publish_target import PublishTargetCreate, PublishTargetRead, PublishTargetUpdate
from app.store import targets_store

log = get_logger("api.publishers")
router = APIRouter(prefix="/api/publishers", tags=["publishers"])


def _to_read(t) -> PublishTargetRead:
    return PublishTargetRead(
        id=t.slug, name=t.name, platform=t.platform, enabled=t.enabled,
        config_json=json.dumps(t.config, ensure_ascii=False) if t.config else None,
        created_at=t.created_at or None,
    )


def _parse_config(config_json: str | None) -> dict:
    if not config_json:
        return {}
    try:
        return json.loads(config_json)
    except (ValueError, TypeError):
        return {}


@router.get("/", response_model=list[PublishTargetRead])
def list_targets():
    return [_to_read(t) for t in targets_store.list_targets()]


@router.post("/", response_model=PublishTargetRead, status_code=201)
def create_target(body: PublishTargetCreate):
    t = targets_store.create_target(
        name=body.name, platform=body.platform, enabled=body.enabled,
        config=_parse_config(body.config_json), slug=body.slug,
    )
    log.info("Created publish target '%s' (%s)", t.slug, t.platform)
    return _to_read(t)


@router.patch("/{slug}", response_model=PublishTargetRead)
def update_target(slug: str, body: PublishTargetUpdate):
    patch: dict = body.model_dump(exclude_unset=True)
    if "config_json" in patch:
        patch["config"] = _parse_config(patch.pop("config_json"))
    t = targets_store.update_target(slug, patch)
    if t is None:
        raise HTTPException(status_code=404, detail="Target not found")
    log.info("Updated publish target '%s'", slug)
    return _to_read(t)


@router.delete("/{slug}")
def delete_target(slug: str):
    if not targets_store.delete_target(slug):
        raise HTTPException(status_code=404, detail="Target not found")
    log.info("Deleted publish target '%s'", slug)
    return {"status": "ok"}
