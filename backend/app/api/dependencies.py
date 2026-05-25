from typing import Generator

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_engine_from_url, create_session_factory

_engine = None
_session_factory = None


def get_db() -> Generator[Session, None, None]:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_engine_from_url(settings.DATABASE_URL)
        _session_factory = create_session_factory(_engine)
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
