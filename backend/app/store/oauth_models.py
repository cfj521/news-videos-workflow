from __future__ import annotations

from pydantic import BaseModel


class OAuthData(BaseModel):
    """供应商订阅 OAuth 凭证（当前仅 openai）。datetime 以 ISO8601 字符串存。"""
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    account_id: str = ""
    expires_at: str = ""        # ISO8601；空串表示未登录
    plan_type: str = ""
    account_email: str = ""
    last_refresh: str = ""
