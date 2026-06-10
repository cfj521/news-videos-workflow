from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult
from app.providers.publisher import sau_runner

log = get_logger("publisher.douyin")


class DouyinPublisher(PublisherAdapter):
    """抖音发布：浏览器自动化（social-auto-upload，扫码登录 + Cookie）。"""

    def __init__(self, account: str = ""):
        self._account = account

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str,
                      description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if not self._account:
            return PublishResult(platform="douyin", status="failed", error_message="未配置账号")
        if not sau_runner.cookie_path("douyin", self._account).exists():
            return PublishResult(platform="douyin", status="failed",
                                 error_message="未登录：请先在发布管理页扫码登录")
        log.info("Publishing to Douyin: '%s'", title[:60])
        ok, msg = await sau_runner.run_upload("douyin", self._account, video_path, title, description, tags or [])
        return PublishResult(platform="douyin", status="success" if ok else "failed",
                             error_message=None if ok else msg)
