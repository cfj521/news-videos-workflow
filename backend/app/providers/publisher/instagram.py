import asyncio
import time

import httpx

from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.instagram")

API = "https://graph.instagram.com/v21.0"


class InstagramPublisher(PublisherAdapter):
    def __init__(self, user_id: str = "", access_token: str = "", file_host_url: str = ""):
        self._user_id = user_id
        self._access_token = access_token
        self._file_host_url = file_host_url

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if not self._user_id or not self._access_token:
            return PublishResult(platform="instagram", status="failed", error_message="Missing user_id or access_token")

        video_url = self._file_host_url
        if not video_url:
            return PublishResult(platform="instagram", status="failed", error_message="Instagram requires a public video URL (file_host_url)")

        caption = f"{description}\n\n" + " ".join(f"#{t}" for t in tags[:30]) if tags else description
        log.info("Publishing Reel: %s", title[:60])
        t0 = time.time()

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # Step 1: create container
                resp = await client.post(f"{API}/{self._user_id}/media", data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption[:2200],
                    "access_token": self._access_token,
                })
                resp.raise_for_status()
                container_id = resp.json()["id"]
                log.info("Container created: %s", container_id)

                # Step 2: poll status
                for _ in range(60):
                    status = (await client.get(f"{API}/{container_id}", params={
                        "fields": "status_code,status", "access_token": self._access_token,
                    })).json()
                    if status.get("status_code") == "FINISHED":
                        break
                    if status.get("status_code") == "ERROR":
                        return PublishResult(platform="instagram", status="failed", error_message=f"Container error: {status}")
                    await asyncio.sleep(5)

                # Step 3: publish
                pub = await client.post(f"{API}/{self._user_id}/media_publish", data={
                    "creation_id": container_id, "access_token": self._access_token,
                })
                pub.raise_for_status()
                media_id = pub.json().get("id", "")

            log.info("Published to Instagram in %.1fs: %s", time.time() - t0, media_id)
            return PublishResult(platform="instagram", status="success", url=f"https://www.instagram.com/reel/{media_id}/")
        except Exception as e:
            log.exception("Instagram publish failed")
            return PublishResult(platform="instagram", status="failed", error_message=str(e))
