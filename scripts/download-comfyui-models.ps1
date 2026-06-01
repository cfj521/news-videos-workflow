# ============================================================================
# ComfyUI 模型统一下载脚本（24GB 显存配置）
# 目标目录: D:\models\comfyui    （已存在的文件自动跳过，可重复运行）
#
# 覆盖：
#   图片  z_image_turbo + Qwen-Image                          [ModelScope]
#   视频  Wan 2.2  5B TI2V + 14B I2V/T2V + 4步Lightning LoRA   [ModelScope]
#   视频  LTX 2.3  主模型 + 上采样x2 + 蒸馏LoRA + Gemma文本编码器  [hf-mirror / 官方HF]
#
# 前置依赖：
#   pip install modelscope          # ModelScope 部分必需
#   aria2c 或 curl                  # LTX 部分（aria2c 16线程更快、支持断点续传）
#   hf auth login                   # 仅 Gemma 需要：Google 受限模型，须先在网页接受许可
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/download-comfyui-models.ps1
#
# 全量约 180GB（图片~47 / Wan 5B~17 + 14B~58 / LTX~58）。请确保磁盘空间充足。
# ============================================================================

$ErrorActionPreference = "Stop"

$ComfyModels = "D:\models\comfyui"      # ComfyUI 模型根目录
$Staging     = "D:\models\_staging"      # ModelScope 下载暂存区（下完挑出文件移到正式目录）
$Mirror      = "https://hf-mirror.com"   # LTX 镜像源（无需登录）

foreach ($d in @("diffusion_models", "text_encoders", "vae", "loras", "checkpoints", "latent_upscale_models")) {
    New-Item -ItemType Directory -Force -Path "$ComfyModels\$d" | Out-Null
}

# 通用单文件下载器（aria2c 优先，回退 curl），用于 LTX
function Get-File($url, $outDir, $fileName) {
    $out = Join-Path $outDir $fileName
    if (Test-Path $out) { Write-Host "  已存在，跳过: $fileName" -ForegroundColor DarkGray; return }
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    if (Get-Command aria2c -ErrorAction SilentlyContinue) {
        aria2c -x 16 -s 16 --continue=true -d $outDir -o $fileName $url
    } else {
        curl.exe -L -C - -o $out $url --progress-bar
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "  ✗ 下载失败: $fileName" -ForegroundColor Red }
    else { Write-Host "  完成: $fileName" -ForegroundColor Green }
}

# ============================================================================
# 第一部分：ModelScope —— 图片(z_image/Qwen) + 视频(Wan 2.2 5B & 14B)
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
    @{ Repo = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"; File = "wan_2.1_vae.safetensors";                                     Dir = "vae" }
)

if (Get-Command modelscope -ErrorAction SilentlyContinue) {
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
} else {
    Write-Host "`n⚠ 未找到 modelscope CLI，跳过图片/Wan 部分。安装： pip install modelscope" -ForegroundColor Yellow
}

# ============================================================================
# 第二部分：LTX 2.3 —— 主模型/上采样/蒸馏LoRA(hf-mirror) + Gemma文本编码器(官方HF)
# ============================================================================
Write-Host "`n========== LTX 2.3 ==========" -ForegroundColor Cyan
$ltxItems = @(
    @{ Url = "$Mirror/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors";            Dir = "checkpoints";           File = "ltx-2.3-22b-dev-fp8.safetensors" },
    @{ Url = "$Mirror/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.0.safetensors";    Dir = "latent_upscale_models"; File = "ltx-2.3-spatial-upscaler-x2-1.0.safetensors" },
    @{ Url = "$Mirror/Lightricks/LTX-2.3/resolve/main/ltx-2.3-temporal-upscaler-x2-1.0.safetensors";   Dir = "latent_upscale_models"; File = "ltx-2.3-temporal-upscaler-x2-1.0.safetensors" },
    @{ Url = "$Mirror/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384-1.1.safetensors"; Dir = "loras";                 File = "ltx-2.3-22b-distilled-lora-384-1.1.safetensors" }
)
foreach ($f in $ltxItems) {
    Write-Host "`n  $($f.File)" -ForegroundColor Cyan
    Get-File $f.Url (Join-Path $ComfyModels $f.Dir) $f.File
}

# Gemma 文本编码器（Google 受限模型：须先 hf auth login + 网页接受许可，且不能走镜像）
$gemmaDir = "$ComfyModels\text_encoders\gemma-3-12b-it-qat-q4_0-unquantized"
if (Test-Path "$gemmaDir\model-00005-of-00005.safetensors") {
    Write-Host "`n  Gemma 文本编码器已存在，跳过" -ForegroundColor DarkGray
} else {
    Write-Host "`n  下载 Gemma 文本编码器（官方源，需 hf auth login + 接受许可）..." -ForegroundColor Yellow
    if (Get-Command hf -ErrorAction SilentlyContinue) {
        $env:HF_ENDPOINT = ""   # Gemma 不能走镜像，必须官方源
        hf download google/gemma-3-12b-it-qat-q4_0-unquantized --local-dir $gemmaDir
    } else {
        Write-Host "  ✗ 未找到 hf CLI，跳过 Gemma。安装： pip install huggingface_hub" -ForegroundColor Red
    }
}

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
