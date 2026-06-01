# ComfyUI 工作流落盘（z_image / Qwen-Image / Wan2.2 / LTX2.3）— 设计文档

## 背景与目标

项目已在 `D:\models\comfyui` 下载好一套 24GB 显存可跑的模型，并配好 `extra_model_paths.yaml`（详见 `scripts/download-comfyui-models.ps1`）。现在要为这几个模型**编写 ComfyUI 工作流并落盘**，供后端 `/prompt` 自动调用 + 人工在编辑器里调试。

目标：为 z_image_turbo、Qwen-Image（文生图）和 Wan 2.2 5B/14B、LTX 2.3（文生/图生视频）产出可用的 ComfyUI 工作流文件，重指向我们实际下载的模型文件名，并附调用说明。

## 调查结论（已用官方源核实）

ComfyUI 的 `/prompt` 接口**无状态**：客户端每次把**完整工作流图（API/prompt 格式）**放进请求体 POST，ComfyUI 当场执行，**无需事先在编辑器保存/注册**任何工作流。

依据：
- 官方 `script_examples/basic_api_example.py` 直接 `POST {"prompt": {...}}` 到 `/prompt`，并在提交前动态改 `prompt["3"]["inputs"]["seed"]` 等。
- 官方 docs：「client submits the whole workflow when you queue a request」「server does not receive any changes you make after you send a request to the queue」。

两种 JSON 格式：
- **API 格式**（后端用）：`{"prompt": {节点id: {"class_type":..., "inputs": {... 引用写成 ["节点id", 输出序号] ...}}}}`，可程序化填参。`/prompt` 直接吃。
- **UI 格式**（编辑器用）：带节点坐标/连线的图。`/prompt` **不直接吃**；需在编辑器「Save (API Format)」转成 API 格式。

**结论**：后端只需项目里一份 API 格式即可跑；但 API 格式难以人工读改，故两份都留（见下）。

## 关键设计决策

- **D1 — UI 格式为权威源，API 格式手写并标注待验证**：以官方 UI 格式工作流为权威源（重指向我们的模型文件名）；同时手写一份 API 格式供后端，但因无法本地跑 ComfyUI 验证，API 件头部明确标注「首次使用前需在编辑器 Save (API Format) 重导以验证」。不发出可能跑不通的假件。
- **D2 — 全集 t2v + i2v**：覆盖文生图 ×2、文生视频 + 图生视频各路线。
- **D3 — 只产工作流文件 + 文档，不写后端接入代码**：本次不实现 ComfyUI provider/接入；不碰现有 LTX Python-lib 路径（`backend/app/providers/video/ltx_video.py` 保留）。

## 交付物：8 个工作流

| # | 名称（文件名 stem） | 路线 | 权威源 | 关键节点 / 模型文件（我们的命名） |
|---|---|---|---|---|
| 1 | `z_image_t2i` | 文生图 | comfyanonymous `z_image` example | UNETLoader(`z_image_turbo_bf16.safetensors`) + CLIPLoader(`qwen_3_4b.safetensors`) + VAELoader(`ae.safetensors`) + KSampler(turbo ~8 步) |
| 2 | `qwen_image_t2i` | 文生图 | `qwen_image` example | UNETLoader(`qwen_image_fp8_e4m3fn.safetensors`) + CLIPLoader(`qwen_2.5_vl_7b_fp8_scaled.safetensors`, type=qwen_image) + VAELoader(`qwen_image_vae.safetensors`) + ModelSamplingAuraFlow |
| 3 | `wan22_5b_t2v` | 文生视频 | `wan22` example (5B) | UNETLoader(`wan2.2_ti2v_5B_fp16.safetensors`) + CLIPLoader(`umt5_xxl_fp8_e4m3fn_scaled.safetensors`, type=wan) + VAELoader(`wan2.2_vae.safetensors`) + ModelSamplingSD3 + KSampler |
| 4 | `wan22_5b_i2v` | 图生视频 | `wan22` example (5B) | 同 #3 + 图像条件（LoadImage + Wan 图生视频条件节点） |
| 5 | `wan22_14b_t2v` | 文生视频 | `wan22` example (14B) | 双 UNETLoader(`wan2.2_t2v_high/low_noise_14B_fp8_scaled`) + 双 LoraLoaderModelOnly(`wan2.2_t2v_lightx2v_4steps_..._high/low_noise`) + KSamplerAdvanced×2(高噪→低噪) + VAELoader(`wan_2.1_vae.safetensors`) |
| 6 | `wan22_14b_i2v` | 图生视频 | `wan22` example (14B) | 同 #5 但用 `wan2.2_i2v_high/low_noise_14B_fp8_scaled` + `wan2.2_i2v_lightx2v_4steps_..._high/low_noise` + WanImageToVideo 图像条件 |
| 7 | `ltx23_t2v` | 文生视频 | docs.comfy.org LTX-2.3 + Lightricks 官方 | **ComfyUI-LTXVideo 自定义节点**：LTXAVTextEncoderLoader(gemma) + `ltx-2.3-22b-dev-fp8.safetensors` + 蒸馏 LoRA(`ltx-2.3-22b-distilled-lora-384-1.1.safetensors`) + 多模态 Guider + 空间/时间上采样两阶段 |
| 8 | `ltx23_i2v` | 图生视频 | 同 #7 | 同 #7 + 图像条件节点 |

> Wan 5B 是统一 TI2V 模型，t2v/i2v 为同模型两种输入变体；14B 分 t2v、i2v 两套独立 high/low 噪声模型 + 各自 lightx2v 4 步 LoRA。

## 目录布局

```
comfyui/                              # 新建于仓库根
  workflows/
    ui/   <stem>.json                 # UI 格式（权威；可拖进编辑器；已重指向我们的模型文件名）
    api/  <stem>.api.json             # API 格式（后端 /prompt 用；含占位符 + 头注「待验证」）
  README.md                           # 调用说明
```
另把 `ui/*.json` 各拷一份到 `D:\ComfyUI\ComfyUI\user\default\workflows\`（人工可直接在编辑器看到）。

## API 格式的参数占位

后端需填字段用占位符标出（README 列清单）：

- `__POSITIVE_PROMPT__`、`__NEGATIVE_PROMPT__`
- `__SEED__`（整数）
- `__WIDTH__`、`__HEIGHT__`
- `__LENGTH__`（视频帧数；图像工作流无此项）
- `__INPUT_IMAGE__`（i2v 的 LoadImage 文件名）

其余（模型文件名、步数、cfg、sampler、scheduler、shift、fps）按官方示例 + 24GB 配置**写死**。占位符用 `__NAME__` 双下划线包裹，便于后端字符串替换且不与 JSON 语法冲突。

## README 调用说明（内容清单）

1. 每个工作流：用途、所用模型文件清单、占位符填充表。
2. `/prompt` POST 示例：`curl`/Python 形式发 `{"prompt": {...}, "client_id": "..."}`，并说明结果经 `/history/{prompt_id}` 或 ws 取回。
3. **依赖**：LTX 两个图（#7/#8）需先在 ComfyUI Manager 安装 `ComfyUI-LTXVideo`；#1–#6 用核心节点。
4. **Gemma 格式校验**：我们下载的是 `gemma-3-12b-it-qat-q4_0-unquantized` **目录**，而 LTXVideo 节点可能期望单文件 encoder（社区常见 `gemma_3_12B_it_fp4_mixed.safetensors`）。README 标注：LTX 工作流的 Gemma 加载需在编辑器内确认/调整，必要时换 encoder 文件——此为已知待办，不阻塞其余 6 个工作流。
5. **首次验证流程**：UI 格式拖进编辑器 → 跑通 → Save (API Format) → 覆盖 `api/` 对应件，确保 API 件可执行。

## 数据流（后端将来如何用，本次不实现）

```
后端 Stage3/Stage4 → 读取 api/<stem>.api.json → 替换 __占位符__ → POST /prompt → 轮询 /history → 取回图片/视频
```

## 边界与风险

- **API 格式未经运行验证**（D1）：复杂图（Wan14B 双采样、LTX 两阶段）手写易错；靠 README 的「编辑器重导」流程兜底。
- **LTX 自定义节点依赖 + Gemma 文件格式**：见 README §3/§4；若 Gemma 目录不被节点接受，LTX 两图需人工换 encoder。
- **模型文件名漂移**：以 `scripts/download-comfyui-models.ps1` 落盘的实际文件名为准；实现时逐一比对。
- **官方示例版本**：z_image/qwen 工作流嵌在示例 PNG 元数据中，实现时需从 PNG 提取或按文档节点模式重建；wan22/LTX 有独立 JSON 可抓。

## 实现时逐工作流的步骤（计划阶段细化）

1. 抓取/提取该工作流官方权威源 → 得到节点图。
2. 重指向模型文件名为我们的实际命名。
3. 落 `ui/<stem>.json`（UI 格式）。
4. 由 UI 图手工派生 `api/<stem>.api.json`（API 格式），插入 `__占位符__`，加头注「待验证」。
5. 拷 UI 件到 ComfyUI workflows 目录。
6. 汇总进 README。

## 测试/验收

- 文件存在性与 JSON 合法性：所有 `ui/*.json` 与 `api/*.api.json` 能被 `json.load` 解析。
- API 件占位符齐全：每个 `api` 件含其路线应有的占位符（i2v 含 `__INPUT_IMAGE__`，视频含 `__LENGTH__`）。
- 模型文件名一致性：API/UI 件引用的模型文件名都在 `scripts/download-comfyui-models.ps1` 的下载清单内（防笔误）。
- README 覆盖全部 8 个工作流 + 依赖 + Gemma 待办 + 验证流程。
- 人工验收（用户侧，不代跑）：编辑器加载 UI 件能跑通、Save (API Format) 与我们手写 api 件结构一致。

## 影响文件

- 新增 `comfyui/workflows/ui/{z_image_t2i,qwen_image_t2i,wan22_5b_t2v,wan22_5b_i2v,wan22_14b_t2v,wan22_14b_i2v,ltx23_t2v,ltx23_i2v}.json`
- 新增 `comfyui/workflows/api/<同名>.api.json`
- 新增 `comfyui/README.md`
- 拷贝（仓库外）：`D:\ComfyUI\ComfyUI\user\default\workflows\<同名>.json`
- 不改任何后端代码。
