import subprocess
from pathlib import Path

from app.config import OverlayCfg
from app.logging import get_logger
from app.providers.base import ComposerProvider, VideoResult
from app.providers.composer.overlay import build_drawtext

log = get_logger("composer.comfyui")


class ComfyUIVideoComposer(ComposerProvider):
    """逐分镜调 ComfyUI 视频 provider 出 clip，加各分镜 TTS 音轨，拼接成最终 mp4。全新实现，不复用 LTX。"""

    def __init__(self, video_provider, fps: int = 24, overlay: OverlayCfg | None = None):
        self._video = video_provider
        self._fps = fps
        self._overlay = overlay or OverlayCfg()

    async def compose(self, timeline_json: dict, assets_dir: str, output_path: str, resolution: str = "704x480") -> VideoResult:
        run_dir = Path(assets_dir).parent
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        parts = resolution.split("x")
        w, h = int(parts[0]), (int(parts[1]) if len(parts) > 1 else int(parts[0]))
        entries = timeline_json.get("entries", [])
        segs: list[str] = []

        for i, entry in enumerate(entries):
            if entry.get("is_cover"):
                continue  # 封面不走 comfyui，改由 hyperframes 渲片段后拼接
            sid = entry["scene_id"]
            image_path = entry.get("image_path", "")
            audio_path = entry.get("audio_path", "")
            dur = max(0.5, (entry["end_ms"] - entry["start_ms"]) / 1000)
            prompt = entry.get("subtitle_text") or f"Scene {sid}"
            raw = str(clips_dir / f"clip_{sid:02d}.mp4")
            log.info("[CFY] Scene %d/%d: %.1fs", i + 1, len(entries), dur)
            try:
                await self._video.generate(image_path=image_path, prompt=prompt, duration=dur,
                                            resolution=resolution, output_path=raw)
            except Exception:
                log.exception("[CFY] Scene %d clip 失败，静态兜底", sid)
                _static_clip(image_path, dur, w, h, self._fps, raw)
            seg = str(clips_dir / f"seg_{sid:02d}.mp4")
            draw = build_drawtext(entry.get("title", ""), w, h, self._overlay,
                                  str(clips_dir / f"title_{sid:02d}.txt"))
            _mux_segment(raw, audio_path, dur, w, h, self._fps, seg, draw)
            segs.append(seg)

        _concat(segs, clips_dir, output_path)
        total_ms = timeline_json.get("total_duration_ms", 0)
        return VideoResult(file_path=output_path, duration_ms=total_ms, resolution=resolution)


def _ff(cmd: list[str], timeout: int = 600) -> None:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 失败: " + r.stderr.decode("utf-8", "replace")[:300])


def _static_clip(image_path: str, dur: float, w: int, h: int, fps: int, out: str) -> None:
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    _ff(["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-t", str(dur), "-vf", vf,
         "-r", str(fps), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "fast", out])


def _mux_segment(clip: str, audio: str, dur: float, w: int, h: int, fps: int, out: str, draw: str | None = None) -> None:
    # tpad=stop_mode=clone 把视频补到 -t dur（clip 比时长短时克隆末帧），保证每段恰好 dur、拼接不漂移
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
          f"setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={dur}")
    if draw:
        vf = vf + "," + draw
    if audio and Path(audio).exists():
        cmd = ["ffmpeg", "-y", "-i", clip, "-i", audio,
               "-filter_complex", f"[0:v]{vf}[v];[1:a]apad[a]",
               "-map", "[v]", "-map", "[a]", "-t", str(dur),
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ar", "48000", out]
    else:
        cmd = ["ffmpeg", "-y", "-i", clip, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-vf", vf, "-t", str(dur),
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", out]
    _ff(cmd)


def _concat(segs: list[str], clips_dir: Path, output_path: str) -> None:
    if not segs:
        raise RuntimeError("无分镜片段可拼接")
    listfile = clips_dir / "concat.txt"
    listfile.write_text("".join(f"file '{Path(s).as_posix()}'\n" for s in segs), encoding="utf-8")
    _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-movflags", "+faststart", output_path])
