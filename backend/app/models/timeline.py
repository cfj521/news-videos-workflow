from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin


class Timeline(Base, TimestampMixin):
    __tablename__ = "timelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(Integer, ForeignKey("scripts.id"))
    timeline_json: Mapped[str] = mapped_column(Text)
    total_duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
