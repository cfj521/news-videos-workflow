from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class NewsSource(Base, TimestampMixin):
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(50), default="general")
    language: Mapped[str] = mapped_column(String(10), default="en")
    priority: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tier: Mapped[str] = mapped_column(String(20), default="free")
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
