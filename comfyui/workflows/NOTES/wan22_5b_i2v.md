# wan22_5b_i2v 工作流说明

## 用途

Wan 2.2 5B TI2V（Text-and-Image-to-Video）的**图生视频（I2V）模式**。
向 `Wan22ImageToVideoLatent.start_image` 输入一张图像，模型以该帧为首帧，文本提示驱动后续动态。
适用于新闻视频 B 卷素材、已有场景图像的动态化、定格转运动镜头。

> 兄弟工作流 `wan22_5b_t2v`（无 start_image）做纯文生视频；两者使用**完全相同的模型文件**。

---

## 模型信息

| 角色 | 文件名 | 路径 |
|------|--------|------|
| UNET (扩散模型) | `wan2.2_ti2v_5B_fp16.safetensors` | `D:\models\comfyui\diffusion_models\` |
| Text Encoder | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `D:\models\comfyui\text_encoders\` |
| VAE | `wan2.2_vae.safetensors` | `D:\models\comfyui\vae\` |

- **架构**: 5B 密集参数 Wan 2.2 TI2V 模型，start_image 将首帧编码进 latent 空间
- **CLIP 类型**: 必须设为 `wan`（CLIPLoader type 参数）
- **VRAM**: fp16 全精度约需 24GB；RTX 4090 24GB 可运行

---

## 研究发现（I2V 关键要点）

### start_image 机制

`Wan22ImageToVideoLatent` 接受可选的 `start_image`（IMAGE 类型）：
- 有 start_image → **I2V 模式**：第一帧锁定为输入图像，后续帧由文本提示驱动
- 无 start_image → T2V 模式（见 wan22_5b_t2v 工作流）

`LoadImage` 节点从 ComfyUI 的 `input/` 目录读取，输入文件名即相对于该目录的文件名（不含路径）。

### 输入图像尺寸建议

- **理想情况**：输入图像的宽高比应与 `width/height` 参数一致。
- 若不一致，ComfyUI 的 `LoadImage` 会自动在 VAE 编码前 resize/pad，但可能导致轻微构图变形。
- 推荐工作流：先用 t2i 工作流生成与目标 width/height 相同尺寸的图，再作为 start_image 传入。
- 生产建议：1280×704（与默认 I2V 分辨率一致）。

### 采样参数（与 t2v 相同，已验证）

| 参数 | 值 | 说明 |
|------|----|------|
| Steps | 30 | 官方默认 |
| CFG | 5.0 | 官方默认 |
| Sampler | `uni_pc` | 官方默认 |
| Scheduler | `simple` | Wan 2.2 推荐 |
| Denoise | 1.0 | I2V 也用 1.0（latent 起点已由 start_image 参与构建） |
| ModelSamplingSD3 shift | 8.0 | 官方 5B 默认 |

### 视频参数

| 参数 | 官方默认 | Smoke test | 说明 |
|------|----------|-----------|------|
| 分辨率 | 1280×704 | 704×480 | 720p 官方最优 |
| 帧数 (length) | 41 | 25 | 必须为 **4n+1** |
| FPS | 24 | 24 | 固定 |
| 输出格式 | AnimatedWEBP | AnimatedWEBP | lossless=false, quality=80 |

### 帧数规则：必须为 4n+1

`Wan22ImageToVideoLatent` 的 `length` step=4，必须满足 4n+1：

| 时长（约） | 帧数 | 公式 |
|------------|------|------|
| ~1s | 25 | 4×6+1 ← smoke test |
| ~1.7s | 41 | 4×10+1 ← 官方默认 |
| ~2.5s | 61 | 4×15+1 |
| ~5s | 121 | 4×30+1 ← 官方最优质量 |

### 运动提示词建议（Motion Prompt）

I2V 模式中，正向提示词应同时描述**内容**（画面中有什么）和**运动**（如何动）：
```
a news reporter standing on a city street, walking forward slowly,
gentle dolly push-in, natural wind, cinematic 720p
```
负向提示词使用官方 UI 原文（中文），涵盖"静止不动"、"伪影"等：
```
色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，
最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，
画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，
杂乱的背景，三条腿，背景人很多，倒着走
```

---

## 节点图结构

```
UNETLoader (wan2.2_ti2v_5B_fp16, weight_dtype=default)
    ↓ MODEL
ModelSamplingSD3 (shift=8.0)
    ↓ MODEL
                CLIPLoader (umt5_xxl_fp8_e4m3fn_scaled, type=wan)
                    ↓ CLIP (共享给正负文本)
CLIPTextEncode (正向) ──┐
CLIPTextEncode (负向) ──┤  CONDITIONING
                        ↓
LoadImage (image=__INPUT_IMAGE__, upload=image)
    ↓ IMAGE (start_image)
VAELoader (wan2.2_vae)
    ↓ VAE ──────────────────────────────────────┐
Wan22ImageToVideoLatent (start_image=↑, vae=↑, width/height/length)
    ↓ LATENT
KSampler (seed, steps=30, cfg=5, uni_pc, simple, denoise=1.0)
    ↓ LATENT
VAEDecode ← VAE (from VAELoader)
    ↓ IMAGE
SaveAnimatedWEBP (fps=24, lossless=false, quality=80)
```

**节点决策**：
- `LoadImage`（node 57）通过 `start_image` 输入接入 `Wan22ImageToVideoLatent`（node 55）。
- `SaveAnimatedWEBP`（node 28）保留，`SaveWEBM`（node 47）丢弃（同 t2v 理由）。
- `Note`（node 56）跳过。

---

## VRAM / 速度实测

| 配置 | 用时 | 备注 |
|------|------|------|
| 704×480, 25 帧, steps=30 | **40.1s** | RTX 4090 24GB，smoke test，I2V 实测 |
| 1280×704, 41 帧, steps=30 | 预估 4~7 min | 官方默认分辨率 |
| 1280×704, 121 帧, steps=30 | 预估 10~15 min | 官方最优质量 |

> I2V 比纯 T2V 略慢（start_image VAE 编码额外开销），但差异不显著。

---

## 已验证 validate.py 命令

### 步骤 1：生成测试输入图像（与目标分辨率一致）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/z_image_t2i.api.json \
  --set "POSITIVE_PROMPT=a news reporter standing on a city street, daytime, cinematic" \
  --set "NEGATIVE_PROMPT=blurry, ugly" \
  --set SEED=7 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --save comfyui/samples/ \
  --timeout 300
```

生成后（`comfyui/samples/ComfyUI_00007_.png`），复制到 ComfyUI input 目录：

```python
import shutil
shutil.copy2('comfyui/samples/ComfyUI_00007_.png', 'D:/comfyui/comfyui/input/wan_i2v_test.png')
```

### 步骤 2：Smoke test（小分辨率快速验证）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_5b_i2v.api.json \
  --set "POSITIVE_PROMPT=a news reporter standing on a city street, walking forward, cinematic camera movement" \
  --set "NEGATIVE_PROMPT=色调艳丽，过曝，静态，细节模糊不清，字幕，静止不动的画面" \
  --set SEED=42 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --set LENGTH=25 \
  --set INPUT_IMAGE=wan_i2v_test.png \
  --save comfyui/samples/ \
  --timeout 900
```

**实测结果**: SUCCESS，用时 40.1s，输出 `ComfyUI_00008_.webp`（动态 WEBP，25 帧 @24fps）

### 步骤 3：官方默认质量（生产用）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_5b_i2v.api.json \
  --set "POSITIVE_PROMPT=a news reporter standing on a city street, walking forward slowly, gentle camera push-in, cinematic 720p" \
  --set "NEGATIVE_PROMPT=色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走" \
  --set SEED=42 \
  --set WIDTH=1280 \
  --set HEIGHT=704 \
  --set LENGTH=41 \
  --set INPUT_IMAGE=wan_i2v_test.png \
  --save comfyui/samples/ \
  --timeout 900
```

> 注意：生产用时请先用 1280×704 尺寸重新生成输入图，使宽高比与 I2V 目标一致。

---

## 参数一览

| 占位符 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `__INPUT_IMAGE__` | string | — | ComfyUI input/ 目录中的文件名（必填） |
| `__POSITIVE_PROMPT__` | string | — | 内容+运动描述 |
| `__NEGATIVE_PROMPT__` | string | — | 质量负向提示 |
| `__SEED__` | int | — | 随机种子 |
| `__WIDTH__` | int | 1280 | 宽度（32 的倍数） |
| `__HEIGHT__` | int | 704 | 高度（32 的倍数） |
| `__LENGTH__` | int | 41 | 帧数（**必须为 4n+1**） |

---

## 信息来源

- ComfyUI 官方示例页: https://comfyanonymous.github.io/ComfyUI_examples/wan22/
- ComfyUI 官方文档 Wan 2.2 教程: https://docs.comfy.org/tutorials/video/wan/wan2_2
- Comfy-Org 打包模型 (HuggingFace): https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged
- Wan 2.2 官方 GitHub: https://github.com/Wan-Video/Wan2.2
- ComfyUI Wiki Wan 2.2 攻略: https://comfyui-wiki.com/en/tutorial/advanced/video/wan2.2/wan2-2
- 实测验证: RTX 4090 24GB, ComfyUI @ http://127.0.0.1:8188, 2026-06-01
