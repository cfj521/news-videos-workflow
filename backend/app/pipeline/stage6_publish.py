from app.logging import get_logger
from app.providers.base import PublishResult

log = get_logger("stage6")


async def run_stage6(
    video_path: str,
    thumbnail_path: str | None,
    title: str,
    description: str,
    tags: list[str],
    publishers: list,
    subtitle_path: str | None = None,
) -> list[PublishResult]:
    """逐个发布账号执行（publishers: [(PublishTarget, PublisherAdapter)]）。

    以账号为单位，同一平台的多个账号各自独立发布，结果用 target_name 区分。
    subtitle_path 为外挂字幕（SRT），支持的平台（如 YouTube）会随视频一起上传。
    """
    log.info("Publishing to %d account(s)", len(publishers))
    results: list[PublishResult] = []

    for target, publisher in publishers:
        log.info("Publishing to %s (%s)...", target.name, target.platform)
        result = await publisher.publish(
            video_path=video_path, thumbnail_path=thumbnail_path,
            title=title, description=description, tags=tags,
            subtitle_path=subtitle_path,
        )
        result.target_name = target.name
        if result.status == "success":
            log.info("Published to %s: %s", target.name, result.url)
        else:
            log.error("Publish to %s failed: %s", target.name, result.error_message)
        results.append(result)

    return results
