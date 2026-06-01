import json
from unittest.mock import AsyncMock, patch

import pytest

from app.providers.base import ProviderError
from app.providers.image.comfyui_image import ComfyUIImageProvider


@pytest.mark.asyncio
async def test_generate_fills_and_writes(tmp_path):
    out = str(tmp_path / "img.png")
    prov = ComfyUIImageProvider(server_url="http://x:8188", workflow="z_image", negative="neg")
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
    prov = ComfyUIImageProvider(server_url="http://x:8188", workflow="qwen")
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
