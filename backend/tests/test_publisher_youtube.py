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


@pytest.mark.asyncio
async def test_youtube_uploads_caption_when_srt_provided(tmp_path, monkeypatch):
    pytest.importorskip("googleapiclient")
    video = tmp_path / "out.mp4"
    video.write_bytes(b"fake")
    srt = tmp_path / "output.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

    calls = {"caption_inserts": 0, "lang": None}

    class _Exec:
        def __init__(self, ret):
            self._ret = ret

        def execute(self):
            return self._ret

    class _Videos:
        def insert(self, part, body, media_body):
            return _Exec({"id": "VID123"})

    class _Captions:
        def insert(self, part, body, media_body):
            calls["caption_inserts"] += 1
            calls["lang"] = body["snippet"]["language"]
            return _Exec({})

    class _Service:
        def videos(self):
            return _Videos()

        def captions(self):
            return _Captions()

    publisher = YouTubePublisher(client_id="c", client_secret="s", refresh_token="r")
    monkeypatch.setattr(publisher, "_get_service", lambda: _Service())

    res = await publisher.publish(
        video_path=str(video), thumbnail_path=None, title="t", description="d",
        tags=[], subtitle_path=str(srt),
    )

    assert res.status == "success"
    assert res.url == "https://www.youtube.com/watch?v=VID123"
    assert calls["caption_inserts"] == 1
    assert calls["lang"] == "zh"


@pytest.mark.asyncio
async def test_youtube_caption_failure_does_not_fail_publish(tmp_path, monkeypatch):
    """字幕上传失败（如缺 force-ssl 权限）不应让整条发布失败。"""
    pytest.importorskip("googleapiclient")
    video = tmp_path / "out.mp4"
    video.write_bytes(b"fake")
    srt = tmp_path / "output.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

    class _Exec:
        def execute(self):
            return {"id": "VID999"}

    class _Videos:
        def insert(self, part, body, media_body):
            return _Exec()

    class _Captions:
        def insert(self, part, body, media_body):
            raise RuntimeError("insufficientPermissions")

    class _Service:
        def videos(self):
            return _Videos()

        def captions(self):
            return _Captions()

    publisher = YouTubePublisher(client_id="c", client_secret="s", refresh_token="r")
    monkeypatch.setattr(publisher, "_get_service", lambda: _Service())

    res = await publisher.publish(
        video_path=str(video), thumbnail_path=None, title="t", description="d",
        tags=[], subtitle_path=str(srt),
    )
    assert res.status == "success"
