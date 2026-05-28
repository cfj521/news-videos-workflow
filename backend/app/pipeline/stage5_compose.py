from app.logging import get_logger
from app.providers.base import ComposerProvider, VideoResult

log = get_logger("stage5")


async def run_stage5(
    timeline: dict,
    composer: ComposerProvider,
    assets_dir: str,
    output_path: str,
    resolution: str = "1080x1920",
) -> VideoResult:
    log.info("Composing video — %d entries, %.1fs, output=%s", len(timeline["entries"]), timeline["total_duration_ms"] / 1000, output_path)
    result = await composer.compose(timeline_json=timeline, assets_dir=assets_dir, output_path=output_path, resolution=resolution)
    log.info("Compose done — %s (%dms)", result.file_path, result.duration_ms)
    return result
