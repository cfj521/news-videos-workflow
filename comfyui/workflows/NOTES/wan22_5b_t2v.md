# wan22_5b_t2v 工作流说明

## 用途

Wan 2.2 5B TI2V（Text-and-Image-to-Video）的**纯文生视频**模式。
不传入 `start_image` 时，`Wan22ImageToVideoLatent` 仅以文本提示驱动，即文生视频 (T2V)。
适用于新闻视频 B 卷素材、场景/情绪镜头自动化批量生成。

---

## 模型信息

| 角色 | 文件名 | 路径 |
|------|--------|------|
| UNET (扩散模型) | `wan2.2_ti2v_5B_fp16.safetensors` | `D:\models\comfyui\diffusion_models\` |
| Text Encoder | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `D:\models\comfyui\text_encoders\` |
| VAE | `wan2.2_vae.safetensors` | `D:\models\comfyui\vae\` |

- **架构**: 5B 密集参数 Wan 2.2 模型，同时支持 T2V 和 I2V（TI2V = Text-and-Image-to-Video）
- **CLIP 类型**: 必须设为 `wan`（CLIPLoader type 参数）
- **VRAM**: fp16 全精度约需 24GB；RTX 4090 刚好可运行，接近极限

---

## 研究发现（关键参数）

### 采样参数（官方 UI graph 默认，已实测确认）

| 参数 | 值 | 说明 |
|------|----|------|
| Steps | 30 | 官方默认，质量与速度平衡 |
| CFG | 5.0 | 官方默认 |
| Sampler | `uni_pc` | 官方默认 |
| Scheduler | `simple` | Wan 2.2 推荐；使 ModelSamplingSD3 噪声曲线生效 |
| Denoise | 1.0 | 完整去噪（T2V 标准） |
| ModelSamplingSD3 shift | 8.0 | 官方 5B 默认值（UI graph）；调整噪声分布 |

### 视频参数

| 参数 | 官方默认 | 说明 |
|------|----------|------|
| 分辨率 | 1280×704 | 720p，官方最优；Note 节点注明 |
| 帧数 (length) | 41 | 官方默认；Note 建议 121 为最佳 |
| FPS | 24 | 720p@24fps |
| 输出格式 | AnimatedWEBP | lossless=false, quality=80 |

### 帧数规则：必须为 4n+1

`Wan22ImageToVideoLatent` 的 `length` 参数 step=4，即帧数必须满足 **4n+1**：

| 时长（约） | 帧数 | 公式 |
|------------|------|------|
| ~1s | 25 | 4×6+1 |
| ~1.7s | 41 | 4×10+1 ← 官方默认 |
| ~2.5s | 61 | 4×15+1 |
| ~3s | 81 | 4×20+1 |
| ~5s | 121 | 4×30+1 ← 官方最优 |

传入非 4n+1 的值将导致节点报错或输出异常。

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
VAELoader (wan2.2_vae)
    ↓ VAE ──────────────────────────────┐
Wan22ImageToVideoLatent (width/height/length, no start_image → T2V)
    ↓ LATENT
KSampler (seed, steps=30, cfg=5, uni_pc, simple, denoise=1.0)
    ↓ LATENT
VAEDecode ← VAE (from VAELoader)
    ↓ IMAGE
SaveAnimatedWEBP (fps=24, lossless=false, quality=80)
```

**节点决策**：
- UI graph 同时有 `SaveAnimatedWEBP`（node 28）和 `SaveWEBM`（node 47），两者均 active (mode=0)。
  API 文件只保留 `SaveAnimatedWEBP`（兼容性更广，validate.py 能检测到 images 类型输出）。
  `SaveWEBM` 丢弃——避免重复写文件，且 validate.py 的 `/history` 解析通过 `images` key 读取 WEBP，若只有 WEBM 会走"无媒体输出"分支。
- `Note`（node 56）跳过，不属于 API 节点。
- `Wan22ImageToVideoLatent` 的 `start_image` 输入 UI 中为 null（T2V 模式），API 中省略该 key。

---

## VRAM / 速度实测

| 配置 | 用时 | 备注 |
|------|------|------|
| 704×480, 25 帧, steps=30 | 26.1s | RTX 4090 24GB，smoke test |
| 1280×704, 41 帧, steps=30 | 预估 3~6 min | 官方默认分辨率 |
| 1280×704, 121 帧, steps=30 | 预估 8~12 min | 官方最优质量 |

- fp16 模型在 24GB 显卡上接近满载，不要同时运行其他重型推理任务。
- 若遇 OOM，可把 `weight_dtype` 改为 `fp8_e4m3fn` 降低显存占用（需评估质量影响）。

---

## 提示词建议（新闻视频场景）

**正向**（Positive）：
```
a professional news reporter standing on a busy city street, speaking confidently to camera,
gentle dolly push-in, cinematic 720p, natural daylight, sharp focus
```

**负向**（Negative，官方 UI graph 原文）：
```
色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，
最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，
画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，
杂乱的背景，三条腿，背景人很多，倒着走
```

---

## 已验证 validate.py 命令

### Smoke test（小分辨率，快速验证）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_5b_t2v.api.json \
  --set "POSITIVE_PROMPT=a news reporter speaking to camera on a city street, gentle camera push-in" \
  --set "NEGATIVE_PROMPT=static, blurry" \
  --set SEED=42 \
  --set WIDTH=704 \
  --set HEIGHT=480 \
  --set LENGTH=25 \
  --save comfyui/samples/ \
  --timeout 900
```

**实测结果**: SUCCESS，用时 26.1s，输出 `ComfyUI_00006_.webp`（动态 WEBP）

### 官方默认质量（生产用）

```bash
python comfyui/validate.py \
  --api comfyui/workflows/api/wan22_5b_t2v.api.json \
  --set "POSITIVE_PROMPT=a news reporter speaking to camera on a city street, gentle camera push-in" \
  --set "NEGATIVE_PROMPT=色调艳丽，过曝，静态，细节模糊不清，字幕，静止不动的画面" \
  --set SEED=42 \
  --set WIDTH=1280 \
  --set HEIGHT=704 \
  --set LENGTH=41 \
  --save comfyui/samples/ \
  --timeout 900
```

---

## 信息来源

- ComfyUI 官方示例页: https://comfyanonymous.github.io/ComfyUI_examples/wan22/
- ComfyUI 官方文档 Wan 2.2 教程: https://docs.comfy.org/tutorials/video/wan/wan2_2
- Comfy-Org 打包模型 (HuggingFace): https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged
- Wan 2.2 官方 GitHub: https://github.com/Wan-Video/Wan2.2
- ComfyUI Wiki Wan 2.2 攻略: https://comfyui-wiki.com/en/tutorial/advanced/video/wan2.2/wan2-2
- 实测验证: RTX 4090 24GB, ComfyUI @ http://127.0.0.1:8188, 2026-06-01
