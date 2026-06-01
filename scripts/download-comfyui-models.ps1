# ============================================================================
# ComfyUI 模型统一下载脚本（24GB 显存配置）—— 全部走 ModelScope，无任何 HF 源
# 目标目录: D:\models\comfyui    （已存在的文件自动跳过，可重复运行）
#
# 覆盖：
#   图片  z_image_turbo + Qwen-Image
#   视频  Wan 2.2  5B TI2V + 14B I2V/T2V + 4步Lightning LoRA
#   视频  LTX 2.3  主模型 + 上采样x2 + 蒸馏LoRA + Gemma(fp4) 文本编码器
#
# 前置依赖：
#   pip install modelscope          # 全部下载均走 ModelScope
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/download-comfyui-models.ps1
#
# 全量约 180GB（图片~47 / Wan 5B~17 + 14B~58 / LTX 主29+Gemma9.5+LoRA7.6+上采样1.3）。请确保磁盘空间充足。
# ============================================================================

$ErrorActionPreference = "Stop"

$ComfyModels = "D:\models\comfyui"      # ComfyUI 模型根目录
$Staging     = "D:\models\_staging"      # ModelScope 下载暂存区（下完挑出文件移到正式目录）

foreach ($d in @("diffusion_models", "text_encoders", "vae", "loras", "checkpoints", "latent_upscale_models")) {
    New-Item -ItemType Directory -Force -Path "$ComfyModels\$d" | Out-Null
}

# ============================================================================
# 全部模型（ModelScope）—— 图片 + Wan 2.2 + LTX 2.3
# 仓库均为 modelscope.cn 上的同名仓库；--include 用文件名匹配（兼容仓库根与 split_files/ 子目录）
# ============================================================================
$msItems = @(
    # ---- z_image_turbo（图片：6B，8步，中英文字都行）----
    @{ Repo = "Comfy-Org/z_image_turbo";      File = "z_image_turbo_bf16.safetensors";        Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/z_image_turbo";      File = "qwen_3_4b.safetensors";                 Dir = "text_encoders" },
    @{ Repo = "Comfy-Org/z_image_turbo";      File = "ae.safetensors";                        Dir = "vae" },

    # ---- Qwen-Image（图片：20B fp8，中文/版面最强；24G 偏紧但可跑）----
    @{ Repo = "Comfy-Org/Qwen-Image_ComfyUI"; File = "qwen_image_fp8_e4m3fn.safetensors";      Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/Qwen-Image_ComfyUI"; File = "qwen_2.5_vl_7b_fp8_scaled.safetensors";  Dir = "text_encoders" },
    @{ Repo = "Comfy-Org/Qwen-Image_ComfyUI"; File = "qwen_image_vae.safetensors";             Dir = "vae" },

    # ---- Wan 2.2 5B TI2V（视频：24G 干净适配）----
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_ti2v_5B_fp16.safetensors";        Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"; Dir = "text_encoders" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_vae.safetensors";                 Dir = "vae" },

    # ---- Wan 2.2 14B I2V（图生视频）+ 4步Lightning LoRA ----
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors";            Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors";             Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors";   Dir = "loras" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors";    Dir = "loras" },

    # ---- Wan 2.2 14B T2V（文生视频）+ 4步Lightning LoRA ----
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors";            Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors";             Dir = "diffusion_models" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"; Dir = "loras" },
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors";  Dir = "loras" },

    # ---- Wan 14B 共用 VAE ----
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan_2.1_vae.safetensors";                                     Dir = "vae" },

    # ---- LTX 2.3（视频：22B，需 ComfyUI-LTXVideo 自定义节点）----
    @{ Repo = "Lightricks/LTX-2.3-fp8"; File = "ltx-2.3-22b-dev-fp8.safetensors";               Dir = "checkpoints" },
    @{ Repo = "Comfy-Org/ltx-2";        File = "gemma_3_12B_it_fp4_mixed.safetensors";          Dir = "text_encoders" },
    @{ Repo = "Lightricks/LTX-2.3";     File = "ltx-2.3-22b-distilled-lora-384-1.1.safetensors"; Dir = "loras" },
    @{ Repo = "Lightricks/LTX-2.3";     File = "ltx-2.3-spatial-upscaler-x2-1.0.safetensors";   Dir = "latent_upscale_models" },
    @{ Repo = "Lightricks/LTX-2.3";     File = "ltx-2.3-temporal-upscaler-x2-1.0.safetensors";  Dir = "latent_upscale_models" }
)

if (-not (Get-Command modelscope -ErrorAction SilentlyContinue)) {
    Write-Host "`n✗ 未找到 modelscope CLI。请先： pip install modelscope" -ForegroundColor Red
    exit 1
}

$idx = 0
foreach ($it in $msItems) {
    $idx++
    $target = Join-Path "$ComfyModels\$($it.Dir)" $it.File
    Write-Host "`n[ModelScope $idx/$($msItems.Count)] $($it.File)" -ForegroundColor Cyan
    if (Test-Path $target) { Write-Host "  已存在，跳过" -ForegroundColor DarkGray; continue }

    $stage = Join-Path $Staging ($it.Repo -replace "/", "_")
    # --include 用文件名匹配（无论它在仓库根还是 split_files/ 子目录下都能命中）
    modelscope download --model $it.Repo --include "*$($it.File)" --local_dir $stage

    # 从暂存区按精确文件名找出来，移到正式目录（扁平化）
    $src = Get-ChildItem -Path $stage -Recurse -Filter $it.File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($src) {
        Move-Item -Force -Path $src.FullName -Destination $target
        $sizeGB = [math]::Round((Get-Item $target).Length / 1GB, 2)
        Write-Host "  完成 -> $target  (${sizeGB}GB)" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 暂存区未找到 $($it.File)，请确认仓库内文件名是否变化" -ForegroundColor Red
    }
}
if (Test-Path $Staging) { Remove-Item -Recurse -Force -Path $Staging -ErrorAction SilentlyContinue }

# ============================================================================
# 汇总
# ============================================================================
Write-Host "`n========== 完成，模型清单 ==========" -ForegroundColor Green
Write-Host "模型目录: $ComfyModels"
Get-ChildItem -Recurse -File -Path $ComfyModels | ForEach-Object {
    $size = [math]::Round($_.Length / 1GB, 2)
    Write-Host ("  {0,-60} {1}GB" -f $_.FullName.Replace($ComfyModels, "."), $size)
}
Write-Host "`nextra_model_paths.yaml 已统一为 comfyui_central 块（base_path: D:/models/comfyui/）。下完重启 ComfyUI 即可识别。" -ForegroundColor Yellow
Write-Host "LTX 工作流另需自定义节点 ComfyUI-LTXVideo（ComfyUI Manager 安装）。" -ForegroundColor Yellow
