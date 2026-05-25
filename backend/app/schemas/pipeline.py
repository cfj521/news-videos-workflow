from datetime import datetime

from pydantic import BaseModel


class PipelineRunCreate(BaseModel):
    mode: str = "manual"
    video_route: str = "hyperframes"
    time_range: str = "7d"
    max_articles: int = 5


class PipelineRunRead(BaseModel):
    id: int
    mode: str
    video_route: str
    status: str
    current_stage: int | None
    time_range: str
    max_articles: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
