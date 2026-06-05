import asyncio

from pathlib import Path

from app.logging import get_logger
from app.providers.base import ImageProvider, TTSProvider

log = get_logger("stage3")


async def _with_retry(make_awaitable, attempts: int, base_delay: float, label: str):
    """对一次素材生成做失败重试 + 指数退避，吃掉限流/超时/5xx/网络抖动等瞬时错误。

    所有异常都重试（最后一次仍失败则抛出）；退避 base_delay * 2**(n-1)，带轻微 jitter。
    """
    last_exc: Exception | None = None
    for n in range(1, max(1, attempts) + 1):
        try:
            return await make_awaitable()
        except Exception as e:  # noqa: BLE001 — 由调用方决定如何记录最终失败
            last_exc = e
            if n < attempts:
                import random
                delay = base_delay * (2 ** (n - 1)) + random.uniform(0, base_delay * 0.3)
                log.warning("%s 第 %d/%d 次失败：%s — %.1fs 后重试", label, n, attempts, e, delay)
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def run_stage3(
    script: dict,
    image_provider: ImageProvider,
    tts_provider: TTSProvider,
    assets_dir: str,
    resolution: str = "1080x1920",
    video_route: str = "hyperframes",
    audio_only: bool = False,
    max_retries: int = 3,
    retry_base_delay: float = 5.0,
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
                image_result = await _with_retry(
                    lambda: image_provider.generate(prompt=scene["image_prompt"], size=resolution, output_path=image_path),
                    max_retries, retry_base_delay, f"图片 S{scene_id}")
                entry["image"] = {"file_path": image_result.file_path, "duration_ms": image_result.duration_ms}
            except Exception as e:
                log.exception("[%d/%d] Image S%d FAILED", i, total, scene_id)
                # 带上真实异常文本，便于在 run 的 pipeline.log 里定位（限流/连接失败/超时等）
                entry["error"] = f"image failed: {type(e).__name__}: {e}"[:300]

        try:
            audio_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_audio.mp3")
            log.info("[%d/%d] TTS S%d: %s...", i, total, scene_id, scene["narration"][:30])
            audio_result = await _with_retry(
                lambda: tts_provider.synthesize(text=scene["narration"], output_path=audio_path),
                max_retries, retry_base_delay, f"语音 S{scene_id}")
            entry["audio"] = {"file_path": audio_result.file_path, "duration_ms": audio_result.duration_ms}
        except Exception as e:
            log.exception("[%d/%d] TTS S%d FAILED", i, total, scene_id)
            entry.setdefault("error", "")
            entry["error"] += f" tts failed: {type(e).__name__}: {e}"[:300]

        scene_assets.append(entry)

    ok = sum(1 for a in scene_assets if "error" not in a)
    log.info("Asset generation done: %d/%d ok", ok, total)
    return scene_assets
