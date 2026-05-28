# ComfyUI + LTX-Video 2.3 部署指南

## 硬件要求

| VRAM | 可用性 |
|------|--------|
| 12 GB (RTX 3060) | GGUF 量化，勉强可用 |
| 16 GB (RTX 4080) | FP8 量化，1024x576 |
| 24 GB (RTX 4090) | FP8 + 上采样两阶段 |
| 32 GB+ (A100) | bf16 完整模型，1080p 直出 |

系统内存 32GB+，磁盘 60GB+ 空闲，CUDA 12.x。

---

## 1. 安装 ComfyUI

```bash
# 方式一：comfy-cli（推荐）
pip install comfy-cli
comfy install --fast-deps
comfy launch

# 方式二：手动
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
python main.py --listen 0.0.0.0 --port 8188
```

Windows 可直接下载 [便携版 .7z](https://github.com/comfyanonymous/ComfyUI/releases)，解压运行 `run_nvidia_gpu.bat`。

要求 ComfyUI **v0.16+**。

---

## 2. 下载模型

HuggingFace 仓库：
- LTX 完整版: [Lightricks/LTX-2.3](https://huggingface.co/Lightricks/LTX-2.3)
- LTX FP8 量化版: [Lightricks/LTX-2.3-fp8](https://huggingface.co/Lightricks/LTX-2.3-fp8)
- Gemma 文本编码器: [google/gemma-3-12b-it-qat-q4_0-unquantized](https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized)（需先接受许可协议）

| 文件 | 来源仓库 | 放置目录 | 说明 |
|------|---------|----------|------|
| `ltx-2.3-22b-dev-fp8.safetensors` (~29GB) | Lightricks/LTX-2.3-fp8 | `models/checkpoints/` | 主模型 (FP8) |
| `gemma-3-12b-it-qat-q4_0-unquantized/` (整个目录, ~24GB) | google/gemma-3-12b-it-qat-q4_0-unquantized | `models/text_encoders/` | 文本编码器 (**需 HF 登录**) |
| `ltx-2.3-spatial-upscaler-x2-1.0.safetensors` (~1GB) | Lightricks/LTX-2.3 | `models/latent_upscale_models/` | 空间上采样 |
| `ltx-2.3-temporal-upscaler-x2-1.0.safetensors` (~262MB) | Lightricks/LTX-2.3 | `models/latent_upscale_models/` | 时间上采样 |
| `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` (~7.6GB) | Lightricks/LTX-2.3 | `models/loras/` | 可选，蒸馏加速 (8步出图) |

### 下载方式

**方式一：使用项目脚本 (推荐)**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/download-ltx-models.ps1
```

LTX 模型走 hf-mirror.com 镜像加速，Gemma 走官方源（需登录）。支持 aria2c 16 线程 + 断点续传。

**方式二：手动下载**

LTX 模型（镜像站，无需登录）：
```
https://hf-mirror.com/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors
https://hf-mirror.com/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.0.safetensors
https://hf-mirror.com/Lightricks/LTX-2.3/resolve/main/ltx-2.3-temporal-upscaler-x2-1.0.safetensors
https://hf-mirror.com/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384-1.1.safetensors
```

Gemma 文本编码器（官方源，**需先登录 + 接受许可**）：
```powershell
# 1. 清除镜像设置，登录 HuggingFace
$env:HF_ENDPOINT = ""
hf auth login

# 2. 下载 Gemma（不走镜像）
hf download google/gemma-3-12b-it-qat-q4_0-unquantized --local-dir D:\models\ltx-2.3\text_encoders\gemma-3-12b-it-qat-q4_0-unquantized
```

> **注意**: Gemma 是 Google 受限模型，必须先在 HuggingFace 网页上接受许可协议，且 `HF_ENDPOINT` 不能指向镜像站（镜像站不支持 Google 认证模型）。

### 自定义模型路径

ComfyUI 支持通过 `extra_model_paths.yaml` 指定外部模型目录：

```yaml
# ComfyUI/extra_model_paths.yaml
ltx_models:
  checkpoints: D:/models/ltx-2.3/checkpoints/
  text_encoders: D:/models/ltx-2.3/text_encoders/
  loras: D:/models/ltx-2.3/loras/
  latent_upscale_models: D:/models/ltx-2.3/latent_upscale_models/
```

---

## 3. 安装自定义节点

[ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)（Lightricks 官方）:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Lightricks/ComfyUI-LTXVideo.git
```

或 ComfyUI Manager 搜索 "LTXVideo" 安装。

示例工作流在: `custom_nodes/ComfyUI-LTXVideo/example_workflows/`

---

## 4. 工作流

**快速启动:** ComfyUI 内置模板库 → Video → LTX-2.3，直接加载。

**推荐两阶段流水线:**
1. Stage 1: 目标分辨率 1/2 生成（768x512），关注运动和连贯性
2. Stage 2: `spatial-upscaler-x2` 上采样到目标分辨率

**关键参数:**
- CFG Scale: **5.5**（不要超过 7）
- Steps: dev 模型 30-50 步，distilled 8 步
- Stage 1 分辨率: 768x512 或 1024x576

**节点链:**
```
Text-to-Video:  [Gemma Text Encoding] → [LTXVTextToVideoSampler] → [VideoCombine]
Image-to-Video: [LoadImage] + [Gemma Text Encoding] → [LTXVImageToVideoSampler] → [VideoCombine]
```

---

## 5. API 调用

ComfyUI 本身就是 API-first，UI 只是客户端。

```bash
python main.py --listen 0.0.0.0 --port 8188
```

| 端点 | 方法 | 用途 |
|------|------|------|
| `/prompt` | POST | 提交工作流 |
| `/history/{prompt_id}` | GET | 获取结果 |
| `/view?filename=xx&type=output` | GET | 下载输出 |
| `/upload/image` | POST | 上传输入图片 |
| `/ws` | WebSocket | 实时进度 |

**Python 调用:**

```python
import json, urllib.request, uuid

SERVER = "127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())

def queue_prompt(workflow: dict) -> str:
    payload = json.dumps({"prompt": workflow, "client_id": CLIENT_ID}).encode()
    req = urllib.request.Request(
        f"http://{SERVER}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())["prompt_id"]

def get_output(prompt_id: str) -> dict:
    resp = json.loads(urllib.request.urlopen(f"http://{SERVER}/history/{prompt_id}").read())
    return resp.get(prompt_id, {}).get("outputs", {})

def download_file(filename: str) -> bytes:
    return urllib.request.urlopen(f"http://{SERVER}/view?filename={filename}&type=output").read()
```

**获取工作流 JSON:** ComfyUI 界面 → 勾选 "Enable Dev Mode Options" → "Save (API Format)" 导出。

**WebSocket 监控长任务:**

```python
import websocket
ws = websocket.WebSocket()
ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")
while True:
    msg = json.loads(ws.recv())
    if msg["type"] == "executing" and msg["data"]["node"] is None:
        break  # 完成
```

---

## 与本项目集成

在 `backend/app/providers/` 下实现 `ComfyUIVideoProvider`:
- HTTP 调用 `/prompt` 提交预设工作流 JSON
- 运行时替换 prompt 文本 / 图片路径 / 参数
- WebSocket 监控进度，对接 pipeline 状态更新
- 工作流模板存放在 `backend/app/providers/composer/workflows/`
