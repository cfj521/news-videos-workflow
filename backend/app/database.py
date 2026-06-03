from sqlalchemy import Engine, event
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import Session, sessionmaker


def _tune_sqlite(dbapi_conn, _record):
    """SQLite 连接级 PRAGMA：让单进程内的并发读写更稳。

    - WAL：读写不互斥（多读 + 单写并行），避免 SELECT 被写事务阻塞。
    - busy_timeout：遇到写锁时等待而非立刻报 "database is locked"。
    - synchronous=NORMAL：WAL 下兼顾安全与吞吐。
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def create_engine_from_url(url: str) -> Engine:
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = _create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _tune_sqlite)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
