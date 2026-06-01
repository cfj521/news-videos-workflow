# LTX 2.3 图生视频（ltx23_i2v）

LTX 2.3 22B 图生视频，复用 t2v 的整条链路（见 `ltx23_t2v.md`），仅把"空文生视频"换成"起始图条件"。需自定义节点 `ComfyUI-LTXVideo`。

## 模型（D:/models/comfyui）

- checkpoint `ltx-2.3-22b-dev-fp8.safetensors`（22B，29GB）
- 文本编码器 `gemma_3_12B_it_fp4_mixed.safetensors`（官方 fp4，9.45GB；**比早期自量化 fp8 小，已实测消除爆显存抖动**）
- 蒸馏 LoRA `ltx-2.3-22b-distilled-lora-384-1.1.safetensors`（4 步）

## 与 t2v 的差异

- 用 `LoadImage`（`__INPUT_IMAGE__`，读 ComfyUI `input/` 目录）→ `LTXVImgToVideo`（width/height/length/strength=1.0）注入起始图条件，替换 t2v 里被 bypass 的空图直通。
- 其余（Gemma 编码、AV latent 拼接、CFGGuider cfg=1、ManualSigmas 4 步、SamplerCustomAdvanced、VAEDecodeTiled、CreateVideo→SaveVideo）与 t2v 完全一致。

## 占位符

`__POSITIVE_PROMPT__ __NEGATIVE_PROMPT__ __SEED__ __WIDTH__ __HEIGHT__ __LENGTH__ __INPUT_IMAGE__`
输入图宽高比应与 WIDTH/HEIGHT 一致，避免编码前 resize 形变。

## 已验证命令（live ComfyUI 实测）

```
python comfyui/validate.py --api comfyui/workflows/api/ltx23_i2v.api.json \
  --set "POSITIVE_PROMPT=the reporter in the photo starts speaking, subtle natural motion, gentle camera movement" \
  --set "NEGATIVE_PROMPT=blurry, ugly, deformed, low quality, watermark" \
  --set SEED=42 --set WIDTH=704 --set HEIGHT=480 --set LENGTH=49 \
  --set INPUT_IMAGE=wan_i2v_test.png --save comfyui/samples/ --timeout 900
```

结果：SUCCESS **51s**（704×480×49 帧，RTX 4090 24GB，干净串行）→ `comfyui/samples/ltx23_i2v.mp4`。

## 显存与注意事项

- LTX 22B 主模型 29GB > 24GB 显存，必走 offload；**务必单任务串行**，多个 LTX 任务并发或残留会触发严重抖动（曾卡 20+ 分钟并拖崩 ComfyUI）。
- fp4 Gemma（9.45GB）相比自量化 fp8（13.2GB）省 ~3.7GB，是稳定跑通的关键之一。
- 单阶段（未接空间上采样）；如需更锐利可加 `LTXVLatentUpsampler` + spatial-upscaler-x2-1.1（已下载）走两阶段，但更吃显存/时间。
