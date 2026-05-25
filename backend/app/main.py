from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="News Videos Workflow", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/")
    async def root():
        return {"message": "News Videos Workflow API"}

    return app


app = create_app()
