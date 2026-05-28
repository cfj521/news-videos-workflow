from pathlib import Path

from app.logging import get_logger
from app.providers.base import ImageProvider, TTSProvider

log = get_logger("stage3")


async def run_stage3(
    script: dict,
    image_provider: ImageProvider,
    tts_provider: TTSProvider,
    assets_dir: str,
    resolution: str = "1080x1920",
    video_route: str = "hyperframes",
    audio_only: bool = False,
) -> list[dict]:
    Path(assets_dir).mkdir(parents=True, exist_ok=True)
    scenes = script["scenes"]
    total = len(scenes)
    log.info("Generating assets for %d scenes (resolution=%s, audio_only=%s)", total, resolution, audio_only)
    scene_assets: list[dict] = []

    for i, scene in enumerate(scenes, 1):
        scene_id = scene["id"]
        entry: dict = {"scene_id": scene_id}

        if not audio_only:
            try:
                image_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_image.png")
                log.info("[%d/%d] Image S%d: %s", i, total, scene_id, scene["image_prompt"][:60])
                image_result = await image_provider.generate(prompt=scene["image_prompt"], size=resolution, output_path=image_path)
                entry["image"] = {"file_path": image_result.file_path, "duration_ms": image_result.duration_ms}
            except Exception:
                log.exception("[%d/%d] Image S%d FAILED", i, total, scene_id)
                entry["error"] = "image generation failed"

        try:
            audio_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_audio.mp3")
            log.info("[%d/%d] TTS S%d: %s...", i, total, scene_id, scene["narration"][:30])
            audio_result = await tts_provider.synthesize(text=scene["narration"], output_path=audio_path)
            entry["audio"] = {"file_path": audio_result.file_path, "duration_ms": audio_result.duration_ms}
        except Exception:
            log.exception("[%d/%d] TTS S%d FAILED", i, total, scene_id)
            entry.setdefault("error", "")
            entry["error"] += " tts failed"

        scene_assets.append(entry)

    ok = sum(1 for a in scene_assets if "error" not in a)
    log.info("Asset generation done: %d/%d ok", ok, total)
    return scene_assets
