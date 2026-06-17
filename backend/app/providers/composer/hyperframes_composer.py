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
            audio_abs = entry.get("audio_path", "")
            try:
                img_rel = str(Path(img_abs).relative_to(run_dir)).replace("\\", "/") if img_abs else ""
            except ValueError:
                img_rel = Path(img_abs).name if img_abs else ""
            try:
                audio_rel = str(Path(audio_abs).relative_to(run_dir)).replace("\\", "/") if audio_abs else ""
            except ValueError:
                audio_rel = Path(audio_abs).name if audio_abs else ""

            is_cover = entry.get("is_cover", False)
            scene_start_s = round(entry["start_ms"] / 1000, 3)

            # 封面 entry 不走逐行字幕处理
            template_lines = []
            if not is_cover:
                sub_lines = entry.get("subtitle_lines", [])
                for sl in sub_lines:
                    template_lines.append({
                        "text": sl["text"],
                        "start_s": round(sl["start_ms"] / 1000, 3),
                        "end_s": round(sl["end_ms"] / 1000, 3),
                    })

            entries.append({
                "scene_id": entry["scene_id"],
                "is_cover": is_cover,
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
                "subtitle": entry.get("subtitle", ""),
                "cover_font_size": entry.get("cover_font_size", 72),
            })

        title_overlays = []
        for e in entries:
            if e.get("is_cover"):
                continue  # 封面 entry 不渲染分组标题叠层
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

    async def render_cover_clip(self, cover_entry: dict, resolution: str, run_dir: Path, output_path: str) -> str:
        """把单个封面 entry 渲成独立片段（cover.mp4），供 comfyui 路拼接到开头。

        优先用 hyperframes（与正片同款视觉）；npx 不可用/失败则 FFmpeg 兜底。

        hyperframes render 默认读当前工作目录的 index.html，不支持指定输入文件路径。
        为避免覆盖正片的 index.html，在 run_dir/_cover/ 子目录里放封面专属 index.html，
        并把 assets（图片/音频）以相对路径引用（cover_entry 里已是绝对路径，写 HTML 时
        _render_html 会尝试相对化；assets 在 run_dir 内均可正确计算出 ../xxx 的相对路径）。
        """
        # 构造只含封面 entry 的临时 timeline，start_ms 归 0
        e = dict(cover_entry)
        e["start_ms"] = 0
        dur_ms = int(e.get("end_ms", 0)) or 4000
        e["end_ms"] = dur_ms
        timeline = {"entries": [e], "total_duration_ms": dur_ms}

        # 子目录用于隔离封面渲染，避免污染正片 index.html
        cover_dir = run_dir / "_cover"
        cover_dir.mkdir(exist_ok=True)

        # _render_html 里路径相对化以 run_dir 为基准，但 npx 渲染 cwd 是 cover_dir；
        # 封面图片/音频均在 run_dir 内（或绝对路径），相对于 cover_dir 需加 "../" 前缀。
        # 直接把绝对路径写入 HTML：浏览器 file:// 协议支持绝对路径，hyperframes 本地渲染同样支持。
        html = self._render_html(timeline, resolution, cover_dir)
        (cover_dir / "index.html").write_text(html, encoding="utf-8")

        abs_out = str(Path(output_path).resolve())

        try:
            log.info("[cover] Running npx hyperframes render → %s (cwd=%s)", abs_out, cover_dir)
            result = subprocess.run(
                ["npx", "hyperframes", "render", "--output", abs_out, "--fps", "30", "--quality", "standard"],
                cwd=str(cover_dir), capture_output=True, timeout=600, shell=_NEEDS_SHELL,
            )
            if result.returncode != 0:
                stderr = ""
                try:
                    stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else (result.stderr or "")
                except Exception:
                    stderr = str(result.stderr)
                raise RuntimeError(f"Hyperframes cover render failed (code {result.returncode}): {stderr[:400]}")

            if Path(abs_out).exists():
                log.info("[cover] hyperframes 封面渲染成功 → %s", abs_out)
                return abs_out
            raise RuntimeError("npx 成功但输出文件不存在")

        except Exception as ex:
            log.warning("[cover] 封面 hyperframes 渲染失败，回退 FFmpeg: %s", ex)

        # FFmpeg 兜底
        self._ffmpeg_cover_fallback(e, resolution, run_dir, abs_out)
        return abs_out

    def _ffmpeg_cover_fallback(self, entry: dict, resolution: str, run_dir: Path, out: str) -> None:
        """FFmpeg 兜底封面：静态图循环 + 可选音频 + 居中标题/副标题 drawtext。

        参照 runner._ffmpeg_compose / comfyui_composer._mux_segment 的 subprocess 风格。
        无封面图时用纯黑底（lavfi color=black）。
        """
        parts = resolution.split("x")
        w, h = int(parts[0]), int(parts[1])
        dur_s = max(1.0, (entry.get("end_ms", 4000)) / 1000)

        image_path = entry.get("image_path", "")
        audio_path = entry.get("audio_path", "")
        title = entry.get("title", "")
        subtitle = entry.get("subtitle", "")
        font_file = getattr(self._overlay, "font_file", "") or ""

        # ── 视频输入：有图用静态图循环，无图用纯黑底 ──
        if image_path and Path(image_path).exists():
            video_inputs = ["-loop", "1", "-t", str(dur_s), "-i", image_path]
            video_idx = 0
        else:
            # lavfi color source：尺寸内置，不需要额外 scale
            video_inputs = ["-f", "lavfi", "-t", str(dur_s),
                            "-i", f"color=black:size={w}x{h}:rate=30"]
            video_idx = 0

        # ── 音频输入：有音频用真实音频，无音频用静音 ──
        if audio_path and Path(audio_path).exists():
            audio_inputs = ["-i", audio_path]
            audio_idx = 1
            audio_map = f"[{audio_idx}:a]apad=whole_dur={dur_s}[aout]"
        else:
            # 无旁白时生成静音轨道
            audio_inputs = ["-f", "lavfi", "-t", str(dur_s), "-i", "anullsrc=r=48000:cl=stereo"]
            audio_idx = 1
            audio_map = f"[{audio_idx}:a]acopy[aout]"

        # ── 视频滤镜：scale/pad → drawtext（有字体才加） ──
        vf = (f"[{video_idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")

        if font_file and Path(font_file).exists() and (title or subtitle):
            # drawtext：标题居中，副标题在标题下方
            def _escape_drawtext(s: str) -> str:
                return s.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")

            font_size = entry.get("cover_font_size", 72)
            sub_size = max(24, int(font_size * 0.55))
            ff_path = font_file.replace("\\", "/")

            if title:
                vf += (f",drawtext=fontfile='{ff_path}':text='{_escape_drawtext(title)}':"
                       f"fontsize={font_size}:fontcolor=white:borderw=3:bordercolor=black:"
                       f"x=(w-text_w)/2:y=(h-text_h)/2-{sub_size if subtitle else 0}")
            if subtitle:
                vf += (f",drawtext=fontfile='{ff_path}':text='{_escape_drawtext(subtitle)}':"
                       f"fontsize={sub_size}:fontcolor=white:borderw=2:bordercolor=black:"
                       f"x=(w-text_w)/2:y=(h+{font_size})/2+10")

        vf += "[vout]"

        fc = vf + ";" + audio_map
        cmd = [
            "ffmpeg", "-y",
            *video_inputs, *audio_inputs,
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(dur_s),
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000",
            out,
        ]
        log.info("[cover] FFmpeg 兜底封面 — dur=%.1fs out=%s", dur_s, out)
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
            msg = "；".join(tail[-4:]) if tail else f"ffmpeg 退出码 {proc.returncode}"
            raise RuntimeError(f"FFmpeg 封面兜底失败: {msg}")
        log.info("[cover] FFmpeg 封面 done → %s", out)

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
