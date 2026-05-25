from app.schemas.common import TimeRangeEnum
from app.schemas.pipeline import PipelineRunCreate
from app.schemas.script import SceneSchema
from app.schemas.source import NewsSourceCreate
from app.schemas.timeline import TimelineEntrySchema


def test_time_range_enum():
    assert TimeRangeEnum.SEVEN_DAYS == "7d"
    assert TimeRangeEnum.ONE_DAY == "1d"


def test_news_source_create():
    source = NewsSourceCreate(name="Test", type="rss", url="https://example.com/feed")
    assert source.category == "general"
    assert source.enabled is True


def test_pipeline_run_create():
    run = PipelineRunCreate(time_range="7d", max_articles=5)
    assert run.mode == "manual"
    assert run.video_route == "hyperframes"


def test_scene_schema():
    scene = SceneSchema(
        id=1, narration="旁白文本", image_prompt="一张科技风格的图片", duration_hint=5.0
    )
    assert scene.motion_prompt == ""


def test_timeline_entry():
    entry = TimelineEntrySchema(
        scene_id=1,
        start_ms=0,
        end_ms=5000,
        image_path="assets/scene_01.png",
        audio_path="assets/scene_01.mp3",
        subtitle_text="旁白文本",
    )
    assert entry.end_ms - entry.start_ms == 5000
