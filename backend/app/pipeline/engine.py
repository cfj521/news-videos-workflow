import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models.pipeline_run import PipelineRun

log = get_logger("engine")


class PipelineEngine:
    def __init__(self, db: Session):
        self.db = db

    def create_run(
        self,
        mode: str = "auto",
        video_route: str = "hyperframes",
        time_range: str = "7d",
        max_articles: int = 5,
        selected_stages: list[int] | None = None,
        publish_platforms: list[str] | None = None,
        auto_collect: bool = True,
    ) -> PipelineRun:
        stages = selected_stages or [1, 2, 3, 4, 5]
        platforms = publish_platforms or []
        run = PipelineRun(
            mode=mode, video_route=video_route, time_range=time_range,
            max_articles=max_articles,
            selected_stages=json.dumps(stages),
            publish_platforms=json.dumps(platforms),
            auto_collect=auto_collect,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        log.info("Created run #%d — mode=%s stages=%s platforms=%s", run.id, mode, stages, platforms)
        return run

    def resume_run(self, run_id: int) -> PipelineRun:
        run = self.db.get(PipelineRun, run_id)
        run.status = "processing"
        self.db.commit()
        self.db.refresh(run)
        log.info("Resumed run #%d (was at stage %s)", run_id, run.current_stage)
        return run

    def fail_run(self, run_id: int, error_message: str) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        log.error("Run #%d failed: %s", run_id, error_message[:200])

    def finish_run(self, run_id: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        log.info("Run #%d finished", run_id)
