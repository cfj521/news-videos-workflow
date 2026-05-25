from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class TimeRange(str, Enum):
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    SEVEN_DAYS = "7d"
    FIFTEEN_DAYS = "15d"
    ONE_MONTH = "1m"


class VideoRoute(str, Enum):
    HYPERFRAMES = "hyperframes"
    LTX = "ltx"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite:///./data/news_videos.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    DATA_DIR: str = "./data"

    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    BRAVE_SEARCH_API_KEY: str = ""
    SERPER_API_KEY: str = ""

    YOUTUBE_CLIENT_ID: str = ""
    YOUTUBE_CLIENT_SECRET: str = ""

    DEFAULT_TIME_RANGE: str = "7d"
    DEFAULT_MAX_ARTICLES: int = 5
    DEFAULT_VIDEO_ROUTE: str = "hyperframes"
    DEFAULT_LANGUAGE: str = "zh"
    DEDUP_LOOKBACK: str = "30d"

    def ensure_data_dirs(self) -> None:
        base = Path(self.DATA_DIR)
        (base / "runs").mkdir(parents=True, exist_ok=True)
        (base / "history").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
