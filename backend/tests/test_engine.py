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


def test_advance_stage(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.start_stage(run.id, stage=1)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "processing"
    assert updated.current_stage == 1
    assert updated.started_at is not None


def test_complete_stage(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.start_stage(run.id, stage=1)
    engine.complete_stage(run.id, stage=1)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "processing"


def test_pause_for_review(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="manual", video_route="hyperframes", time_range="7d")
    engine.start_stage(run.id, stage=1)
    engine.pause_for_review(run.id, stage=1)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "review"


def test_resume_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="manual", video_route="hyperframes", time_range="7d")
    engine.pause_for_review(run.id, stage=1)
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


def test_should_pause(db_session):
    engine = PipelineEngine(db_session)
    auto_run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    manual_run = engine.create_run(mode="manual", video_route="hyperframes", time_range="7d")
    assert engine.should_pause(auto_run.id, 1) is False
    assert engine.should_pause(manual_run.id, 1) is True
