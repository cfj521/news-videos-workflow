import pytest

from app.providers.publisher.youtube import YouTubePublisher


def test_youtube_build_metadata():
    publisher = YouTubePublisher(client_id="test", client_secret="test")
    body = publisher._build_request_body(
        title="AI 新突破",
        description="今天的科技新闻速报",
        tags=["AI", "科技", "新闻"],
    )
    assert body["snippet"]["title"] == "AI 新突破"
    assert body["snippet"]["description"] == "今天的科技新闻速报"
    assert body["snippet"]["tags"] == ["AI", "科技", "新闻"]
    assert body["snippet"]["categoryId"] == "28"
    assert body["status"]["privacyStatus"] == "public"


def test_youtube_title_truncation():
    publisher = YouTubePublisher(client_id="t", client_secret="t")
    long_title = "A" * 200
    body = publisher._build_request_body(title=long_title, description="", tags=[])
    assert len(body["snippet"]["title"]) <= 100


@pytest.mark.asyncio
async def test_youtube_publish_rejects_without_refresh_token():
    # 只有 client_id/secret、缺 refresh_token → 直接失败并给出可操作提示
    publisher = YouTubePublisher(client_id="c", client_secret="s")
    res = await publisher.publish(video_path="v.mp4", thumbnail_path=None, title="t", description="d", tags=[])
    assert res.status == "failed"
    assert "refresh_token" in res.error_message
