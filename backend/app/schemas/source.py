from pydantic import BaseModel


class NewsSourceCreate(BaseModel):
    name: str
    type: str
    url: str = ""
    category: str = "general"
    language: str = "en"
    priority: int = 5
    enabled: bool = True
    pinned: bool = False
    tier: str = "free"
    config_json: str | None = None
    slug: str | None = None


class NewsSourceRead(BaseModel):
    id: str            # slug
    name: str
    type: str
    url: str
    category: str
    language: str
    priority: int
    enabled: bool
    pinned: bool
    tier: str
    config_json: str | None


class NewsSourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    url: str | None = None
    category: str | None = None
    language: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    pinned: bool | None = None
    config_json: str | None = None
