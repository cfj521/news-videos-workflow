from pathlib import Path

from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.youtube")


class YouTubePublisher(PublisherAdapter):
    def __init__(self, client_id: str = "", client_secret: str = "", refresh_token: str = ""):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        # client_id/secret 只是应用身份；真正代表"某账号已授权"的是 refresh_token，缺它无法上传
        if not (self._client_id and self._client_secret and self._refresh_token):
            return PublishResult(platform="youtube", status="failed",
                                 error_message="缺少 YouTube 凭证：需 client_id + client_secret + refresh_token（refresh_token 须先完成一次 OAuth 授权获取）")
        log.info("Publishing to YouTube: '%s' (%s)", title, video_path)
        try:
            from googleapiclient.http import MediaFileUpload

            service = self._get_service()
            body = self._build_request_body(title, description, tags)
            media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
            request = service.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()
            video_id = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            log.info("Published successfully: %s", video_url)

            if thumbnail_path and Path(thumbnail_path).exists():
                service.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
                log.info("Thumbnail uploaded for %s", video_id)

            # 外挂字幕（SRT）：视频已上传成功，字幕失败不阻断主流程，仅告警
            if subtitle_path and Path(subtitle_path).exists():
                self._upload_caption(service, video_id, subtitle_path)

            return PublishResult(platform="youtube", status="success", url=video_url)

        except Exception as e:
            log.exception("YouTube publish failed")
            return PublishResult(platform="youtube", status="failed", error_message=str(e))

    def _upload_caption(self, service, video_id: str, subtitle_path: str, language: str = "zh") -> None:
        """用 captions.insert 上传 SRT 外挂字幕。需 OAuth scope 含 youtube.force-ssl。"""
        from googleapiclient.http import MediaFileUpload

        try:
            service.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "language": language, "name": "中文", "isDraft": False}},
                media_body=MediaFileUpload(subtitle_path, mimetype="application/octet-stream", resumable=False),
            ).execute()
            log.info("Caption uploaded for %s (%s)", video_id, language)
        except Exception as e:
            # 常见：refresh_token 缺 youtube.force-ssl 权限（需重新授权）→ insufficientPermissions
            log.warning("YouTube caption upload failed (non-fatal): %s", e)

    def _build_request_body(self, title: str, description: str, tags: list[str]) -> dict:
        return {
            "snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30], "categoryId": "28", "defaultLanguage": "zh"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        }

    def _get_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        # 用 refresh_token 构造凭证；google 库会在需要时自动用它换取短期 access token
        creds = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            # force-ssl 授予字幕(captions)读写权限；保留 upload 兼容旧 token
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.force-ssl",
            ],
        )
        return build("youtube", "v3", credentials=creds)
