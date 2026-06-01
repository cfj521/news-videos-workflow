import json
from unittest.mock import AsyncMock

import pytest

from app.providers.base import ProviderError
from app.providers.video.comfyui_video import ComfyUIVideoProvider, _snap_frames


def test_snap_frames():
    assert _snap_frames(1) == 5            # 4n+1 下限
    assert _snap_frames(120) == 121        # 4n+1
    assert _snap_frames(10**9) == 257      # 上限
    assert (_snap_frames(60, 8) - 1) % 8 == 0   # LTX 8n+1 对齐
    assert (_snap_frames(53, 8) - 1) % 8 == 0


@pytest.mark.asyncio
async def test_generate_uploads_fills_transcodes(tmp_path, monkeypatch):
    out = str(tmp_path / "clip.mp4")
    prov = ComfyUIVideoProvider(server_url="http://x:8188", workflow="wan5b", fps=24, negative="neg")
    captured = {}

    async def up(image_path): return "scene.png"
    async def run(graph): captured["graph"] = graph; return [{"kind": "images", "filename": "v.mp4", "subfolder": "", "type": "output"}]
    async def fetch(fn, subfolder="", folder_type="output"): return b"MP4DATA"

    monkeypatch.setattr(prov._client, "upload_image", up)
    monkeypatch.setattr(prov._client, "run", run)
    monkeypatch.setattr(prov._client, "fetch", fetch)

    def fake_run(cmd, **kw):
        open(cmd[-1], "wb").write(b"MP4")
        class R: returncode = 0; stderr = b""
        return R()
    monkeypatch.setattr("app.providers.video.comfyui_video.subprocess.run", fake_run)

    res = await prov.generate(image_path=str(tmp_path / "in.png"), prompt="reporter", duration=5.0, resolution="704x480", output_path=out)
    assert res.file_path == out
    blob = json.dumps(captured["graph"], ensure_ascii=False)
    assert "scene.png" in blob and "reporter" in blob and "neg" in blob and "__" not in blob


@pytest.mark.asyncio
async def test_generate_no_output_raises(tmp_path, monkeypatch):
    prov = ComfyUIVideoProvider(server_url="http://x:8188", workflow="ltx")
    monkeypatch.setattr(prov._client, "upload_image", AsyncMock(return_value="s.png"))
    monkeypatch.setattr(prov._client, "run", AsyncMock(return_value=[]))
    with pytest.raises(ProviderError):
        await prov.generate(image_path=str(tmp_path / "i.png"), prompt="p", duration=2.0, resolution="704x480", output_path=str(tmp_path / "o.mp4"))
