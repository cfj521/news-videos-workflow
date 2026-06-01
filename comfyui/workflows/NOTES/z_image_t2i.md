# z_image_t2i 工作流说明

## 模型信息

| 角色 | 文件名 | 路径 |
|------|--------|------|
| UNET (扩散模型) | `z_image_turbo_bf16.safetensors` | `D:\models\comfyui\diffusion_models\` |
| Text Encoder | `qwen_3_4b.safetensors` | `D:\models\comfyui\text_encoders\` |
| VAE | `ae.safetensors` | `D:\models\comfyui\vae\` |

- **架构**: 6B 参数 Scalable Single-Stream DiT，Z-Image-Turbo 是蒸馏加速版本
- **CLIP 类型**: 必须设为 `lumina2`（ComfyUI CLIPLoader 的 type 参数）

---

## 研究发现（关键参数）

### 采样参数（已实测确认）

| 参数 | 标准版 | HQ 版 |
|------|--------|-------|
| Steps | 9 | 9 |
| CFG | 1.0 | 1.0 |
| Sampler | euler | euler |
| Scheduler | simple | simple |
| Denoise | 1.0 | 1.0 |
| 分辨率 | 768×768 | 1024×1024 |
| ModelSamplingAuraFlow | 不使用 | shift=3.0 |

**为什么 cfg=1.0？** Turbo 模型是蒸馏模型，官方 HuggingFace 说明 `guidance_scale=0.0` 必须禁用引导。ComfyUI 中 cfg=1.0 + euler/simple 是等效实现（不使用负向提示引导时的标准行为）。

**ModelSamplingAuraFlow**：UI 示例中存在但默认 bypassed（mode=4）。启用时建议 shift=3（对应约 20 步采样节奏，来源：Lumina2 官方文档），可轻微调整噪声分布。对 9 步 Turbo 流程效果差异不显著，仅在 HQ 版中启用。

### Prompt 格式

官方 ComfyUI 示例 workflow（UI json 中的 Note 节点）说明：

> The "You are an assistant... <Prompt Start>" text before the actual prompt is the one used in the official example.
> The reason it is exposed to the user like this is because the model still works if you modify or remove it.

**结论**: 可以直接使用普通提示词，不强制要求前缀。前缀是从官方 Qwen 对话格式继承的，可选使用。本项目两个版本的 `__POSITIVE_PROMPT__` 参数均兼容两种用法：
- 不带前缀: `"news anchor, professional..."` 
- 带前缀: `"You are a helpful assistant. <Prompt Start> news anchor, professional..."`

### 负向提示

- CFG=1.0 时负向提示影响极弱（技术上几乎无效）
- 保留 `__NEGATIVE_PROMPT__` 占位符以兼容调用方接口
- 建议传入空字符串或简单的 `"blurry ugly bad"`

### 分辨率约束

- EmptySD3LatentImage: 支持 16~16384px，步长 16
- 实测建议范围: 512~1280px（超过 1024 时生成时间显著增加）
- 长宽比: 无硬性约束，但接近方形（1:1 ~ 16:9）效果更稳定

---

## 版本对比

### v1: `z_image_t2i.api.json` — 标准快速版

**用途**: 日常新闻视频素材批量生成，速度优先  
**分辨率**: 768×768（默认，可通过参数调整）  
**特点**: 无 ModelSamplingAuraFlow，图最快（RTX 4090 约 4s）  

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/z_image_t2i.api.json \
  --set "POSITIVE_PROMPT=You are a helpful assistant. <Prompt Start> Professional news anchor, Asian female reporter, sitting at a modern news desk, wearing a formal business suit, studio lighting, high quality, photorealistic" \
  --set "NEGATIVE_PROMPT=blurry ugly bad" \
  --set SEED=42 \
  --set WIDTH=768 \
  --set HEIGHT=768 \
  --save comfyui/samples/
```

**实测结果**: SUCCESS，生成时间 4.0s，输出 `ComfyUI_00002_.png`

---

### v2: `z_image_t2i_hq.api.json` — HQ 高质量版

**用途**: 封面图、关键帧、需要更高细节的场景  
**分辨率**: 1024×1024（默认，可通过参数调整）  
**特点**: 启用 ModelSamplingAuraFlow (shift=3.0)，噪声分布调整，生成约 6s  

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/z_image_t2i_hq.api.json \
  --set "POSITIVE_PROMPT=You are a helpful assistant. <Prompt Start> Professional news anchor, Asian female reporter, sitting at a modern television studio news desk, wearing a formal blue business suit, confident expression, studio lighting with soft key light, blurred newsroom background, photorealistic, sharp focus" \
  --set "NEGATIVE_PROMPT=blurry ugly bad deformed" \
  --set SEED=123 \
  --set WIDTH=1024 \
  --set HEIGHT=1024 \
  --save comfyui/samples/
```

**实测结果**: SUCCESS，生成时间 6.0s，输出 `ComfyUI_00003_.png`

---

## 图形节点结构

```
CLIPLoader (qwen_3_4b, type=lumina2)
    ↓ CLIP
CLIPTextEncode (positive)  CLIPTextEncode (negative)
    ↓ CONDITIONING               ↓ CONDITIONING

UNETLoader (z_image_turbo_bf16)
    ↓ MODEL
[ModelSamplingAuraFlow shift=3]  ← 仅 HQ 版启用
    ↓ MODEL
KSampler (steps=9, cfg=1.0, euler/simple)
    ↓ LATENT
VAEDecode
    ↓ IMAGE
SaveImage
```

---

## 使用建议（新闻视频场景）

| 场景 | 推荐版本 | 备注 |
|------|----------|------|
| 新闻配图批量生成 | 标准版 768px | 速度优先 |
| 主播/记者人像 | HQ 版 1024px | 面部细节更清晰 |
| 视频封面图 | HQ 版 1024px | 可考虑 1280×720 横版 |
| 快速预览 | 标准版 512px | 参数传 WIDTH=512 HEIGHT=512 |

---

## 已知局限

1. **CFG=1.0**: 负向提示基本无效，无法像 SD1.5 那样通过负向词排除内容
2. **Turbo 蒸馏**: 步数 <8 可能出现噪声图；步数 >12 效果提升有限
3. **文字渲染**: 官方宣传支持中英文混排，实测简单文字可渲染，复杂文字（多行）仍有拼写错误风险
4. **采样器兼容性**: 该模型对采样器选择较敏感，euler/simple 是验证过的稳定组合，不建议随意更换
5. **分辨率**: 超过 1280px 单边时 VRAM 消耗显著上升（6B 模型在 RTX 4090 24GB 可跑到约 2048px）

---

## 信息来源

- HuggingFace 模型卡: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- ComfyUI 官方文档: https://docs.comfy.org/tutorials/image/z-image/z-image-turbo
- ComfyUI 示例（UI workflow 内嵌 Note 节点）: `comfyui/workflows/ui/z_image_t2i.json`
- Lumina2 参数参考: https://comfyui-wiki.com/en/tutorial/advanced/lumina-image-2
- 实测验证: RTX 4090, ComfyUI @ http://127.0.0.1:8188, 2026-06-01
