from pydantic import BaseModel


class TimelineEntrySchema(BaseModel):
    scene_id: int
    start_ms: int
    end_ms: int
    image_path: str
    audio_path: str
    video_clip_path: str | None = None
    subtitle_text: str = ""


class TimelineRead(BaseModel):
    id: int
    script_id: int
    timeline_json: str
    total_duration_ms: int
    status: str

    model_config = {"from_attributes": True}
