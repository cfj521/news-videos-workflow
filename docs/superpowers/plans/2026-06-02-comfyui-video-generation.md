# ComfyUI 接入 阶段2：视频生成(i2v) + 删 LTX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端视频(Stage5)从 Python 库版 LTX 全面换成 ComfyUI i2v（4 种模式，默认 wan5b），并彻底删除 Python 库版 LTX。

**Architecture:** 复用阶段1 `ComfyUIClient`(加 upload_image)；新写 `ComfyUIVideoProvider`(VideoClipProvider，逐分镜 i2v + ffmpeg 归一 mp4) + `ComfyUIVideoComposer`(全新，逐分镜 clip → 加音轨 → 拼接)；新增 `comfyui` 视频路线替代 `ltx` 并设默认；删 ltx_video/ltx_composer/LTXCfg/前端 ltx。

**Tech Stack:** Python(FastAPI/httpx/ffmpeg/pytest)，React+TS。

参考 spec：`docs/superpowers/specs/2026-06-02-comfyui-video-generation-design.md`

---

## File Structure
- `backend/app/providers/comfyui/client.py`（改）— `+upload_image`
- `backend/app/providers/video/comfyui_video.py`（新）— `ComfyUIVideoProvider`
- `backend/app/providers/composer/comfyui_composer.py`（新）— `ComfyUIVideoComposer`
- `backend/app/config.py`（改）— `ComfyuiCfg` 扩；`VideoRoute.LTX→COMFYUI`；删 `LTXCfg`/`Settings.ltx`；默认路线 comfyui
- `backend/app/schemas/pipeline.py`、`backend/app/pipeline/engine.py`（改）— `video_route` 默认 comfyui
- `backend/app/pipeline/runner.py`（改）— Stage5 ltx→comfyui 分支；S4 文案
- `backend/app/api/pipeline.py`（改）— render 端点 ltx→comfyui
- 删 `backend/app/providers/video/ltx_video.py`、`backend/app/providers/composer/ltx_composer.py`
- 前端 `types/index.ts`、`api/client.ts`、`pages/Settings.tsx`、`components/CreateRunDialog.tsx`、`pages/Dashboard.tsx`
- 测试：`test_comfyui_video.py`、`test_comfyui_composer.py`（新）；改 `test_config.py`/`test_schemas.py` 默认断言；client upload 用例并入 `test_comfyui_client.py`

---

## Task 1: `ComfyUIClient.upload_image`

**Files:** Modify `backend/app/providers/comfyui/client.py`；Test 追加到 `backend/tests/test_comfyui_client.py`

- [ ] **Step 1: 追加失败测试**：
```python
@pytest.mark.asyncio
async def test_upload_image_returns_name(tmp_path):
    p = tmp_path / "x.png"; p.write_bytes(b"PNG")
    with patch("app.providers.comfyui.client.httpx.AsyncClient") as mc:
        c = _mock_client(mc)
        c.post = AsyncMock(return_value=_resp({"name": "x.png", "subfolder": "", "type": "input"}))
        cli = ComfyUIClient("http://x:8188")
        assert await cli.upload_image(str(p)) == "x.png"
```

- [ ] **Step 2: 跑确认失败** — `cd backend && pytest tests/test_comfyui_client.py -k upload -v`

- [ ] **Step 3: 实现** — 在 `ComfyUIClient` 加方法：
```python
    async def upload_image(self, image_path: str) -> str:
        import os
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                with open(image_path, "rb") as fh:
                    files = {"image": (os.path.basename(image_path), fh, "image/png")}
                    r = await c.post(f"{self._url}/upload/image", files=files, data={"overwrite": "true"})
                    r.raise_for_status()
                    j = r.json()
        except ProviderError:
            raise
        except Exception as e:
            raise self._err(e) from e
        name = j.get("name")
        if not name:
            raise self._err(RuntimeError(f"upload no name: {j}"))
        sub = j.get("subfolder") or ""
        return f"{sub}/{name}" if sub else name
```

- [ ] **Step 4: 跑确认通过** — `cd backend && pytest tests/test_comfyui_client.py -v`（全绿）

- [ ] **Step 5: 提交**
```bash
git add backend/app/providers/comfyui/client.py backend/tests/test_comfyui_client.py
git commit -m "feat(comfyui): client.upload_image（喂分镜图给 i2v LoadImage）"
```
trailer：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。分支 `feat/aihot-default-exclusion`，勿 push。

---

## Task 2: `ComfyUIVideoProvider`

**Files:** Create `backend/app/providers/video/comfyui_video.py`；Test `backend/tests/test_comfyui_video.py`

- [ ] **Step 1: 写失败测试**：
```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.providers.base import ProviderError
from app.providers.video.comfyui_video import ComfyUIVideoProvider, _snap_4n1


def test_snap_4n1():
    assert _snap_4n1(1) == 5
    assert _snap_4n1(120) == 121
    assert _snap_4n1(10**9) == 257  # 上限


@pytest.mark.asyncio
async def test_generate_uploads_fills_transcodes(tmp_path, monkeypatch):
    out = str(tmp_path / "clip.mp4")
    prov = ComfyUIVideoProvider(server_url="http://x:8188", workflow="wan5b", fps=24, negative="neg")
    captured = {}

    async def up(image_path): return "scene.png"
    async def run(graph): captured["graph"] = graph; return [{"kind": "images", "filename": "v.webp", "subfolder": "", "type": "output"}]
    async def fetch(fn, subfolder="", folder_type="output"): return b"WEBP"

    monkeypatch.setattr(prov._client, "upload_image", up)
    monkeypatch.setattr(prov._client, "run", run)
    monkeypatch.setattr(prov._client, "fetch", fetch)
    # mock ffmpeg：写出 output 文件并返回 0
    def fake_run(cmd, **kw):
        # 找到输出路径（cmd 最后一项）写假数据
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
```

- [ ] **Step 2: 跑确认失败** — `cd backend && pytest tests/test_comfyui_video.py -v`

- [ ] **Step 3: 实现** — `backend/app/providers/video/comfyui_video.py`：
```python
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


def _snap_4n1(n: int) -> int:
    return max(5, min(4 * round((n - 1) / 4) + 1, 257))


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
        frames = _snap_4n1(round(duration * self._fps))
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
            ext = Path(pick["filename"]).suffix or ".webp"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                tf.write(data)
                tmp = tf.name
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cmd = ["ffmpeg", "-y", "-i", tmp,
                   "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                   "-r", str(self._fps), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "fast", output_path]
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            Path(tmp).unlink(missing_ok=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg 转码失败: {r.stderr.decode('utf-8', 'replace')[:300]}")
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(service="视频生成", provider="comfyui", model=self._wf, base_url=self._server, cause=e) from e
        log.info("ComfyUI clip done %dx%d %d帧 → %s", w, h, frames, output_path)
        return AssetResult(file_path=output_path, duration_ms=int(frames / self._fps * 1000))
```

- [ ] **Step 4: 跑确认通过** — `cd backend && pytest tests/test_comfyui_video.py -v`（4 passed）

- [ ] **Step 5: 提交**
```bash
git add backend/app/providers/video/comfyui_video.py backend/tests/test_comfyui_video.py
git commit -m "feat(comfyui): ComfyUIVideoProvider（i2v 4 模式 + ffmpeg 归一 mp4）"
```
trailer 同上。

---

## Task 3: `ComfyUIVideoComposer`（全新，不复用 LTX）

**Files:** Create `backend/app/providers/composer/comfyui_composer.py`；Test `backend/tests/test_comfyui_composer.py`

- [ ] **Step 1: 写失败测试**：
```python
from unittest.mock import AsyncMock
import pytest
from app.providers.composer.comfyui_composer import ComfyUIVideoComposer


@pytest.mark.asyncio
async def test_compose_calls_provider_per_scene_and_concats(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    timeline = {"total_duration_ms": 4000, "entries": [
        {"scene_id": 1, "image_path": str(tmp_path / "a.png"), "audio_path": "", "start_ms": 0, "end_ms": 2000, "subtitle_text": "一"},
        {"scene_id": 2, "image_path": str(tmp_path / "b.png"), "audio_path": "", "start_ms": 2000, "end_ms": 4000, "subtitle_text": "二"},
    ]}
    calls = []

    class VP:
        async def generate(self, image_path, prompt, duration, resolution="704x480", output_path=""):
            calls.append((prompt, duration)); open(output_path, "wb").write(b"MP4")
            from app.providers.base import AssetResult
            return AssetResult(file_path=output_path)

    # mock 所有 ffmpeg（mux/concat/static）
    def fake_run(cmd, **kw):
        open(cmd[-1], "wb").write(b"OUT")
        class R: returncode = 0; stderr = b""
        return R()
    monkeypatch.setattr("app.providers.composer.comfyui_composer.subprocess.run", fake_run)

    comp = ComfyUIVideoComposer(VP(), fps=24)
    res = await comp.compose(timeline, str(tmp_path / "assets"), str(tmp_path / "out.mp4"), "704x480")
    assert len(calls) == 2 and calls[0][1] == 2.0   # 每分镜调一次、时长对
    assert res.file_path == str(tmp_path / "out.mp4")
```

- [ ] **Step 2: 跑确认失败** — `cd backend && pytest tests/test_comfyui_composer.py -v`

- [ ] **Step 3: 实现** — `backend/app/providers/composer/comfyui_composer.py`：
```python
import subprocess
from pathlib import Path

from app.logging import get_logger
from app.providers.base import ComposerProvider, VideoResult

log = get_logger("composer.comfyui")


class ComfyUIVideoComposer(ComposerProvider):
    """逐分镜调 ComfyUI 视频 provider 出 clip，加上各分镜 TTS 音轨，拼接成最终 mp4。全新实现。"""

    def __init__(self, video_provider, fps: int = 24):
        self._video = video_provider
        self._fps = fps

    async def compose(self, timeline_json: dict, assets_dir: str, output_path: str, resolution: str = "704x480") -> VideoResult:
        run_dir = Path(assets_dir).parent
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        parts = resolution.split("x")
        w, h = int(parts[0]), int(parts[1]) if len(parts) > 1 else int(parts[0])
        entries = timeline_json.get("entries", [])
        segs: list[str] = []

        for i, entry in enumerate(entries):
            sid = entry["scene_id"]
            image_path = entry.get("image_path", "")
            audio_path = entry.get("audio_path", "")
            dur = max(0.5, (entry["end_ms"] - entry["start_ms"]) / 1000)
            prompt = entry.get("subtitle_text") or f"Scene {sid}"
            raw = str(clips_dir / f"clip_{sid:02d}.mp4")
            log.info("[CFY] Scene %d/%d: %.1fs", i + 1, len(entries), dur)
            try:
                await self._video.generate(image_path=image_path, prompt=prompt, duration=dur,
                                            resolution=resolution, output_path=raw)
            except Exception:
                log.exception("[CFY] Scene %d clip 失败，静态兜底", sid)
                _static_clip(image_path, dur, w, h, self._fps, raw)
            seg = str(clips_dir / f"seg_{sid:02d}.mp4")
            _mux_segment(raw, audio_path, dur, w, h, self._fps, seg)
            segs.append(seg)

        _concat(segs, clips_dir, output_path, w, h, self._fps)
        total_ms = timeline_json.get("total_duration_ms", 0)
        return VideoResult(file_path=output_path, duration_ms=total_ms, resolution=resolution)


def _ff(cmd: list[str], timeout: int = 600) -> None:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 失败: " + r.stderr.decode("utf-8", "replace")[:300])


def _static_clip(image_path: str, dur: float, w: int, h: int, fps: int, out: str) -> None:
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    _ff(["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-t", str(dur), "-vf", vf,
         "-r", str(fps), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "fast", out])


def _mux_segment(clip: str, audio: str, dur: float, w: int, h: int, fps: int, out: str) -> None:
    """把 clip 视频归一(w/h/fps)并配音轨（有 TTS 用之、无则静音），裁/补到 dur。"""
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    has_audio = bool(audio) and Path(audio).exists()
    if has_audio:
        cmd = ["ffmpeg", "-y", "-i", clip, "-i", audio,
               "-filter_complex", f"[0:v]{vf}[v];[1:a]apad[a]",
               "-map", "[v]", "-map", "[a]", "-t", str(dur),
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ar", "48000", out]
    else:
        cmd = ["ffmpeg", "-y", "-i", clip, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-vf", vf, "-t", str(dur), "-shortest",
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", out]
    _ff(cmd)


def _concat(segs: list[str], clips_dir: Path, output_path: str, w: int, h: int, fps: int) -> None:
    if not segs:
        raise RuntimeError("无分镜片段可拼接")
    listfile = clips_dir / "concat.txt"
    listfile.write_text("".join(f"file '{Path(s).as_posix()}'\n" for s in segs), encoding="utf-8")
    # seg 已统一编码，concat demuxer + 重编码确保稳妥
    _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-movflags", "+faststart", output_path])
```

- [ ] **Step 4: 跑确认通过** — `cd backend && pytest tests/test_comfyui_composer.py -v`（1 passed）

- [ ] **Step 5: 提交**
```bash
git add backend/app/providers/composer/comfyui_composer.py backend/tests/test_comfyui_composer.py
git commit -m "feat(comfyui): ComfyUIVideoComposer（逐分镜 clip+音轨拼接，全新）"
```

---

## Task 4: 配置 + 默认路线改 comfyui + 测试断言

**Files:** Modify `config.py`、`schemas/pipeline.py`、`pipeline/engine.py`；改 `tests/test_config.py`、`tests/test_schemas.py`

- [ ] **Step 1: 改两个默认断言测试**（先让它们反映目标，TDD 红→绿）：
  - `backend/tests/test_config.py`：把断言 `default_video_route == "hyperframes"` 改为 `== "comfyui"`。
  - `backend/tests/test_schemas.py`：把断言 `PipelineRunCreate(...)` 的 `video_route == "hyperframes"` 改为 `== "comfyui"`。
  （先改测试，跑 `pytest tests/test_config.py tests/test_schemas.py -v` 应 FAIL，因为实现还是 hyperframes。）

- [ ] **Step 2: 跑确认失败** — `cd backend && pytest tests/test_config.py tests/test_schemas.py -v`

- [ ] **Step 3: 实现** — `backend/app/config.py`：
  - `class VideoRoute(str, Enum):` 把 `LTX = "ltx"` 改为 `COMFYUI = "comfyui"`。
  - 删整个 `class LTXCfg(BaseModel): ...`（约 70-81）。
  - `class Settings` 删 `ltx: LTXCfg = LTXCfg()` 行。
  - `class ComfyuiCfg` 扩字段（加到现有两字段后）：
    ```python
        server_url: str = "http://127.0.0.1:8188"
        video_workflow: str = "wan5b"
        video_fps: int = 24
    ```
  - `class PipelineCfg` 的 `default_video_route: str = "hyperframes"` → `"comfyui"`。

  `backend/app/schemas/pipeline.py`：`PipelineRunCreate.video_route: str = "hyperframes"` → `"comfyui"`。
  `backend/app/pipeline/engine.py`：`create_run(..., video_route: str = "hyperframes", ...)` → `"comfyui"`。

- [ ] **Step 4: 跑确认通过** — `cd backend && pytest tests/test_config.py tests/test_schemas.py -v` + `python -c "import app.config"`

- [ ] **Step 5: 提交**
```bash
git add backend/app/config.py backend/app/schemas/pipeline.py backend/app/pipeline/engine.py backend/tests/test_config.py backend/tests/test_schemas.py
git commit -m "feat(comfyui): ComfyuiCfg 扩视频字段 + VideoRoute comfyui + 默认路线改 comfyui，删 LTXCfg"
```

---

## Task 5: Stage5/render 接 comfyui + 删 LTX 文件

**Files:** Modify `backend/app/pipeline/runner.py`、`backend/app/api/pipeline.py`；删 `providers/video/ltx_video.py`、`providers/composer/ltx_composer.py`

- [ ] **Step 1: 改 runner Stage5**（约 609-632）— 把 `if run.video_route == "ltx":` 整个分支替换为：
```python
            if run.video_route == "comfyui":
                _update(db, run, current_stage=5, progress_detail="S5 ComfyUI 视频生成中...")
                log.info("[S5] ComfyUI rendering — output=%s", output_mp4)
                try:
                    from app.providers.video.comfyui_video import ComfyUIVideoProvider
                    from app.providers.composer.comfyui_composer import ComfyUIVideoComposer
                    vp = ComfyUIVideoProvider(
                        server_url=cfg.comfyui.server_url, workflow=cfg.comfyui.video_workflow,
                        workflows_dir=cfg.comfyui.workflows_dir, fps=cfg.comfyui.video_fps,
                        negative=cfg.comfyui.default_negative,
                    )
                    result = await ComfyUIVideoComposer(vp, fps=cfg.comfyui.video_fps).compose(
                        timeline_json=timeline, assets_dir=str(assets_dir),
                        output_path=output_mp4, resolution=resolution,
                    )
                    final_path = result.file_path
                    log.info("[S5] ComfyUI render ok — %s", final_path)
                except Exception as e:
                    log.warning("[S5] ComfyUI failed: %s — falling back to FFmpeg", e)
                    _update(db, run, progress_detail="S5 ComfyUI 失败，FFmpeg 合成中...")
                    final_path = _ffmpeg_compose(timeline, run_dir, resolution, cfg.video.fps)
```
  并把 Stage4 的 `log.info("[S4] LTX route — no HTML preview, clips will be generated in S5")`（约 562）改为 `log.info("[S4] 视频路线 — 预览/clip 在 S5 生成")`。

- [ ] **Step 2: 改 render 端点**（`api/pipeline.py` 约 694-714）— 把 `if run.video_route == "ltx":` 分支替换为 comfyui 版（同上 provider+composer 构造；该函数内 `resolution` 已有，`cfg` 已 get）。把 `reload_settings` 注释里的 "视频/LTX" 改 "视频"。

- [ ] **Step 3: 删 LTX 文件**
```bash
git rm backend/app/providers/video/ltx_video.py backend/app/providers/composer/ltx_composer.py
```

- [ ] **Step 4: 校验无残留 + 全量测试** —
```
cd backend && python -c "import app.pipeline.runner, app.api.pipeline, app.main" && \
grep -rnE "LTXVideoProvider|LTXComposer|ltx_composer|ltx_video|cfg\.ltx|LTXCfg|VideoRoute\.LTX|video_route == \"ltx\"" app/ && echo "STILL HAS LTX REFS" || echo "no ltx refs" ; \
pytest -q
```
Expected: 导入无错；grep 打印 "no ltx refs"（注意：**只查被删的 LTX 符号**，不要 grep 裸 "ltx"——`comfyui_video.py` 里合法保留了 `"ltx"` 这个 i2v 模式键 `{"ltx": "ltx23_i2v"}`，那是 ComfyUI 的 LTX 工作流模式，不是要删的 Python 库版 LTX）；pytest 除既有 2 个预存失败外全绿。（若命中残留，逐一清除再继续。）

- [ ] **Step 5: 提交**
```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py
git commit -m "feat(comfyui): Stage5/render 接 comfyui 视频路线 + 删 Python 库版 LTX"
```

---

## Task 6: 前端

**Files:** Modify `frontend/src/{types/index.ts, api/client.ts, pages/Settings.tsx, components/CreateRunDialog.tsx, pages/Dashboard.tsx}`

- [ ] **Step 1: types/index.ts** — `video_route: "hyperframes" | "ltx" | "audio"` → `"hyperframes" | "comfyui" | "audio"`；`VIDEO_ROUTE_LABELS` 的 `ltx: "LTX 2.3"` → `comfyui: "ComfyUI"`。

- [ ] **Step 2: api/client.ts** — `AppSettings` 删 `ltx: {...}` 整行；新增 `comfyui: { server_url: string; video_workflow: string; video_fps: number };`。

- [ ] **Step 3: Settings.tsx**
  - `EMPTY_SETTINGS`：删 `ltx: {...}`；加 `comfyui: { server_url: "http://127.0.0.1:8188", video_workflow: "wan5b", video_fps: 24 },`。
  - 「流水线默认值」Section 的「视频路线」选项 `{ value: "ltx", label: "LTX 2.3" }` → `{ value: "comfyui", label: "ComfyUI" }`。
  - `pipeline` 的 `EMPTY_SETTINGS.default_video_route` 仍是 "hyperframes" 字符串——改为 `"comfyui"`。
  - **「视频生成」tab**（当前是占位 div，约 473-479）替换为表单：
    ```tsx
      {activeTab === "video" && (
        <Section title="ComfyUI 视频生成" desc="本地 ComfyUI 出图生视频（i2v）。需 ComfyUI 运行中。">
          <Field label="ComfyUI 地址">
            <input value={settings.comfyui.server_url} onChange={(e) => patch("comfyui", { server_url: e.target.value })} className={monoInputCls} />
          </Field>
          <Field label="视频模式">
            <Select value={settings.comfyui.video_workflow} onChange={(v) => patch("comfyui", { video_workflow: v })} options={[
              { value: "wan5b", label: "Wan2.2 5B (默认/快)" }, { value: "wan14b", label: "Wan2.2 14B (质量)" },
              { value: "wan14b_lightx2v", label: "Wan2.2 14B Lightx2v (4步快)" }, { value: "ltx", label: "LTX 2.3" },
            ]} />
          </Field>
          <Field label="帧率">
            <Select value={String(settings.comfyui.video_fps)} onChange={(v) => patch("comfyui", { video_fps: Number(v) })} options={[
              { value: "16", label: "16" }, { value: "24", label: "24" }, { value: "25", label: "25" },
            ]} />
          </Field>
        </Section>
      )}
    ```
    （删掉原占位 div 的纯文案块。）

- [ ] **Step 4: CreateRunDialog.tsx** — `useState("hyperframes")` → `useState("comfyui")`；音视频路线 options 的 `{ value: "ltx", label: "LTX 2.3" }` → `{ value: "comfyui", label: "ComfyUI" }`。

- [ ] **Step 5: Dashboard.tsx** — 文案 `"LTX 视频预览"` → `"视频预览"`（约 789，纯展示文案）。

- [ ] **Step 6: 构建** — `cd frontend && pnpm build`（无 TS 错误；注意 `patch("comfyui",...)` 依赖 Step 2 的 `AppSettings.comfyui` 已声明）。

- [ ] **Step 7: 提交**
```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/pages/Settings.tsx frontend/src/components/CreateRunDialog.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(comfyui): 前端视频路线 ltx→comfyui + 视频生成 tab 表单"
```

---

## 收尾验证

- [ ] **全量后端测试**：`cd backend && pytest -q`（除既有 2 个预存失败外全绿；新增 video/composer/upload 用例通过）
- [ ] **前端构建**：`cd frontend && pnpm build`
- [ ] **webp 解码门槛（实施 Task 2 前/中先确认，评审 N4）**：临时用 ffmpeg 把一张 ComfyUI 出的动图 webp 转 mp4，确认能解；若不能 → 把 wan 三个 i2v 工作流的 `SaveAnimatedWEBP` 改 `CreateVideo`+`SaveVideo`（出 mp4）再继续。
- [ ] **真实冒烟（控制者手动，对运行中 ComfyUI 127.0.0.1:8188）**：① 用一张分镜图，`ComfyUIVideoProvider(workflow="wan5b")` 与 `workflow="ltx"` 各出一段 mp4 clip，确认有效；② 跑一条完整任务（video_route=comfyui，2-3 分镜）确认 `ComfyUIVideoComposer` 拼出最终 mp4。
