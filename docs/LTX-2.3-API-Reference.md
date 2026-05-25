# LTX-2.3 开发接口参考文档

> 基于 2026-05-26 调研整理，来源：官方 GitHub、HuggingFace、docs.ltx.video

---

## 1. 模型概览

| 项目 | 规格 |
|------|------|
| 架构 | DiT（Diffusion Transformer），音视频联合生成 |
| 参数量 | 22B |
| 精度 | bfloat16 |
| 框架 | PyTorch ~= 2.7 |
| 许可证 | 开源（HuggingFace） |

### 硬件要求

| 项目 | 最低 | 推荐 |
|------|------|------|
| GPU | NVIDIA 16GB VRAM | RTX 4090 / A100 / H100 |
| CUDA | > 12.7 | |
| Python | >= 3.12 | |
| 系统内存 | 16GB | 32GB |
| 磁盘 | 160GB（含模型文件） | |
| macOS | 仅支持 API 模式，不支持本地推理 | |

---

## 2. 可用模型检查点

| 检查点 | 用途 | 推理步数 | CFG |
|--------|------|---------|-----|
| `ltx-2.3-22b-dev` | 完整可训练模型 | 20-50 | 2.0-5.0 |
| `ltx-2.3-22b-distilled` | 蒸馏快速推理 | 4-8 | 1.0（推荐 3.0-3.5）|
| `ltx-2.3-22b-distilled-1.1` | 改进版，更好画面和音频 | 4-8 | 同上 |
| `ltx-2.3-22b-distilled-lora-384` | LoRA 适配器 | — | — |
| `ltx-2.3-spatial-upscaler-x2-1.1` | 2x 空间分辨率提升 | — | — |
| `ltx-2.3-temporal-upscaler-x2-1.0` | 2x 帧率提升 | — | — |

---

## 3. 支持的生成模式

| 模式 | 输入 | 输出 | Pipeline 类 |
|------|------|------|-------------|
| Text-to-Video | 文本 prompt | 视频+音频 | `TI2VidTwoStagesPipeline` |
| Image-to-Video | 图片 + prompt | 动态视频 | `TI2VidTwoStagesPipeline`（带 images 参数）|
| Audio-to-Video | 音频 + prompt | 带嘴型同步的视频 | `A2VidPipelineTwoStage` |
| Video-to-Video | 视频 + prompt（IC-LoRA）| 风格化视频 | `ICLoraPipeline` |
| Retake | 已有视频 + 时间区间 | 局部重新生成 | `RetakePipeline` |
| Keyframe 插值 | 关键帧图片 | 补间动画视频 | `KeyframeInterpolationPipeline` |
| LipDub | 视频 + 目标文本 | 替换嘴型和音频 | `LipDubPipeline` |
| HDR | 视频 + IC-LoRA | HDR 输出 | `HDRICLoraPipeline` |

---

## 4. 视频格式约束

```
宽度/高度：必须是 32 的倍数
帧数：    必须是 8n+1（9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, 121, 161, 193, 257）
最大帧数：257 帧 ≈ 10秒 @25fps
推荐帧数：121-161 帧（约 5-6 秒，平衡质量和显存）
帧率：    24 / 25 / 48 / 50 fps
输入图片：PNG, JPG, WebP
```

### 常用分辨率参考

| 比例 | 分辨率 | 用途 |
|------|--------|------|
| 16:9 横屏 | 768×512 | 快速测试 |
| 16:9 横屏 | 1280×720 | 720p 标准 |
| 16:9 横屏 | 1920×1080 | 1080p（需大显存）|
| 9:16 竖屏 | 512×768 | 快速测试 |
| 9:16 竖屏 | 736×1280 | 720p 竖屏（推荐）|
| 9:16 竖屏 | 1088×1920 | 1080p 竖屏（需 RTX 5090+）|

---

## 5. Pipeline 类详解

### 5.1 所有 Pipeline 类

```python
from ltx_pipelines.ti2vid_two_stages import TI2VidTwoStagesPipeline
from ltx_pipelines.ti2vid_two_stages_hq import TI2VidTwoStagesHQPipeline
from ltx_pipelines.ti2vid_one_stage import TI2VidOneStagePipeline
from ltx_pipelines.distilled_pipeline import DistilledPipeline
from ltx_pipelines.ic_lora_pipeline import ICLoraPipeline
from ltx_pipelines.a2vid_two_stage import A2VidPipelineTwoStage
from ltx_pipelines.retake_pipeline import RetakePipeline
from ltx_pipelines.keyframe_interpolation_pipeline import KeyframeInterpolationPipeline
from ltx_pipelines.lip_dub_pipeline import LipDubPipeline
from ltx_pipelines.hdr_ic_lora_pipeline import HDRICLoraPipeline
```

### 5.2 核心 Pipeline 构造器参数

```python
pipeline = TI2VidTwoStagesPipeline(
    # 必需参数
    checkpoint_path: str,              # 模型 .safetensors 文件路径
    distilled_lora: list,              # 蒸馏 LoRA 配置列表
    spatial_upsampler_path: str,       # 空间上采样器模型路径
    gemma_root: str,                   # Gemma 文本编码器目录

    # 可选参数
    loras: list = [],                  # 额外 LoRA 适配器
    quantization: QuantizationPolicy = None,  # FP8 量化策略
)
```

### 5.3 LoRA 配置

```python
from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP, LoraPathStrengthAndSDOps

distilled_lora = [
    LoraPathStrengthAndSDOps(
        path="/path/to/ltx-2.3-22b-distilled-lora-384.safetensors",
        strength=0.6,
        sd_ops=LTXV_LORA_COMFY_RENAMING_MAP,
    ),
]
```

---

## 6. 生成调用参数

### 6.1 Pipeline __call__ 参数

```python
pipeline(
    # 内容控制
    prompt: str,                       # 文本描述
    seed: int,                         # 随机种子（确保可复现）

    # 视频格式
    height: int,                       # 高度（32 的倍数）
    width: int,                        # 宽度（32 的倍数）
    num_frames: int,                   # 帧数（8n+1 格式）
    frame_rate: float,                 # 帧率（如 25.0）

    # 推理控制
    num_inference_steps: int = 40,     # 去噪步数（蒸馏模型用 4-8）

    # 引导参数
    video_guider_params: MultiModalGuiderParams,
    audio_guider_params: MultiModalGuiderParams,

    # 图片条件（Image-to-Video 时使用）
    images: list[ImageConditioningInput] = [],

    # 输出
    output_path: str,                  # 输出 MP4 文件路径
)
```

### 6.2 MultiModalGuiderParams（引导参数）

```python
from ltx_core.components.guiders import MultiModalGuiderParams

video_guider_params = MultiModalGuiderParams(
    cfg_scale=3.0,         # Classifier-Free Guidance 强度（1.0=禁用，推荐 2.0-5.0）
    stg_scale=1.0,         # 时空引导强度（0.0=禁用，推荐 0.5-1.5）
    stg_blocks=[29],       # 要扰动的 Transformer block 索引
    rescale_scale=0.7,     # 方差重缩放，防止过饱和
    modality_scale=3.0,    # 音视频同步强度（1.0=禁用）
    skip_step=0,           # 每 N 步跳过引导
)

audio_guider_params = MultiModalGuiderParams(
    cfg_scale=7.0,         # 音频引导通常用更高的 CFG
    stg_scale=1.0,
    stg_blocks=[29],
    rescale_scale=0.7,
    modality_scale=3.0,
    skip_step=0,
)
```

### 6.3 ImageConditioningInput（图片条件输入）

```python
from ltx_pipelines.ti2vid_two_stages import ImageConditioningInput

images = [
    ImageConditioningInput(
        path="input_image.jpg",        # 图片文件路径
        frame_index=0,                 # 条件帧索引（0=第一帧）
        strength=1.0,                  # 条件强度
        downsample_factor=33,          # 下采样因子
    )
]
```

**注意**：输入图片分辨率应与目标视频分辨率匹配，否则会出现上采样伪影。

---

## 7. 完整代码示例

### 7.1 原生 Pipeline：Image-to-Video（推荐用于生产）

```python
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP, LoraPathStrengthAndSDOps
from ltx_core.components.guiders import MultiModalGuiderParams
from ltx_pipelines.ti2vid_two_stages import (
    TI2VidTwoStagesPipeline,
    ImageConditioningInput,
)

# --- 模型路径配置 ---
MODEL_DIR = "/path/to/models"
CHECKPOINT = f"{MODEL_DIR}/ltx-2.3-22b-distilled-1.1.safetensors"
UPSAMPLER = f"{MODEL_DIR}/ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
DISTILLED_LORA = f"{MODEL_DIR}/ltx-2.3-22b-distilled-lora-384.safetensors"
GEMMA_DIR = f"{MODEL_DIR}/gemma"

# --- 构建 Pipeline ---
pipeline = TI2VidTwoStagesPipeline(
    checkpoint_path=CHECKPOINT,
    distilled_lora=[
        LoraPathStrengthAndSDOps(DISTILLED_LORA, 0.6, LTXV_LORA_COMFY_RENAMING_MAP)
    ],
    spatial_upsampler_path=UPSAMPLER,
    gemma_root=GEMMA_DIR,
)

# --- 引导参数 ---
video_guider = MultiModalGuiderParams(
    cfg_scale=3.0, stg_scale=1.0, stg_blocks=[29],
    rescale_scale=0.7, modality_scale=3.0, skip_step=0,
)
audio_guider = MultiModalGuiderParams(
    cfg_scale=7.0, stg_scale=1.0, stg_blocks=[29],
    rescale_scale=0.7, modality_scale=3.0, skip_step=0,
)

# --- 生成视频 ---
pipeline(
    prompt="镜头缓慢推进，展示一座现代化城市的天际线，阳光从高楼间洒落",
    output_path="output.mp4",
    seed=42,
    height=512,
    width=768,
    num_frames=121,           # 约 4.8 秒 @25fps
    frame_rate=25.0,
    num_inference_steps=8,    # 蒸馏模型用 4-8 步
    video_guider_params=video_guider,
    audio_guider_params=audio_guider,
    images=[
        ImageConditioningInput("city_skyline.jpg", 0, 1.0, 33)
    ],
)
```

### 7.2 HuggingFace Diffusers：简化接口

```python
import torch
from diffusers import DiffusionPipeline
from diffusers.utils import load_image, export_to_video

pipe = DiffusionPipeline.from_pretrained(
    "Lightricks/LTX-2.3",
    dtype=torch.bfloat16,
    device_map="cuda",
)
pipe.to("cuda")

image = load_image("city_skyline.jpg")
prompt = "镜头缓慢推进，展示城市天际线"

output = pipe(image=image, prompt=prompt).frames[0]
export_to_video(output, "output.mp4")
```

> **注意**：LTX-2.3 的 Diffusers 集成标注为 "coming soon"，可能部分功能尚未完整支持。
> 生产环境建议使用原生 ltx-pipelines。

### 7.3 Distilled Pipeline（最快推理）

```python
from ltx_pipelines.distilled_pipeline import DistilledPipeline

pipeline = DistilledPipeline.from_config("path/to/config.yaml")

output = pipeline(
    prompt="A golden retriever running through a sunlit meadow",
    width=768,
    height=512,
    num_frames=97,
    fps=24.0,
    seed=42,
)
```

---

## 8. 显存优化

### FP8 量化（减少约 40% 显存）

```python
from ltx_core.quantization.policy import QuantizationPolicy

pipeline = TI2VidTwoStagesPipeline(
    checkpoint_path=CHECKPOINT,
    ...,
    quantization=QuantizationPolicy.fp8_cast(),  # 或 fp8_scaled_mm()
)
```

### 环境变量

```bash
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

---

## 9. 托管 API（无需 GPU 的备选方案）

LTX 提供按秒计费的云端 API，无需管理 GPU 基础设施。

### 可用模型

| 模型 | 特点 |
|------|------|
| `ltx-2-3-fast` | 低计算开销，快速渲染 |
| `ltx-2-3-pro` | 增强细节和稳定性 |

### 支持规格

- 分辨率：720p / 1080p / 1440p / 4K
- 帧率：24 / 25 / 48 / 50 fps
- 时长：6-20 秒（因模型而异）
- 计费方式：按生成视频秒数

### 接入方式

- API 文档：https://docs.ltx.video/welcome
- 控制台/Playground：https://console.ltx.video/playground
- 定价：https://ltx.io/model/api/pricing

> 详细的 API endpoint、请求/响应格式、认证方式需查阅官方文档，
> 此处未完整收录因官方营销页未公开全部细节。

---

## 10. 特殊 Pipeline 约束

| Pipeline | 约束 |
|----------|------|
| `RetakePipeline` | 源视频帧数必须满足 8n+1，分辨率必须是 32 的倍数 |
| `A2VidPipelineTwoStage` | 需要 `--audio-path`（必需）、`--audio-start-time`、`--audio-max-duration` |
| `LipDubPipeline` | 需要恰好一个 lip-dub IC-LoRA；帧数和帧率从参考视频自动推导 |
| `HDRICLoraPipeline` | 需要 `--hdr-lora`、`--text-embeddings`（预计算 .safetensors）|

---

## 11. 安装步骤

```bash
# 克隆仓库
git clone https://github.com/Lightricks/LTX-2.git
cd LTX-2

# 安装依赖（使用 uv 包管理器）
uv sync
source .venv/bin/activate  # Linux/Mac
# Windows: .venv\Scripts\activate

# 或者使用 pip
pip install ltx-pipelines ltx-core
```

### 模型下载

从 HuggingFace 下载检查点：

```bash
# 安装 huggingface-cli
pip install huggingface_hub

# 下载模型（约 80GB+）
huggingface-cli download Lightricks/LTX-2.3 --local-dir ./models/ltx-2.3
```

---

## 12. 与我们项目的集成设计

### VideoProvider 接口适配

```python
# 我们的统一接口
class VideoProvider(ABC):
    async def generate(
        self,
        prompt: str,
        image_path: str | None,
        duration: float,
        resolution: tuple[int, int],  # (width, height)
        output_path: str,
    ) -> VideoAsset: ...

# LTX 实现需要做的转换：
# duration → num_frames: round(duration * fps) 取最近的 8n+1 值
# resolution → width/height: 各自 round 到最近的 32 的倍数
```

### 帧数计算辅助函数

```python
def duration_to_frames(duration_sec: float, fps: float = 25.0) -> int:
    """将目标时长转换为最近的合法帧数（8n+1 格式）"""
    raw_frames = duration_sec * fps
    n = round((raw_frames - 1) / 8)
    n = max(1, n)  # 最少 9 帧
    frames = 8 * n + 1
    return min(frames, 257)  # 不超过最大帧数

def snap_to_32(value: int) -> int:
    """将分辨率值对齐到 32 的倍数"""
    return round(value / 32) * 32
```

---

## 参考链接

- GitHub 仓库：https://github.com/Lightricks/LTX-2
- HuggingFace 模型：https://huggingface.co/Lightricks/LTX-2.3
- 官方文档：https://docs.ltx.video
- Prompting 指南：https://ltx.video/blog/how-to-prompt-for-ltx-2
- ComfyUI 集成：https://github.com/Lightricks/ComfyUI-LTXVideo
- 论文：arXiv 2601.03233
