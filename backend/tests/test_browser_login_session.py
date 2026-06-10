from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.browser_login_session import BrowserLoginSession


def test_insert_and_query_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(BrowserLoginSession(sid="abc", platform="douyin", account="acct1", status="starting"))
    s.commit()
    row = s.query(BrowserLoginSession).filter_by(sid="abc").first()
    assert row.platform == "douyin"
    assert row.status == "starting"
    assert row.qr_base64 is None


def test_registered_in_metadata():
    assert "browser_login_sessions" in Base.metadata.tables
