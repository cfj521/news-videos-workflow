from typing import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import create_engine_from_url, create_session_factory

_engine = None
_session_factory: sessionmaker[Session] | None = None


def _ensure_factory() -> sessionmaker[Session]:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_engine_from_url(settings.DATABASE_URL)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    factory = _ensure_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_session_factory() -> sessionmaker[Session]:
    return _ensure_factory()
