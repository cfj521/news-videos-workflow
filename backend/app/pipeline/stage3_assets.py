from pathlib import Path

from app.providers.base import ImageProvider, TTSProvider


async def run_stage3(
    script: dict,
    image_provider: ImageProvider,
    tts_provider: TTSProvider,
    assets_dir: str,
    resolution: str = "1080x1920",
    video_route: str = "hyperframes",
) -> list[dict]:
    Path(assets_dir).mkdir(parents=True, exist_ok=True)
    scene_assets: list[dict] = []

    for scene in script["scenes"]:
        scene_id = scene["id"]
        entry: dict = {"scene_id": scene_id}

        try:
            image_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_image.png")
            image_result = await image_provider.generate(
                prompt=scene["image_prompt"],
                size=resolution,
                output_path=image_path,
            )
            entry["image"] = {
                "file_path": image_result.file_path,
                "duration_ms": image_result.duration_ms,
            }
        except Exception as e:
            entry["error"] = f"image generation failed: {e}"

        try:
            audio_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_audio.mp3")
            audio_result = await tts_provider.synthesize(
                text=scene["narration"],
                output_path=audio_path,
            )
            entry["audio"] = {
                "file_path": audio_result.file_path,
                "duration_ms": audio_result.duration_ms,
            }
        except Exception as e:
            entry.setdefault("error", "")
            entry["error"] += f" tts failed: {e}"

        scene_assets.append(entry)

    return scene_assets
