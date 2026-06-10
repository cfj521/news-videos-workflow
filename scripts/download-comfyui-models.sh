#!/usr/bin/env bash
# ============================================================================
# ComfyUI 模型统一下载脚本（Linux / WSL / bash）—— 全部走 ModelScope，无任何 HF 源
# 已存在的文件自动跳过，可重复运行。PowerShell 版同功能：download-comfyui-models.ps1
#
# 覆盖（对齐 comfyui/workflows/api/*.json，全部默认下载）：
#   图片  z_image_turbo + Qwen-Image
#   视频  Wan 2.2  5B TI2V + 14B I2V/T2V + 4步Lightning LoRA
#   视频  LTX 2.3  api 工作流所需的 dev-fp8 + Gemma(fp4) + 蒸馏LoRA 384-1.1
#
# 前置依赖：pip install modelscope
#
# 用法：
#   bash scripts/download-comfyui-models.sh
#   bash scripts/download-comfyui-models.sh --models-dir /data/models/comfyui
#
# 体积参考：图片+Wan ≈ 122GB + LTX ≈ 38GB ≈ 160GB 全量。请确保磁盘空间充足。
# LTX 工作流另需自定义节点 ComfyUI-LTXVideo（ComfyUI Manager 安装）。
# ============================================================================
set -euo pipefail

MODELS_DIR="${HOME}/models/comfyui"   # ComfyUI 模型根目录

while [[ $# -gt 0 ]]; do
    case "$1" in
        --models-dir) MODELS_DIR="$2"; shift 2 ;;
        -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $1（用 --help 看用法）" >&2; exit 2 ;;
    esac
done

STAGING="$(dirname "$MODELS_DIR")/_staging"   # ModelScope 下载暂存区

# 每个条目一行："仓库|文件名|子目录"。--include 用文件名匹配（兼容仓库根与 split_files/ 子目录）。
ITEMS=(
    # ---- 图片：z_image_turbo ----
    "Comfy-Org/z_image_turbo|z_image_turbo_bf16.safetensors|diffusion_models"
    "Comfy-Org/z_image_turbo|qwen_3_4b.safetensors|text_encoders"
    "Comfy-Org/z_image_turbo|ae.safetensors|vae"
    # ---- 图片：Qwen-Image（20B fp8，中文/版面最强）----
    "Comfy-Org/Qwen-Image_ComfyUI|qwen_image_fp8_e4m3fn.safetensors|diffusion_models"
    "Comfy-Org/Qwen-Image_ComfyUI|qwen_2.5_vl_7b_fp8_scaled.safetensors|text_encoders"
    "Comfy-Org/Qwen-Image_ComfyUI|qwen_image_vae.safetensors|vae"
    # ---- 视频：Wan 2.2 5B TI2V ----
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_ti2v_5B_fp16.safetensors|diffusion_models"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|umt5_xxl_fp8_e4m3fn_scaled.safetensors|text_encoders"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_vae.safetensors|vae"
    # ---- 视频：Wan 2.2 14B I2V + 4步Lightning LoRA ----
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors|diffusion_models"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors|diffusion_models"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors|loras"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors|loras"
    # ---- 视频：Wan 2.2 14B T2V + 4步Lightning LoRA ----
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors|diffusion_models"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors|diffusion_models"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors|loras"
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors|loras"
    # ---- Wan 14B 共用 VAE ----
    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|wan_2.1_vae.safetensors|vae"
)

# ---- LTX 2.3：仅 api 工作流（comfyui/workflows/api/ltx23_*.api.json）所需的 3 个文件 ----
ITEMS+=(
    "Lightricks/LTX-2.3-fp8|ltx-2.3-22b-dev-fp8.safetensors|checkpoints"
    "Comfy-Org/ltx-2|gemma_3_12B_it_fp4_mixed.safetensors|text_encoders"
    "Lightricks/LTX-2.3|ltx-2.3-22b-distilled-lora-384-1.1.safetensors|loras"
)

if ! command -v modelscope >/dev/null 2>&1; then
    echo -e "\n✗ 未找到 modelscope CLI。请先： pip install modelscope" >&2
    exit 1
fi

echo "模型目录: $MODELS_DIR"

idx=0
total=${#ITEMS[@]}
for item in "${ITEMS[@]}"; do
    idx=$((idx + 1))
    IFS='|' read -r repo file dir <<< "$item"
    target_dir="$MODELS_DIR/$dir"
    target="$target_dir/$file"
    mkdir -p "$target_dir"
    echo -e "\n[ModelScope $idx/$total] $file"
    if [[ -f "$target" ]]; then echo "  已存在，跳过"; continue; fi

    stage="$STAGING/${repo//\//_}"
    modelscope download --model "$repo" --include "*$file" --local_dir "$stage"

    # 从暂存区按精确文件名找出来，移到正式目录（扁平化）
    src="$(find "$stage" -type f -name "$file" 2>/dev/null | head -n1 || true)"
    if [[ -n "$src" ]]; then
        mv -f "$src" "$target"
        echo "  完成 -> $target ($(du -h "$target" | cut -f1))"
    else
        echo "  ✗ 暂存区未找到 $file，请确认仓库内文件名是否变化" >&2
    fi
done
[[ -d "$STAGING" ]] && rm -rf "$STAGING"

echo -e "\n========== 完成，模型清单 =========="
echo "模型目录: $MODELS_DIR"
find "$MODELS_DIR" -type f -printf '  %p\t%s bytes\n' 2>/dev/null | sed "s#$MODELS_DIR#.#"
echo -e "\n把 ComfyUI 的 extra_model_paths.yaml 的 base_path 指向 $MODELS_DIR，重启 ComfyUI 即可识别。"
echo "LTX 工作流另需自定义节点 ComfyUI-LTXVideo（ComfyUI Manager 安装）。"
