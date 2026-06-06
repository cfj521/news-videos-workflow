from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class OAuthCredential(Base, TimestampMixin):
    """OAuth 订阅凭证（当前仅 openai/ChatGPT）。token 明文存，仅个人本机使用。"""
    __tablename__ = "oauth_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # "openai"
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    id_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    plan_type: Mapped[str] = mapped_column(String(32), default="")
    account_email: Mapped[str] = mapped_column(String(255), default="")
    last_refresh: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthLoginSession(Base, TimestampMixin):
    """一次登录流程的临时态：跨进程（--reload）共享 PKCE/state 与结果，故落 DB。"""
    __tablename__ = "oauth_login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|success|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
