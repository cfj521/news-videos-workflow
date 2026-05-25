import pytest

from app.providers.base import (
    AssetResult,
    CollectorProvider,
    ComposerProvider,
    ImageProvider,
    PublisherAdapter,
    PublishResult,
    RawArticleData,
    TextProvider,
    TTSProvider,
    VideoResult,
)


def test_raw_article_data():
    article = RawArticleData(
        title="Test",
        content="Content",
        source_url="https://example.com",
        source_name="Test",
        published_at=None,
    )
    assert article.title == "Test"
    assert article.language == "en"
    assert article.category == "general"


def test_asset_result():
    result = AssetResult(file_path="/tmp/image.png", duration_ms=None)
    assert result.file_path == "/tmp/image.png"


def test_video_result():
    result = VideoResult(file_path="/tmp/video.mp4")
    assert result.resolution == "1080x1920"
    assert result.duration_ms == 0


def test_publish_result():
    result = PublishResult(
        platform="youtube", status="success", url="https://youtube.com/watch?v=abc"
    )
    assert result.platform == "youtube"


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        CollectorProvider()
    with pytest.raises(TypeError):
        TextProvider()
    with pytest.raises(TypeError):
        ImageProvider()
    with pytest.raises(TypeError):
        TTSProvider()
    with pytest.raises(TypeError):
        ComposerProvider()
    with pytest.raises(TypeError):
        PublisherAdapter()
