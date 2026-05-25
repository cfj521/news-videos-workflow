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
