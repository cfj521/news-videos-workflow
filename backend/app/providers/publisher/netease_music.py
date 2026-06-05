from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.netease_music")


class NeteaseMusicPublisher(PublisherAdapter):
    """网易云音乐（音频）。占位适配器：需登录态/创作者权限，暂未实现。"""

    def __init__(self, cookie: str = "", **kwargs):
        self._cookie = cookie

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if not self._cookie:
            return PublishResult(platform="netease_music", status="failed", error_message="Missing NetEase Music cookie")
        return PublishResult(platform="netease_music", status="failed", error_message="网易云音乐 发布暂未实现")
