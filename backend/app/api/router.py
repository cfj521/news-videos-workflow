from fastapi import APIRouter, Depends

from app.api.auth import router as auth_router
from app.api.pipeline import router as pipeline_router
from app.api.publishers import router as publishers_router
from app.api.settings import router as settings_router
from app.api.sources import router as sources_router
from app.auth import get_current_user

api_router = APIRouter()

# 公开：登录与用户管理（用户管理内部各路由自带登录校验）
api_router.include_router(auth_router)

# 受保护：业务路由统一要求已登录
_guard = [Depends(get_current_user)]
api_router.include_router(pipeline_router, dependencies=_guard)
api_router.include_router(sources_router, dependencies=_guard)
api_router.include_router(publishers_router, dependencies=_guard)
api_router.include_router(settings_router, dependencies=_guard)
