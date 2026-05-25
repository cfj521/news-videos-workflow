from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models.pipeline_run import PipelineRun
from app.pipeline.engine import PipelineEngine
from app.schemas.pipeline import PipelineRunCreate, PipelineRunRead

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/runs", response_model=PipelineRunRead, status_code=201)
def create_run(body: PipelineRunCreate, db: Session = Depends(get_db)):
    engine = PipelineEngine(db)
    run = engine.create_run(
        mode=body.mode,
        video_route=body.video_route,
        time_range=body.time_range,
        max_articles=body.max_articles,
    )
    return run


@router.get("/runs", response_model=list[PipelineRunRead])
def list_runs(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    runs = (
        db.query(PipelineRun)
        .order_by(PipelineRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return runs


@router.get("/runs/{run_id}", response_model=PipelineRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    engine = PipelineEngine(db)
    resumed = engine.resume_run(run_id)
    return {"status": "resumed", "run_id": resumed.id}
