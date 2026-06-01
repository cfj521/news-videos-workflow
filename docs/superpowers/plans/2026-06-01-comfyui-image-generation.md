# ComfyUI 接入 阶段1：图片生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端图片生成(Stage3)从只支持商用模型，扩展为可选商用或 ComfyUI 本地(z_image/Qwen)，并沉淀可复用的 ComfyUI 客户端（阶段2视频复用）。

**Architecture:** 新建 `providers/comfyui/`（client + workflow 加载/填充）→ `ComfyUIImageProvider(ImageProvider)` → `build_image_provider(cfg)` 工厂按 `cfg.image.provider` 选商用/ComfyUI，runner Stage3 与 api regen 共用。配置复用 `cfg.image`（provider=comfyui/base_url=地址/model=z_image|qwen）+ 新 `ComfyuiCfg`。

**Tech Stack:** Python(FastAPI/httpx/pytest)，React+TS。

参考 spec：`docs/superpowers/specs/2026-06-01-comfyui-image-generation-design.md`

---

## File Structure
- `backend/app/providers/comfyui/__init__.py`（新，空）
- `backend/app/providers/comfyui/client.py`（新）— `ComfyUIClient`
- `backend/app/providers/comfyui/workflow.py`（新）— `load_api_workflow` / `fill_placeholders`
- `backend/app/providers/image/comfyui_image.py`（新）— `ComfyUIImageProvider`
- `backend/app/providers/image/__init__.py`（改/新）— `build_image_provider(cfg)` 工厂
- `backend/app/config.py`（改）— `ComfyuiCfg` + `Settings.comfyui`
- `backend/app/pipeline/runner.py`（改）— Stage3 用工厂
- `backend/app/api/pipeline.py`（改）— regen 单图用工厂
- `frontend/src/pages/Settings.tsx`（改）— `IMAGE_PRESETS` 加 comfyui
- 测试：`backend/tests/test_comfyui_client.py`、`test_comfyui_image.py`、`test_build_image_provider.py`

---

## Task 1: ComfyUI 客户端 + 工作流加载/填充

**Files:** Create `backend/app/providers/comfyui/__init__.py`(空)、`client.py`、`workflow.py`；Test `backend/tests/test_comfyui_client.py`

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_comfyui_client.py`：

```python
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
    assert isinstance(g, dict) and g  # 真实文件存在
    filled = fill_placeholders(g, {"POSITIVE_PROMPT": "p", "NEGATIVE_PROMPT": "n", "SEED": 1, "WIDTH": 512, "HEIGHT": 512})
    s = json.dumps(filled, ensure_ascii=False)
    assert "__" not in s  # 占位符全部替换


def test_fill_raises_on_unfilled():
    with pytest.raises(ValueError):
        fill_placeholders({"a": "__MISSING__"}, {})
```

- [ ] **Step 2: 跑测试确认失败** — `cd backend && pytest tests/test_comfyui_client.py -v`（模块不存在）

- [ ] **Step 3: 实现** — 新建空 `backend/app/providers/comfyui/__init__.py`；

`backend/app/providers/comfyui/workflow.py`：
```python
import copy
import json
from pathlib import Path


def _repo_root() -> Path:
    # workflow.py 在 backend/app/providers/comfyui/ ；parents[4] = 仓库根
    return Path(__file__).resolve().parents[4]


def load_api_workflow(name: str, workflows_dir: str) -> dict:
    base = Path(workflows_dir)
    if not base.is_absolute():
        base = _repo_root() / base
    return json.loads((base / f"{name}.api.json").read_text(encoding="utf-8"))


def fill_placeholders(graph: dict, values: dict) -> dict:
    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str) and x.startswith("__") and x.endswith("__") and x[2:-2] in values:
            return values[x[2:-2]]
        return x
    out = walk(copy.deepcopy(graph))
    leftover = sorted({p for p in json.dumps(out).split('"') if p.startswith("__") and p.endswith("__")})
    if leftover:
        raise ValueError(f"unfilled placeholders: {leftover}")
    return out
```

`backend/app/providers/comfyui/client.py`：
```python
import asyncio
import json
import time
import uuid

import httpx

from app.logging import get_logger
from app.providers.base import ProviderError

log = get_logger("provider.comfyui.client")


class ComfyUIClient:
    def __init__(self, server_url: str = "http://127.0.0.1:8188", timeout: float = 600.0, poll_interval: float = 1.5):
        self._url = server_url.rstrip("/")
        self._timeout = timeout
        self._poll = poll_interval

    def _err(self, cause):
        return ProviderError(service="ComfyUI", provider="comfyui", base_url=self._url, cause=cause)

    async def submit(self, prompt_graph: dict) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._url}/prompt", json={"prompt": prompt_graph, "client_id": uuid.uuid4().hex})
                r.raise_for_status()
                pid = r.json().get("prompt_id")
        except ProviderError:
            raise
        except Exception as e:
            raise self._err(e) from e
        if not pid:
            raise self._err(RuntimeError("no prompt_id in /prompt response"))
        return pid

    async def wait(self, prompt_id: str) -> dict:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30) as c:
            while time.time() - t0 < self._timeout:
                r = await c.get(f"{self._url}/history/{prompt_id}")
                r.raise_for_status()
                hist = r.json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    if entry.get("status", {}).get("status_str") == "error":
                        msgs = entry.get("status", {}).get("messages", [])
                        raise self._err(RuntimeError(json.dumps(msgs, ensure_ascii=False)[:500]))
                    return entry.get("outputs", {})
                await asyncio.sleep(self._poll)
        raise self._err(RuntimeError(f"timeout {self._timeout}s waiting prompt {prompt_id}"))

    async def fetch(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.get(f"{self._url}/view", params={"filename": filename, "subfolder": subfolder, "type": folder_type})
                r.raise_for_status()
                return r.content
        except ProviderError:
            raise
        except Exception as e:
            raise self._err(e) from e

    async def run(self, prompt_graph: dict) -> list[dict]:
        outputs = await self.wait(await self.submit(prompt_graph))
        files: list[dict] = []
        for node_out in outputs.values():
            for kind in ("images", "gifs", "videos"):
                for f in node_out.get(kind, []):
                    files.append({"kind": kind, "filename": f.get("filename"),
                                  "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
        return files
```

- [ ] **Step 4: 跑测试确认通过** — `cd backend && pytest tests/test_comfyui_client.py -v`（6 passed）

- [ ] **Step 5: 提交**
```bash
git add backend/app/providers/comfyui backend/tests/test_comfyui_client.py
git commit -m "feat(comfyui): ComfyUI 客户端 + 工作流加载/填充"
```
结尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。分支 `feat/aihot-default-exclusion`，勿 push。

---

## Task 2: ComfyUIImageProvider

**Files:** Create `backend/app/providers/image/comfyui_image.py`；Test `backend/tests/test_comfyui_image.py`

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_comfyui_image.py`：

```python
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
    # 占位符已填：宽高按 /16 取整（1080->1072, 1920->1920），prompt/negative 注入
    g = captured["graph"]
    blob = __import__("json").dumps(g, ensure_ascii=False)
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
    # 回退 1024x1024
    assert '"width": 1024' in __import__("json").dumps(captured["graph"]) or 1024 in [
        v.get("inputs", {}).get("width") for v in captured["graph"].values() if isinstance(v, dict)]


@pytest.mark.asyncio
async def test_generate_no_image_raises(tmp_path):
    prov = ComfyUIImageProvider(server_url="http://x:8188")
    with patch.object(prov._client, "run", side_effect=AsyncMock(return_value=[])):
        with pytest.raises(ProviderError):
            await prov.generate(prompt="p", size="512x512", output_path=str(tmp_path / "o.png"))
```

- [ ] **Step 2: 跑测试确认失败** — `cd backend && pytest tests/test_comfyui_image.py -v`（模块不存在）

- [ ] **Step 3: 实现** — `backend/app/providers/image/comfyui_image.py`：
```python
import random
from pathlib import Path

from app.logging import get_logger
from app.providers.base import AssetResult, ImageProvider, ProviderError
from app.providers.comfyui.client import ComfyUIClient
from app.providers.comfyui.workflow import fill_placeholders, load_api_workflow

log = get_logger("provider.image.comfyui")

_WORKFLOW_MAP = {"z_image": "z_image_t2i", "qwen": "qwen_image_t2i"}


def _snap16(v: int) -> int:
    return max(256, (v // 16) * 16)


class ComfyUIImageProvider(ImageProvider):
    def __init__(self, server_url: str, workflow: str = "z_image",
                 workflows_dir: str = "comfyui/workflows/api", negative: str = ""):
        self._client = ComfyUIClient(server_url=server_url)
        self._wf = _WORKFLOW_MAP.get(workflow, "z_image_t2i")
        self._dir = workflows_dir
        self._negative = negative
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
```

- [ ] **Step 4: 跑测试确认通过** — `cd backend && pytest tests/test_comfyui_image.py -v`（3 passed）

- [ ] **Step 5: 提交**
```bash
git add backend/app/providers/image/comfyui_image.py backend/tests/test_comfyui_image.py
git commit -m "feat(comfyui): ComfyUIImageProvider（z_image/qwen 出图）"
```
结尾加 Co-Authored-By 行。

---

## Task 3: 配置 + 工厂 + 接线（runner + api regen）

**Files:** Modify `backend/app/config.py`、新增/改 `backend/app/providers/image/__init__.py`、`backend/app/pipeline/runner.py`、`backend/app/api/pipeline.py`；Test `backend/tests/test_build_image_provider.py`

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_build_image_provider.py`：

```python
from app import config
from app.providers.image import build_image_provider
from app.providers.image.comfyui_image import ComfyUIImageProvider
from app.providers.image.openai_image import OpenAIImageProvider


def test_factory_picks_comfyui(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(
        image={"provider": "comfyui", "base_url": "http://127.0.0.1:8188", "model": "qwen", "api_key": ""}))
    p = build_image_provider(config.get_settings())
    assert isinstance(p, ComfyUIImageProvider)


def test_factory_picks_commercial_by_default(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(
        image={"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-image-1", "api_key": "k"}))
    p = build_image_provider(config.get_settings())
    assert isinstance(p, OpenAIImageProvider)


def test_comfyui_cfg_defaults():
    s = config.Settings()
    assert s.comfyui.workflows_dir == "comfyui/workflows/api"
    assert s.comfyui.default_negative
```

- [ ] **Step 2: 跑测试确认失败** — `cd backend && pytest tests/test_build_image_provider.py -v`（无 `build_image_provider` / `Settings.comfyui`）

- [ ] **Step 3: 实现**

`backend/app/config.py`：在 `class Settings` 之前加：
```python
class ComfyuiCfg(BaseModel):
    workflows_dir: str = "comfyui/workflows/api"
    default_negative: str = "模糊, 丑陋, 变形, 低质量, 水印"
```
在 `class Settings` 内（`ltx: LTXCfg = LTXCfg()` 之后、`prompts` 之前或之后均可）加：
```python
    comfyui: ComfyuiCfg = ComfyuiCfg()
```

`backend/app/providers/image/__init__.py`（若不存在则新建；若已存在则追加函数）：
```python
def build_image_provider(cfg):
    """按 cfg.image.provider 选商用或 ComfyUI 图片 provider。runner Stage3 与 api regen 共用。"""
    from app.providers.image.openai_image import OpenAIImageProvider
    if cfg.image.provider == "comfyui":
        from app.providers.image.comfyui_image import ComfyUIImageProvider
        return ComfyUIImageProvider(
            server_url=cfg.image.base_url or "http://127.0.0.1:8188",
            workflow=cfg.image.model or "z_image",
            workflows_dir=cfg.comfyui.workflows_dir,
            negative=cfg.comfyui.default_negative,
        )
    return OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)
```

`backend/app/pipeline/runner.py`（约 478）：把
```python
image_provider = OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)
```
改为：
```python
from app.providers.image import build_image_provider
image_provider = build_image_provider(cfg)
```
（顶部若已 `from app.providers.image.openai_image import OpenAIImageProvider` 且不再直接用，可保留不动以免动到其它引用；只要 Stage3 这行改成工厂即可。）

`backend/app/api/pipeline.py`（约 420-421）：把
```python
from app.providers.image.openai_image import OpenAIImageProvider
img_provider = OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)
```
改为：
```python
from app.providers.image import build_image_provider
img_provider = build_image_provider(cfg)
```

- [ ] **Step 4: 跑测试确认通过 + import 健全** — `cd backend && python -c "import app.pipeline.runner, app.api.pipeline" && pytest tests/test_build_image_provider.py -v`（3 passed）

- [ ] **Step 5: 提交**
```bash
git add backend/app/config.py backend/app/providers/image/__init__.py backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_build_image_provider.py
git commit -m "feat(comfyui): ComfyuiCfg + build_image_provider 工厂 + Stage3/regen 接线"
```
结尾加 Co-Authored-By 行。

---

## Task 4: 前端图片源加「ComfyUI 本地」

**Files:** Modify `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: 改 IMAGE_PRESETS**（约 32-35 行）：
```ts
const IMAGE_PRESETS: Record<string, ProviderPreset> = {
  openai: { label: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-image-1", "dall-e-3"] },
  dashscope: { label: "阿里云 (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["wanx-v1", "wanx2.1-t2i-turbo"] },
  comfyui: { label: "ComfyUI 本地", baseUrl: "http://127.0.0.1:8188", models: ["z_image", "qwen"], needsKey: false },
};
```

- [ ] **Step 2: 构建校验** — `cd frontend && pnpm build`（无 TS 错误，成功）

- [ ] **Step 3: 提交**
```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(comfyui): 图片模型设置加「ComfyUI 本地」预设(z_image/qwen)"
```
结尾加 Co-Authored-By 行。

---

## 收尾验证

- [ ] **全量后端测试**：`cd backend && pytest -q`（除既有 2 个预存失败外全绿）
- [ ] **前端构建**：`cd frontend && pnpm build`
- [ ] **真实出图冒烟（对运行中的 ComfyUI 127.0.0.1:8188）**：临时把 `config.yaml` 的 image.provider 设 comfyui，或直接用一段脚本调 `ComfyUIImageProvider(...).generate(...)` 生成 z_image、qwen 各一张到临时目录，确认成功落盘为有效 PNG。（实现完成后由控制者手动跑，不写进自动化测试。）
