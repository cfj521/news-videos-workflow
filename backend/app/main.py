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


def _ensure_pipeline_run_columns(engine) -> None:
    """轻量迁移：为 pipeline_runs 补齐新增列（SQLite 无 Alembic 时的兜底）。"""
    from sqlalchemy import text
    needed = {
        "auto_collect": "BOOLEAN DEFAULT 1",
        "resolution": "VARCHAR(20)",
        "aspect_ratio": "VARCHAR(10)",
        "language": "VARCHAR(10)",
        "max_images": "INTEGER",
    }
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(pipeline_runs)"))]
        if not cols:
            return
        for name, ddl in needed.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE pipeline_runs ADD COLUMN {name} {ddl}"))


def _seed_aihot_source(factory) -> None:
    import json

    from app.models.news_source import NewsSource

    db = factory()
    try:
        exists = db.query(NewsSource).filter(NewsSource.url.like("%aihot.virxact.com%")).first()
        if exists:
            return
        db.add(NewsSource(
            name="AI HOT", type="api", url="https://aihot.virxact.com/api/public",
            category="ai", language="zh", priority=1, enabled=True, tier="standard",
            config_json=json.dumps({"provider": "aihot", "method": "items"}),
        ))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_global_logger()
    get_settings().ensure_data_dirs()
    factory = get_session_factory()
    Base.metadata.create_all(bind=factory.kw["bind"])
    _ensure_pipeline_run_columns(factory.kw["bind"])
    _seed_aihot_source(factory)
    seed_default_admin(factory)
    yield


def _mount_frontend(app: FastAPI) -> bool:
    """单端口部署：后端直接托管前端构建产物（frontend/dist）。

    存在 dist 时挂 /assets 并对非 /api 路由做 SPA 回退（index.html），使访问后端端口即得整页。
    未构建（纯 vite dev）时返回 False，退回 API-only。dist 路径取 FRONTEND_DIST，缺省为仓库 frontend/dist。
    """
    dist = Path(os.getenv("FRONTEND_DIST") or (Path(__file__).resolve().parents[2] / "frontend" / "dist"))
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
