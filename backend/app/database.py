from sqlalchemy import create_engine as _create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session


def create_engine_from_url(url: str) -> Engine:
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return _create_engine(url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
