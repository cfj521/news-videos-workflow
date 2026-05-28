import asyncio
import pytest
from app.providers.publisher.ximalaya import XimalayaPublisher
from app.providers.publisher.xiaoyuzhou import XiaoyuzhouPublisher
from app.providers.publisher.netease_music import NeteaseMusicPublisher
from app.providers.publisher.apple_podcasts import ApplePodcastsPublisher


@pytest.mark.parametrize("cls,platform", [
    (XimalayaPublisher, "ximalaya"),
    (XiaoyuzhouPublisher, "xiaoyuzhou"),
    (NeteaseMusicPublisher, "netease_music"),
    (ApplePodcastsPublisher, "apple_podcasts"),
])
def test_audio_publisher_graceful_without_creds(cls, platform):
    pub = cls()
    res = asyncio.run(pub.publish("out.mp3", None, "标题", "简介", ["tag"]))
    assert res.platform == platform
    assert res.status == "failed"
    assert res.error_message
