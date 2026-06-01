# ============================================================================
# LTX 2.3 官方模板配套模型下载（ComfyUI）
# 目标目录: D:\models\comfyui    （已存在的文件自动跳过，可重复运行）
#
# 背景：Comfy-Org 官方 LTX 2.3 工作流模板（video_ltx2_3_t2v / i2v）期望的
#       蒸馏 LoRA / Gemma LoRA / 空间上采样 版本，与早先 download-comfyui-models.ps1
#       下的不完全一致。本脚本按官方模板补齐这几个文件，让官方模板开箱即跑。
#
# 官方模板要求（见模板内 MarkdownNote）：
#   checkpoints/            ltx-2.3-22b-dev-fp8.safetensors                                  （早先已下，幂等跳过）
#   text_encoders/          gemma_3_12B_it_fp4_mixed.safetensors                             （官方 fp4 Gemma 编码器，~9.5GB，比自量化 fp8 更小更正规）
#   loras/                  ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors
#   loras/                  gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors
#   latent_upscale_models/  ltx-2.3-spatial-upscaler-x2-1.1.safetensors
#
# 注：fp4 Gemma 也可从 ModelScope 同名仓库 Comfy-Org/ltx-2 下（国内可能更快）；本脚本统一走 hf-mirror。
#
# 前置：aria2c 或 curl（aria2c 16 线程更快、支持断点续传）
# 用法：powershell -ExecutionPolicy Bypass -File scripts/download-ltx23-comfyui-models.ps1
#
# 注：这几个仓库（Lightricks / Comfy-Org）均无门禁，走 hf-mirror 即可，无需登录。
# ============================================================================

$ErrorActionPreference = "Stop"

$ComfyModels = "D:\models\comfyui"
$Mirror      = "https://hf-mirror.com"

foreach ($d in @("checkpoints", "text_encoders", "loras", "latent_upscale_models")) {
    New-Item -ItemType Directory -Force -Path "$ComfyModels\$d" | Out-Null
}

# 通用单文件下载器（aria2c 优先，回退 curl）
function Get-File($url, $outDir, $fileName) {
    $out = Join-Path $outDir $fileName
    if (Test-Path $out) { Write-Host "  已存在，跳过: $fileName" -ForegroundColor DarkGray; return }
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    if (Get-Command aria2c -ErrorAction SilentlyContinue) {
        aria2c -x 16 -s 16 --continue=true -d $outDir -o $fileName $url
    } else {
        curl.exe -L -C - -o $out $url --progress-bar
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "  X 下载失败: $fileName" -ForegroundColor Red }
    else { Write-Host "  完成: $fileName" -ForegroundColor Green }
}

Write-Host "`n========== LTX 2.3 官方模板配套模型 ==========" -ForegroundColor Cyan

$items = @(
    @{ Url = "$Mirror/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors";
       Dir = "checkpoints";           File = "ltx-2.3-22b-dev-fp8.safetensors" },
    @{ Url = "$Mirror/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors";
       Dir = "text_encoders";         File = "gemma_3_12B_it_fp4_mixed.safetensors" },
    @{ Url = "$Mirror/Comfy-Org/ltx-2.3/resolve/main/split_files/loras/ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors";
       Dir = "loras";                 File = "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors" },
    @{ Url = "$Mirror/Comfy-Org/ltx-2/resolve/main/split_files/loras/gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors";
       Dir = "loras";                 File = "gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors" },
    @{ Url = "$Mirror/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.1.safetensors";
       Dir = "latent_upscale_models"; File = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors" }
)

foreach ($it in $items) {
    Write-Host "`n  $($it.File)" -ForegroundColor Cyan
    Get-File $it.Url (Join-Path $ComfyModels $it.Dir) $it.File
}

Write-Host "`n========== 完成 ==========" -ForegroundColor Green
Write-Host "下完后在 ComfyUI 加载 comfyui/workflows/ui/ltx23_*.json，按模板内 Note 核对模型即可。" -ForegroundColor Yellow
