<p align="right"><a href="README.md">English</a> | <b>简体中文</b></p>

# 新闻视频自动化工作流

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Deploy](https://img.shields.io/badge/deploy-systemd-FCC624?logo=linux&logoColor=black)

从新闻采集到视频发布的全链路自动化平台：抓取新闻 → 生成脚本 → 生成图片/视频素材 → 合成配音视频 → 多平台发布。

**技术栈**：Python（FastAPI）后端 · React（Vite + TypeScript）前端

## 流水线

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   抓取新闻      整理/脚本      图片/视频素材    合成视频+配音      多平台发布
   S1            S2/S3          S3/S5           S4/S5             S6
```

每个 stage 在后端进程内顺序执行；整条任务通过进程内**全局串行队列**（单 worker 线程）**逐个执行**，同一时刻最多一个，无需额外 worker/broker。状态存 DB，支持从任意 stage 重试。

## 环境准备

### 后端（conda + requirements.txt）

依赖统一在根目录 `requirements.txt`，`backend/pyproject.toml` 只保留 ruff / pytest 配置。

```bash
conda create -n env_news_videos_wf python=3.12
conda activate env_news_videos_wf
pip install -r requirements.txt        # 含发布可选依赖 biliup / google-*
```

### 前端

```bash
cd frontend
pnpm install
```

### 基础设施 / 外部依赖

- **FFmpeg**：需在系统 PATH 中可用（视频合成）
- **ComfyUI**（可选，默认的本地图片/视频生成路线）：本机运行 ComfyUI（默认 `http://127.0.0.1:8188`），模型见 `scripts/download-comfyui-models.ps1`

## 运行

```bash
# 后端 API（流水线跑在进程内，任务串行执行、同一时刻一个，无需额外 worker/broker）
cd backend && uvicorn app.main:app --reload --port 8000   # http://127.0.0.1:8000
# 前端
cd frontend && pnpm dev                              # http://127.0.0.1:5173
```

首次启动会播种默认管理员账号 **admin / admin**，登录后请在「设置 → 用户」修改密码。

## 部署

推荐 **Ubuntu + systemd**，见 [`deploy/README.md`](deploy/README.md)。一个进程单端口托管前端（静态）+ 后端（API + 进程内流水线），无需 worker/broker。

> 原先的**单容器 Docker** 方案已**归档**（暂不维护），移至 [`deploy/docker-archive/`](deploy/docker-archive/README.md)，需要时按该目录说明恢复。

> 本地开发仍是两端口：`pnpm dev`（vite :5173，热更新）把 `/api` 代理到后端（:8000）。

## 测试

```bash
cd backend && pytest          # 后端
cd frontend && pnpm build     # 前端类型检查 + 构建
```

## 配置

- 首次配置：在仓库根目录复制模板 `cp config.yaml.example config.yaml`，填入 API Key 即可启动（`config.yaml` 已 gitignore，不入库）；之后推荐用设置页（`/settings`）可视化修改，保存时写回该文件。加载由 `backend/app/config.py`（pydantic + YAML）负责——**项目用根目录的 `config.yaml`，不是 `.env`**。
- **模型配置**页：按用途分组（文本 / 图片 / 多模态 / TTS）的供应商参数库，每个供应商配 base_url / API Key / 输出 tokens 上限 + **可编辑的模型名列表**，支持自定义供应商；接口/Key 按供应商共享。
- **流水线配置**页：唯一选「当前用哪个供应商 + 模型」的地方（总结 / 文案 / 图片 / 多模态 / 语音），并设默认分辨率、语言、视频路线、ComfyUI 视频模型与帧率。
- **ComfyUI 参数**页：图片（z_image / qwen）与视频（wan5b / wan14b / lightx2v / ltx）各 workflow 的 steps/cfg 参数。
- **提示词配置**页：中文 / 英文两套可编辑提示词，任务语言决定用哪套。
- **发布平台**：凭证在「发布管理」页按平台配置（存 DB），不写在配置文件里。

## ComfyUI 模型（本地图片/视频生成）

默认的图片/视频路线跑在**本地 ComfyUI**（工作流见 `comfyui/workflows/api/*.json`）。模型需你**自行下载**并让 ComfyUI 识别。参考配置：**24GB 显存**；全量约 **180GB** 磁盘——只需下你实际用到的路线即可。下表文件名省略 `.safetensors` 后缀；完整清单与下载源以 `scripts/download-comfyui-models.ps1` 为准。

| 路线 | ComfyUI 目录 | 模型文件 |
|---|---|---|
| **z_image** — 图片，默认/快 | `diffusion_models` · `text_encoders` · `vae` | `z_image_turbo_bf16` · `qwen_3_4b` · `ae` |
| **Qwen-Image** — 图片，中文/版面强 | `diffusion_models` · `text_encoders` · `vae` | `qwen_image_fp8_e4m3fn` · `qwen_2.5_vl_7b_fp8_scaled` · `qwen_image_vae` |
| **Wan 2.2 5B** — 视频，默认/快 | `diffusion_models` · `text_encoders` · `vae` | `wan2.2_ti2v_5B_fp16` · `umt5_xxl_fp8_e4m3fn_scaled` · `wan2.2_vae` |
| **Wan 2.2 14B** — 视频，质量（i2v & t2v） | `diffusion_models` · `vae` | `wan2.2_{i2v,t2v}_{high,low}_noise_14B_fp8_scaled` · `wan_2.1_vae` |
| **Wan 2.2 Lightning** — 视频，4 步 LoRA | `loras` | `wan2.2_{i2v,t2v}_lightx2v_4steps_lora_*` |
| **LTX 2.3** — 视频 | `checkpoints` · `text_encoders` · `loras` · `latent_upscale_models` | `ltx-2.3-22b-dev-fp8` · `gemma_3_12B_it_fp4_mixed` · `ltx-2.3-22b-distilled-lora-384-1.1` · `ltx-2.3-{spatial,temporal}-upscaler-x2-1.0` |

模型全部在 **ModelScope**（`Comfy-Org/*`、`Lightricks/LTX-2.3*`）。脚本会统一下载到一个目录：

```powershell
pip install modelscope
powershell -ExecutionPolicy Bypass -File scripts/download-comfyui-models.ps1      # 图片 + Wan 2.2
powershell -ExecutionPolicy Bypass -File scripts/download-ltx23-comfyui-models.ps1 # LTX 2.3（可选）
```

下完把 ComfyUI 的 `extra_model_paths.yaml` 的 `base_path` 指向该目录（脚本默认 `D:/models/comfyui/`），重启 ComfyUI，再到**设置 → 流水线配置**选对应模型（workflow 的 steps/cfg 在**设置 → ComfyUI 参数**）。**没有 GPU？** 把视频路线设为 `hyperframes`（回退 FFmpeg）——ComfyUI 是可选的。

## 发布

支持 YouTube、Bilibili 等。各平台所需账号/Cookie/Token 的申请与填写，见 **[docs/video-publish-guide.md](docs/video-publish-guide.md)**：

- **YouTube**：OAuth（Client ID + Client Secret + Refresh Token），需先在 OAuth Playground 获取 refresh_token，应用须设「外部 + 正式版」。
- **Bilibili**：浏览器 Cookie（SESSDATA + bili_jct 必填，DedeUserID/buvid3/buvid4 建议），基于 biliup 投稿。

## 文档

- [docs/video-publish-guide.md](docs/video-publish-guide.md) — 发布平台账号申请与配置（操作向）
- [docs/video-publish-api-reference.md](docs/video-publish-api-reference.md) — 发布适配器 API 参考
- [CLAUDE.md](CLAUDE.md) — 架构、模块划分、约定（开发者向）
- `comfyui/` — ComfyUI 工作流 JSON 与调用说明
