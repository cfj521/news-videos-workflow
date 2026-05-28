import time

from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.bilibili")


class BilibiliPublisher(PublisherAdapter):
    def __init__(self, sessdata: str = "", bili_jct: str = "", buvid3: str = "", tid: int = 17):
        self._cookie = {"sessdata": sessdata, "bili_jct": bili_jct, "buvid3": buvid3}
        self._tid = tid

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str]) -> PublishResult:
        if not self._cookie["sessdata"]:
            return PublishResult(platform="bilibili", status="failed", error_message="Missing Bilibili cookies (sessdata)")

        log.info("Publishing to Bilibili: '%s'", title[:60])
        t0 = time.time()

        try:
            from biliup.plugins.bili_webup import BiliBili, Data

            video = Data()
            video.title = title[:80]
            video.desc = description[:250]
            video.tag = tags[:12] if tags else ["科技"]
            video.tid = self._tid

            with BiliBili(video) as bili:
                bili.login_by_cookie(self._cookie)
                video_part = bili.upload_file(video_path)
                video.append(video_part)
                result = bili.submit()

            bvid = result if isinstance(result, str) else ""
            url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
            log.info("Published to Bilibili in %.1fs: %s", time.time() - t0, url)
            return PublishResult(platform="bilibili", status="success", url=url)
        except ImportError:
            return PublishResult(platform="bilibili", status="failed", error_message="biliup not installed: pip install biliup")
        except Exception as e:
            log.exception("Bilibili publish failed")
            return PublishResult(platform="bilibili", status="failed", error_message=str(e))
