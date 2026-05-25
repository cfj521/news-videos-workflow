from app.providers.base import ComposerProvider, VideoResult


async def run_stage5(
    timeline: dict,
    composer: ComposerProvider,
    assets_dir: str,
    output_path: str,
    resolution: str = "1080x1920",
) -> VideoResult:
    return await composer.compose(
        timeline_json=timeline,
        assets_dir=assets_dir,
        output_path=output_path,
        resolution=resolution,
    )
