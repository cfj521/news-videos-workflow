from fastapi import APIRouter

from app.api.pipeline import router as pipeline_router
from app.api.sources import router as sources_router

api_router = APIRouter()
api_router.include_router(pipeline_router)
api_router.include_router(sources_router)
