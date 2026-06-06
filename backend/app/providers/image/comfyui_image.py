import random
from pathlib import Path

from app.logging import get_logger
from app.providers.base import AssetResult, ImageProvider, ProviderError
from app.providers.comfyui.client import ComfyUIClient
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow

log = get_logger("provider.image.comfyui")

_WORKFLOW_MAP = {"z_image_turbo": "z_image_t2i", "qwen_image": "qwen_image_t2i"}


def _snap16(v: int) -> int:
    return max(256, (v // 16) * 16)


class ComfyUIImageProvider(ImageProvider):
    def __init__(self, server_url: str, workflow: str = "z_image_turbo",
                 workflows_dir: str = "comfyui/workflows/api", negative: str = "",
                 steps: int = 9, cfg: float = 1.0):
        self._client = ComfyUIClient(server_url=server_url)
        self._wf = _WORKFLOW_MAP.get(workflow, "z_image_t2i")
        self._dir = workflows_dir
        self._negative = negative
        self._steps = steps
        self._cfg = cfg
        self._server = server_url
        log.info("Initialized ComfyUIImageProvider server=%s workflow=%s", server_url, self._wf)

    async def generate(self, prompt: str, size: str = "1080x1920", output_path: str = "") -> AssetResult:
        parts = str(size).lower().split("x")
        try:
            w, h = _snap16(int(parts[0])), _snap16(int(parts[1]))
        except Exception:
            w, h = 1024, 1024
        try:
            graph = fill_placeholders(load_api_workflow(self._wf, self._dir), {
                "POSITIVE_PROMPT": prompt, "NEGATIVE_PROMPT": self._negative,
                "SEED": random.randint(0, 2**31 - 1), "WIDTH": w, "HEIGHT": h,
                "STEPS": self._steps, "CFG": self._cfg,
            })
            files = await self._client.run(graph)
            imgs = [f for f in files if f["kind"] == "images"]
            if not imgs:
                raise RuntimeError("ComfyUI 未产出图片")
            data = await self._client.fetch(imgs[0]["filename"], imgs[0]["subfolder"], imgs[0]["type"])
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(data)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(service="图片生成", provider="comfyui", model=self._wf, base_url=self._server, cause=e) from e
        log.info("ComfyUI image done %dx%d → %s", w, h, output_path)
        return AssetResult(file_path=output_path)
