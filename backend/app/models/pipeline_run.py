from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .raw_article import RawArticle


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(20))
    video_route: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    current_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_range: Mapped[str] = mapped_column(String(10), default="7d")
    max_articles: Mapped[int] = mapped_column(Integer, default=5)
    selected_stages: Mapped[str] = mapped_column(Text, default="[1,2,3,4,5]")
    publish_platforms: Mapped[str] = mapped_column(Text, default="[]")
    progress_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preview_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    auto_collect: Mapped[bool] = mapped_column(Boolean, default=True)
    # 任务级分辨率（图片与视频共用），创建时必填
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 任务级语言（zh|en），影响脚本/字幕/图片风格；创建时从流水线配置默认读取
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    articles: Mapped[list["RawArticle"]] = relationship(back_populates="run")
