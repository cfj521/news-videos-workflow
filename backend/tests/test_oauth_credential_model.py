from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.oauth_credential import OAuthCredential, OAuthLoginSession


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_credential_roundtrip():
    s = _session()
    s.add(OAuthCredential(
        provider="openai", access_token="at", refresh_token="rt",
        account_id="acc", expires_at=datetime.now(timezone.utc),
        plan_type="plus", account_email="a@b.com",
    ))
    s.commit()
    row = s.query(OAuthCredential).filter_by(provider="openai").one()
    assert row.access_token == "at"
    assert row.plan_type == "plus"


def test_login_session_roundtrip():
    s = _session()
    s.add(OAuthLoginSession(state="st", code_verifier="cv", status="pending"))
    s.commit()
    row = s.query(OAuthLoginSession).filter_by(state="st").one()
    assert row.status == "pending"
    assert row.code_verifier == "cv"
