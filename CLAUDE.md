# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

新闻视频自动化工作流系统：从新闻采集到视频发布的全链路自动化平台。

**Tech Stack**: Python (FastAPI) backend, React (Vite + TypeScript) frontend

## Architecture

### Pipeline Stages

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   抓取新闻      整理/生成脚本    生成图片素材     合成视频+配音      多平台发布
```

每个 stage 在后端进程内顺序执行（FastAPI BackgroundTasks，`app/pipeline/runner.py`），状态存 DB，pipeline 支持从任意 stage 重试。

### Core Modules

- **`backend/app/pipeline/`** — 核心流水线，每个 stage 一个子包
  - `collector/` — 基于 Scrapling 的新闻抓取，支持 RSS、网页、API 多种数据源
  - `processor/` — 内容去重、摘要、视频脚本生成（通过 AI provider 接口）
  - `generator/` — 图片/视频素材生成（通过 AI provider 接口）
  - `composer/` — FFmpeg/MoviePy 视频合成、TTS 配音、唇形同步校正
  - `publisher/` — 多平台发布适配器（抖音、YouTube、B站等）

- **`backend/app/providers/`** — AI 服务的 Provider 抽象层
  - 统一接口：`TextProvider`, `ImageProvider`, `TTSProvider`, `LipSyncProvider`
  - 具体实现按需接入（OpenAI、DashScope、Stable Diffusion、Edge-TTS、CosyVoice 等）
  - 通过配置文件切换 provider，不改业务代码

- **`backend/app/api/`** — FastAPI 路由层
- **`backend/app/models/`** — SQLAlchemy 数据模型
- **`frontend/`** — React 管理面板（任务监控、内容审核、手动干预）

### Data Flow

一条新闻从采集到发布的完整数据流：

```
NewsSource → RawArticle → ProcessedScript → [ImageAsset[], AudioAsset] → Video → PublishResult
```

每条数据在 DB 中有状态追踪（pending → processing → done / failed），支持断点续跑。

### Key Design Patterns

- **Provider Pattern**: 所有 AI 服务通过抽象接口调用，`backend/app/providers/base.py` 定义接口，具体实现在子模块中注册
- **Adapter Pattern**: 每个发布平台是一个 Publisher Adapter，统一 `publish(video, metadata)` 接口
- **Pipeline as State Machine**: 每个 task 有明确的状态流转，失败可单独重试

## Commands

### Backend

依赖统一在仓库根 `requirements.txt` 管理（conda 环境 + pip）。`backend/pyproject.toml` 只保留 ruff / pytest 工具配置。

```bash
# 一次性：创建并激活 conda 环境（Python 3.12）
conda create -n env_nvw python=3.12 && conda activate env_nvw
pip install -r requirements.txt  # 安装依赖（含发布可选依赖 biliup / google-*）

cd backend
uvicorn app.main:app --reload --port 8189   # 启动 API 服务 (端口取 .env 的 APP_PORT，默认 8189)；流水线跑在进程内的后台任务，无需独立 worker
pytest                           # 运行全部测试
pytest tests/test_collector.py -k "test_rss"  # 运行单个测试
ruff check .                     # lint
ruff format .                    # format
```

### Frontend

```bash
cd frontend
pnpm install                     # 安装前端依赖
pnpm dev                         # 启动开发服务器 (默认 :5173)
pnpm build                       # 生产构建
pnpm lint                        # ESLint
pnpm test                        # Vitest
```

## Dependencies

- **Scrapling**: 新闻抓取框架，需 Python 3.10+，安装时用 `pip install "scrapling[all]"`，首次运行 `scrapling install` 下载浏览器
- **FFmpeg**: 视频合成必须在系统 PATH 中可用（是 Hyperframes 渲染失败时的兜底合成器；**ComfyUI 视频路失败/未启动则直接报错停止，不兜底 FFmpeg**——与图片路一致，选了 ComfyUI 就必须 ComfyUI 出片）
- **CJK 字体（标题烧录，仅 FFmpeg 路）**: comfyui / FFmpeg 兜底路用 `drawtext` 把分镜标题烧到画面右上角，需一个可用的中日韩字体文件。Windows 默认 `C:/Windows/Fonts/msyh.ttc`（微软雅黑，系统自带）；其它平台在 `config.yaml` 的 `overlay.font_file` 指定（如 `/usr/share/fonts/.../NotoSansCJK-Regular.ttc`）。缺失时仅跳过烧录、不影响出片。hyperframes(HTML) 路不依赖此项（走 CSS 字体）。
- **Hyperframes**（hyperframes 视频路线）: 需 Node.js + `npx hyperframes`（npm 包，非 Python 依赖，不在 requirements.txt）。首次渲染由 npx 联网拉取，或预装 `npm i -g hyperframes`。缺失时自动回退到 FFmpeg 合成。
- **ComfyUI**（可选，本地图片/视频生成）: 默认视频路线，需本机运行 ComfyUI（默认 `http://127.0.0.1:8188`）+ 下载模型（见 `scripts/download-comfyui-models.ps1`）。工作流 JSON 在 `comfyui/workflows/api/`，配置在设置页「ComfyUI」标签。
- **发布可选依赖**（按需）: B站投稿用 `biliup`；YouTube 用 `google-api-python-client` / `google-auth` / `google-auth-oauthlib`。均已列入 `requirements.txt`。发布平台凭证在「发布管理」页配置，详见 `docs/video-publish-guide.md`。
- **APScheduler / tzlocal**（计划任务）: 「计划任务」页排期存仓库根 `schedule.yaml`，由进程内 `BackgroundScheduler` 到点自动建 run（执行模式强制 auto）。调度按**后端进程所在机器的本地时区**（`tzlocal` 自动取）。

## Configuration

配置统一在**仓库根目录的 `config.yaml`**（不是 `.env`），由 `backend/app/config.py`（pydantic BaseModel + `yaml.safe_load`）加载，`CONFIG_PATH` 指向 `parents[2]/config.yaml`。首次复制 `config.yaml.example` 为 `config.yaml` 填入密钥；设置页保存时会写回该文件。关键分组：

- `text` / `image` / `vision` / `tts` / `summary` — 各 AI provider 的 provider/base_url/model/api_key
- `pipeline` — 默认时间范围、最大文章数、视频路线（comfyui | hyperframes | audio）等
- `comfyui` — 本地图片/视频生成的 workflow 与每流 steps/cfg
- `hyperframes` — Hyperframes 视频路线的渲染参数（fps / 转场 / 字幕等；原 `video` 段，已重命名）
- 发布平台凭证不在此文件，存仓库根的 `publish_targets.yaml`（按账号，「发布管理」页配置）
- `overlay` — 分镜标题烧录样式（`font_file` / `font_size_ratio` / `color` / `bg_opacity` / `margin_ratio` 等；仅 FFmpeg 两路读 `font_file`，HTML 路走 CSS 字体）；`pipeline.max_articles`（per-run）是统一的内容条数上限（top-N）——普通源与 AI HOT 直用都经 `ScoringService` 选取此数量；`pipeline.max_images` 超限时按评分裁掉低分整组（`cap_scenes_by_score`，不再 AI 合并）
- 计划任务排期不在 `config.yaml`，存仓库根 `schedule.yaml`（不入库，模板见 `schedule.yaml.example`）
- 提示词不在 `config.yaml`，存仓库根 `prompts.yaml`（不入库，模板见 `prompts.yaml.example`，由 `app/store/prompts_store.py` 读写）：5 套预设（`#1~#5`，每套中英两份），`active` 指向当前生效预设，由 `config.get_settings()` 注入 `settings.prompt_presets` 并把生效预设镜像到 `settings.prompts`（`resolve_prompt` 仍读 `settings.prompts`，不变）；首次启动自动从旧 `config.yaml` 的 `prompts` 块迁入预设 `#1`。在「设置 → 提示词配置」页切换/重命名/清空，统一由顶部「保存」落盘

## Conventions

- 中文注释和文档，代码标识符用英文
- Provider 接口用 `async def`，所有 AI 调用走异步
- Pipeline stage 在 runner 内顺序 await 串联，每个 stage 是幂等的（失败可单独重试）
- 新增 AI provider 需实现 `base.py` 中对应的抽象类并在 `__init__.py` 注册
- 新增发布平台需实现 `PublisherAdapter` 接口并加到 adapter registry
