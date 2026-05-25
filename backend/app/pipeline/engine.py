from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.pipeline_run import PipelineRun


class PipelineEngine:
    def __init__(self, db: Session):
        self.db = db

    def create_run(
        self,
        mode: str = "auto",
        video_route: str = "hyperframes",
        time_range: str = "7d",
        max_articles: int = 5,
    ) -> PipelineRun:
        run = PipelineRun(
            mode=mode,
            video_route=video_route,
            time_range=time_range,
            max_articles=max_articles,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def start_stage(self, run_id: int, stage: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "processing"
        run.current_stage = stage
        if stage == 1 and not run.started_at:
            run.started_at = datetime.now(timezone.utc)
        self.db.commit()

    def complete_stage(self, run_id: int, stage: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.current_stage = stage
        self.db.commit()

    def pause_for_review(self, run_id: int, stage: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "review"
        run.current_stage = stage
        self.db.commit()

    def resume_run(self, run_id: int) -> PipelineRun:
        run = self.db.get(PipelineRun, run_id)
        run.status = "processing"
        self.db.commit()
        self.db.refresh(run)
        return run

    def fail_run(self, run_id: int, error_message: str) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

    def finish_run(self, run_id: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

    def should_pause(self, run_id: int, stage: int) -> bool:
        run = self.db.get(PipelineRun, run_id)
        return run.mode == "manual"
