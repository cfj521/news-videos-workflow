import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.pipeline_run import PipelineRun
from app.models.raw_article import RawArticle


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_pipeline_run_create(db_session):
    run = PipelineRun(mode="auto", video_route="hyperframes", time_range="7d", max_articles=5)
    db_session.add(run)
    db_session.commit()
    assert run.id is not None
    assert run.status == "pending"
    assert run.current_stage is None


def test_pipeline_run_status_update(db_session):
    run = PipelineRun(mode="auto", video_route="hyperframes", time_range="7d")
    db_session.add(run)
    db_session.commit()
    run.status = "processing"
    run.current_stage = 1
    db_session.commit()
    assert run.status == "processing"
    assert run.current_stage == 1


def test_raw_article_create(db_session):
    run = PipelineRun(mode="auto", video_route="hyperframes", time_range="7d")
    db_session.add(run)
    db_session.commit()

    article = RawArticle(
        run_id=run.id,
        title="Test Article",
        content="Article content here",
        source_url="https://example.com/article",
        source_name="Test Source",
        category="ai",
        language="en",
    )
    db_session.add(article)
    db_session.commit()
    assert article.id is not None
    assert article.score == 0.0
    assert article.compliance_status == "pending"
    assert article.selected is False


def test_raw_article_relationship(db_session):
    run = PipelineRun(mode="auto", video_route="hyperframes", time_range="7d")
    db_session.add(run)
    db_session.commit()

    article = RawArticle(
        run_id=run.id,
        title="Test",
        content="Content",
        source_url="https://example.com",
        source_name="Test",
    )
    db_session.add(article)
    db_session.commit()

    loaded_run = db_session.get(PipelineRun, run.id)
    assert len(loaded_run.articles) == 1
    assert loaded_run.articles[0].title == "Test"
