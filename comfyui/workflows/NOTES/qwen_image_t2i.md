# qwen_image_t2i 工作流说明

## 模型信息

| 角色 | 文件名 | 路径 |
|------|--------|------|
| UNET (扩散模型) | `qwen_image_fp8_e4m3fn.safetensors` | `D:\models\comfyui\diffusion_models\` |
| Text Encoder (CLIP) | `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `D:\models\comfyui\text_encoders\` |
| VAE | `qwen_image_vae.safetensors` | `D:\models\comfyui\vae\` |

- **架构**: 20B 参数 MMDiT（Multimodal Diffusion Transformer），由阿里巴巴 Qwen 团队开源（Apache 2.0）
- **CLIP 类型**: 必须设为 `qwen_image`（ComfyUI CLIPLoader 的 `type` 参数）
- **Text Encoder**: Qwen2.5-VL 7B fp8 量化版本，支持多语言（中/英/日/韩等），是该模型中文文字渲染能力的来源
- **VRAM**: RTX 4090 24GB，fp8 版约占 86% VRAM（~20.4GB）

---

## 研究发现（关键参数）

### 采样参数（已实测确认）

| 参数 | 标准版 | 中文海报版 |
|------|--------|-----------|
| Steps | 20 | 10 |
| CFG | 2.5 | 2.5 |
| Sampler | euler | euler |
| Scheduler | simple | simple |
| Denoise | 1.0 | 1.0 |
| 分辨率 | 1024×1024 | 1664×928 (16:9) |
| ModelSamplingAuraFlow | shift=3.1 | shift=3.1 |

**官方参数参考** (HuggingFace diffusers)：`num_inference_steps=50`，`true_cfg_scale=4.0`。ComfyUI 原生工作流实测 20 步 cfg=2.5 即可获得优质效果。

**ModelSamplingAuraFlow shift=3.1**：控制噪声分布，来源于 AuraFlow 架构。UI workflow 中内嵌 Note 说明："Increase the shift if you get too many blurry/dark/bad images. Decrease if you want to try increasing detail."

**关于步数**：UI workflow 内嵌 Note 说明："The official number of steps is 50 but I think that's too much. Even just 10 steps seems to work." 实测 10 步比 20 步约快 40%，质量可接受。

### 支持的分辨率（官方推荐宽高比）

| 宽高比 | 分辨率 | 适用场景 |
|--------|--------|----------|
| 1:1 | 1328×1328 | 默认正方形，配图通用 |
| 16:9 | 1664×928 | 新闻横版封面/字幕条 |
| 9:16 | 928×1664 | 竖版短视频封面 |
| 4:3 | 1472×1104 | 传统电视比例 |
| 3:2 | 1584×1056 | 宽屏配图 |

注：ComfyUI 的 EmptySD3LatentImage 支持 16~16384px，步长 16。实测建议单边不超过 1664px 以控制生成时间。

### Prompt 格式

Qwen-Image 原生支持长文本提示词（最长约 1K tokens），不需要特殊前缀。直接描述即可，中英文均可，支持混排。

**中文文字渲染提示**（Qwen 的核心优势）：
- 在 prompt 中用引号标注要渲染的文字内容，如：`bold white Chinese text reading "突发新闻" in large font`
- 指定字体样式、颜色、位置（如 "at top"、"left side"）可提高准确率
- 建议在正向提示中加入 `sharp text rendering` / `legible text` 等短语
- 官方推荐负向提示（中文）：`"低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。"`

### 负向提示

CFG=2.5 时负向提示有效，建议使用官方推荐的中文负向提示词以获得最佳效果。

---

## 版本对比

### v1: `qwen_image_t2i.api.json` — 标准版（20 步）

**用途**: 日常新闻视频素材生成，质量与速度平衡  
**分辨率**: 默认参数化（示例 1024×1024）  
**特点**: 20 步，完整质量，ModelSamplingAuraFlow shift=3.1

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/qwen_image_t2i.api.json \
  --set "POSITIVE_PROMPT=A professional news broadcast studio, modern television news desk, LED backdrop showing breaking news graphics, studio lighting, cinematic quality, photorealistic" \
  --set "NEGATIVE_PROMPT=低分辨率，低画质，肢体畸形，手指畸形，画面过饱和" \
  --set SEED=42 \
  --set WIDTH=1024 \
  --set HEIGHT=1024 \
  --save comfyui/samples/
```

**实测结果**: SUCCESS，生成时间 92.4s，输出 `ComfyUI_00004_.png`（RTX 4090, 1024×1024）

---

### v2: `qwen_image_t2i_cn_poster.api.json` — 中文新闻海报版（10 步）

**用途**: 新闻字幕条、下三分之一横幅、中文文字海报、需要快速出图的场景  
**分辨率**: 默认参数化（示例 1664×928，16:9 横版）  
**特点**: 10 步快速，充分展示 Qwen 中文文字渲染能力，生成约 54s

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/qwen_image_t2i_cn_poster.api.json \
  --set "POSITIVE_PROMPT=A professional news broadcast lower-third graphic banner design, dark navy blue background, bold white Chinese text reading \"突发新闻\" in large font at top, subtitle text \"科技革新改变未来\" in smaller font below, red accent bar on left side, clean modern news television graphics style, high resolution, sharp text rendering" \
  --set "NEGATIVE_PROMPT=低分辨率，低画质，文字模糊，扭曲，构图混乱" \
  --set SEED=88 \
  --set WIDTH=1664 \
  --set HEIGHT=928 \
  --save comfyui/samples/
```

**实测结果**: SUCCESS，生成时间 54.2s，输出 `ComfyUI_00005_.png`（RTX 4090, 1664×928）

---

## 图形节点结构

```
UNETLoader (qwen_image_fp8_e4m3fn)
    ↓ MODEL
ModelSamplingAuraFlow (shift=3.1)   ← 两个版本均启用
    ↓ MODEL
CLIPLoader (qwen_2.5_vl_7b_fp8_scaled, type=qwen_image)
    ↓ CLIP
CLIPTextEncode (positive)  CLIPTextEncode (negative)
    ↓ CONDITIONING               ↓ CONDITIONING
                    ↓
EmptySD3LatentImage (width, height, batch=1)
    ↓ LATENT
KSampler (steps, cfg=2.5, euler/simple)
    ↓ LATENT
VAEDecode (qwen_image_vae)
    ↓ IMAGE
SaveImage
```

---

## 版本选择指南（新闻视频场景）

| 场景 | 推荐版本 | 参数建议 |
|------|----------|----------|
| 新闻配图（人像/场景） | 标准版 20 步 | 1024×1024 或 1328×1328 |
| 新闻字幕条/下三分之一 | 中文海报版 10 步 | 1664×928 (16:9) |
| 竖版封面（短视频） | 标准版 20 步 | 928×1664 (9:16) |
| 中文文字海报 | 中文海报版 10 步 | 1328×1328 或 1472×1104 |
| 快速预览/批量生成 | 中文海报版 10 步 | WIDTH=1024 HEIGHT=1024 |

---

## 已知局限与注意事项

1. **VRAM 占用高**: fp8 版约需 20GB VRAM，RTX 4090 可用但无余量跑第二个大模型
2. **生成速度慢**: 20 步约 92s（RTX 4090），10 步约 54s，相比 Z-Image（4s）慢 10-20x；适合质量优先而非速度优先的场景
3. **中文文字精度**: 单词/短句（4-8 字）准确率高；复杂多行布局仍有一定错误率，建议生成多张取优
4. **无 Lightning/蒸馏 LoRA 可用**: `D:\models\comfyui\loras` 中无 Qwen-Image 加速 LoRA（社区有 Qwen-Image-Lightning/distilled 版本，若需可下载）
5. **无 bf16 完整版**: 只有 fp8 量化版（20.4GB），bf16 完整版需 40.9GB，超出单卡显存
6. **采样器兼容性**: euler/simple 是验证过的稳定组合，res_multistep 在 cfg=1.0 时也有文献记录但未实测
7. **CFG 调节**: cfg=1.0 可再提速（与 Turbo 模式类似），但负向提示会完全失效；cfg=2.5 是质量/速度平衡点

---

## 与 Z-Image-Turbo 的对比

| 维度 | Qwen-Image | Z-Image-Turbo |
|------|-----------|---------------|
| 参数量 | 20B MMDiT | 6B DiT |
| 中文文字渲染 | 核心优势，高精度 | 支持但较弱 |
| 生成速度 | 54-92s (RTX 4090) | 4-6s |
| 语义理解 | 更强（Qwen2.5-VL 编码器）| 标准 |
| 适用场景 | 文字海报、新闻字幕图 | 批量配图、快速原型 |

**推荐策略**: 日常批量配图用 Z-Image-Turbo；需要渲染中文文字或高语义复杂度提示时用 Qwen-Image。

---

## 信息来源

- GitHub 官方仓库: https://github.com/QwenLM/Qwen-Image
- ComfyUI 官方文档: https://docs.comfy.org/tutorials/image/qwen/qwen-image
- ComfyUI 博客（发布公告）: https://blog.comfy.org/p/qwen-image-in-comfyui-new-era-of
- ComfyUI Wiki 完整教程: https://comfyui-wiki.com/en/tutorial/advanced/image/qwen/qwen-image
- ComfyUI 官方示例页面: https://comfyanonymous.github.io/ComfyUI_examples/qwen_image/
- ComfyUI UI workflow 内嵌 Note 节点: `comfyui/workflows/ui/qwen_image_t2i.json`
- 实测验证: RTX 4090, ComfyUI @ http://127.0.0.1:8188, 2026-06-01
