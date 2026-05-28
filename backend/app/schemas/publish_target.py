from datetime import datetime

from pydantic import BaseModel


class PublishTargetCreate(BaseModel):
    name: str
    platform: str
    enabled: bool = True
    config_json: str | None = None


class PublishTargetRead(BaseModel):
    id: int
    name: str
    platform: str
    enabled: bool
    config_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublishTargetUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    enabled: bool | None = None
    config_json: str | None = None
