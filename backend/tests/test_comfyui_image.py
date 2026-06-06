import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow
from app.providers.image import build_image_provider
from app.providers.image.comfyui_image import ComfyUIImageProvider

_IMG_VALUES = {
    "POSITIVE_PROMPT": "p", "NEGATIVE_PROMPT": "n",
    "SEED": 1, "WIDTH": 1024, "HEIGHT": 1024, "STEPS": 12, "CFG": 3.0,
}


@pytest.mark.parametrize("name", ["z_image_t2i", "qwen_image_t2i"])
def test_image_workflows_fill_steps_cfg(name):
    g = fill_placeholders(load_api_workflow(name, "comfyui/workflows/api"), _IMG_VALUES)
    assert g["3"]["inputs"]["steps"] == 12
    assert g["3"]["inputs"]["cfg"] == 3.0


def test_build_image_provider_uses_comfyui_group():
    s = Settings()
    s.pipeline.image_provider = "comfyui"
    s.pipeline.image_model = "qwen_image"      # 当前图片 workflow 由 pipeline 选型决定
    s.comfyui.server_url = "http://test:8188"
    prov = build_image_provider(s)
    assert isinstance(prov, ComfyUIImageProvider)
    assert prov._wf == "qwen_image_t2i"        # workflow 来自 pipeline.image_model
    assert prov._server == "http://test:8188"  # 统一用 comfyui.server_url
    assert prov._steps == 20 and prov._cfg == 2.5


@pytest.mark.asyncio
async def test_generate_fills_and_writes(tmp_path):
    out = str(tmp_path / "img.png")
    prov = ComfyUIImageProvider(server_url="http://x:8188", workflow="z_image_turbo", negative="neg")
    captured = {}

    async def fake_run(graph):
        captured["graph"] = graph
        return [{"kind": "images", "filename": "a.png", "subfolder": "", "type": "output"}]

    async def fake_fetch(filename, subfolder="", folder_type="output"):
        return b"PNGDATA"

    with patch.object(prov._client, "run", side_effect=fake_run), \
         patch.object(prov._client, "fetch", side_effect=fake_fetch):
        res = await prov.generate(prompt="a reporter", size="1080x1920", output_path=out)

    assert res.file_path == out
    assert (tmp_path / "img.png").read_bytes() == b"PNGDATA"
    blob = json.dumps(captured["graph"], ensure_ascii=False)
    assert "a reporter" in blob and "neg" in blob and "__" not in blob


@pytest.mark.asyncio
async def test_generate_bad_size_falls_back(tmp_path):
    prov = ComfyUIImageProvider(server_url="http://x:8188", workflow="qwen_image")
    captured = {}

    async def fake_run(graph):
        captured["graph"] = graph
        return [{"kind": "images", "filename": "a.png", "subfolder": "", "type": "output"}]

    with patch.object(prov._client, "run", side_effect=fake_run), \
         patch.object(prov._client, "fetch", side_effect=AsyncMock(return_value=b"X")):
        await prov.generate(prompt="p", size="不合法", output_path=str(tmp_path / "o.png"))
    widths = [v.get("inputs", {}).get("width") for v in captured["graph"].values() if isinstance(v, dict)]
    assert 1024 in widths


@pytest.mark.asyncio
async def test_generate_no_image_raises(tmp_path):
    prov = ComfyUIImageProvider(server_url="http://x:8188")
    with patch.object(prov._client, "run", side_effect=AsyncMock(return_value=[])):
        with pytest.raises(ProviderError):
            await prov.generate(prompt="p", size="512x512", output_path=str(tmp_path / "o.png"))
