<p align="right"><a href="README.md">English</a> | <b>简体中文</b></p>

# 新闻视频自动化工作流

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Deploy](https://img.shields.io/badge/deploy-systemd-FCC624?logo=linux&logoColor=black)

把新闻做成成片并发布的全链路平台——**抓取 → 评分选材 → 写脚本 → 生成图片/视频素材 → 配音合成 → 多平台发布**——可全自动，也可在任意环节暂停人工审核。全程在 Web 管理面板里操作。

**技术栈**：Python（FastAPI）后端 · React（Vite + TypeScript）前端。

## 功能特点

**采集与选材**
- 多种采集器：**RSS**、**网页抓取**（Scrapling，针对无 RSS 的站）、**搜索 API**（Tavily / Brave / Serper / DuckDuckGo）、以及 **AI-HOT** 直用源。
- 分类标签（AI 模型 / 产品 / 行业 / 论文 / 技巧）+ 可配置时间窗口。
- 跨任务**去重**（回溯窗口内）后，再走一遍 AI **评分**排序，取分数最高的 top-N（`max_articles`）。
- **人工导入**：可按 URL 或上传文件添加文章，或完全跳过采集、喂自己的内容。

**脚本与素材**
- AI 为每条资讯生成**分镜脚本**（口播旁白 + 英文画面/运镜提示词）——支持单条汇总、日报批量、周报归纳三种框定。
- **中英双语**：任务语言决定用哪套提示词，并提供 **5 套可切换预设**（双击重命名）。
- 图片素材走所选图片 provider；**配音**走所选 TTS provider。
- **逐分镜人工干预**：重生成脚本、单张图片、单条画面提示词；重摇文章列表。

**三条出片路线**
- **ComfyUI** —— 本地 GPU 扩散（图片：z_image / Qwen-Image；视频：Wan 2.2 / LTX 2.3）。
- **Hyperframes** —— HTML/CSS 动态图形，无需 GPU（Node + `hyperframes`）。
- **纯语音** —— 只有口播、无画面。
- 可选**标题烧录**叠加层（CJK 字体），样式可调。

**可插拔 AI provider**
- **文本 / 图片 / 多模态 / 语音** 各自通过配置切换——OpenAI、DashScope、Edge-TTS、ComfyUI…… —— 不改业务代码。
- 按供应商的凭证库；**流水线配置**页是唯一选「每个用途用哪个供应商 + 模型」的地方。

**本地 ComfyUI + 远程唤醒**
- 图片/视频生成跑在**本地 ComfyUI**，一键测试连接。
- 可把 app 部署在**无 GPU 的服务器**、ComfyUI 放另一台 GPU 机器，按需 **Wake-on-LAN** 唤醒。ComfyUI 不可达时任务直接报错停止（不静默兜底）。

**发布与编排**
- **多平台发布**（适配器模式：YouTube、Bilibili……），凭证按账号管理。
- **计划任务**：类 cron 排期（每日 / 每周 / 每月），到点自动建任务。
- **自动** 或 **手动（逐步审核）** 两种执行模式；每个 stage 幂等、**可从任意 stage 重试**。
- 任务**全局串行**、同一时刻一个，其余排队，无需额外 worker/broker。
- Web 管理面板：仪表盘（监控/审核/干预）、新闻源、发布管理、计划任务、设置，以及用户管理。

## 流水线

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   抓取+评分    脚本/分镜      图片/视频素材   合成+配音      多平台发布
   S1           S2/S3         S3/S5          S4/S5          S6
```

每个 stage 在后端进程内顺序执行，状态存 DB，可从任意 stage 续跑/重试。整条任务经单一进程内 worker 串行执行（其余显示 `pending`）；重启会丢「排队中」的任务、正在跑的优雅停止。

## 运行选项

新建任务时可选：**时间范围**（1d/3d/7d/15d/1m）· **最大文章数** · **分类** · **语言**（中/英）· **视频路线**（ComfyUI / Hyperframes / 纯语音）· **采集模式**（自动采集 / 人工导入）· **执行模式**（自动 / 手动逐步审核）· **信息源** · **发布账号**。计划任务沿用同一组选项（执行模式强制 auto）。

## 安装

### 后端（conda + requirements.txt）

依赖统一在根目录 `requirements.txt`，`backend/pyproject.toml` 只保留 ruff / pytest 配置。

```bash
conda create -n env_news_videos_wf python=3.12
conda activate env_news_videos_wf
pip install -r requirements.txt        # 含发布可选依赖 biliup / google-*
```

### 前端

```bash
cd frontend && pnpm install && pnpm build   # 后端托管构建产物 frontend/dist
```

### 系统依赖

- **FFmpeg** —— 视频合成必需（也是 Hyperframes 路线的兜底合成器）。Ubuntu：`sudo apt install -y ffmpeg fonts-noto-cjk`。
- **CJK 字体** —— FFmpeg / ComfyUI 路的标题烧录用。Ubuntu 用 `fonts-noto-cjk`（见上）；Windows 用自带 `C:/Windows/Fonts/msyh.ttc`。缺失只跳过烧录、不影响出片。
- **Node ≥ 22 + Hyperframes** —— 仅 `hyperframes` 路线需要。Ubuntu（默认源太旧，用 NodeSource）：`curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs`，再 `sudo npm i -g hyperframes`（或首次渲染由 `npx` 拉取）。非 pip 依赖。
- **ComfyUI** —— 可选，仅默认的本地图片/视频路线需要；见 [ComfyUI 模型](#comfyui-模型本地图片视频生成)。

### 配置文件

配置均为仓库根的 YAML 文件（已 gitignore），从同名 `.example` 模板创建：

```bash
cp config.yaml.example          config.yaml            # 必需：基础配置（端口/路线/分辨率/语言…）
cp model_providers.yaml.example model_providers.yaml   # provider 的 base_url/api_key（也可在「模型配置」页填）
```

只有 `config.yaml` 必须先建。其余首次使用时自动生成、或由对应设置页写入：`prompts.yaml`（提示词预设）、`news_sources.yaml`（新闻源）、`publish_targets.yaml`（发布账号）、`schedule.yaml`（计划任务）。需要预置时再 `cp` 对应模板。

> 首次启动会播种默认管理员 **admin / admin**，请在「设置 → 用户」尽快改密。

## 配置

一切都可在设置页（`/settings`）里改，保存时写回各 YAML 文件。加载由 `backend/app/config.py`（pydantic + YAML）负责——**项目用根目录的 `config.yaml`，不是 `.env`**。

- **模型配置** —— 按用途分组（文本 / 图片 / 多模态 / 语音）的供应商库：base_url / API Key / 输出 token 上限 + 可编辑模型名列表；支持自定义供应商，凭证按供应商共享。
- **流水线配置** —— 选「每个用途用哪个供应商 + 模型」（总结 / 文案 / 图片 / 多模态 / 语音），并设默认分辨率、语言、视频路线、ComfyUI 视频模型与帧率。
- **ComfyUI** —— 连接地址带**测试连接**按钮、可选 **Wake-on-LAN 远程唤醒**；图片（z_image / qwen）与视频（wan5b / wan14b / lightx2v / ltx）各 workflow 的 steps/cfg。
- **提示词** —— 5 套可切换预设（#1–#5，双击重命名），每套中英各一份；留空回退内置默认。
- **发布管理** —— 各平台凭证按账号配置。
- **新闻源** / **计划任务** —— 管理信息源与排期。

## ComfyUI 模型（本地图片/视频生成）

默认的图片/视频路线跑在**本地 ComfyUI**（工作流见 `comfyui/workflows/api/*.json`）。模型需你**自行下载**并让 ComfyUI 识别。参考配置：**24GB 显存**；全量约 **160GB** 磁盘——只需下你实际用到的路线即可。下表文件名省略 `.safetensors` 后缀；完整清单与下载源以 `scripts/download-comfyui-models.ps1` / `.sh` 为准。

| 路线 | ComfyUI 目录 | 模型文件 |
|---|---|---|
| **z_image** — 图片，默认/快 | `diffusion_models` · `text_encoders` · `vae` | `z_image_turbo_bf16` · `qwen_3_4b` · `ae` |
| **Qwen-Image** — 图片，中文/版面强 | `diffusion_models` · `text_encoders` · `vae` | `qwen_image_fp8_e4m3fn` · `qwen_2.5_vl_7b_fp8_scaled` · `qwen_image_vae` |
| **Wan 2.2 5B** — 视频，默认/快 | `diffusion_models` · `text_encoders` · `vae` | `wan2.2_ti2v_5B_fp16` · `umt5_xxl_fp8_e4m3fn_scaled` · `wan2.2_vae` |
| **Wan 2.2 14B** — 视频，质量（i2v & t2v） | `diffusion_models` · `vae` | `wan2.2_{i2v,t2v}_{high,low}_noise_14B_fp8_scaled` · `wan_2.1_vae` |
| **Wan 2.2 Lightning** — 视频，4 步 LoRA | `loras` | `wan2.2_{i2v,t2v}_lightx2v_4steps_lora_*` |
| **LTX 2.3** — 视频 | `checkpoints` · `text_encoders` · `loras` | `ltx-2.3-22b-dev-fp8` · `gemma_3_12B_it_fp4_mixed` · `ltx-2.3-22b-distilled-lora-384-1.1` |

模型全部在 **ModelScope**（`Comfy-Org/*`、`Lightricks/LTX-2.3*`）。一个脚本（PowerShell + bash 两版）把全部模型（图片 + Wan 2.2 + LTX 2.3，对齐 api 工作流）统一下载到一个目录：

```bash
pip install modelscope
# Windows（PowerShell）
powershell -ExecutionPolicy Bypass -File scripts/download-comfyui-models.ps1
# Linux / WSL（bash）
bash scripts/download-comfyui-models.sh
```

> 自定义目标目录：`-ModelsDir <路径>`（PowerShell）/ `--models-dir <路径>`（bash）；默认 `D:\models\comfyui` / `~/models/comfyui`。

下完把 ComfyUI 的 `extra_model_paths.yaml` 的 `base_path` 指向该目录，重启 ComfyUI，再到**设置 → 流水线配置**选对应模型。**app 主机没有 GPU？** 要么把视频路线设为 `hyperframes`（无需 GPU）/ `纯语音`（只口播），要么把 ComfyUI 放另一台 GPU 机、用 **Wake-on-LAN** 唤醒（设置 → ComfyUI）。

## 发布

支持 YouTube、Bilibili 等。各平台所需账号/Cookie/Token 的申请与填写，见 **[docs/video-publish-guide.md](docs/video-publish-guide.md)**：

- **YouTube**：OAuth（Client ID + Client Secret + Refresh Token），需先在 OAuth Playground 获取 refresh_token，应用须设「外部 + 正式版」。
- **Bilibili**：浏览器 Cookie（SESSDATA + bili_jct 必填，DedeUserID/buvid3/buvid4 建议），基于 biliup 投稿。

## 部署

推荐 **Ubuntu + systemd**，完整步骤（服务账号、挂载、配置文件、单元文件）见 **[deploy/README.md](deploy/README.md)**。一个进程单端口托管前端（静态）+ 后端（API + 进程内流水线），无需 worker/broker。

> 原单容器 **Docker** 方案已归档（暂不维护），见 [`deploy/docker-archive/`](deploy/docker-archive/README.md)。

## 文档

- [docs/video-publish-guide.md](docs/video-publish-guide.md) — 发布平台账号申请与配置（操作向）
- [docs/video-publish-api-reference.md](docs/video-publish-api-reference.md) — 发布适配器 API 参考
- [CLAUDE.md](CLAUDE.md) — 架构、模块划分、约定（开发者向）
- `comfyui/` — ComfyUI 工作流 JSON 与调用说明
