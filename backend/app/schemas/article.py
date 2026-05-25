from datetime import datetime

from pydantic import BaseModel


class RawArticleRead(BaseModel):
    id: int
    run_id: int
    title: str
    content: str
    source_url: str
    source_name: str
    category: str
    language: str
    score: float
    compliance_status: str
    selected: bool
    published_at: datetime | None
    author: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
