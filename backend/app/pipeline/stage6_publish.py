from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("stage6")


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
    log.info("Publishing to %d platforms: %s", len(platforms), platforms)
    results: list[PublishResult] = []

    for platform in platforms:
        publisher = publishers.get(platform)
        if not publisher:
            log.warning("No publisher adapter for '%s'", platform)
            results.append(PublishResult(platform=platform, status="failed", error_message=f"No publisher for {platform}"))
            continue

        log.info("Publishing to %s...", platform)
        result = await publisher.publish(video_path=video_path, thumbnail_path=thumbnail_path, title=title, description=description, tags=tags)
        if result.status == "success":
            log.info("Published to %s: %s", platform, result.url)
        else:
            log.error("Publish to %s failed: %s", platform, result.error_message)
        results.append(result)

    return results
