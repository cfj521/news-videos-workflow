# ltx23_t2v 工作流说明

## 用途

LTX-2.3 **22B 文生视频（T2V）**——Lightricks 最新一代音视频联合生成模型，基于 Gemma 3 12B 文本编码器 + 蒸馏 LoRA 4步推理。

---

## 节点链（Node Chain）

```
LTXAVTextEncoderLoader         # 加载 Gemma 3 12B (fp8) + LTX checkpoint → CLIP
CLIPTextEncode(positive)       # 正向提示词 → CONDITIONING
CLIPTextEncode(negative)       # 负向提示词 → CONDITIONING
LTXVConditioning(fps=25)       # 附加帧率信息 → (positive, negative) CONDITIONING
CheckpointLoaderSimple         # LTX-2.3 22B fp8 → MODEL, CLIP, VAE
LTXVAudioVAELoader             # 同一个 checkpoint → Audio VAE
LoraLoaderModelOnly            # 蒸馏 LoRA → MODEL
EmptyLTXVLatentVideo(W×H×L)    # 空白视频 latent
EmptyImage(W×H)                # 占位图（T2V 时 bypass=true）
LTXVImgToVideoInplace(bypass)  # bypass=true = 纯 T2V，不需要图片条件
LTXVEmptyLatentAudio(L, fps)   # 空白音频 latent
LTXVConcatAVLatent             # 拼接视频+音频 latent → AV_LATENT
CFGGuider(cfg=1.0)             # 引导器（蒸馏模型 cfg=1 无需 STGGuider）
RandomNoise(seed)              # 噪声
KSamplerSelect(euler)          # 采样器
ManualSigmas("0.85, 0.725, 0.421875, 0.0")  # 4步蒸馏 sigma 表
SamplerCustomAdvanced          # 采样 → (output, denoised_output) LATENT
LTXVSeparateAVLatent           # 分离 → video_latent, audio_latent
VAEDecodeTiled(tile=512)       # 解码 video_latent → IMAGE 帧序列
CreateVideo(fps=25)            # 帧序列 → VIDEO
SaveVideo                      # 输出 MP4
```

**说明**：本工作流为**单阶段**（跳过空间上采样）。官方模板使用两阶段：先生成低分辨率，再经 `LTXVLatentUpsampler` 上采样 2× 后细化。单阶段可直接生成目标分辨率，速度更快，效果基本等同。

---

## 模型文件

| 角色 | 实际使用文件 | 官方模板期望文件 |
|------|------------|----------------|
| 主模型（checkpoint） | `ltx-2.3-22b-dev-fp8.safetensors` | `ltx-2.3-22b-dev-fp8.safetensors` ✅ 一致 |
| 蒸馏 LoRA | `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` | `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors` ⚠️ 不同 |
| 文本编码器（Gemma） | `gemma_3_12B_it_fp4_mixed.safetensors`（本地重打包） | `gemma_3_12B_it_fp4_mixed.safetensors` ⚠️ 不同 |
| Audio VAE | `ltx-2.3-22b-dev-fp8.safetensors`（同主模型文件） | `ltx-2.3-22b-dev-fp8.safetensors` ✅ 一致 |
| 空间上采样器 | **跳过**（单阶段） | `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` |

---

## Gemma 文本编码器特殊处理

**问题**：官方模板需要 `gemma_3_12B_it_fp4_mixed.safetensors`（单文件 9.5GB fp4 量化），而我们只下载了 HuggingFace 原始 5 分片 BF16 格式（`gemma-3-12b-it-qat-q4_0-unquantized/model-0000X-of-00005.safetensors`，共 22.7GB）。

**限制**：
1. `LTXAVTextEncoderLoader` 只接受单文件，不能一次加载 5 个分片
2. HF 分片格式的 key 前缀是 `language_model.model.layers.X...`，而 ComfyUI 期望 `model.layers.X...`
3. HF 分片不包含 `spiece_model` tokenizer tensor（ComfyUI 用它初始化 SentencePiece）
4. 22.7GB BF16 + 11GB LTX fp8 = 33.7GB，超出 24GB 显存

**解决方案**：本地重打包生成 `gemma_3_12B_it_fp4_mixed.safetensors`（13.2GB）：
- 读取全部 5 个 HF 分片，key 前缀 `language_model.` → 去掉（`model.layers.X...`）
- 线性层权重（2D BF16）→ fp8_e4m3fn 量化（有损，scale=1.0）
- 非线性层（LayerNorm、Embedding 等 1D/非weight BF16）→ 保持 BF16
- 添加 `spiece_model` tensor（从 `tokenizer.model` 读取）
- 为每个线性层添加 `{layer}.weight_scale`（1.0 float32）和 `{layer}.comfy_quant` 元数据
- ComfyUI 的 `detect_layer_quantization` 读到 `comfy_quant` 后启用 mixed_ops 模式，加载时自动 dequantize

重打包脚本已嵌入工作流构建过程（约 25 秒），无需重复运行。

**注意**：scale=1.0 是近似处理（非精确校准）。如需最佳画质，应下载官方 `gemma_3_12B_it_fp4_mixed.safetensors`（见下节）。

---

## 与官方模板的差异

| 差异点 | 本工作流 | 官方模板 |
|--------|---------|---------|
| Gemma 加载节点 | `LTXAVTextEncoderLoader` | `LTXAVTextEncoderLoader` |
| Gemma 文件 | 本地重打包 fp8（重映射 key）| 官方 fp4 单文件 |
| LoRA | `ltx-2.3-22b-distilled-lora-384-1.1`（下载的版本）| `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16` |
| 引导器 | `CFGGuider(cfg=1.0)` | `STGGuiderAdvanced`（用于精细控制） |
| 上采样 | **单阶段，无上采样** | `LTXVLatentUpsampler` 2× + 细化 |
| 音频输出 | LTXVSeparateAVLatent → VAEDecodeTiled（跳过音频解码） | 完整音频 VAE 解码 → CreateVideo |

---

## 推荐配置

| 参数 | 快速测试 | 新闻视频 | 说明 |
|------|---------|---------|------|
| WIDTH | 512 | 704 | 必须是 32 的倍数 |
| HEIGHT | 320 | 480 | 必须是 32 的倍数 |
| LENGTH | 17 | 25-97 | 必须是 8n+1（如 9/17/25/33...97） |
| SEED | 任意 | 任意 | 固定可复现 |
| sigmas | `0.85, 0.725, 0.421875, 0.0` | 同左 | 4步蒸馏专用 |
| fps | 25 | 25 | LTX 推荐 25fps |
| cfg | 1.0 | 1.0 | 蒸馏模型必须 1.0 |

---

## 验证记录

```
# 快速测试（512×320, 17帧）
python comfyui/validate.py \
  --api comfyui/workflows/api/ltx23_t2v.api.json \
  --set "POSITIVE_PROMPT=a news anchor presenting in a modern television studio, cinematic lighting, professional" \
  --set "NEGATIVE_PROMPT=blurry, ugly, distorted, cartoon, watermark" \
  --set SEED=42 --set WIDTH=512 --set HEIGHT=320 --set LENGTH=17 \
  --save comfyui/samples/ --timeout 1200
# → SUCCESS 68.2s

# 新闻视频分辨率（704×480, 25帧）
python comfyui/validate.py \
  --api comfyui/workflows/api/ltx23_t2v.api.json \
  --set "POSITIVE_PROMPT=a professional news anchor presenting in a modern television studio, cinematic lighting, detailed, 4k quality" \
  --set "NEGATIVE_PROMPT=blurry, ugly, distorted, cartoon, watermark, low quality" \
  --set SEED=12345 --set WIDTH=704 --set HEIGHT=480 --set LENGTH=25 \
  --save comfyui/samples/ --timeout 1200
# → SUCCESS 60.3s
```

---

## 获取官方 Gemma 文件（可选，提升质量）

若要使用官方 `gemma_3_12B_it_fp4_mixed.safetensors`（9.5GB，精度更高）：

```powershell
# 需要 HuggingFace 账号（免登录公开文件，via hf-mirror）
$url = "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors"
$out = "D:\models\comfyui\text_encoders\gemma_3_12B_it_fp4_mixed.safetensors"
curl.exe -L -C - -o $out $url --progress-bar
```

下载后修改 `ltx23_t2v.api.json` 中的 `text_encoder` 字段为 `gemma_3_12B_it_fp4_mixed.safetensors`，并删除 `gemma_3_12B_it_fp4_mixed.safetensors`。

---

## 获取官方 LoRA（可选）

官方 LoRA `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors` 可从 [Comfy-Org/ltx-2.3](https://huggingface.co/Comfy-Org/ltx-2.3) 下载。当前使用的 `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` 是 Lightricks 官方分发版，效果等同。

---

## 生成的附属文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `gemma_3_12B_it_fp4_mixed.safetensors` | `D:\models\comfyui\text_encoders\` | 重打包的 Gemma fp8，本工作流专用 |
| `gemma3_12b_spiece_only.safetensors` | `D:\models\comfyui\text_encoders\` | 仅含 tokenizer（调试用，可删除） |
| `gemma3_12b_fp8_scaled.safetensors` | `D:\models\comfyui\text_encoders\` | 早期尝试版本（无 weight_scale，无法使用，可删除） |
