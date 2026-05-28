from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.ximalaya")


class XimalayaPublisher(PublisherAdapter):
    """喜马拉雅（音频）。占位适配器：需开放平台凭证，暂未实现实际上传。"""

    def __init__(self, access_token: str = "", **kwargs):
        self._token = access_token

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str]) -> PublishResult:
        if not self._token:
            return PublishResult(platform="ximalaya", status="failed", error_message="Missing Ximalaya access_token")
        return PublishResult(platform="ximalaya", status="failed", error_message="Ximalaya 发布暂未实现")
