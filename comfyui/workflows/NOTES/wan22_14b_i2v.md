# wan22_14b_i2v 工作流说明

## 用途

Wan 2.2 **14B 双专家模型**图生视频（I2V）——以一张静态图像为首帧，文本提示驱动后续动态。
提供两个版本：

| 版本 | API 文件 | 特点 |
|------|---------|------|
| **Base** | `wan22_14b_i2v.api.json` | 20步官方默认，画质最优 |
| **LightX2V 4-step** | `wan22_14b_i2v_lightx2v.api.json` | 4步蒸馏加速 LoRA，约 2.3x 更快 |

---

## 模型信息

| 角色 | 文件名 | 路径 |
|------|--------|------|
| UNET (High Noise) | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | `D:\models\comfyui\diffusion_models\` |
| UNET (Low Noise) | `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | `D:\models\comfyui\diffusion_models\` |
| Text Encoder | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `D:\models\comfyui\text_encoders\` |
| VAE | `wan_2.1_vae.safetensors` | `D:\models\comfyui\vae\` |
| LoRA (HN, lightx2v) | `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | `D:\models\comfyui\loras\` |
| LoRA (LN, lightx2v) | `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | `D:\models\comfyui\loras\` |

注意：i2v lightx2v LoRA 是 **v1**（非 v1.1，与 t2v 版本不同）。

---

## 关键研究发现：clip_vision 不需要单独模型

**`WanImageToVideo` 节点的 `clip_vision_output` 输入是可选的（optional），`start_image` 也是可选的。**

通过 `GET /object_info/WanImageToVideo` 验证：
- `required` 输入: `positive`, `negative`, `vae`, `width`, `height`, `length`, `batch_size`
- `optional` 输入: `clip_vision_output`, `start_image`

**结论**：ComfyUI 官方重打包的 Wan 2.2 14B i2v 模型已将 CLIP Vision 功能内嵌到 i2v UNET 权重中，无需单独加载 `CLIPVisionLoader` 或提供外部 clip_vision_output。
只需将 `LoadImage` 输出连接到 `WanImageToVideo` 的 `start_image` 输入即可实现图生视频。

与 5B i2v（使用 `Wan22ImageToVideoLatent` 节点）不同，14B i2v 使用 `WanImageToVideo` 节点，接口更简洁。

---

## I2V 节点架构：WanImageToVideo

`WanImageToVideo` 节点同时承担以下职责：
1. 将文本条件（positive/negative CONDITIONING）与图像条件融合
2. 将输入图像（start_image）编码入 latent 空间（内部调用 VAE encode）
3. 输出 positive CONDITIONING、negative CONDITIONING 和 LATENT 三个通道

```
CLIPTextEncode (正) ──┐
                       ├── WanImageToVideo ─→ positive CONDITIONING ──→ KSamplerAdvanced (High)
CLIPTextEncode (负) ──┤     (width/height/      negative CONDITIONING ──→ KSamplerAdvanced (High/Low)
                       │      length)            latent ──────────────────→ KSamplerAdvanced (High)
VAELoader ───────────┤
                       │
LoadImage ────────────┘ (start_image, optional)
```

两个 KSamplerAdvanced 共享来自 WanImageToVideo 的相同 CONDITIONING，latent 由高噪声采样器串联低噪声采样器。

---

## 双采样器架构（与 t2v 相同）

见 `wan22_14b_t2v.md` 详细说明。要点：
- 高噪声专家处理前半程（step 0→10），`return_with_leftover_noise=enable`
- 低噪声专家处理后半程（step 10→∞），`add_noise=disable`
- `ModelSamplingSD3 shift=8.0`（Base）或 `shift=5.0`（LightX2V）

---

## 输入图像尺寸建议

- 输入图像的宽高比**应与 `width/height` 参数一致**，否则 ComfyUI 内部会 resize，可能导致轻微变形
- 推荐工作流：先用 z_image/qwen t2i 工作流生成与目标分辨率相同尺寸的图像，再作为 start_image
- 测试图像 `wan_i2v_test.png`：704×480（已存于 `d:/comfyui/comfyui/input/`）
- 生产推荐分辨率：`1280×704`（16:9 720p），`832×480`（16:9 标清）

**帧数规则**（与 t2v 相同）：length 必须满足 **4n+1**（25, 41, 57, 81, 121...）

---

## Base 版本参数

| 参数 | 值 | 说明 |
|------|----|------|
| steps (总) | 20 | 两个采样器各用 10 步 |
| CFG | 3.5 | 官方默认 |
| Sampler | `euler` | 官方 UI graph 默认 |
| Scheduler | `simple` | Wan 2.2 推荐 |
| ModelSamplingSD3 shift | **8.0** | 官方 14B 默认值 |
| High KSampler start/end | 0 / 10 | 前半程 |
| Low KSampler start/end | 10 / 10000 | 后半程 |

---

## LightX2V 4-step 版本参数

### 与 Base 的差异

| 参数 | Base | LightX2V 4-step | 说明 |
|------|------|-----------------|------|
| steps (总) | 20 | **4** | 蒸馏大幅减步 |
| CFG | 3.5 | **1.0** | 蒸馏模型禁用 CFG（≈1.0即关闭） |
| shift | 8.0 | **5.0** | 官方 distill config 值 |
| High start/end | 0 / 10 | **0 / 2** | 4步中前2步 |
| Low start/end | 10 / 10000 | **2 / 10000** | 4步中后2步 |
| LoRA (High) | 无 | `..._v1_high_noise.safetensors`, strength=1.0 | UNETLoader → LoRA → ModelSamplingSD3 |
| LoRA (Low) | 无 | `..._v1_low_noise.safetensors`, strength=1.0 | 同上 |

### 节点插入位置

```
UNETLoader (high) → LoraLoaderModelOnly (HN, str=1.0) → ModelSamplingSD3 (shift=5) → KSamplerAdvanced (4步, 0→2)
UNETLoader (low)  → LoraLoaderModelOnly (LN, str=1.0) → ModelSamplingSD3 (shift=5) → KSamplerAdvanced (4步, 2→∞)
```

---

## 节点图结构（Base）

```
UNETLoader (i2v_high_noise_14B)     UNETLoader (i2v_low_noise_14B)
    ↓ MODEL                              ↓ MODEL
ModelSamplingSD3 (shift=8)          ModelSamplingSD3 (shift=8)
    ↓ MODEL                              ↓ MODEL
          CLIPLoader (umt5_xxl, type=wan)
                ↓ CLIP (共享)
CLIPTextEncode (正) ──┐
                       ├── WanImageToVideo ──→ positive/negative CONDITIONING (共享)
CLIPTextEncode (负) ──┤     width/height/       latent
                       │     length             ↓
VAELoader ────────────┤         ┌──────── KSamplerAdvanced HIGH (step=20,cfg=3.5,0→10,leftover=on)
                       │         ↓ LATENT (含残留噪声)
LoadImage ────────────┘  KSamplerAdvanced LOW (step=20,cfg=3.5,10→∞,add_noise=off)
                                  ↓ LATENT
VAELoader ──────────────── VAEDecode
                                  ↓ IMAGE
                         SaveAnimatedWEBP (fps=16)
```

---

## VRAM / 速度实测

| 配置 | 用时 | 备注 |
|------|------|------|
| Base, 704×480, 25帧, steps=20 | **92.3s** | RTX 4090 24GB fp8 烟雾测试 |
| LightX2V, 704×480, 25帧, steps=4 | **40.1s** | RTX 4090 24GB fp8 烟雾测试 |
| Base, 1280×704, 57帧, steps=20 | 预估 12~18 min | 官方默认分辨率 |
| LightX2V, 1280×704, 57帧, steps=4 | 预估 5~8 min | 加速版 |

- **2.3x 加速**（704×480×25帧烟雾测试比值，略低于 t2v 的 2.5x，i2v 图像编码额外开销）
- i2v 比 t2v 略慢（WanImageToVideo 内部额外 VAE encode start_image）
- 双模型同时加载 14B fp8 × 2 ≈ 占满 24GB 显卡

---

## 何时使用哪个版本

| 场景 | 推荐版本 | 理由 |
|------|---------|------|
| 新闻 B 卷素材，以已有截图/生图为首帧 | LightX2V | 速度快 2.3x，40s 出结果 |
| 主打镜头、封面级动态视频 | Base | 画质更优，运动细节更自然 |
| 快速验证首帧是否合适 | LightX2V | 40s 快速预览 |
| 长视频（length≥81）| Base | 长时序下 4-step 可能有伪影 |
| 纯文生视频（无起始图）| 改用 wan22_14b_t2v | i2v 不带 start_image 也能跑但无意义 |

---

## 提示词建议（新闻视频场景）

I2V 模式中，正向提示词应同时描述**内容**和**运动**：

**正向**：
```
a news reporter standing on a city street with cars passing behind,
gentle dolly push-in, natural wind in hair, cinematic 720p, broadcast quality
```

**负向**（官方 UI graph）：
```
色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，
最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，
画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，
杂乱的背景，三条腿，背景人很多，倒着走
```

---

## 已验证 validate.py 命令

### Base — 烟雾测试（已实测 SUCCESS 92.3s）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_14b_i2v.api.json \
  --set "POSITIVE_PROMPT=a news reporter standing on a city street with cars passing, gentle camera pan, cinematic lighting, broadcast quality" \
  --set "NEGATIVE_PROMPT=static, blurry, low quality, watermark" \
  --set SEED=42 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --set LENGTH=25 \
  --set INPUT_IMAGE=wan_i2v_test.png \
  --save comfyui/samples/ \
  --timeout 1200
```

**输出**: `comfyui/samples/ComfyUI_00011_.webp`

### LightX2V 4-step — 烟雾测试（已实测 SUCCESS 40.1s）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_14b_i2v_lightx2v.api.json \
  --set "POSITIVE_PROMPT=a news reporter standing on a city street with cars passing, gentle camera pan, cinematic lighting, broadcast quality" \
  --set "NEGATIVE_PROMPT=static, blurry, low quality, watermark" \
  --set SEED=42 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --set LENGTH=25 \
  --set INPUT_IMAGE=wan_i2v_test.png \
  --save comfyui/samples/ \
  --timeout 600
```

**输出**: `comfyui/samples/ComfyUI_00012_.webp`

### Base — 官方默认质量（生产用）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_14b_i2v.api.json \
  --set "POSITIVE_PROMPT=a professional news anchor in a broadcast studio, subtle camera push-in, professional lighting, 720p cinematic" \
  --set "NEGATIVE_PROMPT=色调艳丽，过曝，静态，细节模糊不清，字幕，静止不动的画面" \
  --set SEED=42 \
  --set WIDTH=1280 \
  --set HEIGHT=704 \
  --set LENGTH=57 \
  --set INPUT_IMAGE=wan_i2v_test.png \
  --save comfyui/samples/ \
  --timeout 1200
```

---

## 信息来源

- ComfyUI WanImageToVideo 节点信息（实测）: `GET http://127.0.0.1:8188/object_info/WanImageToVideo`
  - 证实 `clip_vision_output` 和 `start_image` 均为 optional
- LightX2V i2v LoRA HuggingFace: https://huggingface.co/lightx2v/Wan2.2-Distill-Loras
  - i2v LoRA 版本为 `v1`（t2v 为 `v1.1`）
- LightX2V distill config (i2v): https://github.com/ModelTC/LightX2V/blob/main/configs/wan22/wan_moe_i2v_distill.json
- ComfyUI 官方 Wan2.2 i2v 教程: https://docs.comfy.org/tutorials/video/wan/wan2_2
- Wan 2.2 14B i2v UI graph: `comfyui/workflows/ui/wan22_14b_i2v.json`（WanImageToVideo 节点 clip_vision_output link=null，已确认不接外部 clip_vision）
- 实测验证: RTX 4090 24GB, ComfyUI @ http://127.0.0.1:8188, 2026-06-01
