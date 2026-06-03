from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.auth import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.logging import get_logger
from app.models.user import User

log = get_logger("api.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str = Field(min_length=1)


class CreateUserBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=1)


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "created_at": u.created_at}


# ---- 登录（公开）--------------------------------------------------------

@router.post("/login")
async def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    log.info("Login: %s", user.username)
    return {"token": create_token(user.username), "username": user.username}


# ---- 当前用户（需登录）--------------------------------------------------

@router.get("/me")
async def me(current: str = Depends(get_current_user)):
    return {"username": current}


@router.post("/password")
async def change_password(
    body: ChangePasswordBody,
    current: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == current).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    log.info("Password changed: %s", user.username)
    return {"status": "ok"}


# ---- 用户管理（需登录）--------------------------------------------------

@router.get("/users")
async def list_users(
    _: str = Depends(get_current_user), db: Session = Depends(get_db)
):
    users = db.query(User).order_by(User.id).all()
    return [_user_out(u) for u in users]


@router.post("/users")
async def create_user(
    body: CreateUserBody,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("User created: %s", user.username)
    return _user_out(user)


@router.post("/users/{user_id}/password")
async def reset_password(
    user_id: int,
    body: ResetPasswordBody,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    log.info("Password reset: %s", user.username)
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.username == current:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    if db.query(User).count() <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个用户")
    db.delete(user)
    db.commit()
    log.info("User deleted: %s", user.username)
    return {"status": "ok"}
