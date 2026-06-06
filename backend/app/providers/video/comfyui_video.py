import random
import subprocess
import tempfile
from pathlib import Path

from app.logging import get_logger
from app.providers.base import AssetResult, ProviderError, VideoClipProvider
from app.providers.comfyui.client import ComfyUIClient
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow

log = get_logger("provider.video.comfyui")

_WORKFLOW_MAP = {"wan2.2_5b": "wan22_5b_i2v", "wan2.2_14b": "wan22_14b_i2v",
                 "wan2.2_14b_lightx2v": "wan22_14b_i2v_lightx2v", "ltx_2.3": "ltx23_i2v"}
# 文生视频（t2v）工作流：无 INPUT_IMAGE / STEPS / CFG 占位符，步数 cfg 写死在 json。
_T2V_WORKFLOW_MAP = {"wan2.2_5b": "wan22_5b_t2v", "wan2.2_14b": "wan22_14b_t2v",
                     "wan2.2_14b_lightx2v": "wan22_14b_t2v_lightx2v", "ltx_2.3": "ltx23_t2v"}


def _snap16(v: int) -> int:
    return max(256, (v // 16) * 16)


def _snap_frames(n: int, step: int = 4) -> int:
    """帧数对齐到 step*k+1（wan 用 4，LTX 时间 VAE 用 8），下限 step+1、上限 257。"""
    return max(step + 1, min(step * round((n - 1) / step) + 1, 257))


class ComfyUIVideoProvider(VideoClipProvider):
    def __init__(self, server_url: str, workflow: str = "wan2.2_5b",
                 workflows_dir: str = "comfyui/workflows/api", fps: int = 24, negative: str = "",
                 steps: int = 20, cfg: float = 5.0, mode: str = "i2v"):
        # 视频生成远慢于图片：14B 满帧单段可达 10+ 分钟。默认 600s 会让 ComfyUI 已成功的
        # 结果被客户端提前丢弃（实测 wan14b 即如此），故视频 provider 用更长的轮询超时。
        self._client = ComfyUIClient(server_url=server_url, timeout=1800.0)
        self._mode = mode
        wfmap = _T2V_WORKFLOW_MAP if mode == "t2v" else _WORKFLOW_MAP
        self._wf = wfmap.get(workflow, "wan22_5b_t2v" if mode == "t2v" else "wan22_5b_i2v")
        self._dir = workflows_dir
        self._fps = fps
        self._negative = negative
        self._steps = steps
        self._cfg = cfg
        self._server = server_url

    async def generate(self, image_path: str, prompt: str, duration: float,
                       resolution: str = "704x480", output_path: str = "") -> AssetResult:
        parts = str(resolution).lower().split("x")
        try:
            w, h = _snap16(int(parts[0])), _snap16(int(parts[1]))
        except Exception:
            w, h = 704, 480
        # 各模型原生帧率不同：wan2.2 5B=24fps、14B=16fps、LTX=25fps（内部 8n+1 帧）。
        # 必须按原生帧率算帧数+转码——否则帧数(按 24 算)与 workflow 内 CreateVideo 标注的 fps 不符，
        # 时长会偏（实测 14b 每段变 15s/10s）。14B 的 i2v/t2v workflow 名均含 "14b"。
        is_ltx = self._wf in ("ltx23_i2v", "ltx23_t2v")
        if is_ltx:
            eff_fps = 25
        elif "14b" in self._wf:
            eff_fps = 16
        else:
            eff_fps = self._fps
        frames = _snap_frames(round(duration * eff_fps), 8 if is_ltx else 4)
        tmp = None
        try:
            values = {
                "POSITIVE_PROMPT": prompt, "NEGATIVE_PROMPT": self._negative,
                "SEED": random.randint(0, 2**31 - 1), "WIDTH": w, "HEIGHT": h, "LENGTH": frames,
                # wan5b/wan14b 用 STEPS/CFG；wan14b 双段切换点 SPLIT=steps//2；ltx 仅用 CFG。
                # 各 workflow 只填自身存在的占位符，多传的 key 无害。
                "STEPS": self._steps, "CFG": self._cfg, "SPLIT": max(1, self._steps // 2),
            }
            # i2v 需上传源图并填 INPUT_IMAGE；t2v 无图，直接文生视频。
            if self._mode != "t2v":
                values["INPUT_IMAGE"] = await self._client.upload_image(image_path)
            graph = fill_placeholders(load_api_workflow(self._wf, self._dir), values)
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
