import json
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow
from app.providers.video import build_video_provider
from app.providers.video.comfyui_video import ComfyUIVideoProvider, _snap_frames

# 给 fill_placeholders 的占位符全集（含视频参数）；各 workflow 只取自身存在的，多传无害。
_VALUES = {
    "INPUT_IMAGE": "s.png", "POSITIVE_PROMPT": "p", "NEGATIVE_PROMPT": "n",
    "SEED": 1, "WIDTH": 704, "HEIGHT": 480, "LENGTH": 49,
    "STEPS": 24, "CFG": 4.0, "SPLIT": 12,
}


def test_wan5b_fills_steps_cfg():
    g = fill_placeholders(load_api_workflow("wan22_5b_i2v", "comfyui/workflows/api"), _VALUES)
    assert g["3"]["inputs"]["steps"] == 24
    assert g["3"]["inputs"]["cfg"] == 4.0


def test_wan14b_fills_steps_cfg_and_split():
    g = fill_placeholders(load_api_workflow("wan22_14b_i2v", "comfyui/workflows/api"), _VALUES)
    for nid in ("57", "58"):
        assert g[nid]["inputs"]["steps"] == 24
        assert g[nid]["inputs"]["cfg"] == 4.0
    # 高噪段 end_at_step 与低噪段 start_at_step 都取切换点 SPLIT
    assert g["57"]["inputs"]["end_at_step"] == 12
    assert g["58"]["inputs"]["start_at_step"] == 12


def test_ltx_fills_cfg_only():
    g = fill_placeholders(load_api_workflow("ltx23_i2v", "comfyui/workflows/api"), _VALUES)
    assert g["13"]["inputs"]["cfg"] == 4.0


def test_build_video_provider_resolves_params_for_selected_workflow():
    s = Settings()
    s.comfyui.video_workflow = "wan14b"
    prov = build_video_provider(s)
    assert prov._steps == s.comfyui.video_params["wan14b"].steps == 20
    assert prov._cfg == s.comfyui.video_params["wan14b"].cfg == 3.5


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
