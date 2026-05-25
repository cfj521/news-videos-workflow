from datetime import datetime

from pydantic import BaseModel


class NewsSourceCreate(BaseModel):
    name: str
    type: str
    url: str
    category: str = "general"
    language: str = "en"
    priority: int = 5
    enabled: bool = True
    tier: str = "free"
    config_json: str | None = None


class NewsSourceRead(BaseModel):
    id: int
    name: str
    type: str
    url: str
    category: str
    language: str
    priority: int
    enabled: bool
    tier: str
    config_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NewsSourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    config_json: str | None = None
