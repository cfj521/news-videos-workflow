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
    slug: str  # 账号自身的 slug（= 登录态标识 / cookie 文件名）


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
    from datetime import datetime, timedelta, timezone

    t = targets_store.get_target(body.slug)
    if t is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if t.platform not in _LOGIN_PLATFORMS:
        raise HTTPException(status_code=422, detail="仅支持抖音/快手扫码登录")
    platform = t.platform
    account = sau_runner.safe_account(body.slug)  # slug 即登录态标识
    if not account:
        raise HTTPException(status_code=422, detail="账号 slug 非法")

    # 清理本账号旧的非进行中会话（终态：success/failed/timeout）
    db.query(BrowserLoginSession).filter_by(platform=platform, account=account)\
        .filter(BrowserLoginSession.status.notin_(["starting", "qr_ready"])).delete(synchronize_session=False)

    # 并发判据：同账号仍在进行中（starting/qr_ready）且未超 LOGIN_TIMEOUT → 拒绝；
    # 更老的视为僵死，清掉后放行。
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=sau_runner.LOGIN_TIMEOUT)
    existing = db.query(BrowserLoginSession).filter_by(platform=platform, account=account)\
        .filter(BrowserLoginSession.status.in_(["starting", "qr_ready"])).all()
    for row in existing:
        updated = row.updated_at
        if updated is not None and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if updated is not None and updated > cutoff:
            raise HTTPException(status_code=409, detail="该账号已有进行中的扫码登录，请先完成或等待超时")
        # 僵死会话：删除后放行
        db.delete(row)
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
    # 登录态标识就是账号自身的 slug（cookie 文件名），无需单独的 account 字段
    account = sau_runner.safe_account(slug)
    if not account:
        return {"logged_in": False}
    logged_in = await sau_runner.check_login(t.platform, account, deep=deep)
    return {"logged_in": logged_in}
