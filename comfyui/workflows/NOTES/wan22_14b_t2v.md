# wan22_14b_t2v 工作流说明

## 用途

Wan 2.2 **14B 双专家模型**文生视频（T2V）——高精度主力方案，支持电影级运动和语义遵循。
提供两个版本：

| 版本 | API 文件 | 特点 |
|------|---------|------|
| **Base** | `wan22_14b_t2v.api.json` | 20步官方默认，画质最优 |
| **LightX2V 4-step** | `wan22_14b_t2v_lightx2v.api.json` | 4步蒸馏加速 LoRA，约 2-3x 更快 |

---

## 模型信息

| 角色 | 文件名 | 路径 |
|------|--------|------|
| UNET (High Noise) | `wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors` | `D:\models\comfyui\diffusion_models\` |
| UNET (Low Noise) | `wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors` | `D:\models\comfyui\diffusion_models\` |
| Text Encoder | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `D:\models\comfyui\text_encoders\` |
| VAE | `wan_2.1_vae.safetensors` | `D:\models\comfyui\vae\` |
| LoRA (HN, lightx2v) | `wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors` | `D:\models\comfyui\loras\` |
| LoRA (LN, lightx2v) | `wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors` | `D:\models\comfyui\loras\` |

- **架构**: 14B MoE（Mixture of Experts），两个独立的专家 UNET 分别处理高噪声阶段和低噪声阶段
- **CLIP 类型**: `wan`（CLIPLoader type 参数必须填 wan）
- **VAE**: 使用 Wan 2.1 VAE（与 5B 不同，注意文件名为 `wan_2.1_vae.safetensors`）

---

## 双采样器架构（Dual-Sampler Rationale）

### 为什么用两个 UNET？

Wan 2.2 14B 采用 MoE 专家分工架构：

- **高噪声专家（High-Noise UNET）**: 负责扩散早期阶段（高噪声区间），学习全局运动轨迹、构图与结构。这一阶段噪声大、信号弱，需要对全局语义敏感的专家。
- **低噪声专家（Low-Noise UNET）**: 负责扩散后期阶段（低噪声区间），专注细节生成、纹理细化和画质提升。

两个专家在各自擅长的噪声区间分别优化，比单一 14B 全程模型有更好的专业化效果。

### 步骤分界（为什么是 step 10/20）

官方 UI graph 将 20 步均分：
- 高噪声采样器：`start_at_step=0, end_at_step=10`（前半程，step 0→10）
- 低噪声采样器：`start_at_step=10, end_at_step=10000`（后半程，step 10→20）

中间点 10/20 = 50%，即噪声调度曲线的中点。`return_with_leftover_noise=enable` 使高噪声采样器输出的带残留噪声的 latent 直接作为低噪声采样器的输入，两者无缝衔接。

---

## Base 版本参数

### 采样参数

| 参数 | 值 | 说明 |
|------|----|------|
| steps (总) | 20 | 两个采样器各用 10 步 |
| CFG | 3.5 | 官方默认 |
| Sampler | `euler` | 官方 UI graph 默认 |
| Scheduler | `simple` | Wan 2.2 推荐 |
| ModelSamplingSD3 shift | **8.0** | 官方 14B 默认值 |
| High KSampler start/end | 0 / 10 | 前半程 |
| Low KSampler start/end | 10 / 10000 | 后半程（10000=不限制） |
| High add_noise | enable | 从纯噪声开始 |
| Low add_noise | disable | 延续高噪声输出 |
| High return_leftover_noise | enable | 携带剩余噪声传给低噪声 |

### 视频参数（官方默认，生产用）

| 参数 | 官方默认 | 烟雾测试 | 说明 |
|------|----------|----------|------|
| 分辨率 | 1280×704 | 704×480 | 720p 官方最优 |
| 帧数 (length) | 57 | 25 | 必须为 4n+1 |
| FPS | 16 | 16 | SaveAnimatedWEBP fps |
| 输出格式 | AnimatedWEBP | — | lossless=false, quality=80 |

**帧数规则**: `EmptyHunyuanLatentVideo` 的 `length` step=4，必须满足 **4n+1**（如 25、57、81、121）。

---

## LightX2V 4-step 版本参数

### 研究来源

- LightX2V 官方 config: `wan_moe_t2v_distill.json` → `infer_steps=4`, `boundary_step_index=2`, `sample_shift=5.0`, `enable_cfg=false`
- HuggingFace 讨论 (Kijai/X-niper): 4 步总计，高低各 2 步；shift=5；CFG=1；euler/simple；LoRA strength=1.0
- 本地实测：RTX 4090 24GB，704×480×25帧，34.1s 通过

### 与 Base 的差异

| 参数 | Base | LightX2V 4-step | 说明 |
|------|------|-----------------|------|
| steps (总) | 20 | **4** | 蒸馏大幅减步 |
| CFG | 3.5 | **1.0** | 蒸馏模型禁用 CFG（≈1.0即关闭） |
| shift | 8.0 | **5.0** | 官方 distill config 值 |
| High start/end | 0 / 10 | **0 / 2** | 4步中前2步 |
| Low start/end | 10 / 10000 | **2 / 10000** | 4步中后2步 |
| LoRA (High) | 无 | `..._high_noise.safetensors`, strength=1.0 | UNETLoader → LoRA → ModelSamplingSD3 |
| LoRA (Low) | 无 | `..._low_noise.safetensors`, strength=1.0 | 同上 |

### 节点插入位置

```
UNETLoader (high) → LoraLoaderModelOnly (HN, str=1.0) → ModelSamplingSD3 (shift=5) → KSamplerAdvanced (4步, 0→2)
UNETLoader (low)  → LoraLoaderModelOnly (LN, str=1.0) → ModelSamplingSD3 (shift=5) → KSamplerAdvanced (4步, 2→∞)
```

---

## 节点图结构

### Base 版本

```
UNETLoader (high_noise_14B)         UNETLoader (low_noise_14B)
    ↓ MODEL                              ↓ MODEL
ModelSamplingSD3 (shift=8)          ModelSamplingSD3 (shift=8)
    ↓ MODEL                              ↓ MODEL
              CLIPLoader (umt5_xxl, type=wan)
                  ↓ CLIP (共享)
CLIPTextEncode (正) ──┐          CLIPTextEncode (负) ──┐
                       └──────────────────────────────┤ CONDITIONING
                                                       ↓
EmptyHunyuanLatentVideo (W×H×L) → KSamplerAdvanced HIGH (step=20,cfg=3.5,0→10,leftover=on)
                                       ↓ LATENT (含残留噪声)
                              KSamplerAdvanced LOW (step=20,cfg=3.5,10→∞,add_noise=off)
                                       ↓ LATENT
VAELoader (wan_2.1_vae) ──────── VAEDecode
                                       ↓ IMAGE
                              SaveAnimatedWEBP (fps=16)
```

### LightX2V 版本（差异部分）

在每个 UNETLoader 和 ModelSamplingSD3 之间插入 `LoraLoaderModelOnly`，并将 shift 改为 5.0，steps=4，cfg=1.0，步骤分界 2/4。

---

## VRAM / 速度实测

| 配置 | 用时 | 备注 |
|------|------|------|
| Base, 704×480, 25帧, steps=20 | **84.3s** | RTX 4090 24GB fp8 烟雾测试 |
| LightX2V, 704×480, 25帧, steps=4 | **34.1s** | RTX 4090 24GB fp8 烟雾测试 |
| Base, 1280×704, 57帧, steps=20 | 预估 10~15 min | 官方默认分辨率 |
| LightX2V, 1280×704, 57帧, steps=4 | 预估 4~6 min | 加速版 |

- **2.5x 加速**（704×480×25帧烟雾测试比值）
- 双模型同时加载 14B fp8 × 2 ≈ 占满 24GB 显卡，不可同时运行其他重型推理
- 若遇 OOM 可降低分辨率/帧数，不建议降低 weight_dtype（fp8 已是压缩版）

---

## 何时使用哪个版本

| 场景 | 推荐版本 | 理由 |
|------|---------|------|
| 新闻 B 卷素材生产、批量生成 | LightX2V | 速度快 2-3x，质量可接受 |
| 主打镜头、关键封面视频 | Base | 画质更优，运动细节更丰富 |
| 快速迭代 prompt/构图验证 | LightX2V | 34s 快速反馈 |
| 长视频（length≥81）| Base | 长时序下 4-step 可能有伪影 |

---

## 提示词建议（新闻视频场景）

**正向**（Positive）：
```
a professional news anchor delivering breaking news in a sleek modern studio,
subtle camera push-in, broadcast lighting, sharp focus, cinematic 720p, photorealistic
```

**负向**（官方 UI graph 原文）：
```
色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，
最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，
画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，
杂乱的背景，三条腿，背景人很多，倒着走
```

---

## 已验证 validate.py 命令

### Base — 烟雾测试（已实测 SUCCESS 84.3s）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_14b_t2v.api.json \
  --set "POSITIVE_PROMPT=a news anchor delivering breaking news in a modern studio, cinematic lighting, professional broadcast" \
  --set "NEGATIVE_PROMPT=static, blurry, low quality" \
  --set SEED=42 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --set LENGTH=25 \
  --save comfyui/samples/ \
  --timeout 1200
```

**输出**: `comfyui/samples/ComfyUI_00009_.webp`

### LightX2V 4-step — 烟雾测试（已实测 SUCCESS 34.1s）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_14b_t2v_lightx2v.api.json \
  --set "POSITIVE_PROMPT=a news anchor delivering breaking news in a modern studio, cinematic lighting, professional broadcast" \
  --set "NEGATIVE_PROMPT=static, blurry, low quality" \
  --set SEED=42 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --set LENGTH=25 \
  --save comfyui/samples/ \
  --timeout 600
```

**输出**: `comfyui/samples/ComfyUI_00010_.webp`

### Base — 官方默认质量（生产用）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_14b_t2v.api.json \
  --set "POSITIVE_PROMPT=a news anchor delivering breaking news in a modern studio, cinematic lighting, professional broadcast" \
  --set "NEGATIVE_PROMPT=色调艳丽，过曝，静态，细节模糊不清，字幕，静止不动的画面" \
  --set SEED=42 \
  --set WIDTH=1280 \
  --set HEIGHT=704 \
  --set LENGTH=57 \
  --save comfyui/samples/ \
  --timeout 1200
```

---

## 信息来源

- LightX2V 官方 GitHub: https://github.com/ModelTC/LightX2V
- LightX2V distill config (T2V): https://github.com/ModelTC/LightX2V/blob/main/configs/wan22/wan_moe_t2v_distill.json
- LightX2V HuggingFace LoRA: https://huggingface.co/lightx2v/Wan2.2-Distill-Loras
- Kijai/WanVideo_comfy 讨论 (4steps total/per model): https://huggingface.co/Kijai/WanVideo_comfy/discussions/59
- Wan2.2 Lightning 讨论 (shift=5, cfg=1): https://huggingface.co/lightx2v/Wan2.2-Lightning/discussions/5
- ComfyUI 官方 Wan2.2 教程: https://docs.comfy.org/tutorials/video/wan/wan2_2
- ComfyUI Wan2.2 LightX2V 公告: https://blog.comfy.org/p/comfyui-wan22-fun-inp-support
- 实测验证: RTX 4090 24GB, ComfyUI @ http://127.0.0.1:8188, 2026-06-01
