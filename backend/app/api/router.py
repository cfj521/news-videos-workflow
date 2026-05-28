from fastapi import APIRouter

from app.api.pipeline import router as pipeline_router
from app.api.publishers import router as publishers_router
from app.api.settings import router as settings_router
from app.api.sources import router as sources_router

api_router = APIRouter()
api_router.include_router(pipeline_router)
api_router.include_router(sources_router)
api_router.include_router(publishers_router)
api_router.include_router(settings_router)
