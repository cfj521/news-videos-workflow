from pydantic import BaseModel
from datetime import datetime


class VideoRead(BaseModel):
    id: int
    timeline_id: int
    file_path: str
    thumbnail_path: str | None
    resolution: str
    format: str
    file_size_bytes: int | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PublishRecordRead(BaseModel):
    id: int
    video_id: int
    platform: str
    status: str
    url: str | None
    published_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}
