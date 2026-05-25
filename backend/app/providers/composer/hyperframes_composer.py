import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.providers.base import ComposerProvider, VideoResult

TEMPLATE_DIR = Path(__file__).parent / "templates"


class HyperframesComposer(ComposerProvider):
    async def compose(
        self,
        timeline_json: dict,
        assets_dir: str,
        output_path: str,
        resolution: str = "1080x1920",
    ) -> VideoResult:
        html = self._render_html(timeline_json, resolution)

        project_dir = Path(assets_dir).parent / "hyperframes_project"
        project_dir.mkdir(parents=True, exist_ok=True)
        index_html = project_dir / "index.html"
        index_html.write_text(html, encoding="utf-8")

        self._link_assets(assets_dir, project_dir)

        result = subprocess.run(
            [
                "npx",
                "hyperframes",
                "render",
                "--output",
                output_path,
                "--fps",
                "30",
                "--quality",
                "standard",
            ],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Hyperframes render failed: {result.stderr}")

        thumbnail_path = output_path.replace(".mp4", "_thumb.jpg")
        self._extract_thumbnail(output_path, thumbnail_path)

        return VideoResult(
            file_path=output_path,
            thumbnail_path=thumbnail_path if Path(thumbnail_path).exists() else None,
            duration_ms=timeline_json.get("total_duration_ms", 0),
            resolution=resolution,
        )

    def _render_html(self, timeline: dict, resolution: str) -> str:
        parts = resolution.split("x")
        width, height = int(parts[0]), int(parts[1])
        total_ms = timeline["total_duration_ms"]
        total_s = total_ms / 1000

        entries = []
        prev_scene_ids = []
        for i, entry in enumerate(timeline["entries"]):
            if i > 0:
                prev_scene_ids.append(timeline["entries"][i - 1]["scene_id"])
            else:
                prev_scene_ids.append(None)

            entries.append(
                {
                    "scene_id": entry["scene_id"],
                    "start_s": round(entry["start_ms"] / 1000, 3),
                    "end_s": round(entry["end_ms"] / 1000, 3),
                    "duration_s": round((entry["end_ms"] - entry["start_ms"]) / 1000, 3),
                    "image_path": entry["image_path"],
                    "audio_path": entry["audio_path"],
                    "audio_duration_s": round(entry.get("audio_duration_ms", 0) / 1000, 3),
                    "subtitle_text": entry.get("subtitle_text", ""),
                }
            )

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("composition.html.j2")
        return template.render(
            width=width,
            height=height,
            total_duration_s=round(total_s, 3),
            entries=entries,
            prev_scene_ids=prev_scene_ids,
        )

    def _link_assets(self, assets_dir: str, project_dir: Path) -> None:
        assets_link = project_dir / "assets"
        if not assets_link.exists():
            assets_src = Path(assets_dir).resolve()
            try:
                assets_link.symlink_to(assets_src)
            except OSError:
                import shutil

                if assets_src.exists():
                    shutil.copytree(str(assets_src), str(assets_link))

    def _extract_thumbnail(self, video_path: str, thumb_path: str) -> None:
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-ss",
                    "1",
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    thumb_path,
                    "-y",
                ],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass
