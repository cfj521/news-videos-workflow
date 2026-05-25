from pydantic import BaseModel


class SceneSchema(BaseModel):
    id: int
    narration: str
    image_prompt: str
    motion_prompt: str = ""
    duration_hint: float = 5.0


class ScriptCreate(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = []
    scenes: list[SceneSchema]
    mode: str = "single"


class ScriptRead(BaseModel):
    id: int
    run_id: int
    title: str
    description: str | None
    tags_json: str | None
    scenes_json: str
    mode: str
    status: str

    model_config = {"from_attributes": True}
