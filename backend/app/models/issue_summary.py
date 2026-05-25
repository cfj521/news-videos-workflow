from sqlalchemy import Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin


class IssueSummary(Base, TimestampMixin):
    __tablename__ = "issue_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("pipeline_runs.id"))
    summary_text: Mapped[str] = mapped_column(Text)
    article_fingerprints_json: Mapped[str] = mapped_column(Text)
