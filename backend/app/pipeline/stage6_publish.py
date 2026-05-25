from app.providers.base import PublisherAdapter, PublishResult


async def run_stage6(
    video_path: str,
    thumbnail_path: str | None,
    title: str,
    description: str,
    tags: list[str],
    publishers: dict[str, PublisherAdapter],
    platforms: list[str] | None = None,
) -> list[PublishResult]:
    platforms = platforms or list(publishers.keys())
    results: list[PublishResult] = []

    for platform in platforms:
        publisher = publishers.get(platform)
        if not publisher:
            results.append(
                PublishResult(
                    platform=platform,
                    status="failed",
                    error_message=f"No publisher for {platform}",
                )
            )
            continue

        result = await publisher.publish(
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            title=title,
            description=description,
            tags=tags,
        )
        results.append(result)

    return results
