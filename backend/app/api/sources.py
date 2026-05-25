from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models.news_source import NewsSource
from app.schemas.source import NewsSourceCreate, NewsSourceRead, NewsSourceUpdate

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/", response_model=list[NewsSourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.query(NewsSource).order_by(NewsSource.priority).all()


@router.post("/", response_model=NewsSourceRead, status_code=201)
def create_source(body: NewsSourceCreate, db: Session = Depends(get_db)):
    source = NewsSource(**body.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.patch("/{source_id}", response_model=NewsSourceRead)
def update_source(source_id: int, body: NewsSourceUpdate, db: Session = Depends(get_db)):
    source = db.get(NewsSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    return source
