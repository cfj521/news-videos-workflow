import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.base import ProviderError
from app.providers.comfyui.client import ComfyUIClient
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow


def _resp(json_value=None, content=b"", status=200):
    r = MagicMock()
    r.json.return_value = json_value or {}
    r.content = content
    r.text = json.dumps(json_value or {})
    r.raise_for_status = MagicMock()
    return r


def _mock_client(mock_cls):
    c = AsyncMock()
    c.__aenter__.return_value = c
    mock_cls.return_value = c
    return c


def test_server_url_env_override(monkeypatch):
    """NV_COMFYUI_URL 覆盖传入的 server_url（docker 场景注入 host.docker.internal）。"""
    monkeypatch.setenv("NV_COMFYUI_URL", "http://host.docker.internal:8188")
    c = ComfyUIClient(server_url="http://127.0.0.1:8188")
    assert c._url == "http://host.docker.internal:8188"


def test_server_url_without_env(monkeypatch):
    """无环境变量时用传入的 server_url，并去掉尾部斜杠。"""
    monkeypatch.delenv("NV_COMFYUI_URL", raising=False)
    c = ComfyUIClient(server_url="http://127.0.0.1:8188/")
    assert c._url == "http://127.0.0.1:8188"


@pytest.mark.asyncio
async def test_submit_returns_prompt_id():
    with patch("app.providers.comfyui.client.httpx.AsyncClient") as mc:
        c = _mock_client(mc)
        c.post = AsyncMock(return_value=_resp({"prompt_id": "pid123"}))
        cli = ComfyUIClient("http://x:8188")
        assert await cli.submit({"1": {}}) == "pid123"


@pytest.mark.asyncio
async def test_wait_collects_outputs():
    with patch("app.providers.comfyui.client.httpx.AsyncClient") as mc:
        c = _mock_client(mc)
        hist = {"pid": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        c.get = AsyncMock(return_value=_resp(hist))
        cli = ComfyUIClient("http://x:8188")
        outs = await cli.wait("pid")
        assert outs["9"]["images"][0]["filename"] == "a.png"


@pytest.mark.asyncio
async def test_wait_raises_on_error_status():
    with patch("app.providers.comfyui.client.httpx.AsyncClient") as mc:
        c = _mock_client(mc)
        c.get = AsyncMock(return_value=_resp({"pid": {"status": {"status_str": "error", "messages": ["boom"]}}}))
        cli = ComfyUIClient("http://x:8188")
        with pytest.raises(ProviderError):
            await cli.wait("pid")


@pytest.mark.asyncio
async def test_run_flattens_image_files():
    with patch("app.providers.comfyui.client.httpx.AsyncClient") as mc:
        c = _mock_client(mc)
        c.post = AsyncMock(return_value=_resp({"prompt_id": "p"}))
        c.get = AsyncMock(return_value=_resp({"p": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "sf", "type": "output"}]}}}}))
        cli = ComfyUIClient("http://x:8188")
        files = await cli.run({"1": {}})
        assert files == [{"kind": "images", "filename": "a.png", "subfolder": "sf", "type": "output"}]


def test_load_and_fill_workflow():
    g = load_api_workflow("z_image_t2i", "comfyui/workflows/api")
    assert isinstance(g, dict) and g
    filled = fill_placeholders(g, {"POSITIVE_PROMPT": "p", "NEGATIVE_PROMPT": "n", "SEED": 1, "WIDTH": 512, "HEIGHT": 512, "STEPS": 9, "CFG": 1.0})
    s = json.dumps(filled, ensure_ascii=False)
    assert "__" not in s


def test_fill_raises_on_unfilled():
    with pytest.raises(ValueError):
        fill_placeholders({"a": "__MISSING__"}, {})


@pytest.mark.asyncio
async def test_upload_image_returns_name(tmp_path):
    p = tmp_path / "x.png"; p.write_bytes(b"PNG")
    with patch("app.providers.comfyui.client.httpx.AsyncClient") as mc:
        c = _mock_client(mc)
        c.post = AsyncMock(return_value=_resp({"name": "x.png", "subfolder": "", "type": "input"}))
        cli = ComfyUIClient("http://x:8188")
        assert await cli.upload_image(str(p)) == "x.png"
