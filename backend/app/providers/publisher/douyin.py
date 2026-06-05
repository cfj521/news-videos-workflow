import time

import httpx

from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.douyin")

API = "https://open.douyin.com/api/douyin/v1/video"


class DouyinPublisher(PublisherAdapter):
    def __init__(self, access_token: str = "", method: str = "api"):
        self._access_token = access_token
        self._method = method

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if self._method == "playwright":
            return await self._publish_playwright(video_path, title, tags)
        return await self._publish_api(video_path, title, description, tags)

    async def _publish_api(self, video_path: str, title: str, description: str, tags: list[str]) -> PublishResult:
        if not self._access_token:
            return PublishResult(platform="douyin", status="failed", error_message="Missing access_token")

        text = f"{title}\n{description}\n" + " ".join(f"#{t}" for t in tags[:5]) if tags else f"{title}\n{description}"
        log.info("Publishing to Douyin (API): '%s'", title[:60])
        t0 = time.time()

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with open(video_path, "rb") as f:
                    resp = await client.post(
                        f"{API}/upload_video/",
                        headers={"Authorization": f"Bearer {self._access_token}"},
                        files={"video": f},
                    )
                    resp.raise_for_status()
                video_id = resp.json()["data"]["video"]["video_id"]

                pub = await client.post(
                    f"{API}/create_video/",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    json={"video_id": video_id, "text": text[:300]},
                )
                pub.raise_for_status()
                item_id = pub.json().get("data", {}).get("item_id", "")

            log.info("Published to Douyin in %.1fs: %s", time.time() - t0, item_id)
            return PublishResult(platform="douyin", status="success", url=f"https://www.douyin.com/video/{item_id}" if item_id else None)
        except Exception as e:
            log.exception("Douyin API publish failed")
            return PublishResult(platform="douyin", status="failed", error_message=str(e))

    async def _publish_playwright(self, video_path: str, title: str, tags: list[str]) -> PublishResult:
        log.info("Publishing to Douyin (Playwright): '%s'", title[:60])
        try:
            from social_auto_upload.douyin import DouYinUploader
            uploader = DouYinUploader()
            uploader.upload(file_path=video_path, title=title, tags=tags)
            return PublishResult(platform="douyin", status="success")
        except ImportError:
            return PublishResult(platform="douyin", status="failed", error_message="social-auto-upload not installed")
        except Exception as e:
            log.exception("Douyin Playwright publish failed")
            return PublishResult(platform="douyin", status="failed", error_message=str(e))
