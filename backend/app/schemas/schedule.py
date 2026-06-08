from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.pipeline import PipelineRunCreate


class ScheduleCreate(BaseModel):
    name: str
    freq: Literal["once", "daily", "weekly", "monthly"]
    run_at: datetime                 # 由前端 datetime-local 原始字符串解析为 naive 本地时刻
    enabled: bool = True
    payload: PipelineRunCreate


class ScheduleRead(BaseModel):
    slug: str
    name: str
    enabled: bool
    freq: str
    run_at: datetime
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_id: int | None = None
    created_at: str | None = None
    payload: dict = {}


class ScheduleUpdate(BaseModel):
    name: str | None = None
    freq: Literal["once", "daily", "weekly", "monthly"] | None = None
    run_at: datetime | None = None
    enabled: bool | None = None
    payload: PipelineRunCreate | None = None
