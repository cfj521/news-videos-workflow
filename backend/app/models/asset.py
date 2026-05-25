from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(Integer, ForeignKey("scripts.id"))
    scene_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(500))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="done")
