# ComfyUI 工作流（z_image / Qwen-Image / Wan 2.2 / LTX 2.3）

本目录存放为本项目选用的几个模型编写的 ComfyUI 工作流，供**后端 `/prompt` 自动调用**与**人工在编辑器里调试**。模型已下载到 `D:/models/comfyui`（见 `scripts/download-comfyui-models.ps1`），并通过 `extra_model_paths.yaml` 挂给 ComfyUI。

## 关于 ComfyUI API（重要结论）

ComfyUI 的 `/prompt` 接口**无状态**：客户端每次把**完整工作流图（API/prompt 格式）**放进请求体 POST，ComfyUI 当场执行，**无需事先在编辑器保存/注册**任何工作流（依据：官方 `script_examples/basic_api_example.py` 直接 POST 图到 `/prompt`；docs 明确「client submits the whole workflow when you queue a request」）。

两种 JSON 格式：

- **API 格式**（`api/*.api.json`，后端用）：`{节点id: {"class_type":..., "inputs": {... 引用写成 ["节点id", 输出序号] ...}}}`。`/prompt` 直接吃（包在 `{"prompt": ...}` 里发）。
- **UI 格式**（`ui/*.json`，编辑器用）：带节点坐标/连线的图，拖进 ComfyUI 网页编辑器即可加载。`/prompt` **不直接吃**。

## 目录结构

```
comfyui/
  workflows/
    ui/    <name>.json        # UI 格式（权威源，可拖进编辑器）
    api/   <name>.api.json    # API 格式（后端 /prompt 用，含 __占位符__）
  README.md
```

UI 文件已另拷一份到 `D:\ComfyUI\ComfyUI\user\default\workflows\`，可直接在编辑器侧边栏看到。

## 工作流清单

| 名称 | 路线 | 关键模型文件（已挂在 `D:/models/comfyui`） | 默认参数 | UI | API |
|---|---|---|---|---|---|
| `z_image_t2i` | 文生图 | `z_image_turbo_bf16`(unet) · `qwen_3_4b`(clip, type=**lumina2**) · `ae`(vae) | 1024×1024, 9 步, cfg 1.0, euler/simple | ✅ | ✅ 官方 |
| `qwen_image_t2i` | 文生图 | `qwen_image_fp8_e4m3fn`(unet) · `qwen_2.5_vl_7b_fp8_scaled`(clip, type=**qwen_image**) · `qwen_image_vae`(vae) · ModelSamplingAuraFlow shift 3.1 | 1328×1328, 20 步, cfg 2.5, euler/simple | ✅ | ✅ 官方 |
| `wan22_5b_t2v` | 文生视频 | `wan2.2_ti2v_5B_fp16`(unet) · `umt5_xxl_fp8_e4m3fn_scaled`(clip, type=wan) · `wan2.2_vae` · ModelSamplingSD3 shift 8 | 1280×704, **41 帧**, 30 步, cfg 5, uni_pc/simple, **fps 24** | ✅ | ⚠️ 编辑器导出 |
| `wan22_5b_i2v` | 图生视频 | 同上 + `LoadImage` + `Wan22ImageToVideoLatent` | 1280×704, 41 帧, fps 24 | ✅ | ⚠️ 编辑器导出 |
| `wan22_14b_t2v` | 文生视频 | 双 unet `wan2.2_t2v_high/low_noise_14B_fp8_scaled` · `umt5_xxl…`(clip) · `wan_2.1_vae` · 双 ModelSamplingSD3 shift 8 | 1280×704, **57 帧**, 双 KSamplerAdvanced（高噪 0–10 步 → 低噪 10–20 步）, cfg 3.5, euler/simple, **fps 16** | ✅ | ⚠️ 编辑器导出 |
| `wan22_14b_i2v` | 图生视频 | 双 unet `wan2.2_i2v_high/low_noise_14B_fp8_scaled` · `wan_2.1_vae` · `WanImageToVideo` + `LoadImage` | 768×768, **81 帧**, 双采样同上, fps 16 | ✅ | ⚠️ 编辑器导出 |
| `ltx23_t2v` | 文生视频 | **需装 `ComfyUI-LTXVideo` 自定义节点**；`ltx-2.3-22b-dev-fp8`(checkpoint) + 蒸馏/Gemma LoRA + 空间上采样（见下「LTX 模型差异」） | 见模板内 Note | ✅ | ⚠️ 编辑器导出 |
| `ltx23_i2v` | 图生视频 | 同上 + 图像条件 | 见模板内 Note | ✅ | ⚠️ 编辑器导出 |

> **为什么视频工作流只给 UI、API 标「编辑器导出」**：ComfyUI 把「UI 图 → API 图」的转换内置在编辑器里（处理 bypass 节点改线、`control_after_generate` 控件剔除等细节）。本仓库无法运行 ComfyUI 验证，手写复杂视频图的 API 极易出错。图片两个工作流的 API 是**直接从官方示例 PNG 里提取的 ComfyUI 自身导出件**（可靠），故保留；视频的请按下方流程在编辑器一键导出，保证可执行。

## 用法 A：后端 `/prompt` 调用（图片工作流）

`api/*.api.json` 里用 `__占位符__` 标出需后端填的字段，其余（模型名、步数、cfg、scheduler、shift）已按官方 + 24GB 配置写死。

占位符清单：

| 占位符 | 含义 | 出现于 |
|---|---|---|
| `__POSITIVE_PROMPT__` | 正向提示词 | 全部 |
| `__NEGATIVE_PROMPT__` | 反向提示词 | 全部 |
| `__SEED__` | 随机种子（整数） | 全部 |
| `__WIDTH__` / `__HEIGHT__` | 分辨率 | 全部 |
| `__LENGTH__` | 视频帧数 | 视频工作流（编辑器导出后自行标注） |
| `__INPUT_IMAGE__` | i2v 输入图文件名 | i2v 工作流 |

Python 示例（填占位符 → 提交 → 取回结果）：

```python
import json, copy, urllib.request, uuid

def run(api_json_path, *, positive, negative="", seed=0, width=1024, height=1024,
        host="http://127.0.0.1:8188"):
    tmpl = json.load(open(api_json_path, encoding="utf-8"))
    repl = {"__POSITIVE_PROMPT__": positive, "__NEGATIVE_PROMPT__": negative,
            "__SEED__": seed, "__WIDTH__": width, "__HEIGHT__": height}
    def fill(x):
        if isinstance(x, dict): return {k: fill(v) for k, v in x.items()}
        if isinstance(x, list): return [fill(v) for v in x]
        return repl.get(x, x) if isinstance(x, str) else x
    prompt = fill(copy.deepcopy(tmpl))
    body = json.dumps({"prompt": prompt, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(f"{host}/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req).read())["prompt_id"]
    # 轮询 /history/{pid} 拿输出文件名；或用 ws /ws 收 executed 事件
    return pid

run("comfyui/workflows/api/z_image_t2i.api.json",
    positive="a news anchor in a studio, cinematic", seed=42, width=1024, height=1024)
```

> 注意：`__SEED__`/`__WIDTH__`/`__HEIGHT__` 在模板里是字符串占位符，**必须替换成数值**后再发，否则 ComfyUI 校验会报类型错误。

## 用法 B：视频工作流的 API 格式怎么来

1. 启动 ComfyUI，在网页编辑器里**拖入** `ui/<name>.json`（或从侧边栏 workflows 选）。
2. 确认能跑通（首次会提示缺节点/模型 → 见下方依赖与 LTX 差异）。
3. 菜单 **Save (API Format)**（需在设置里开启 *Enable Dev mode Options*）导出 → 覆盖 `api/<name>.api.json`。
4. 把要后端控制的字段手动改成 `__占位符__`（prompt / seed / 宽高 / 帧数 / 输入图）。

## 依赖与注意事项

- **LTX 两个工作流需自定义节点**：在 ComfyUI Manager 搜索安装 `ComfyUI-LTXVideo`，否则节点缺失无法加载。其余 6 个用核心节点即可。
- **Wan 14B 提速（lightx2v 4 步）**：官方 14B 模板是基础双采样（20 步、cfg 3.5），较慢。我们已下载 4 步 lightning LoRA。提速做法：在每个 `UNETLoader` 后接一个 `LoraLoaderModelOnly`（高噪模型配 `wan2.2_{t2v|i2v}_lightx2v_4steps_..._high_noise`，低噪配 `..._low_noise`），并把两个 `KSamplerAdvanced` 总步数降到 4（高噪 0–2、低噪 2–4）、cfg 1.0。改完在编辑器重导 API。
- **Wan 5B 文生/图生同模型**：`wan22_5b_t2v` 与 `wan22_5b_i2v` 是同一 TI2V 模型，区别仅在 i2v 多了 `LoadImage` 接入 `Wan22ImageToVideoLatent` 的起始帧。

## LTX 模型差异（需你确认/补齐）

官方 LTX 2.3 模板期望的文件**与我们 `download-comfyui-models.ps1` 当时下载的不完全一致**：

| 用途 | 官方模板期望 | 我们已下载 | 处理 |
|---|---|---|---|
| checkpoint | `ltx-2.3-22b-dev-fp8.safetensors` | 同 ✅ | 一致 |
| 蒸馏 LoRA | `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors` | `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` | ⚠️ 不同文件，建议按模板补下 |
| Gemma | `gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors`（LoRA，叠在内置 Gemma 上） | 整目录 `gemma-3-12b-it-qat-q4_0-unquantized/` | ⚠️ 方式不同，需在编辑器里确认 `LTXAVTextEncoderLoader` 的 Gemma 来源 |
| 空间上采样 | `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `ltx-2.3-spatial-upscaler-x2-1.0.safetensors` | ⚠️ 版本 1.1 vs 1.0，建议补 1.1 |

模板内的 **MarkdownNote 节点**列了官方下载链接。LTX 工作流首次在编辑器加载时，按 Note 把缺的文件补到 `D:/models/comfyui/{checkpoints,loras,latent_upscale_models}` 下，或把节点指向我们已有的同类文件后再测试。

## 模型路径

所有模型挂在 `D:/models/comfyui`（`extra_model_paths.yaml` 的 `comfyui_central` 块）：`checkpoints/ diffusion_models/ text_encoders/ vae/ loras/ latent_upscale_models/`。
