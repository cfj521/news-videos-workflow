from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class BrowserLoginSession(Base, TimestampMixin):
    """抖音/快手扫码登录临时态：跨进程（--reload）共享二维码与结果，故落 DB（仿 OAuthLoginSession）。"""
    __tablename__ = "browser_login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(16))   # douyin|kuaishou
    account: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="starting")  # starting|qr_ready|success|failed|timeout
    qr_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
