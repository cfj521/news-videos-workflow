# ComfyUI 接入 阶段2：视频生成(i2v) + 移除 Python 库版 LTX — 设计文档

## 背景与目标

把后端视频合成(Stage5)从 Python 库版 LTX（`LTXVideoProvider` + `LTXComposer`，`video_route=="ltx"`）**全面更换为 ComfyUI i2v 流程**，并**彻底删除 Python 库版 LTX 的全部内容**（不复用 `LTXComposer`）。复用阶段1沉淀的 `ComfyUIClient`。

这是「ComfyUI 全面接入」的第 2 阶段，并合并了原计划阶段3的 LTX 删除。完成后：图片(阶段1)与视频均走 ComfyUI，Python 库版 LTX 不再存在。

## 现状

- Stage5（`runner.py:609`）：`video_route=="ltx"` → `LTXVideoProvider`(Python库 `ltx_core`/`ltx_pipelines`) + `LTXComposer`（逐分镜 clip + ffmpeg 拼接 + 静态兜底）；否则 hyperframes；audio 单独。
- `api/pipeline.py:694` "重新渲染"端点有同样的 `ltx` 分支。
- ComfyUI i2v 工作流（`comfyui/workflows/api/{wan22_5b_i2v,wan22_14b_i2v,wan22_14b_i2v_lightx2v,ltx23_i2v}.api.json`）占位符统一：`__INPUT_IMAGE__ __POSITIVE_PROMPT__ __NEGATIVE_PROMPT__ __SEED__ __WIDTH__ __HEIGHT__ __LENGTH__`，均含 `LoadImage`；wan 用 `SaveAnimatedWEBP`(webp)，ltx 用 `SaveVideo`(mp4)。
- `VideoClipProvider.generate(image_path, prompt, duration, resolution, output_path)`（base.py）逐分镜接口。
- 阶段1已有 `ComfyUIClient`(submit/wait/fetch/run) + `load_api_workflow`/`fill_placeholders`。

## 关键决策

- **D1 不复用 LTX**：新写 `ComfyUIVideoComposer`（自带 ffmpeg 拼接逻辑），**不 import `LTXComposer`**。
- **D2 彻底删 Python 库版 LTX**：删 `ltx_video.py`、`ltx_composer.py`、`LTXCfg`+`Settings.ltx`、前端 `AppSettings.ltx`/`EMPTY_SETTINGS.ltx`、`VideoRoute.LTX`、所有 `video_route=="ltx"` 分支。
- **D3 新增 `comfyui` 视频路线**替代 `ltx`，并设为默认视频路线。
- **D4 4 种 i2v 模式全暴露，默认 wan5b**：`wan5b/wan14b/wan14b_lightx2v/ltx`（仅 i2v，流水线是 image→video）。
- **D5 clip 归一 mp4**：provider 取回 clip（webp/mp4）后用 ffmpeg 统一转 mp4（scale + fps），喂给 composer 拼接。

## 详细设计

### 1. `ComfyUIClient.upload_image` — 扩 `providers/comfyui/client.py`

```python
async def upload_image(self, image_path: str) -> str:
    # POST /upload/image (multipart: image=文件, overwrite=true) → 返回 ComfyUI 端文件名
    # 用于把分镜图喂给工作流的 LoadImage(__INPUT_IMAGE__)
```
返回 ComfyUI `/upload/image` 响应里的 `name`（含 subfolder 时按 `subfolder/name` 组合，本设计图存根目录，取 `name`）。错误包 `ProviderError`。

### 2. `ComfyUIVideoProvider` — 新建 `providers/video/comfyui_video.py`

```python
class ComfyUIVideoProvider(VideoClipProvider):
    _WORKFLOW_MAP = {"wan5b": "wan22_5b_i2v", "wan14b": "wan22_14b_i2v",
                     "wan14b_lightx2v": "wan22_14b_i2v_lightx2v", "ltx": "ltx23_i2v"}
    def __init__(self, server_url, workflow="wan5b", workflows_dir="comfyui/workflows/api",
                 fps=24, negative=""):
        ...
    async def generate(self, image_path, prompt, duration, resolution="704x480", output_path=""):
        # 1. server_name = client.upload_image(image_path)
        # 2. W,H = resolution 解析 + /16 取整（默认 704x480）
        # 3. frames = _snap_4n1(round(duration * fps))   # 4n+1，下限 5（约 9/13...）
        # 4. fill: INPUT_IMAGE=server_name, POSITIVE=prompt, NEGATIVE=self._negative,
        #          SEED=随机, WIDTH=W, HEIGHT=H, LENGTH=frames
        # 5. files = client.run(graph); 取首个 videos→gifs→images 输出 → fetch 到临时文件(带原扩展)
        # 6. ffmpeg 转 output_path(mp4): -i tmp -vf scale=W:H -r fps -pix_fmt yuv420p
        # 7. AssetResult(file_path=output_path, duration_ms=int(frames/fps*1000))
```
- `_snap_4n1(n)`：`max(5, 4*round((n-1)/4)+1)`。
- 失败（upload/run/无输出/ffmpeg 非 0）→ `ProviderError(service="视频生成", provider="comfyui", model=workflow, base_url=server, ...)`。
- ffmpeg 经 `subprocess.run`（项目已这么用，`shell=True` win 兼容，见现有 composer）。

### 3. `ComfyUIVideoComposer` — 新建 `providers/composer/comfyui_composer.py`（全新，不复用 LTX）

`class ComfyUIVideoComposer(ComposerProvider)`，`compose(timeline_json, assets_dir, output_path, resolution)`：
- 遍历 `timeline.entries`，对每个分镜调 `self._video.generate(image_path, prompt=subtitle_or_default, duration, resolution, output_path=clips/clip_NN.mp4)`；失败 → 静态兜底（ffmpeg loop 单图成 clip）。
- 全部 clip + 各自 audio → ffmpeg `concat` 滤镜合成带音轨的最终 mp4（自带实现，逻辑参考但**不 import** 旧 `ltx_composer` 的 `_ffmpeg_concat`/`_static_clip`，在本文件内重写）。
- 构造：`ComfyUIVideoComposer(video_provider)`。

### 4. 配置 — `config.py`

- `ComfyuiCfg` 扩字段：
  ```python
  server_url: str = "http://127.0.0.1:8188"   # 视频用（图片仍用 cfg.image.base_url）
  video_workflow: str = "wan5b"                 # wan5b|wan14b|wan14b_lightx2v|ltx
  video_fps: int = 24
  ```
- `VideoRoute` 枚举（约行 20-24）：`LTX = "ltx"` → `COMFYUI = "comfyui"`。
- **删** `LTXCfg`（70-81）、`Settings.ltx`（133）。
- `default_video_route` 默认：`"hyperframes"` → `"comfyui"`（schema `PipelineRunCreate.video_route` 默认、`PipelineCfg.default_video_route`、engine 默认 一并改）。

### 5. Stage5 接线 — `runner.py`

- 删 `video_route=="ltx"` 整个分支（609-632）。
- 新增：
  ```python
  if run.video_route == "comfyui":
      from app.providers.video.comfyui_video import ComfyUIVideoProvider
      from app.providers.composer.comfyui_composer import ComfyUIVideoComposer
      vp = ComfyUIVideoProvider(server_url=cfg.comfyui.server_url, workflow=cfg.comfyui.video_workflow,
                                workflows_dir=cfg.comfyui.workflows_dir, fps=cfg.comfyui.video_fps,
                                negative=cfg.comfyui.default_negative)
      result = await ComfyUIVideoComposer(vp).compose(timeline, str(assets_dir), output_mp4, resolution)
      final_path = result.file_path   # 失败兜底 _ffmpeg_compose（沿用现有）
  else:  # hyperframes
      ...
  ```
- Stage4 的 `log.info("[S4] LTX route ...")`（562）措辞改中性（"视频路线 — 预览在 S5 生成"）。

### 6. "重新渲染"端点 — `api/pipeline.py:694`

把 `ltx` 分支同样替换为 `comfyui` 分支（同上 provider+composer）。`reload_settings` 注释（663）"视频/LTX" 改"视频"。

### 7. 删除文件

- `backend/app/providers/video/ltx_video.py`
- `backend/app/providers/composer/ltx_composer.py`
（删后全仓 grep 确认无 `LTXVideoProvider`/`LTXComposer`/`ltx_composer`/`ltx_video`/`cfg.ltx`/`video_route == "ltx"` 残留——含测试。）

### 8. 前端

- `types/index.ts`：`video_route` 联合类型 `"ltx"`→`"comfyui"`；`VIDEO_ROUTE_LABELS` `ltx:"LTX 2.3"`→`comfyui:"ComfyUI"`。
- `client.ts`：删 `AppSettings.ltx`。
- `Settings.tsx`：删 `EMPTY_SETTINGS.ltx`；「视频路线」选项 `ltx`→`comfyui`；`default_video_route` 默认改 `comfyui`；**填充「视频生成」tab**：ComfyUI 地址(`comfyui.server_url`)、视频模式(wan5b/wan14b/wan14b_lightx2v/ltx 下拉)、fps —— 需在 `AppSettings`/`EMPTY_SETTINGS` 增 `comfyui` 组、`patch("comfyui",...)`。
- `CreateRunDialog.tsx`：`videoRoute` 默认 `"comfyui"`；路线选项 `ltx`→`comfyui`。
- `Dashboard.tsx`：`"LTX 视频预览"` 等文案改中性（"视频预览"）。

## 数据流

```
Stage5 video_route="comfyui"
 → ComfyUIVideoComposer.compose(timeline)
   逐分镜: ComfyUIVideoProvider.generate(scene_image, narration, dur, res)
     → client.upload_image → 选 i2v 工作流 → 填占位符(含 INPUT_IMAGE/LENGTH)
     → client.run(/prompt→/history→/view) → 取 clip → ffmpeg 归一 mp4
   → 所有 clip + audio ffmpeg concat → 最终 output.mp4
```

## 边界与错误处理

- wan 出动图 webp → ffmpeg 转 mp4（冒烟确认 ffmpeg 能解 webp；不行则把 wan 工作流保存节点改视频节点，列为备选）。
- 单分镜失败 → 静态兜底 clip（不中断整片）。
- 整体 ComfyUI 不可达 → composer 内每分镜抛 ProviderError → 走静态兜底；若全失败则最终视频为静态拼接（与现有 LTX 失败兜底语义一致）。
- 删 LTX 后遗留 DB 里 `video_route=="ltx"` 的旧任务：重跑会落入 else(hyperframes) 分支——可接受（开发期）。

## 测试计划

- `ComfyUIClient.upload_image`：mock httpx，POST /upload/image 取 name。
- `ComfyUIVideoProvider`：mock client(upload/run/fetch) + mock ffmpeg(subprocess)，验证 upload→选工作流→帧数 4n+1→占位符齐全→归一 mp4 调用→AssetResult；失败抛 ProviderError。
- `ComfyUIVideoComposer`：mock video_provider，验证逐分镜调用 + 失败兜底 + concat 调用（mock subprocess）。
- 路由：Stage5/render 在 `video_route=="comfyui"` 时建对 provider/composer。
- 删除后：`python -c "import app.pipeline.runner, app.api.pipeline, app.main"` 无错；grep 无 LTX 残留；全量 pytest 绿（含删掉/改写涉 ltx 的旧测试，如有）。
- **真实冒烟**（控制者手动）：用一张分镜图，wan5b + ltx 各出一段 mp4 clip；再跑一条完整任务（video_route=comfyui）确认拼接出最终 mp4。

## 影响文件

- 改 `backend/app/providers/comfyui/client.py`（upload_image）
- 新 `backend/app/providers/video/comfyui_video.py`
- 新 `backend/app/providers/composer/comfyui_composer.py`
- 改 `backend/app/config.py`（ComfyuiCfg 扩、VideoRoute、删 LTXCfg/Settings.ltx、默认路线）
- 改 `backend/app/pipeline/runner.py`（Stage5 comfyui 分支、删 ltx 分支、S4 文案）
- 改 `backend/app/api/pipeline.py`（render 端点 comfyui 分支）
- 改 `backend/app/schemas/pipeline.py`、`backend/app/pipeline/engine.py`（default_video_route）
- 删 `backend/app/providers/video/ltx_video.py`、`backend/app/providers/composer/ltx_composer.py`
- 改前端 `types/index.ts`、`api/client.ts`、`pages/Settings.tsx`、`components/CreateRunDialog.tsx`、`pages/Dashboard.tsx`
- 测试：新增 client/video/composer/路由 用例；清理涉 ltx 旧测试（若有）

## 不做（YAGNI）

- t2v（流水线只 image→video）。
- 视频两阶段超分 / 高级参数（先标准 i2v）。
- per-run 选视频模式（先全局 `comfyui.video_workflow`）。
