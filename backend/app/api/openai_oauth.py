import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.logging import get_logger

# 顶部 import 新模型：保证启动时注册到 Base.metadata（create_all 建表）—— 见 spec S1
from app.models.oauth_credential import OAuthLoginSession  # noqa: F401
from app.oauth import openai_oauth as oo

log = get_logger("api.auth.openai")
router = APIRouter(prefix="/api/auth/openai", tags=["openai-oauth"])


@router.post("/login/start")
async def login_start(db: Session = Depends(get_db)):
    verifier, challenge = oo.gen_pkce()
    state = secrets.token_urlsafe(24)
    # 清理旧的 pending 会话，避免堆积
    db.query(OAuthLoginSession).filter_by(status="pending").delete()
    db.add(OAuthLoginSession(state=state, code_verifier=verifier, status="pending"))
    db.commit()
    oo.start_login_listener(state)
    return {"authorize_url": oo.build_authorize_url(challenge, state), "state": state}


@router.get("/login/status")
async def login_status(state: str, db: Session = Depends(get_db)):
    sess = db.query(OAuthLoginSession).filter_by(state=state).first()
    if sess is None:
        return {"status": "error", "error": "会话不存在"}
    return {"status": sess.status, "error": sess.error}


@router.get("/status")
async def status():
    return oo.get_status()


@router.post("/logout")
async def logout():
    oo.logout()
    return {"status": "ok"}
