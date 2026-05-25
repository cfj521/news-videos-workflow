import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.news_source import NewsSource


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_news_source_create(db_session):
    source = NewsSource(
        name="Hacker News",
        type="api",
        url="https://hn.algolia.com/api/v1/",
        category="tech",
        language="en",
        priority=1,
        config_json='{"provider": "hackernews_algolia"}',
    )
    db_session.add(source)
    db_session.commit()
    assert source.id is not None
    assert source.enabled is True
    assert source.created_at is not None


def test_news_source_defaults(db_session):
    source = NewsSource(
        name="Test",
        type="rss",
        url="https://example.com/feed",
    )
    db_session.add(source)
    db_session.commit()
    assert source.category == "general"
    assert source.language == "en"
    assert source.priority == 5
    assert source.enabled is True
    assert source.tier == "free"
