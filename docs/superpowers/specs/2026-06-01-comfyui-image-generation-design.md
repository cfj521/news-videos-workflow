# ComfyUI 接入 阶段1：图片生成可选「商用 / ComfyUI」— 设计文档

## 背景与目标

把后端图片生成（Stage3）从只支持商用模型（`OpenAIImageProvider`）扩展为**可选商用或 ComfyUI 本地生成**（z_image / Qwen-Image 两种模式）。这是「ComfyUI 全面接入」三阶段的**第 1 阶段**——先打通 ComfyUI 调用链（客户端 + 工作流加载/填充），并落地图片这条最自包含的路径。

阶段 2（视频，替换 Python 库版 LTX）、阶段 3（删 LTX + 前端打磨）后续单独做。

## 现状

- Stage3（`runner.py:478`）固定 `image_provider = OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)`，经 `TrackedImageProvider` 包装，调 `ImageProvider.generate(prompt, size, output_path)`。
- `ImageProvider` 抽象在 `backend/app/providers/base.py`：`async def generate(self, prompt, size="1080x1920", output_path="") -> AssetResult`。
- ComfyUI 工作流（API 格式）在仓库 `comfyui/workflows/api/`，图片用 `z_image_t2i.api.json`、`qwen_image_t2i.api.json`，占位符 `__POSITIVE_PROMPT__ __NEGATIVE_PROMPT__ __SEED__ __WIDTH__ __HEIGHT__`。`comfyui/validate.py` 已验证 /prompt→/history→/view 调用链可用。

## 关键决策

- **D1 复用 `cfg.image` ProviderCfg**：新增 `provider="comfyui"` 选项，`base_url`=ComfyUI 地址，`model`=生成模式（`z_image` / `qwen`）。不新建图片专属配置组，天然适配现有图片设置 UI。
- **D2 ComfyUI 客户端沉淀为正式模块**：把 `validate.py` 的调用逻辑抽成 `providers/comfyui/client.py`，供本阶段图片与阶段 2 视频共用。
- **D3 不静默回退**：ComfyUI 不可达/报错 → 抛 `ProviderError`，该图失败（与现有 OpenAIImageProvider 失败语义一致），不偷偷换成商用。
- **D4 全局配置，暂不 per-run**：用哪种图片源/模式由全局设置决定；per-run 选择留待以后。

## 详细设计

### 1. ComfyUI 客户端 — 新建 `backend/app/providers/comfyui/client.py`

```python
class ComfyUIClient:
    def __init__(self, server_url: str = "http://127.0.0.1:8188", timeout: float = 600):
        ...
    async def submit(self, prompt_graph: dict) -> str:          # POST /prompt → prompt_id
    async def wait(self, prompt_id: str) -> dict:               # 轮询 /history/{id}；返回 outputs；报错抛 ProviderError
    async def fetch(self, filename, subfolder="", type="output") -> bytes:  # GET /view
    async def run(self, prompt_graph: dict) -> list[dict]:      # submit→wait→收集 outputs 里的 images/gifs/videos 文件项
```

- 用 `httpx.AsyncClient`（项目已用 httpx）。
- `wait` 轮询间隔 ~1.5s，超时抛 `ProviderError(service="ComfyUI", ...)`；`/history` 里 status error 也抛。
- 错误统一包成 `ProviderError`（base.py 已有），带 server_url 上下文。

### 2. 工作流加载/填充 — 新建 `backend/app/providers/comfyui/workflow.py`

```python
def load_api_workflow(name: str, workflows_dir: str) -> dict     # 读 <dir>/<name>.api.json
def fill_placeholders(graph: dict, values: dict[str, str|int]) -> dict
    # 深拷贝；把字符串 "__KEY__" 替换为 values[KEY]（缺失则保留，由调用方保证齐全）
```

- `fill_placeholders` 复用 `validate.py` 的替换语义（`__KEY__` 整串匹配）。
- 残留未替换占位符 → 抛错（防发非法图）。

### 3. ComfyUI 图片 Provider — 新建 `backend/app/providers/image/comfyui_image.py`

```python
class ComfyUIImageProvider(ImageProvider):
    def __init__(self, server_url: str, workflow: str = "z_image",
                 workflows_dir: str = "comfyui/workflows/api", negative: str = ""):
        # workflow: "z_image" -> z_image_t2i ; "qwen" -> qwen_image_t2i
    async def generate(self, prompt, size="1080x1920", output_path="") -> AssetResult:
        # 1. 解析 size "WxH" → W,H，各按 /16 向下取整、下限 256
        # 2. load_api_workflow(<映射名>) + fill_placeholders(
        #      POSITIVE_PROMPT=prompt, NEGATIVE_PROMPT=self._negative,
        #      SEED=随机 int, WIDTH=W, HEIGHT=H)
        # 3. client.run(graph) → 取第一张 image 输出 → client.fetch → 写 output_path
        # 4. 返回 AssetResult(file_path=output_path)
```

- `workflow` → 文件名映射：`{"z_image": "z_image_t2i", "qwen": "qwen_image_t2i"}`；未知值默认 z_image。
- 随机 SEED：`random.randint(0, 2**31-1)`。
- 失败（client 抛、无图输出、写盘失败）→ `ProviderError(service="图片生成", provider="comfyui", ...)`。

### 4. 配置 — `backend/app/config.py`

新增 `ComfyuiCfg`（阶段 2 视频会扩字段）：

```python
class ComfyuiCfg(BaseModel):
    workflows_dir: str = "comfyui/workflows/api"   # 相对仓库根（后端工作目录的上一级）
    default_negative: str = "模糊, 丑陋, 变形, 低质量, 水印"
```

`Settings` 加 `comfyui: ComfyuiCfg = ComfyuiCfg()`。`cfg.image` 仍是 ProviderCfg（`provider` 现可取 `"comfyui"`）。

> `workflows_dir` 解析（确定）：若为绝对路径直接用；否则相对**仓库根**解析，仓库根 = `Path(__file__).resolve().parents[N]`。`workflow.py` 位于 `backend/app/providers/comfyui/workflow.py`，到仓库根上溯 5 级（comfyui→providers→app→backend→repo，即 `parents[4]`）。`load_api_workflow` 内：`root = Path(__file__).resolve().parents[4]; path = Path(workflows_dir); full = path if path.is_absolute() else root / path; (full / f"{name}.api.json")`。

### 5. Stage3 接线 — `backend/app/pipeline/runner.py`（约 478）

把：
```python
image_provider = OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)
```
改为按 provider 选择：
```python
if cfg.image.provider == "comfyui":
    from app.providers.image.comfyui_image import ComfyUIImageProvider
    image_provider = ComfyUIImageProvider(
        server_url=cfg.image.base_url or "http://127.0.0.1:8188",
        workflow=cfg.image.model or "z_image",
        workflows_dir=cfg.comfyui.workflows_dir,
        negative=cfg.comfyui.default_negative,
    )
else:
    image_provider = OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)
```
（`api/pipeline.py` 里若也有重建 image provider 的地方——如 regen 单图——同步用同一选择逻辑；实现时 grep `OpenAIImageProvider` 全部命中点统一。）

### 6. 前端 — `frontend/src/pages/Settings.tsx`

`IMAGE_PRESETS` 增加一项：
```ts
comfyui: { label: "ComfyUI 本地", baseUrl: "http://127.0.0.1:8188", models: ["z_image", "qwen"] },
```
现有 `ProviderSection`（图片模型）直接渲染：服务商选「ComfyUI 本地」→ base_url 填地址、模型下拉 z_image/qwen。api_key 字段对 comfyui 无意义（留空即可，不强制改 UI）。`client.ts` 的 `AppSettings.image` 类型不变（仍是 ProviderCfg 形状）。

## 数据流

```
Stage3 → cfg.image.provider=="comfyui"
  → ComfyUIImageProvider.generate(prompt,size,out)
  → 选 z_image/qwen 工作流 → 填占位符 → ComfyUIClient.run(/prompt→/history→/view)
  → 写 output_path → AssetResult
```

## 边界与错误处理

- ComfyUI 不可达 / 执行 error / 无图输出 → `ProviderError`，Stage3 该图失败（沿用现有失败链）。
- 残留未替换占位符 → 抛错。
- `size` 非法（无 "x"）→ 回退默认 1024×1024。
- 模型文件缺失（ComfyUI 端报 node/model 错）→ /history error → ProviderError，文案含 server 信息。

## 测试计划

- `ComfyUIClient`：mock httpx，验证 submit 取 prompt_id、wait 轮询到 success 收集 outputs、wait 遇 error 抛 ProviderError、fetch 拼对 /view URL。
- `workflow.py`：load 读对文件；fill_placeholders 替换 + 残留占位符抛错。
- `ComfyUIImageProvider`：mock ComfyUIClient，验证 size→W/H 取整、占位符值正确、取第一张图 fetch 并写盘、失败抛 ProviderError。
- Stage3 选择：`cfg.image.provider=="comfyui"` 时建 `ComfyUIImageProvider`，否则 `OpenAIImageProvider`（可对 runner 的 provider 构建段做小单测或 import 健全 + 既有回归）。
- **真实冒烟（用户在跑的 ComfyUI 127.0.0.1:8188）**：z_image、qwen 各生成一张到临时目录，确认成功落盘（实现完成后我手动跑，不写进自动化测试）。

## 影响文件

- 新增 `backend/app/providers/comfyui/__init__.py`、`client.py`、`workflow.py`
- 新增 `backend/app/providers/image/comfyui_image.py`
- `backend/app/config.py`（`ComfyuiCfg` + `Settings.comfyui`）
- `backend/app/pipeline/runner.py`（Stage3 provider 选择）
- `backend/app/api/pipeline.py`（若有重建 image provider 处，同步选择逻辑）
- `frontend/src/pages/Settings.tsx`（`IMAGE_PRESETS` 加 comfyui）
- 测试：`backend/tests/` 新增 client / workflow / comfyui_image / stage3-选择 用例

## 不做（阶段 1 YAGNI）

- 视频生成、删 Python 库版 LTX（阶段 2/3）。
- per-run 选图片源/模式（先全局配置）。
- 把 `validate.py` 重构成复用 client（可后续；本阶段 client 为新模块，validate.py 保持原样）。
