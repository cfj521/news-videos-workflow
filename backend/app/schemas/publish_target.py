from pydantic import BaseModel


class PublishTargetCreate(BaseModel):
    name: str
    platform: str
    enabled: bool = True
    config_json: str | None = None
    slug: str | None = None  # 可显式指定 slug；缺省按 name 生成


class PublishTargetRead(BaseModel):
    id: str            # slug
    name: str
    platform: str
    enabled: bool
    config_json: str | None
    created_at: str | None


class PublishTargetUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    enabled: bool | None = None
    config_json: str | None = None
