from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .pipeline_run import PipelineRun


class RawArticle(Base, TimestampMixin):
    __tablename__ = "raw_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("pipeline_runs.id"))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1000))
    source_name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50), default="general")
    language: Mapped[str] = mapped_column(String(10), default="en")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    compliance_status: Mapped[str] = mapped_column(String(20), default="pending")
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    run: Mapped["PipelineRun"] = relationship(back_populates="articles")
