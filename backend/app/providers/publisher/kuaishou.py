import asyncio
import time

import httpx

from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.kuaishou")

API = "https://open.kuaishou.com/rest/ks/open/photo"


class KuaishouPublisher(PublisherAdapter):
    def __init__(self, access_token: str = "", method: str = "api"):
        self._access_token = access_token
        self._method = method

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if self._method == "playwright":
            return await self._publish_playwright(video_path, title, tags)
        return await self._publish_api(video_path, title, description, tags)

    async def _publish_api(self, video_path: str, title: str, description: str, tags: list[str]) -> PublishResult:
        if not self._access_token:
            return PublishResult(platform="kuaishou", status="failed", error_message="Missing access_token")

        caption = f"{title} {description}\n" + " ".join(f"#{t}" for t in tags[:5]) if tags else f"{title} {description}"
        log.info("Publishing to Kuaishou (API): '%s'", title[:60])
        t0 = time.time()

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                start = await client.post(f"{API}/start_upload", headers={"Authorization": f"Bearer {self._access_token}"}, json={})
                start.raise_for_status()
                data = start.json()["data"]
                upload_token = data["upload_token"]
                endpoint = data["endpoint"]

                with open(video_path, "rb") as f:
                    await client.put(endpoint, headers={"Upload-Token": upload_token}, content=f.read())

                pub = await client.post(f"{API}/publish", headers={"Authorization": f"Bearer {self._access_token}"}, json={
                    "upload_token": upload_token, "caption": caption[:500],
                })
                pub.raise_for_status()
                photo_id = pub.json().get("data", {}).get("photo_id", "")

                # Poll publish status
                for _ in range(30):
                    st = await client.post(f"{API}/query_publish_status", headers={"Authorization": f"Bearer {self._access_token}"}, json={"upload_token": upload_token})
                    status_code = st.json().get("data", {}).get("status_code", 0)
                    if status_code == 2:
                        break
                    if status_code == 3:
                        return PublishResult(platform="kuaishou", status="failed", error_message="Kuaishou publish rejected")
                    await asyncio.sleep(2)

            log.info("Published to Kuaishou in %.1fs: %s", time.time() - t0, photo_id)
            return PublishResult(platform="kuaishou", status="success", url=f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else None)
        except Exception as e:
            log.exception("Kuaishou API publish failed")
            return PublishResult(platform="kuaishou", status="failed", error_message=str(e))

    async def _publish_playwright(self, video_path: str, title: str, tags: list[str]) -> PublishResult:
        log.info("Publishing to Kuaishou (Playwright): '%s'", title[:60])
        try:
            from social_auto_upload.kuaishou import KuaiShouUploader
            uploader = KuaiShouUploader()
            uploader.upload(file_path=video_path, title=title, tags=tags)
            return PublishResult(platform="kuaishou", status="success")
        except ImportError:
            return PublishResult(platform="kuaishou", status="failed", error_message="social-auto-upload not installed")
        except Exception as e:
            log.exception("Kuaishou Playwright publish failed")
            return PublishResult(platform="kuaishou", status="failed", error_message=str(e))
