import os
import subprocess
import time
from pathlib import Path

# Windows 上 npx 是 npx.cmd，subprocess 需经 shell 才能解析；POSIX 上 npx 是真实
# 可执行文件，且 shell=True 配合列表参数会丢掉除第一项外的所有参数，必须 shell=False。
_NEEDS_SHELL = os.name == "nt"

from jinja2 import Environment, FileSystemLoader

from app.logging import get_logger
from app.providers.base import ComposerProvider, VideoResult

log = get_logger("composer.hyperframes")

TEMPLATE_DIR = Path(__file__).parent / "templates"


class HyperframesComposer(ComposerProvider):
    def __init__(self, overlay=None):
        from app.config import OverlayCfg
        self._overlay = overlay or OverlayCfg()

    async def compose(self, timeline_json: dict, assets_dir: str, output_path: str, resolution: str = "1080x1920") -> VideoResult:
        run_dir = Path(assets_dir).parent
        log.info("compose() entries=%d resolution=%s run_dir=%s", len(timeline_json.get("entries", [])), resolution, run_dir)
        t0 = time.time()

        html = self._render_html(timeline_json, resolution, run_dir)
        (run_dir / "index.html").write_text(html, encoding="utf-8")
        log.info("index.html written to %s", run_dir)

        abs_output = str(Path(output_path).resolve())
        abs_thumb = abs_output.replace(".mp4", "_thumb.jpg")

        log.info("Running npx hyperframes render → %s", abs_output)
        result = subprocess.run(
            ["npx", "hyperframes", "render", "--output", abs_output, "--fps", "30", "--quality", "standard"],
            cwd=str(run_dir), capture_output=True, timeout=600, shell=_NEEDS_SHELL,
        )

        if result.returncode != 0:
            stderr = ""
            try:
                stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else (result.stderr or "")
            except Exception:
                stderr = str(result.stderr)
            log.error("Hyperframes render failed (code %d): %s", result.returncode, stderr[:500])
            raise RuntimeError(f"Hyperframes render failed: {stderr[:500]}")

        elapsed = time.time() - t0
        log.info("Hyperframes render done in %.1fs", elapsed)

        self._extract_thumbnail(abs_output, abs_thumb)

        return VideoResult(
            file_path=abs_output,
            thumbnail_path=abs_thumb if Path(abs_thumb).exists() else None,
            duration_ms=timeline_json.get("total_duration_ms", 0),
            resolution=resolution,
        )

    def _render_html(self, timeline: dict, resolution: str, run_dir: Path, transition: str = "crossfade", subtitle_font_size: int = 48, subtitle_bottom_px: int = 80) -> str:
        parts = resolution.split("x")
        width, height = int(parts[0]), int(parts[1])
        total_s = timeline["total_duration_ms"] / 1000

        entries = []
        prev_scene_ids = []
        for i, entry in enumerate(timeline["entries"]):
            prev_scene_ids.append(timeline["entries"][i - 1]["scene_id"] if i > 0 else None)

            img_abs = entry["image_path"]
            audio_abs = entry["audio_path"]
            try:
                img_rel = str(Path(img_abs).relative_to(run_dir)).replace("\\", "/")
            except ValueError:
                img_rel = Path(img_abs).name
            try:
                audio_rel = str(Path(audio_abs).relative_to(run_dir)).replace("\\", "/")
            except ValueError:
                audio_rel = Path(audio_abs).name

            sub_lines = entry.get("subtitle_lines", [])
            scene_start_s = round(entry["start_ms"] / 1000, 3)
            template_lines = []
            for sl in sub_lines:
                template_lines.append({
                    "text": sl["text"],
                    "start_s": round(sl["start_ms"] / 1000, 3),
                    "end_s": round(sl["end_ms"] / 1000, 3),
                })

            entries.append({
                "scene_id": entry["scene_id"],
                "start_s": scene_start_s,
                "end_s": round(entry["end_ms"] / 1000, 3),
                "duration_s": round((entry["end_ms"] - entry["start_ms"]) / 1000, 3),
                "image_path": img_rel,
                "audio_path": audio_rel,
                "audio_duration_s": round(entry.get("audio_duration_ms", 0) / 1000, 3),
                "subtitle_text": entry.get("subtitle_text", ""),
                "subtitle_lines": template_lines,
                "group_id": entry.get("group_id"),
                "title": entry.get("title", ""),
            })

        title_overlays = []
        for e in entries:
            gid = e.get("group_id")
            title = e.get("title", "")
            if title and gid is not None and title_overlays and title_overlays[-1]["group_id"] == gid:
                title_overlays[-1]["end_s"] = e["end_s"]       # 同组连续 → 延长
            elif title:
                title_overlays.append({"group_id": gid, "title": title,
                                       "start_s": e["start_s"], "end_s": e["end_s"]})
        title_font_size = max(20, int(height * self._overlay.font_size_ratio))
        title_margin_px = int(min(width, height) * self._overlay.margin_ratio)

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("composition.html.j2")
        return template.render(width=width, height=height, total_duration_s=round(total_s, 3),
                               entries=entries, prev_scene_ids=prev_scene_ids, transition=transition,
                               subtitle_font_size=subtitle_font_size,
                               subtitle_bottom_px=subtitle_bottom_px,
                               title_overlays=title_overlays, title_font_size=title_font_size,
                               title_margin_px=title_margin_px,
                               overlay=self._overlay)

    def _extract_thumbnail(self, video_path: str, thumb_path: str) -> None:
        try:
            subprocess.run(
                ["ffmpeg", "-i", video_path, "-ss", "1", "-vframes", "1", "-q:v", "2", thumb_path, "-y"],
                capture_output=True, timeout=30,
            )
            if Path(thumb_path).exists():
                log.info("Thumbnail extracted → %s", thumb_path)
            else:
                log.warning("Thumbnail extraction produced no output")
        except Exception:
            log.warning("Thumbnail extraction failed", exc_info=True)
