import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.base import Base
from app.models.pipeline_run import PipelineRun
from app.models.script import Script
from app.models.asset import Asset
from app.models.timeline import Timeline
from app.models.video import Video
from app.models.publish_record import PublishRecord
from app.models.issue_summary import IssueSummary


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def run(db_session):
    r = PipelineRun(mode="auto", video_route="hyperframes", time_range="7d")
    db_session.add(r)
    db_session.commit()
    return r


def test_script_create(db_session, run):
    script = Script(
        run_id=run.id, title="AI 新突破", description="今天的科技新闻",
        tags_json='["AI", "科技"]', scenes_json='[{"id": 1, "narration": "test"}]',
        mode="single",
    )
    db_session.add(script)
    db_session.commit()
    assert script.id is not None
    assert script.status == "pending"


def test_asset_create(db_session, run):
    script = Script(run_id=run.id, title="T", scenes_json="[]", mode="single")
    db_session.add(script)
    db_session.commit()

    asset = Asset(
        script_id=script.id, scene_id=1, type="image",
        file_path="data/runs/1/assets/scene_01_image.png", duration_ms=5000,
    )
    db_session.add(asset)
    db_session.commit()
    assert asset.id is not None


def test_timeline_create(db_session, run):
    script = Script(run_id=run.id, title="T", scenes_json="[]", mode="single")
    db_session.add(script)
    db_session.commit()

    tl = Timeline(
        script_id=script.id,
        timeline_json='[{"scene_id": 1, "start_ms": 0, "end_ms": 5000}]',
        total_duration_ms=5000,
    )
    db_session.add(tl)
    db_session.commit()
    assert tl.id is not None


def test_video_and_publish(db_session, run):
    script = Script(run_id=run.id, title="T", scenes_json="[]", mode="single")
    db_session.add(script)
    db_session.commit()

    tl = Timeline(script_id=script.id, timeline_json="[]", total_duration_ms=5000)
    db_session.add(tl)
    db_session.commit()

    video = Video(
        timeline_id=tl.id, file_path="data/runs/1/output.mp4",
        thumbnail_path="data/runs/1/thumbnail.jpg",
        resolution="1080x1920", format="mp4", file_size_bytes=10_000_000,
    )
    db_session.add(video)
    db_session.commit()

    record = PublishRecord(video_id=video.id, platform="youtube", status="pending")
    db_session.add(record)
    db_session.commit()
    assert record.id is not None


def test_issue_summary(db_session, run):
    summary = IssueSummary(
        run_id=run.id, summary_text="本期包含 5 条 AI 相关新闻",
        article_fingerprints_json='["abc123", "def456"]',
    )
    db_session.add(summary)
    db_session.commit()
    assert summary.id is not None
