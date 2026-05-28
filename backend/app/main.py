from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import get_session_factory
from app.api.router import api_router
from app.config import get_settings
from app.logging import setup_global_logger
from app.models.base import Base


def create_app() -> FastAPI:
    app = FastAPI(title="News Videos Workflow", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.on_event("startup")
    def on_startup():
        setup_global_logger()
        get_settings().ensure_data_dirs()
        factory = get_session_factory()
        Base.metadata.create_all(bind=factory.kw["bind"])

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/")
    async def root():
        return {"message": "News Videos Workflow API"}

    return app


app = create_app()
