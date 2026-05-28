from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.logging import get_logger
from app.models.publish_target import PublishTarget
from app.schemas.publish_target import PublishTargetCreate, PublishTargetRead, PublishTargetUpdate

log = get_logger("api.publishers")
router = APIRouter(prefix="/api/publishers", tags=["publishers"])


@router.get("/", response_model=list[PublishTargetRead])
def list_targets(db: Session = Depends(get_db)):
    return db.query(PublishTarget).order_by(PublishTarget.id).all()


@router.post("/", response_model=PublishTargetRead, status_code=201)
def create_target(body: PublishTargetCreate, db: Session = Depends(get_db)):
    target = PublishTarget(**body.model_dump())
    db.add(target)
    db.commit()
    db.refresh(target)
    log.info("Created publish target #%d: '%s' (%s)", target.id, target.name, target.platform)
    return target


@router.patch("/{target_id}", response_model=PublishTargetRead)
def update_target(target_id: int, body: PublishTargetUpdate, db: Session = Depends(get_db)):
    target = db.get(PublishTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    db.commit()
    db.refresh(target)
    log.info("Updated publish target #%d: %s", target_id, body.model_dump(exclude_unset=True).keys())
    return target


@router.delete("/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)):
    target = db.get(PublishTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()
    log.info("Deleted publish target #%d", target_id)
    return {"status": "ok"}
