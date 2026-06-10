import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_session_factory
from app.logging import get_logger
from app.models.browser_login_session import BrowserLoginSession  # noqa: F401  注册建表
from app.providers.publisher import sau_runner
from app.schemas.publish_target import PublishTargetCreate, PublishTargetRead, PublishTargetUpdate
from app.store import targets_store

log = get_logger("api.publishers")
router = APIRouter(prefix="/api/publishers", tags=["publishers"])

_LOGIN_PLATFORMS = {"douyin", "kuaishou"}
_LOGIN_TASKS: set = set()  # 持有后台任务引用，防被 GC


class LoginStartBody(BaseModel):
    platform: str
    account: str  # 账号的内部标识（前端自动生成的 UUID，= cookie 文件名）；保存前即可扫码


def _to_read(t) -> PublishTargetRead:
    return PublishTargetRead(
        id=t.slug, name=t.name, platform=t.platform, enabled=t.enabled,
        config_json=json.dumps(t.config, ensure_ascii=False) if t.config else None,
        created_at=t.created_at or None,
    )


def _parse_config(config_json: str | None) -> dict:
    if not config_json:
        return {}
    try:
        return json.loads(config_json)
    except (ValueError, TypeError):
        return {}


async def _run_login_flow(sid: str, platform: str, account: str) -> None:
    """后台跑扫码登录：自开 DB session，二维码就绪/终态都回写 BrowserLoginSession。"""
    factory = get_session_factory()

    def on_qr(data_url: str) -> None:
        s = factory()
        try:
            row = s.query(BrowserLoginSession).filter_by(sid=sid).first()
            if row:
                row.qr_base64 = data_url
                row.status = "qr_ready"
                s.commit()
        finally:
            s.close()

    try:
        _ok, status = await sau_runner.run_login(platform, account, on_qr)
    except Exception:  # noqa: BLE001
        log.exception("login worker crashed")
        status = "failed"

    s = factory()
    try:
        row = s.query(BrowserLoginSession).filter_by(sid=sid).first()
        if row:
            row.status = status if status in ("success", "timeout", "failed") else "failed"
            s.commit()
    finally:
        s.close()


@router.get("/", response_model=list[PublishTargetRead])
def list_targets():
    return [_to_read(t) for t in targets_store.list_targets()]


@router.post("/", response_model=PublishTargetRead, status_code=201)
def create_target(body: PublishTargetCreate):
    t = targets_store.create_target(
        name=body.name, platform=body.platform, enabled=body.enabled,
        config=_parse_config(body.config_json), slug=body.slug,
    )
    log.info("Created publish target '%s' (%s)", t.slug, t.platform)
    return _to_read(t)


@router.patch("/{slug}", response_model=PublishTargetRead)
def update_target(slug: str, body: PublishTargetUpdate):
    patch: dict = body.model_dump(exclude_unset=True)
    if "config_json" in patch:
        parsed = _parse_config(patch.pop("config_json"))
        if parsed:  # 仅在非空时写 config，避免 config_json=null 静默清空已有配置
            patch["config"] = parsed
    t = targets_store.update_target(slug, patch)
    if t is None:
        raise HTTPException(status_code=404, detail="Target not found")
    log.info("Updated publish target '%s'", slug)
    return _to_read(t)


@router.delete("/{slug}")
def delete_target(slug: str):
    if not targets_store.delete_target(slug):
        raise HTTPException(status_code=404, detail="Target not found")
    log.info("Deleted publish target '%s'", slug)
    return {"status": "ok"}


@router.post("/login/start")
async def login_start(body: LoginStartBody, db: Session = Depends(get_db)):
    if body.platform not in _LOGIN_PLATFORMS:
        raise HTTPException(status_code=422, detail="仅支持抖音/快手扫码登录")
    platform = body.platform
    account = sau_runner.safe_account(body.account)
    if not account:
        raise HTTPException(status_code=422, detail="账号标识非法")

    # 「重新生成」语义：杀掉同账号上一个仍在跑的 worker（含其 Chrome），清掉该账号所有旧会话，重开。
    # 旧 worker 即使没被杀到，其后续对旧 sid 的回写也会因行已删除而成 no-op。
    sau_runner.kill_login_worker(platform, account)
    db.query(BrowserLoginSession).filter_by(platform=platform, account=account)\
        .delete(synchronize_session=False)
    db.commit()

    sid = secrets.token_urlsafe(24)
    db.add(BrowserLoginSession(sid=sid, platform=platform, account=account, status="starting"))
    db.commit()

    task = asyncio.create_task(_run_login_flow(sid, platform, account))
    _LOGIN_TASKS.add(task)
    task.add_done_callback(_LOGIN_TASKS.discard)
    return {"sid": sid}


@router.get("/login/status")
def login_status(sid: str, db: Session = Depends(get_db)):
    s = db.query(BrowserLoginSession).filter_by(sid=sid).first()
    if s is None:
        return {"status": "error", "error": "会话不存在"}
    return {"status": s.status, "qr_base64": s.qr_base64, "error": s.error}


@router.get("/{slug}/login-status")
async def target_login_status(slug: str, deep: bool = False):
    t = targets_store.get_target(slug)
    if t is None:
        raise HTTPException(status_code=404, detail="Target not found")
    if t.platform not in _LOGIN_PLATFORMS:
        raise HTTPException(status_code=422, detail="该平台不支持扫码登录态查询")
    account = sau_runner.safe_account((t.config or {}).get("account", ""))
    if not account:
        return {"logged_in": False}
    logged_in = await sau_runner.check_login(t.platform, account, deep=deep)
    return {"logged_in": logged_in}
