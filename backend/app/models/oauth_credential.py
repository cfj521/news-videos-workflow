from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class OAuthLoginSession(Base, TimestampMixin):
    """一次登录流程的临时态：跨进程（--reload）共享 PKCE/state 与结果，故落 DB。"""
    __tablename__ = "oauth_login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|success|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
