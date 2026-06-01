# ============================================================================
# LTX 2.3 官方模板配套模型下载（ComfyUI）—— 全部走 ModelScope，无任何 HF 源
# 目标目录: D:\models\comfyui    （已存在的文件自动跳过，可重复运行）
#
# 背景：Comfy-Org 官方 LTX 2.3 工作流模板（video_ltx2_3_t2v / i2v）期望的
#       fp4 Gemma 编码器 / 蒸馏 LoRA / Gemma LoRA / 空间上采样，按官方模板补齐，开箱即跑。
#
# 官方模板要求（见模板内 MarkdownNote），ModelScope 源：
#   checkpoints/            ltx-2.3-22b-dev-fp8.safetensors                                    [Lightricks/LTX-2.3-fp8]
#   text_encoders/          gemma_3_12B_it_fp4_mixed.safetensors  (~9.5GB)                     [Comfy-Org/ltx-2]
#   loras/                  ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16...  [Comfy-Org/ltx-2.3]
#   loras/                  gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors            [Comfy-Org/ltx-2]
#   latent_upscale_models/  ltx-2.3-spatial-upscaler-x2-1.1.safetensors                        [Lightricks/LTX-2.3]
#
# 前置：pip install modelscope
# 用法：powershell -ExecutionPolicy Bypass -File scripts/download-ltx23-comfyui-models.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

$ComfyModels = "D:\models\comfyui"
$Staging     = "D:\models\_staging"

foreach ($d in @("checkpoints", "text_encoders", "loras", "latent_upscale_models")) {
    New-Item -ItemType Directory -Force -Path "$ComfyModels\$d" | Out-Null
}

# ModelScope 条目（--include 用文件名匹配，兼容仓库根与 split_files/ 子目录）
$msItems = @(
    @{ Repo = "Lightricks/LTX-2.3-fp8"; File = "ltx-2.3-22b-dev-fp8.safetensors";                                     Dir = "checkpoints" },
    @{ Repo = "Comfy-Org/ltx-2";        File = "gemma_3_12B_it_fp4_mixed.safetensors";                                Dir = "text_encoders" },
    @{ Repo = "Comfy-Org/ltx-2.3";      File = "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors"; Dir = "loras" },
    @{ Repo = "Comfy-Org/ltx-2";        File = "gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors";             Dir = "loras" },
    @{ Repo = "Lightricks/LTX-2.3";     File = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors";                         Dir = "latent_upscale_models" }
)

if (-not (Get-Command modelscope -ErrorAction SilentlyContinue)) {
    Write-Host "`n✗ 未找到 modelscope CLI。请先： pip install modelscope" -ForegroundColor Red
    exit 1
}

Write-Host "`n========== LTX 2.3 官方模板配套模型（ModelScope）==========" -ForegroundColor Cyan

$idx = 0
foreach ($it in $msItems) {
    $idx++
    $target = Join-Path "$ComfyModels\$($it.Dir)" $it.File
    Write-Host "`n[$idx/$($msItems.Count)] $($it.File)" -ForegroundColor Cyan
    if (Test-Path $target) { Write-Host "  已存在，跳过" -ForegroundColor DarkGray; continue }

    $stage = Join-Path $Staging ($it.Repo -replace "/", "_")
    modelscope download --model $it.Repo --include "*$($it.File)" --local_dir $stage

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

Write-Host "`n========== 完成 ==========" -ForegroundColor Green
Write-Host "下完后在 ComfyUI 加载 comfyui/workflows/ui/ltx23_*.json，按模板内 Note 核对模型即可。" -ForegroundColor Yellow
