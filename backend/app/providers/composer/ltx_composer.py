"""LTX-2.3 Composer — generates per-scene video clips via LTX, then FFmpeg-concatenates with audio."""

import subprocess
import time
from pathlib import Path

from app.logging import get_logger
from app.providers.base import ComposerProvider, VideoResult

log = get_logger("composer.ltx")


class LTXComposer(ComposerProvider):
    def __init__(self, video_provider):
        self._video = video_provider

    async def compose(
        self,
        timeline_json: dict,
        assets_dir: str,
        output_path: str,
        resolution: str = "768x512",
    ) -> VideoResult:
        run_dir = Path(assets_dir).parent
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(exist_ok=True)

        entries = timeline_json.get("entries", [])
        total = len(entries)
        log.info("LTX compose: %d scenes, resolution=%s", total, resolution)
        t0 = time.time()

        clip_paths: list[dict] = []

        for i, entry in enumerate(entries):
            sid = entry["scene_id"]
            image_path = entry.get("image_path", "")
            audio_path = entry.get("audio_path", "")
            duration_s = (entry["end_ms"] - entry["start_ms"]) / 1000
            subtitle = entry.get("subtitle_text", "")

            clip_path = str(clips_dir / f"clip_{sid:02d}.mp4")
            prompt = subtitle or f"Scene {sid}"

            log.info("[LTX] Scene %d/%d: %.1fs image=%s", i + 1, total, duration_s, Path(image_path).name if image_path else "none")

            try:
                await self._video.generate(
                    image_path=image_path,
                    prompt=prompt,
                    duration=duration_s,
                    resolution=resolution,
                    output_path=clip_path,
                )
            except Exception:
                log.exception("[LTX] Scene %d clip generation failed, using static fallback", sid)
                _static_clip(image_path, duration_s, resolution, clip_path)

            clip_paths.append({"clip": clip_path, "audio": audio_path, "duration_s": duration_s})

        log.info("[LTX] All clips generated in %.1fs, composing final video", time.time() - t0)

        final_path = _ffmpeg_concat(clip_paths, output_path, resolution)

        total_ms = timeline_json.get("total_duration_ms", 0)
        log.info("[LTX] Final video: %s (%.1fs)", final_path, total_ms / 1000)

        return VideoResult(
            file_path=final_path,
            duration_ms=total_ms,
            resolution=resolution,
        )


def _static_clip(image_path: str, duration: float, resolution: str, output_path: str):
    """Fallback: create a static video from an image using FFmpeg."""
    parts = resolution.split("x")
    w, h = parts[0], parts[1] if len(parts) >= 2 else parts[0]
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-t", str(duration), "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=60, shell=True)


def _ffmpeg_concat(clips: list[dict], output_path: str, resolution: str) -> str:
    """Concatenate video clips with their audio tracks."""
    parts = resolution.split("x")
    w, h = parts[0], parts[1] if len(parts) >= 2 else parts[0]

    inputs = []
    filter_parts = []
    concat_inputs = []

    for i, c in enumerate(clips):
        inputs.extend(["-i", c["clip"]])
        if c["audio"] and Path(c["audio"]).exists():
            inputs.extend(["-i", c["audio"]])
            vi, ai = i * 2, i * 2 + 1
            filter_parts.append(f"[{vi}:v]scale={w}:{h},setsar=1,fps=25[v{i}]")
            filter_parts.append(f"[{ai}:a]apad=whole_dur={c['duration_s']}[a{i}]")
            concat_inputs.append(f"[v{i}][a{i}]")
        else:
            vi = i * 2 if any(Path(x["audio"]).exists() for x in clips if x["audio"]) else i
            filter_parts.append(f"[{i}:v]scale={w}:{h},setsar=1,fps=25[v{i}]")
            filter_parts.append(f"anullsrc=r=48000:cl=stereo[a{i}]")
            concat_inputs.append(f"[v{i}][a{i}]")

    if not concat_inputs:
        raise RuntimeError("No valid clips for FFmpeg concat")

    n = len(concat_inputs)
    fc = ";".join(filter_parts) + f";{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]"
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", fc,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest", output_path,
    ]
    log.info("FFmpeg concat: %d clips → %s", n, output_path)
    result = subprocess.run(cmd, capture_output=True, timeout=600, shell=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr)
        log.error("FFmpeg concat failed: %s", stderr[:500])
    return output_path
