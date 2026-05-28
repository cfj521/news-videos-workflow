# LTX-2.3 模型下载脚本
# 目标目录: D:/models/ltx-2.3
# 总计约 50-60GB，请确保磁盘空间充足

$ModelDir = "D:\models\ltx-2.3"
$Mirror = "https://hf-mirror.com"

# 创建目录
$dirs = @("checkpoints", "text_encoders\gemma-3-12b-it-qat-q4_0-unquantized", "latent_upscale_models", "loras")
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path "$ModelDir\$d" | Out-Null
}
Write-Host "目录已创建: $ModelDir" -ForegroundColor Green
Write-Host "镜像源: $Mirror`n" -ForegroundColor Yellow

# 单文件下载列表: [URL路径, 本地子目录, 文件名, 说明]
$files = @(
    @("Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors",                  "checkpoints",           "ltx-2.3-22b-dev-fp8.safetensors",                  "主模型 FP8 (~29GB)"),
    @("Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.0.safetensors",           "latent_upscale_models", "ltx-2.3-spatial-upscaler-x2-1.0.safetensors",      "空间上采样器 (~1GB)"),
    @("Lightricks/LTX-2.3/resolve/main/ltx-2.3-temporal-upscaler-x2-1.0.safetensors",          "latent_upscale_models", "ltx-2.3-temporal-upscaler-x2-1.0.safetensors",     "时间上采样器 (~262MB)"),
    @("Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384-1.1.safetensors",        "loras",                 "ltx-2.3-22b-distilled-lora-384-1.1.safetensors",   "蒸馏 LoRA (~7.6GB)")
)

$total = $files.Count + 1  # +1 for Gemma
for ($i = 0; $i -lt $files.Count; $i++) {
    $urlPath, $subDir, $fileName, $desc = $files[$i]
    $url = "$Mirror/$urlPath"
    $outPath = "$ModelDir\$subDir\$fileName"

    Write-Host "========== $($i+1)/$total $desc ==========" -ForegroundColor Cyan

    if (Test-Path $outPath) {
        Write-Host "  已存在，跳过: $outPath" -ForegroundColor DarkGray
        continue
    }

    Write-Host "  下载: $url"
    Write-Host "  保存: $outPath"

    if (Get-Command aria2c -ErrorAction SilentlyContinue) {
        aria2c -x 16 -s 16 --continue=true -d "$ModelDir\$subDir" -o $fileName $url
    } else {
        curl.exe -L -C - -o $outPath $url --progress-bar
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  下载失败！" -ForegroundColor Red
    } else {
        Write-Host "  完成" -ForegroundColor Green
    }
}

# Gemma 文本编码器 (逐文件 aria2c/curl 下载)
Write-Host "`n========== Gemma 文本编码器 (~24GB) ==========" -ForegroundColor Cyan
$gemmaDir = "$ModelDir\text_encoders\gemma-3-12b-it-qat-q4_0-unquantized"
# Gemma 用官方源（镜像站不支持 Google 受限模型）
$gemmaRepo = "google/gemma-3-12b-it-qat-q4_0-unquantized"
$gemmaMirror = "https://huggingface.co"
$gemmaFiles = @(
    "config.json", "generation_config.json", "preprocessor_config.json",
    "processor_config.json", "special_tokens_map.json", "added_tokens.json",
    "chat_template.json", "tokenizer_config.json", "tokenizer.json", "tokenizer.model",
    "model.safetensors.index.json",
    "model-00001-of-00005.safetensors",
    "model-00002-of-00005.safetensors",
    "model-00003-of-00005.safetensors",
    "model-00004-of-00005.safetensors",
    "model-00005-of-00005.safetensors"
)

$gi = 0
foreach ($gf in $gemmaFiles) {
    $gi++
    $gUrl = "$gemmaMirror/$gemmaRepo/resolve/main/$gf"
    $gOut = "$gemmaDir\$gf"

    Write-Host "  [$gi/$($gemmaFiles.Count)] $gf" -ForegroundColor Cyan -NoNewline

    if (Test-Path $gOut) {
        Write-Host " (已存在，跳过)" -ForegroundColor DarkGray
        continue
    }
    Write-Host ""

    if (Get-Command aria2c -ErrorAction SilentlyContinue) {
        aria2c -x 16 -s 16 --continue=true -d $gemmaDir -o $gf $gUrl
    } else {
        curl.exe -L -C - -o $gOut $gUrl --progress-bar
    }

    if ($LASTEXITCODE -ne 0) { Write-Host "    下载失败！" -ForegroundColor Red }
}

Write-Host "`n========== 下载完成 ==========" -ForegroundColor Green
Write-Host "模型目录: $ModelDir"
Get-ChildItem -Recurse -File "$ModelDir" | ForEach-Object {
    $size = [math]::Round($_.Length / 1GB, 2)
    Write-Host "  $($_.FullName.Replace($ModelDir, '.'))  ${size}GB"
}
