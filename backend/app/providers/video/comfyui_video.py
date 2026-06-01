import random
import subprocess
import tempfile
from pathlib import Path

from app.logging import get_logger
from app.providers.base import AssetResult, ProviderError, VideoClipProvider
from app.providers.comfyui.client import ComfyUIClient
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow

log = get_logger("provider.video.comfyui")

_WORKFLOW_MAP = {"wan5b": "wan22_5b_i2v", "wan14b": "wan22_14b_i2v",
                 "wan14b_lightx2v": "wan22_14b_i2v_lightx2v", "ltx": "ltx23_i2v"}


def _snap16(v: int) -> int:
    return max(256, (v // 16) * 16)


def _snap_frames(n: int, step: int = 4) -> int:
    """帧数对齐到 step*k+1（wan 用 4，LTX 时间 VAE 用 8），下限 step+1、上限 257。"""
    return max(step + 1, min(step * round((n - 1) / step) + 1, 257))


class ComfyUIVideoProvider(VideoClipProvider):
    def __init__(self, server_url: str, workflow: str = "wan5b",
                 workflows_dir: str = "comfyui/workflows/api", fps: int = 24, negative: str = ""):
        self._client = ComfyUIClient(server_url=server_url)
        self._wf = _WORKFLOW_MAP.get(workflow, "wan22_5b_i2v")
        self._dir = workflows_dir
        self._fps = fps
        self._negative = negative
        self._server = server_url

    async def generate(self, image_path: str, prompt: str, duration: float,
                       resolution: str = "704x480", output_path: str = "") -> AssetResult:
        parts = str(resolution).lower().split("x")
        try:
            w, h = _snap16(int(parts[0])), _snap16(int(parts[1]))
        except Exception:
            w, h = 704, 480
        # LTX 时间 VAE 需 8n+1 帧、内部 25fps；wan 系列 4n+1、用配置 fps
        is_ltx = self._wf == "ltx23_i2v"
        eff_fps = 25 if is_ltx else self._fps
        frames = _snap_frames(round(duration * eff_fps), 8 if is_ltx else 4)
        tmp = None
        try:
            server_name = await self._client.upload_image(image_path)
            graph = fill_placeholders(load_api_workflow(self._wf, self._dir), {
                "INPUT_IMAGE": server_name, "POSITIVE_PROMPT": prompt, "NEGATIVE_PROMPT": self._negative,
                "SEED": random.randint(0, 2**31 - 1), "WIDTH": w, "HEIGHT": h, "LENGTH": frames,
            })
            files = await self._client.run(graph)
            pick = None
            for kind in ("videos", "gifs", "images"):
                cands = [f for f in files if f["kind"] == kind]
                if cands:
                    pick = cands[0]
                    break
            if not pick:
                raise RuntimeError("ComfyUI 未产出视频/图片输出")
            data = await self._client.fetch(pick["filename"], pick["subfolder"], pick["type"])
            ext = Path(pick["filename"]).suffix or ".mp4"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                tf.write(data)
                tmp = tf.name
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cmd = ["ffmpeg", "-y", "-i", tmp,
                   "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                   "-r", str(eff_fps), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "fast", output_path]
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg 转码失败: {r.stderr.decode('utf-8', 'replace')[:300]}")
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(service="视频生成", provider="comfyui", model=self._wf, base_url=self._server, cause=e) from e
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)
        log.info("ComfyUI clip done %dx%d %d帧 @%sfps → %s", w, h, frames, eff_fps, output_path)
        return AssetResult(file_path=output_path, duration_ms=int(frames / eff_fps * 1000))
