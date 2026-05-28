from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.apple_podcasts")


class ApplePodcastsPublisher(PublisherAdapter):
    """Apple Podcasts（音频）。占位适配器：Apple 走 RSS 分发，需托管 RSS，暂未实现。"""

    def __init__(self, rss_url: str = "", **kwargs):
        self._rss_url = rss_url

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str]) -> PublishResult:
        if not self._rss_url:
            return PublishResult(platform="apple_podcasts", status="failed", error_message="Missing Apple Podcasts rss_url")
        return PublishResult(platform="apple_podcasts", status="failed", error_message="Apple Podcasts 发布暂未实现（需 RSS 托管）")
