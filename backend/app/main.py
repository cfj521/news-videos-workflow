import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.dependencies import get_session_factory
from app.api.router import api_router
from app.auth import seed_default_admin
from app.config import get_settings
from app.logging import setup_global_logger
from app.models.base import Base


def _sqlite_path_from_url(url: str) -> Path:
    """从 sqlite URL 解析出文件路径（仅 sqlite 支持文件迁移）。"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        import logging
        logging.getLogger("nv.migrate").debug("非 sqlite 数据库，跳过 oauth 迁移：%s", url[:20])
        return Path("")
    raw = url[len(prefix):]
    p = Path(raw)
    return p if p.is_absolute() else (Path(__file__).resolve().parents[1] / raw).resolve()


def _run_storage_migrations() -> None:
    from app.config import CONFIG_PATH, get_settings, reload_settings
    from app.store.migrate import migrate_providers_to_yaml
    migrate_providers_to_yaml(
        config_path=CONFIG_PATH,
        sqlite_path=_sqlite_path_from_url(get_settings().infra.database_url),
    )
    reload_settings()  # 迁移可能新建 model_providers.yaml，清缓存让 providers 重新从 store 注入


def _ensure_pipeline_run_columns(engine) -> None:
    """轻量迁移：为 pipeline_runs 补齐新增列（SQLite 无 Alembic 时的兜底）。"""
    from sqlalchemy import text
    needed = {
        "auto_collect": "BOOLEAN DEFAULT 1",
        "resolution": "VARCHAR(20)",
        "aspect_ratio": "VARCHAR(10)",
        "language": "VARCHAR(10)",
        "max_images": "INTEGER",
        "source_ids": "TEXT",
        "aihot_config": "TEXT",
    }
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(pipeline_runs)"))]
        if not cols:
            return
        for name, ddl in needed.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE pipeline_runs ADD COLUMN {name} {ddl}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_global_logger()
    get_settings().ensure_data_dirs()
    factory = get_session_factory()
    _run_storage_migrations()
    Base.metadata.create_all(bind=factory.kw["bind"])
    _ensure_pipeline_run_columns(factory.kw["bind"])
    seed_default_admin(factory)
    yield


def _mount_frontend(app: FastAPI) -> bool:
    """单端口部署：后端直接托管前端构建产物（frontend/dist）。

    存在 dist 时挂 /assets 并对非 /api 路由做 SPA 回退（index.html），使访问后端端口即得整页。
    未构建（纯 vite dev）时返回 False，退回 API-only。
    dist 路径取 FRONTEND_DIST，缺省为仓库 frontend/dist。
    """
    _default_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    dist = Path(os.getenv("FRONTEND_DIST") or _default_dist)
    index = dist / "index.html"
    if not index.is_file():
        return False
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))  # SPA 前端路由回退

    return True


def create_app() -> FastAPI:
    app = FastAPI(title="News Videos Workflow", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    # 前端托管放最后注册：/api 路由优先匹配，其余交给 SPA 回退
    if not _mount_frontend(app):
        @app.get("/")
        async def root():
            return {"message": "News Videos Workflow API"}

    return app


app = create_app()
