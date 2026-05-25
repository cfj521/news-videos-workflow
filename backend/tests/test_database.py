from sqlalchemy import text


def test_engine_creation(tmp_path):
    from app.database import create_engine_from_url
    db_path = tmp_path / "test.db"
    engine = create_engine_from_url(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_session_factory(tmp_path):
    from app.database import create_engine_from_url, create_session_factory
    db_path = tmp_path / "test.db"
    engine = create_engine_from_url(f"sqlite:///{db_path}")
    SessionLocal = create_session_factory(engine)
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1"))
        assert result.scalar() == 1
