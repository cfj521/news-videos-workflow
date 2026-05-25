from pathlib import Path

from app.providers.base import PublisherAdapter, PublishResult


class YouTubePublisher(PublisherAdapter):
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self._client_id = client_id
        self._client_secret = client_secret

    async def publish(
        self,
        video_path: str,
        thumbnail_path: str | None,
        title: str,
        description: str,
        tags: list[str],
    ) -> PublishResult:
        try:
            from googleapiclient.http import MediaFileUpload

            service = self._get_service()
            body = self._build_request_body(title, description, tags)
            media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            response = request.execute()
            video_id = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            if thumbnail_path and Path(thumbnail_path).exists():
                service.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path),
                ).execute()

            return PublishResult(platform="youtube", status="success", url=video_url)

        except Exception as e:
            return PublishResult(
                platform="youtube",
                status="failed",
                error_message=str(e),
            )

    def _build_request_body(
        self,
        title: str,
        description: str,
        tags: list[str],
    ) -> dict:
        return {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": "28",
                "defaultLanguage": "zh",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

    def _get_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_info(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        )
        return build("youtube", "v3", credentials=creds)
