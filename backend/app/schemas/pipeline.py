from datetime import datetime

from pydantic import BaseModel


class PipelineRunCreate(BaseModel):
    mode: str = "manual"
    video_route: str = "comfyui"
    time_range: str = "7d"
    max_articles: int = 5
    selected_stages: list[int] = [1, 2, 3, 4, 5]
    publish_platforms: list[str] = []
    auto_collect: bool = True
    resolution: str = ""
    language: str = ""
    max_images: int | None = None


class PipelineRunRead(BaseModel):
    id: int
    mode: str
    video_route: str
    status: str
    current_stage: int | None
    time_range: str
    max_articles: int
    selected_stages: str
    publish_platforms: str
    progress_detail: str | None
    preview_path: str | None
    output_path: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    auto_collect: bool
    resolution: str | None
    language: str | None
    max_images: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
