from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.xiaoyuzhou")


class XiaoyuzhouPublisher(PublisherAdapter):
    """小宇宙（音频/播客）。占位适配器：小宇宙无公开发布 API，需 cookie/人工。"""

    def __init__(self, cookie: str = "", **kwargs):
        self._cookie = cookie

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if not self._cookie:
            return PublishResult(platform="xiaoyuzhou", status="failed", error_message="Missing Xiaoyuzhou cookie")
        return PublishResult(platform="xiaoyuzhou", status="failed", error_message="小宇宙 发布暂未实现")
