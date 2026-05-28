import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.pipeline_run import PipelineRun
from app.pipeline.engine import PipelineEngine


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_create_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    assert run.id is not None
    assert run.status == "pending"


def test_resume_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="manual", video_route="hyperframes", time_range="7d")
    run.status = "review"
    db_session.commit()
    resumed = engine.resume_run(run.id)
    assert resumed.status == "processing"


def test_fail_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.fail_run(run.id, "Something went wrong")
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "failed"
    assert updated.error_message == "Something went wrong"
    assert updated.finished_at is not None


def test_finish_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.finish_run(run.id)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "done"
    assert updated.finished_at is not None


def test_create_run_persists_auto_collect(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", auto_collect=False)
    assert run.auto_collect is False
    run2 = engine.create_run(mode="auto")
    assert run2.auto_collect is True
